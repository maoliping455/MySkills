#!/usr/bin/env python3
"""Fetch current Hong Kong IPO data from public structured sources.

The script is stateless and dependency-free. It writes JSON to stdout and does
not store pages or credentials. HKEX/AASTOCKS pages can change, so parser
failures are returned as source-status entries instead of hard failures.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


AASTOCKS_UPCOMING_URL = (
    "https://www.aastocks.com/sc/stocks/market/ipo/upcomingipo/company-summary"
)
HKEX_MAIN_BOARD_URL = (
    "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board"
    "?sc_lang=zh-CN"
)
HKEX_GEM_URL = (
    "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/GEM"
    "?sc_lang=zh-CN"
)
USER_AGENT = "Mozilla/5.0 (compatible; hk-ipo-reference/0.1)"
STOCK_NAME_STATUS_HINTS = [
    "今日暗盘",
    "今日上市",
    "明日上市",
    "即将上市",
    "开始招股",
    "招股中",
    "截止认购",
    "跌穿上市价",
]


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def extract_stock_name_status(value: str | None) -> str | None:
    text = clean_text(value)
    for hint in STOCK_NAME_STATUS_HINTS:
        if hint in text:
            return hint
    return None


def clean_stock_name(value: str | None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = re.sub(r"(?<!\d)\d{4,5}(?:\.HK)?(?!\d)", "", text)
    for hint in STOCK_NAME_STATUS_HINTS:
        text = text.replace(hint, "")
    text = re.sub(r"\b(?:today|grey market|listed)\b", "", text, flags=re.IGNORECASE)
    return clean_text(text).strip(" -—|｜")


def parse_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text or text.upper() in {"N/A", "NA", "-"}:
        return None
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    number = parse_float(value)
    if number is None:
        return None
    return int(number)


def parse_date(value: str | None) -> str | None:
    text = clean_text(value)
    if not text or "不支援" in text or text.upper() in {"N/A", "NA", "-"}:
        return None
    patterns = [
        r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            year, month, day = (int(part) for part in match.groups())
            try:
                return dt.date(year, month, day).isoformat()
            except ValueError:
                return None
    return None


def canonical_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)(\d{4,5})(?:\.HK)?(?!\d)", value)
    if not match:
        return None
    return match.group(1).zfill(5)


def display_code(code: str | None) -> str | None:
    if not code:
        return None
    return f"{canonical_code(code)}.HK"


@dataclass
class Cell:
    text: str
    links: list[dict[str, str]]


class TableParser(HTMLParser):
    """Small table parser that preserves text and links per cell."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.rows: list[list[Cell]] = []
        self._row: list[Cell] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_links: list[dict[str, str]] | None = None
        self._link: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._cell_links = []
        elif tag == "a" and self._cell_parts is not None:
            href = attrs_dict.get("href", "")
            self._link = {"href": urljoin(self.base_url, href), "text_parts": []}

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._link is not None:
            self._link["text_parts"].append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._link is not None and self._cell_links is not None:
            href = self._link.get("href", "")
            if href:
                self._cell_links.append(
                    {
                        "href": str(href),
                        "text": clean_text("".join(self._link.get("text_parts", []))),
                    }
                )
            self._link = None
        elif tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(Cell(clean_text("".join(self._cell_parts)), self._cell_links or []))
            self._cell_parts = None
            self._cell_links = None
            self._link = None
        elif tag == "tr" and self._row is not None:
            if any(cell.text or cell.links for cell in self._row):
                self.rows.append(self._row)
            self._row = None


def parse_tables(html_text: str, base_url: str) -> list[list[Cell]]:
    parser = TableParser(base_url)
    parser.feed(html_text)
    return parser.rows


def fetch_url(url: str, timeout: int, retries: int) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                },
            )
            with urlopen(req, timeout=timeout) as response:
                raw = response.read()
            for encoding in ("utf-8", "big5", "gb18030"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_error}")


def read_html(path: str | None, url: str, timeout: int, retries: int) -> tuple[str, str]:
    if path:
        return Path(path).read_text(encoding="utf-8"), f"fixture:{path}"
    return fetch_url(url, timeout=timeout, retries=retries), url


def first_link(cell: Cell | None) -> str | None:
    if not cell:
        return None
    for link in cell.links:
        href = link.get("href")
        if href and not href.startswith("javascript:"):
            return href
    return None


def parse_aastocks_upcoming(html_text: str, base_url: str) -> list[dict[str, Any]]:
    rows = parse_tables(html_text, base_url)
    ipos: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        texts = [cell.text for cell in row]
        if len(row) < 8:
            continue
        code = canonical_code(texts[1] if len(texts) > 1 else "")
        if not code or code in seen:
            continue
        if len(texts) > 6 and "招股截止" in texts[6]:
            continue

        name_cell = row[1]
        status_hint = extract_stock_name_status(name_cell.text)
        name = clean_stock_name(name_cell.text)
        if not name and name_cell.links:
            name = clean_stock_name(name_cell.links[0].get("text", ""))

        ipo = {
            "code": display_code(code),
            "canonical_code": code,
            "name": name or None,
            "industry": texts[2] if len(texts) > 2 else None,
            "offer_price_raw": texts[3] if len(texts) > 3 else None,
            "offer_price_hkd": parse_float(texts[3] if len(texts) > 3 else None),
            "lot_size": parse_int(texts[4] if len(texts) > 4 else None),
            "entry_fee_hkd": parse_float(texts[5] if len(texts) > 5 else None),
            "closing_date": parse_date(texts[6] if len(texts) > 6 else None),
            "grey_market_date": parse_date(texts[7] if len(texts) > 7 else None),
            "listing_date": parse_date(texts[8] if len(texts) > 8 else None),
            "status": status_hint,
            "source_urls": {
                "aastocks_summary": AASTOCKS_UPCOMING_URL,
                "aastocks_detail": first_link(name_cell),
            },
            "documents": {},
            "raw": {"aastocks_upcoming_row": texts},
        }
        seen.add(code)
        ipos.append(ipo)

    return ipos


def parse_hkex_listing_rows(
    html_text: str, base_url: str, market: str
) -> list[dict[str, Any]]:
    rows = parse_tables(html_text, base_url)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        if len(row) < 5:
            continue
        code = canonical_code(row[0].text)
        if not code or code in seen:
            continue
        if not re.fullmatch(r"\d{4,5}", row[0].text.strip()):
            continue
        name = clean_stock_name(row[1].text)
        record = {
            "code": display_code(code),
            "canonical_code": code,
            "name": name or None,
            "market": market,
            "documents": {
                "listing_announcement_url": first_link(row[2]),
                "prospectus_url": first_link(row[3]),
                "allotment_result_url": first_link(row[4]),
            },
            "source_urls": {
                "hkex_listing_information": base_url,
            },
            "raw": {"hkex_row": [cell.text for cell in row]},
        }
        seen.add(code)
        records.append(record)

    return records


def parse_detail_fields(html_text: str, base_url: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in parse_tables(html_text, base_url):
        if len(row) != 2:
            continue
        label = clean_text(row[0].text).rstrip(":：")
        value = clean_text(row[1].text)
        if not label or not value:
            continue
        if len(label) > 30:
            continue
        fields[label] = value
    return fields


def apply_detail_fields(ipo: dict[str, Any], fields: dict[str, str]) -> None:
    detail_map = {
        "上市市场": "market",
        "行业": "industry",
        "背景": "listing_background",
        "业务主要地区": "business_region",
        "网址": "website",
        "每手股数": "lot_size",
        "招股价": "offer_price_raw",
        "上市市值": "market_cap_raw",
        "香港配售股份数目3": "hk_public_offer_shares_raw",
        "香港配售股份数目": "hk_public_offer_shares_raw",
        "保荐人": "sponsor",
        "包销商": "underwriters",
        "招股日期": "subscription_period_raw",
        "招股截止日": "closing_date",
        "暗盘日期": "grey_market_date",
        "上市日期": "listing_date",
    }

    ipo.setdefault("aastocks_detail_fields", {})
    for label, value in fields.items():
        normalized_label = label.replace(" ", "")
        key = detail_map.get(normalized_label)
        ipo["aastocks_detail_fields"][label] = value
        if not key:
            continue
        if key == "lot_size":
            ipo[key] = parse_int(value) or ipo.get(key)
        elif key == "offer_price_raw":
            ipo[key] = value
            ipo["offer_price_hkd"] = parse_float(value) or ipo.get("offer_price_hkd")
        elif key in {"closing_date", "grey_market_date", "listing_date"}:
            ipo[key] = parse_date(value) or ipo.get(key)
        else:
            ipo[key] = value

    period = fields.get("招股日期") or fields.get("招股日期 ")
    if period:
        dates = re.findall(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", period)
        if dates:
            ipo["subscription_start_date"] = parse_date(dates[0])
        if len(dates) > 1 and not ipo.get("closing_date"):
            ipo["closing_date"] = parse_date(dates[-1])


def merge_record(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if key == "source_urls":
            target.setdefault("source_urls", {}).update(value or {})
        elif key == "documents":
            target.setdefault("documents", {}).update(
                {k: v for k, v in (value or {}).items() if v}
            )
        elif key == "raw":
            target.setdefault("raw", {}).update(value or {})
        elif value not in (None, "", [], {}):
            if key not in target or target.get(key) in (None, "", [], {}):
                target[key] = value


def derive_status(ipo: dict[str, Any], as_of: dt.date) -> str:
    close = iso_to_date(ipo.get("closing_date"))
    listing = iso_to_date(ipo.get("listing_date"))
    if close and as_of <= close:
        return "招股中"
    if close and listing and close < as_of <= listing:
        return "已截止待上市"
    if listing and as_of > listing:
        return "已上市待复盘"
    return "待核实"


def iso_to_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    as_of = dt.date.fromisoformat(args.as_of_date) if args.as_of_date else dt.date.today()
    sources: list[dict[str, Any]] = []
    by_code: dict[str, dict[str, Any]] = {}

    try:
        html_text, source_ref = read_html(
            args.aastocks_html,
            AASTOCKS_UPCOMING_URL,
            timeout=args.timeout,
            retries=args.retries,
        )
        records = parse_aastocks_upcoming(html_text, AASTOCKS_UPCOMING_URL)
        for record in records:
            by_code[record["canonical_code"]] = record
        sources.append(
            {
                "name": "AASTOCKS current IPO",
                "url": source_ref,
                "status": "ok",
                "items": len(records),
            }
        )
    except Exception as exc:  # noqa: BLE001 - status payload should capture parser/network failures.
        sources.append(
            {
                "name": "AASTOCKS current IPO",
                "url": AASTOCKS_UPCOMING_URL,
                "status": "error",
                "error": str(exc),
            }
        )

    if not args.no_hkex:
        hkex_inputs = [
            ("HKEX Main Board", HKEX_MAIN_BOARD_URL, args.hkex_main_html, "主板"),
            ("HKEX GEM", HKEX_GEM_URL, args.hkex_gem_html, "GEM"),
        ]
        for name, url, fixture, market in hkex_inputs:
            try:
                html_text, source_ref = read_html(
                    fixture, url, timeout=args.timeout, retries=args.retries
                )
                records = parse_hkex_listing_rows(html_text, url, market)
                added = 0
                for record in records:
                    code = record["canonical_code"]
                    if code in by_code:
                        merge_record(by_code[code], record)
                    elif args.include_hkex_only or not by_code:
                        record.setdefault("source_urls", {})["hkex_listing_information"] = url
                        by_code[code] = record
                        added += 1
                sources.append(
                    {"name": name, "url": source_ref, "status": "ok", "items": len(records), "added": added}
                )
            except Exception as exc:  # noqa: BLE001
                sources.append({"name": name, "url": url, "status": "error", "error": str(exc)})

    if not args.no_details:
        detail_candidates = [
            ipo for ipo in by_code.values() if ipo.get("source_urls", {}).get("aastocks_detail")
        ][: max(0, args.max_details)]
        for ipo in detail_candidates:
            url = ipo["source_urls"]["aastocks_detail"]
            try:
                detail_html = fetch_url(url, timeout=args.timeout, retries=args.retries)
                fields = parse_detail_fields(detail_html, url)
                apply_detail_fields(ipo, fields)
                sources.append(
                    {
                        "name": f"AASTOCKS detail {ipo.get('code')}",
                        "url": url,
                        "status": "ok",
                        "fields": len(fields),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                sources.append(
                    {
                        "name": f"AASTOCKS detail {ipo.get('code')}",
                        "url": url,
                        "status": "error",
                        "error": str(exc),
                    }
                )

    ipos = sorted(
        by_code.values(),
        key=lambda item: (
            item.get("listing_date") or "9999-12-31",
            item.get("closing_date") or "9999-12-31",
            item.get("code") or "",
        ),
    )
    for ipo in ipos:
        ipo["status"] = derive_status(ipo, as_of)

    return {
        "generated_at": generated_at,
        "as_of_date": as_of.isoformat(),
        "sources": sources,
        "ipos": ipos,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", help="Override analysis date in YYYY-MM-DD format.")
    parser.add_argument("--aastocks-html", help="Fixture HTML file for AASTOCKS current IPO page.")
    parser.add_argument("--hkex-main-html", help="Fixture HTML file for HKEX Main Board page.")
    parser.add_argument("--hkex-gem-html", help="Fixture HTML file for HKEX GEM page.")
    parser.add_argument("--no-hkex", action="store_true", help="Skip HKEX enrichment.")
    parser.add_argument("--include-hkex-only", action="store_true", help="Include HKEX rows absent from AASTOCKS.")
    parser.add_argument("--no-details", action="store_true", help="Skip per-stock AASTOCKS detail pages.")
    parser.add_argument("--max-details", type=int, default=8, help="Maximum AASTOCKS detail pages to fetch.")
    parser.add_argument("--timeout", type=int, default=20, help="Network timeout in seconds.")
    parser.add_argument("--retries", type=int, default=2, help="Network retries after the first attempt.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(args)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
