#!/usr/bin/env python3
"""Fetch and parse HKEX New Listing Report workbooks.

HKEX publishes annual New Listing Reports as Excel workbooks from the New
Listing Information page. This script parses the public reports statelessly and
prints normalized JSON. It is intended to supplement AASTOCKS detail fields in
historical backtests, especially sponsor, official English name, listing date,
offer price, and funds raised.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from fetch_current_ipos import canonical_code, clean_text, display_code, parse_float


HKEX_NEW_LISTING_INFO_URL = (
    "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en"
)
HKEX_BASE_URL = "https://www2.hkexnews.hk"
USER_AGENT = "Mozilla/5.0 (compatible; hk-ipo-reference/0.1)"


def fetch_bytes(url: str, *, timeout: int, retries: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en,zh-CN;q=0.8,zh;q=0.7",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_error}")


def read_text(path: str | None, url: str, *, timeout: int, retries: int) -> tuple[str, str]:
    if path:
        return Path(path).read_text(encoding="utf-8"), f"fixture:{path}"
    return fetch_bytes(url, timeout=timeout, retries=retries).decode("utf-8", errors="ignore"), url


def parse_report_links(html_text: str, base_url: str = HKEX_BASE_URL) -> dict[tuple[str, int], str]:
    links: dict[tuple[str, int], str] = {}
    for href in sorted(set(re.findall(r'href="([^"]+?\.xlsx?)"', html_text, flags=re.IGNORECASE))):
        year: int | None = None
        if "/GEM/" in href:
            board = "GEM"
            match = re.search(r"e_newlistings(?P<year>20\d{2}|\d{2})\.xlsx?", href, flags=re.IGNORECASE)
            if match:
                raw_year = match.group("year")
                year = int(raw_year) if len(raw_year) == 4 else (1900 + int(raw_year) if int(raw_year) >= 90 else 2000 + int(raw_year))
        elif "/Main/" in href:
            board = "Main"
            match = re.search(r"(?:NLR)?(?P<year>20\d{2}|19\d{2})(?:_Eng)?\.xlsx?", href, flags=re.IGNORECASE)
            if match:
                year = int(match.group("year"))
        else:
            continue
        if year:
            links[(board, year)] = urljoin(base_url, href)
    return links


def xml_attr(attrs: str, name: str) -> str | None:
    match = re.search(rf'\b{name}="([^"]*)"', attrs)
    return match.group(1) if match else None


def load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        xml_text = archive.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
    except KeyError:
        return []
    strings: list[str] = []
    for item in re.findall(r"<si\b[^>]*>(.*?)</si>", xml_text, flags=re.DOTALL):
        texts = re.findall(r"<t\b[^>]*>(.*?)</t>", item, flags=re.DOTALL)
        strings.append(clean_text("".join(texts)))
    return strings


def column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def cell_text(attrs: str, body: str, shared_strings: list[str]) -> Any:
    cell_type = xml_attr(attrs, "t")
    if cell_type == "inlineStr":
        return clean_text("".join(re.findall(r"<t\b[^>]*>(.*?)</t>", body, flags=re.DOTALL)))
    value_match = re.search(r"<v>(.*?)</v>", body, flags=re.DOTALL)
    if not value_match:
        return None
    raw = value_match.group(1)
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type in {"str", "b"}:
        return clean_text(raw)
    try:
        number = float(raw)
    except ValueError:
        return clean_text(raw)
    if number.is_integer():
        return int(number)
    return number


def parse_xlsx_rows(payload: bytes) -> list[list[Any]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        shared_strings = load_shared_strings(archive)
        worksheet_name = "xl/worksheets/sheet1.xml"
        xml_text = archive.read(worksheet_name).decode("utf-8", errors="ignore")
        rows: list[list[Any]] = []
        for row_body in re.findall(r"<row\b[^>]*>(.*?)</row>", xml_text, flags=re.DOTALL):
            values: list[Any] = []
            for attrs, body in re.findall(r"<c\b([^>]*)>(.*?)</c>", row_body, flags=re.DOTALL):
                index = column_index(xml_attr(attrs, "r") or "A")
                while len(values) <= index:
                    values.append(None)
                values[index] = cell_text(attrs, body, shared_strings)
            rows.append(values)
        return rows


def excel_date(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    try:
        serial = float(value)
    except (TypeError, ValueError):
        return None
    if serial <= 0:
        return None
    return (dt.date(1899, 12, 30) + dt.timedelta(days=int(serial))).isoformat()


def normalize_text_field(value: Any) -> str | None:
    text = clean_text(str(value)) if value is not None else ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s*/\s*", " / ", text)
    text = re.sub(r"\s+", " ", text).strip(" \"")
    if not text or text.upper() in {"N/A", "NA", "-", "N / A"}:
        return None
    return text


def normalize_money(value: Any) -> float | None:
    number = parse_float(str(value)) if value is not None else None
    return float(number) if number is not None else None


def parse_main_rows(rows: list[list[Any]], *, year: int, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 10:
            continue
        code = canonical_code(str(row[1] or ""))
        sequence = row[0]
        if not code or sequence in (None, "", '"'):
            continue
        try:
            float(sequence)
        except (TypeError, ValueError):
            continue
        record = {
            "code": display_code(code),
            "canonical_code": code,
            "board": "Main",
            "report_year": year,
            "official_english_name": normalize_text_field(row[2]),
            "prospectus_date": excel_date(row[3]),
            "listing_date": excel_date(row[4]),
            "sponsor": normalize_text_field(row[5]),
            "reporting_accountants": normalize_text_field(row[6]),
            "valuer": normalize_text_field(row[7]),
            "funds_raised_hkd": normalize_money(row[8]),
            "offer_price_hkd": normalize_money(row[9]),
            "source_urls": {"hkex_listing_report": source_url},
        }
        records.append({key: value for key, value in record.items() if value not in (None, "", {}, [])})
    return records


def parse_gem_rows(rows: list[list[Any]], *, year: int, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 13:
            continue
        listing_date = excel_date(row[0])
        code = canonical_code(str(row[1] or ""))
        if not listing_date or not code:
            continue
        record = {
            "code": display_code(code),
            "canonical_code": code,
            "board": "GEM",
            "report_year": year,
            "official_english_name": normalize_text_field(row[2]),
            "listing_date": listing_date,
            "offer_price_hkd": normalize_money(row[5]),
            "subscription_ratio": normalize_money(row[7]),
            "funds_raised_hkd": normalize_money(row[9]),
            "outstanding_shares_at_listing": normalize_money(row[10]),
            "market_cap_at_listing_hkd": normalize_money(row[12]),
            "source_urls": {"hkex_listing_report": source_url},
        }
        records.append({key: value for key, value in record.items() if value not in (None, "", {}, [])})
    return records


def parse_report_workbook(payload: bytes, *, board: str, year: int, source_url: str) -> list[dict[str, Any]]:
    rows = parse_xlsx_rows(payload)
    if board == "Main":
        return parse_main_rows(rows, year=year, source_url=source_url)
    if board == "GEM":
        return parse_gem_rows(rows, year=year, source_url=source_url)
    raise ValueError(f"Unsupported board: {board}")


def parse_years(value: str) -> list[int]:
    years = sorted({int(item.strip()) for item in value.split(",") if item.strip()}, reverse=True)
    if not years:
        raise argparse.ArgumentTypeError("Provide at least one year.")
    return years


def parse_boards(value: str) -> list[str]:
    boards = []
    for item in value.split(","):
        board = item.strip()
        if not board:
            continue
        normalized = "GEM" if board.upper() == "GEM" else "Main" if board.lower() in {"main", "main board"} else None
        if not normalized:
            raise argparse.ArgumentTypeError("Boards must be Main and/or GEM.")
        boards.append(normalized)
    return boards or ["Main", "GEM"]


def parse_report_files(values: list[str] | None) -> dict[tuple[str, int], str]:
    mapping: dict[tuple[str, int], str] = {}
    for value in values or []:
        parts = value.split("=", 2)
        if len(parts) != 3:
            raise argparse.ArgumentTypeError("--report-file must be BOARD=YEAR=PATH")
        board = parse_boards(parts[0])[0]
        mapping[(board, int(parts[1]))] = parts[2]
    return mapping


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    html_text, html_source = read_text(args.html, HKEX_NEW_LISTING_INFO_URL, timeout=args.timeout, retries=args.retries)
    links = parse_report_links(html_text, HKEX_BASE_URL)
    report_files = parse_report_files(args.report_file)
    records: list[dict[str, Any]] = []
    sources = [{"name": "HKEX New Listing Information page", "url": html_source, "status": "ok", "report_links": len(links)}]

    for year in args.years:
        for board in args.boards:
            file_path = report_files.get((board, year))
            url = links.get((board, year))
            try:
                if file_path:
                    payload = Path(file_path).read_bytes()
                    source_ref = f"fixture:{file_path}"
                elif url:
                    payload = fetch_bytes(url, timeout=args.timeout, retries=args.retries)
                    source_ref = url
                else:
                    sources.append({"name": f"HKEX {board} New Listing Report {year}", "status": "missing"})
                    continue
                parsed = parse_report_workbook(payload, board=board, year=year, source_url=source_ref)
                records.extend(parsed)
                sources.append(
                    {
                        "name": f"HKEX {board} New Listing Report {year}",
                        "url": source_ref,
                        "status": "ok",
                        "items": len(parsed),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                sources.append({"name": f"HKEX {board} New Listing Report {year}", "url": url, "status": "error", "error": str(exc)})

    records.sort(key=lambda item: (item.get("listing_date") or "9999-12-31", item.get("code") or ""))
    return {
        "generated_at": generated_at,
        "years": args.years,
        "boards": args.boards,
        "sources": sources,
        "records": records,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=parse_years, default=parse_years(str(dt.date.today().year)))
    parser.add_argument("--boards", type=parse_boards, default=parse_boards("Main,GEM"))
    parser.add_argument("--html", help="Fixture HTML file for the HKEX New Listing Information page.")
    parser.add_argument("--report-file", action="append", help="Fixture workbook as BOARD=YEAR=PATH.")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(args)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
