#!/usr/bin/env python3
"""Backtest the Hong Kong IPO recommendation heuristic for a given year.

The backtest is stateless. It fetches AASTOCKS listed-IPO pages, enriches each
stock with public detail fields, scores only pre-listing/static fields, then
compares the resulting recommendation bucket with actual first-day performance.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import re
import statistics
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode

from build_recommendation_report import (
    DEFENSIVE_INDUSTRY_KEYWORDS,
    GENERIC_TECH_KEYWORDS,
    HARD_TECH_QUALITY_KEYWORDS,
    HOT_INDUSTRY_KEYWORDS,
    STRONG_SPONSOR_KEYWORDS,
    WEAK_INDUSTRY_KEYWORDS,
    chinese_display_alias,
    contains_chinese,
    margin_heat_for_ipo,
    money,
)
from calculate_subscription_return import calculate_return_metrics
from fetch_current_ipos import (
    canonical_code,
    clean_stock_name,
    clean_text,
    fetch_url,
    parse_date,
    parse_detail_fields,
    parse_float,
    parse_hkex_listing_rows,
    parse_int,
    parse_tables,
)
from fetch_hkex_listing_reports import (
    HKEX_BASE_URL as HKEX_REPORT_BASE_URL,
    HKEX_NEW_LISTING_INFO_URL as HKEX_REPORT_PAGE_URL,
    fetch_bytes as fetch_hkex_report_bytes,
    parse_report_links as parse_hkex_report_links,
    parse_report_workbook as parse_hkex_report_workbook,
)
from normalize_margin_input import strict_execution_ready, timing_evidence_valid


AASTOCKS_LISTED_URL = "https://www.aastocks.com/sc/stocks/market/ipo/listedipo.aspx"
AASTOCKS_DETAIL_URL = (
    "https://www.aastocks.com/sc/stocks/market/ipo/upcomingipo/company-summary?symbol={code}#info"
)
HKEX_MAIN_BOARD_URL = (
    "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=zh-CN"
)
HKEX_GEM_URL = "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/GEM?sc_lang=zh-CN"
USER_AGENT = "Mozilla/5.0 (compatible; hk-ipo-reference/0.1)"

SCARCE_SECTOR_KEYWORDS = [
    "先进硬件",
    "新一代信息技术",
    "半导体",
    "线路板",
    "机器人",
    "应用软件",
    "资讯科技",
    "电脑存储",
    "电讯及网络",
    "电子设备",
    "电器部件",
    "智能手机",
    "先进材料",
]
STRUCTURAL_WEAK_KEYWORDS = [
    "建筑",
    "美容护肤",
    "零售",
    "消闲用品",
    "包装",
    "汽车制造商",
]
MEDICAL_QUALITY_KEYWORDS = ["医疗器械", "医疗保健设备", "保健护理服务"]
FINANCING_TIERS = ["乙组候选", "甲组候选", "现金参与", "不融资"]
DEFAULT_BACKTEST_CASH_HKD = 550_000.0
SCORE_BANDS = [
    ("<58", 0, 57),
    ("58-64", 58, 64),
    ("65-71", 65, 71),
    ("72-77", 72, 77),
    ("78+", 78, 100),
]
CAPITAL_PRIORITY_STRATEGIES = [
    (
        "score",
        "基础分数优先",
        "先按事前分数排序，再按锁定窗口开始日排序。",
    ),
    (
        "score_entry",
        "分数+低入场费优先",
        "先按事前分数排序；同分时，低入场费和占款灵活度优先。",
    ),
    (
        "utility_score_entry",
        "事前效用组合最优",
        "在每个重叠窗口组内最大化事前分数、受限入场敞口和锁定天数组合效用；不使用复盘收益。",
    ),
    (
        "tier_score_entry",
        "融资分层+分数+低入场费",
        "先按事前融资分层排序，再按分数和低入场费排序。",
    ),
    (
        "entry_score",
        "低入场费+分数优先",
        "先按低入场费排序，再按事前分数排序。",
    ),
]
CAPITAL_PRIORITY_LABELS = {code: label for code, label, _ in CAPITAL_PRIORITY_STRATEGIES}
CAPITAL_PRIORITY_DESCRIPTIONS = {code: description for code, _, description in CAPITAL_PRIORITY_STRATEGIES}
CAPITAL_TIER_RANK = {"乙组候选": 0, "甲组候选": 1, "现金参与": 2, "不融资": 3}


def pct(value: float | None) -> str:
    if value is None:
        return "待核实"
    return f"{value:+.2f}%"


def to_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if not value:
        return None
    parsed = parse_date(str(value))
    if not parsed:
        return None
    try:
        return dt.date.fromisoformat(parsed)
    except ValueError:
        return None


def parse_name_code(value: str) -> tuple[str | None, str | None]:
    code = canonical_code(value)
    if not code:
        return None, None
    name = clean_stock_name(value)
    return name or None, f"{code}.HK"


def display_stock(record: dict[str, Any]) -> str:
    code = record.get("code") or (f"{record.get('canonical_code')}.HK" if record.get("canonical_code") else "")
    name = clean_stock_name(record.get("name") or "")
    if contains_chinese(name):
        return f"{name}（{code}）" if code else name
    alias = chinese_display_alias(record)
    if alias:
        return f"{alias}（{code}）" if code else alias
    if code:
        return f"代码{code}（中文名待核实）"
    return "未命名新股（中文名待核实）"


def has_prospectus_or_detail(record: dict[str, Any]) -> bool:
    return bool(record.get("documents", {}).get("prospectus_url") or record.get("source_urls", {}).get("aastocks_detail"))


def has_official_listing_report(record: dict[str, Any]) -> bool:
    return bool(record.get("source_urls", {}).get("hkex_listing_report") or record.get("hkex_listing_report_match"))


def has_official_static_source(record: dict[str, Any]) -> bool:
    return has_prospectus_or_detail(record) or has_official_listing_report(record)


def fetch_listed_page(page: int, timeout: int, retries: int) -> str:
    query = urlencode({"s": 3, "o": 0, "page": page})
    listed_timeout = max(12, timeout * 2)
    return fetch_detail_url(f"{AASTOCKS_LISTED_URL}?{query}", timeout=listed_timeout, retries=retries)


def parse_listed_rows(html_text: str, base_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in parse_tables(html_text, base_url):
        texts = [cell.text for cell in row]
        if len(texts) < 13:
            continue
        listing_date = parse_date(texts[2])
        name, code = parse_name_code(texts[1])
        if not listing_date or not code:
            continue
        lot_size = parse_int(texts[3])
        listing_price = parse_float(texts[6])
        entry_fee = None
        if lot_size and listing_price:
            entry_fee = lot_size * listing_price * 1.0077
        rows.append(
            {
                "code": code,
                "canonical_code": canonical_code(code),
                "name": name,
                "listing_date": listing_date,
                "lot_size": lot_size,
                "offer_price_raw": texts[4] if texts[4] and texts[4].upper() != "N/A" else None,
                "offer_price_hkd": parse_float(texts[5]) or parse_float(texts[6]),
                "listing_price_hkd": listing_price,
                "entry_fee_hkd": entry_fee,
                "oversubscription_rate": parse_float(texts[7]),
                "applied_lots_for_one_lot": None if texts[8].upper() == "N/A" else texts[8],
                "one_lot_success_rate_pct": parse_float(texts[9]),
                "current_price_hkd": parse_float(texts[10]),
                "first_day_change_pct": parse_float(texts[11]),
                "cumulative_change_pct": parse_float(texts[12]),
                "source_urls": {"aastocks_listed": f"{AASTOCKS_LISTED_URL}?s=3&o=0&page=1"},
                "raw": {"listed_row": texts},
            }
        )
    return rows


def fetch_year_listed(year: int, max_pages: int, timeout: int, retries: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    start = dt.date(year, 1, 1)
    stop = False
    for page in range(1, max_pages + 1):
        url = f"{AASTOCKS_LISTED_URL}?s=3&o=0&page={page}"
        try:
            html_text = fetch_listed_page(page, timeout=timeout, retries=retries)
            page_records = parse_listed_rows(html_text, url)
            sources.append({"name": f"AASTOCKS listed IPO page {page}", "url": url, "status": "ok", "items": len(page_records)})
        except Exception as exc:  # noqa: BLE001
            sources.append({"name": f"AASTOCKS listed IPO page {page}", "url": url, "status": "error", "error": str(exc)})
            break

        if not page_records:
            break
        for record in page_records:
            listing = dt.date.fromisoformat(record["listing_date"])
            if listing.year == year and record["code"] not in seen:
                seen.add(record["code"])
                records.append(record)
            elif listing < start:
                stop = True
        if stop:
            break
    records.sort(key=lambda item: item["listing_date"])
    return records, sources


def enrich_one_detail(record: dict[str, Any], *, timeout: int, retries: int) -> dict[str, Any]:
    item = dict(record)
    code = record["canonical_code"]
    url = AASTOCKS_DETAIL_URL.format(code=code)
    item.setdefault("source_urls", {})["aastocks_detail"] = url
    try:
        html_text = fetch_detail_url(url, timeout=timeout, retries=retries)
        fields = parse_detail_fields(html_text, url)
        apply_detail_fields(item, fields)
        item["detail_status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        item["detail_status"] = f"error: {exc}"
    return item


def fetch_detail_url(url: str, *, timeout: int, retries: int) -> str:
    """Fetch detail pages with a hard wall-clock timeout.

    AASTOCKS detail pages occasionally hang during TLS negotiation in urllib on
    this environment. curl's --max-time gives the backtest a reliable cutoff.
    """

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            completed = subprocess.run(
                [
                    "curl",
                    "-fsSL",
                    "--compressed",
                    "--max-time",
                    str(max(1, timeout)),
                    "-A",
                    USER_AGENT,
                    "-H",
                    "Accept-Language: zh-CN,zh;q=0.9,en;q=0.6",
                    url,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(2, timeout + 2),
            )
            return completed.stdout.decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"detail fetch failed: {last_error}")


def enrich_details(
    records: list[dict[str, Any]],
    *,
    timeout: int,
    retries: int,
    delay: float,
    max_details: int | None,
    workers: int,
) -> list[dict[str, Any]]:
    if max_details is not None:
        target_records = records[:max_details]
        untouched = records[max_details:]
    else:
        target_records = records
        untouched = []

    if workers <= 1:
        enriched: list[dict[str, Any]] = []
        for record in target_records:
            enriched.append(enrich_one_detail(record, timeout=timeout, retries=retries))
            if delay:
                time.sleep(delay)
        return retry_failed_details(enriched, timeout=timeout, retries=retries, delay=delay) + untouched

    enriched_by_code: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(enrich_one_detail, record, timeout=timeout, retries=retries): record
            for record in target_records
        }
        for future in concurrent.futures.as_completed(futures):
            original = futures[future]
            try:
                item = future.result()
            except Exception as exc:  # noqa: BLE001
                item = dict(original)
                item["detail_status"] = f"error: {exc}"
            enriched_by_code[item["canonical_code"]] = item
    enriched = [enriched_by_code.get(record["canonical_code"], record) for record in target_records]
    enriched = retry_failed_details(enriched, timeout=timeout, retries=retries, delay=delay)
    return enriched + untouched


def retry_failed_details(
    records: list[dict[str, Any]],
    *,
    timeout: int,
    retries: int,
    delay: float,
    limit: int = 30,
    target_ratio: float = 0.70,
) -> list[dict[str, Any]]:
    """Retry failed detail pages sequentially with a longer timeout.

    AASTOCKS detail fetches are the noisiest part of the backtest. A small
    sequential retry pass improves data coverage without persisting pages or
    making final scoring depend on network timing.
    """

    if limit <= 0 or not records:
        return records
    result = list(records)
    target_ok_count = min(len(result), math.ceil(len(result) * target_ratio))
    current_ok_count = sum(1 for record in result if record.get("detail_status") == "ok")
    if current_ok_count >= target_ok_count:
        return result
    retry_timeout = max(12, timeout * 3)
    retry_retries = max(1, retries)
    failed_indexes = [
        index
        for index, record in enumerate(result)
        if record.get("canonical_code") and record.get("detail_status") != "ok"
    ][:limit]
    for index in failed_indexes:
        if current_ok_count >= target_ok_count:
            break
        retried = enrich_one_detail(result[index], timeout=retry_timeout, retries=retry_retries)
        if retried.get("detail_status") == "ok":
            retried["detail_retry_status"] = "ok"
            current_ok_count += 1
        else:
            retried["detail_retry_status"] = retried.get("detail_status") or "error"
        result[index] = retried
        if delay:
            time.sleep(delay)
    return result


def apply_detail_fields(item: dict[str, Any], fields: dict[str, str]) -> None:
    item["aastocks_detail_fields"] = fields
    mapping = {
        "上市市场": "market",
        "行业": "industry",
        "背景": "listing_background",
        "业务主要地区": "business_region",
        "每手股数": "lot_size",
        "招股价": "offer_price_raw",
        "入场费": "entry_fee_hkd",
        "上市市值": "market_cap_raw",
        "香港配售股份数目3": "hk_public_offer_shares_raw",
        "香港发售股份数目": "hk_public_offer_shares_raw",
        "保荐人": "sponsor",
        "包销商": "underwriters",
        "公布售股结果日期": "allotment_date",
        "退票寄发日期": "refund_date",
        "上市日期": "listing_date",
    }
    for label, value in fields.items():
        key = mapping.get(label.replace(" ", ""))
        if not key:
            continue
        if key == "lot_size":
            item[key] = parse_int(value) or item.get(key)
        elif key == "entry_fee_hkd":
            item[key] = parse_float(value) or item.get(key)
        elif key in {"allotment_date", "refund_date", "listing_date"}:
            item[key] = parse_date(value) or item.get(key)
        else:
            item[key] = value
    period = fields.get("招股日期")
    if period:
        dates = re.findall(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", period)
        if dates:
            item["subscription_start_date"] = parse_date(dates[0])
        if len(dates) > 1:
            item["closing_date"] = parse_date(dates[-1])
    if not item.get("entry_fee_hkd") and item.get("lot_size") and item.get("listing_price_hkd"):
        item["entry_fee_hkd"] = float(item["lot_size"]) * float(item["listing_price_hkd"]) * 1.0077


def enrich_hkex_documents(records: list[dict[str, Any]], timeout: int, retries: int) -> list[dict[str, Any]]:
    by_code = {record["canonical_code"]: record for record in records}
    for market, url in [("主板", HKEX_MAIN_BOARD_URL), ("GEM", HKEX_GEM_URL)]:
        try:
            html_text = fetch_url(url, timeout=timeout, retries=retries)
            rows = parse_hkex_listing_rows(html_text, url, market)
        except Exception:
            continue
        for row in rows:
            target = by_code.get(row.get("canonical_code"))
            if not target:
                continue
            target.setdefault("documents", {}).update(row.get("documents") or {})
            target.setdefault("source_urls", {})["hkex_listing_information"] = url
            if row.get("name") and (not target.get("name") or contains_chinese(row.get("name"))):
                target["name"] = row.get("name")
    return records


def enrich_hkex_listing_reports(
    records: list[dict[str, Any]],
    *,
    year: int,
    timeout: int,
    retries: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    if not records:
        return records, sources

    try:
        html_text = fetch_hkex_report_bytes(HKEX_REPORT_PAGE_URL, timeout=timeout, retries=retries).decode("utf-8", errors="ignore")
        links = parse_hkex_report_links(html_text, HKEX_REPORT_BASE_URL)
        sources.append(
            {
                "name": "HKEX New Listing Report index",
                "url": HKEX_REPORT_PAGE_URL,
                "status": "ok",
                "report_links": len(links),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return records, [{"name": "HKEX New Listing Report index", "url": HKEX_REPORT_PAGE_URL, "status": "error", "error": str(exc)}]

    report_records: list[dict[str, Any]] = []
    for board in ["Main", "GEM"]:
        url = links.get((board, year))
        if not url:
            sources.append({"name": f"HKEX {board} New Listing Report {year}", "status": "missing"})
            continue
        try:
            payload = fetch_hkex_report_bytes(url, timeout=timeout, retries=retries)
            parsed = parse_hkex_report_workbook(payload, board=board, year=year, source_url=url)
            report_records.extend(parsed)
            sources.append({"name": f"HKEX {board} New Listing Report {year}", "url": url, "status": "ok", "items": len(parsed)})
        except Exception as exc:  # noqa: BLE001
            sources.append({"name": f"HKEX {board} New Listing Report {year}", "url": url, "status": "error", "error": str(exc)})

    stats = apply_hkex_report_records(records, report_records)
    sources.append({"name": f"HKEX listing report merge {year}", "status": "ok", **stats})
    return records, sources


def apply_hkex_report_records(records: list[dict[str, Any]], report_records: list[dict[str, Any]]) -> dict[str, int]:
    by_code = {record.get("canonical_code"): record for record in records if record.get("canonical_code")}
    stats = {"matches": 0, "sponsor_filled": 0, "offer_price_filled": 0, "listing_date_filled": 0}
    for report in report_records:
        target = by_code.get(report.get("canonical_code"))
        if not target:
            continue
        stats["matches"] += 1
        target["hkex_listing_report_match"] = True
        target.setdefault("source_urls", {}).update(report.get("source_urls") or {})
        for key in ["official_english_name", "funds_raised_hkd", "board", "prospectus_date"]:
            if report.get(key) not in (None, "", [], {}):
                target.setdefault(key, report[key])
        if not target.get("sponsor") and report.get("sponsor"):
            target["sponsor"] = report["sponsor"]
            stats["sponsor_filled"] += 1
        if not target.get("offer_price_hkd") and report.get("offer_price_hkd") is not None:
            target["offer_price_hkd"] = report["offer_price_hkd"]
            stats["offer_price_filled"] += 1
        if not target.get("listing_date") and report.get("listing_date"):
            target["listing_date"] = report["listing_date"]
            stats["listing_date_filled"] += 1
    return stats


def static_score(record: dict[str, Any], *, optimized: bool = False) -> dict[str, Any]:
    score = 50
    evidence: list[str] = []
    risks: list[str] = []

    entry_fee = record.get("entry_fee_hkd")
    if isinstance(entry_fee, (int, float)):
        if entry_fee <= 5_000:
            score += 6
            evidence.append("低入场费")
        elif entry_fee <= 30_000:
            score += 3
            evidence.append("入场费可控")
        elif entry_fee >= 100_000:
            score -= 6
            risks.append("高入场费")
    else:
        score -= 6
        risks.append("缺入场费")

    industry = record.get("industry") or ""
    hot = [kw for kw in HOT_INDUSTRY_KEYWORDS if kw.lower() in industry.lower()]
    weak = [kw for kw in WEAK_INDUSTRY_KEYWORDS if kw in industry]
    defensive = [kw for kw in DEFENSIVE_INDUSTRY_KEYWORDS if kw in industry]
    if hot:
        score += 7
        evidence.append("热门行业：" + "、".join(hot[:2]))
    elif defensive:
        score += 2
        evidence.append("防守行业：" + "、".join(defensive[:2]))
    if weak:
        score -= 5
        risks.append("弱题材行业：" + "、".join(weak[:2]))

    name_background = f"{record.get('name') or ''} {record.get('listing_background') or ''}"
    if "－Ｂ" in name_background or "-B" in name_background or "生物科技" in industry:
        penalty = 4 if optimized else 8
        score -= penalty
        risks.append("B类/生物科技")
    if "－Ｐ" in name_background or "-P" in name_background:
        penalty = 3 if optimized else 8
        score -= penalty
        risks.append("P类/18C")
    if "－Ｗ" in name_background or "-W" in name_background:
        risks.append("WVR")

    sponsor = record.get("sponsor") or ""
    if sponsor:
        if any(keyword in sponsor for keyword in STRONG_SPONSOR_KEYWORDS):
            score += 6
            evidence.append("强保荐人")
        else:
            score += 1
            evidence.append("保荐人已披露")
    else:
        score -= 3
        risks.append("缺保荐人")

    if record.get("hk_public_offer_shares_raw"):
        score += 2
        evidence.append("公开发售字段已披露")
    else:
        risks.append("缺公开发售字段")

    if has_prospectus_or_detail(record):
        score += 4
        evidence.append("可查招股资料")
    elif has_official_listing_report(record):
        score += 2
        evidence.append("可查HKEX年度上市报告")
        risks.append("缺招股书/详情页字段")
    else:
        score -= 5
        risks.append("缺招股资料")

    if optimized:
        listing_price = record.get("listing_price_hkd")
        oversub = record.get("oversubscription_rate")
        one_lot = record.get("one_lot_success_rate_pct")
        # This branch is a review-only calibration label based on final
        # allotment-result data. It must not drive pre-close financing decisions.
        if isinstance(oversub, (int, float)):
            if oversub >= 1000:
                score += 10
                evidence.append("最终超购强")
            elif oversub < 50:
                score -= 8
                risks.append("最终热度弱")
        if isinstance(one_lot, (int, float)) and one_lot <= 2:
            score += 3
            evidence.append("一手中签率极低")
        if isinstance(listing_price, (int, float)) and listing_price >= 80 and not hot:
            score -= 6
            risks.append("高价非热门")

    score = max(0, min(100, score))
    action = "建议申购" if score >= 70 else "可选观察" if score >= 55 else "暂不参与"
    return {"score": score, "action": action, "evidence": evidence, "risks": risks}


def optimized_preclose_score(record: dict[str, Any]) -> dict[str, Any]:
    """Score only information that can be known before the subscription closes."""

    score = 48
    evidence: list[str] = []
    risks: list[str] = []

    entry_fee = record.get("entry_fee_hkd")
    if isinstance(entry_fee, (int, float)):
        if entry_fee <= 5_000:
            score += 7
            evidence.append("低入场费")
        elif entry_fee <= 10_000:
            score += 5
            evidence.append("入场费较低")
        elif entry_fee <= 30_000:
            score += 2
            evidence.append("入场费可控")
        elif entry_fee >= 100_000:
            score -= 10
            risks.append("极高入场费")
        elif entry_fee >= 50_000:
            score -= 5
            risks.append("高入场费")
    else:
        score -= 4
        risks.append("缺入场费")

    industry = record.get("industry") or ""
    scarce = [kw for kw in SCARCE_SECTOR_KEYWORDS if kw in industry]
    hot = [kw for kw in HOT_INDUSTRY_KEYWORDS if kw.lower() in industry.lower()]
    medical_quality = [kw for kw in MEDICAL_QUALITY_KEYWORDS if kw in industry]
    weak = [kw for kw in STRUCTURAL_WEAK_KEYWORDS if kw in industry]
    generic_tech = [kw for kw in GENERIC_TECH_KEYWORDS if kw in industry]
    hard_tech = [kw for kw in HARD_TECH_QUALITY_KEYWORDS if kw.lower() in industry.lower()]

    if scarce:
        score += 10
        evidence.append("稀缺/科技行业：" + "、".join(scarce[:2]))
    elif hot:
        score += 7
        evidence.append("热门行业：" + "、".join(hot[:2]))
    elif medical_quality:
        score += 5
        evidence.append("医疗器械/服务：" + "、".join(medical_quality[:2]))
    elif any(keyword in industry for keyword in DEFENSIVE_INDUSTRY_KEYWORDS):
        score += 1
        evidence.append("防守行业")

    if weak:
        score -= 4
        risks.append("弱结构行业：" + "、".join(weak[:2]))

    name_background = f"{record.get('name') or ''} {record.get('listing_background') or ''}"
    is_b = "－Ｂ" in name_background or "-B" in name_background or "生物科技" in industry
    is_p = "－Ｐ" in name_background or "-P" in name_background
    is_w = "－Ｗ" in name_background or "-W" in name_background
    if is_b:
        score -= 3
        risks.append("B类/生物科技，需融资截止前再确认热度")
    if is_p:
        score -= 2
        risks.append("P类/18C，商业化不确定")
    if is_w:
        risks.append("WVR")

    sponsor = record.get("sponsor") or ""
    strong_sponsor = any(keyword in sponsor for keyword in STRONG_SPONSOR_KEYWORDS)
    if sponsor:
        if strong_sponsor:
            score += 8
            evidence.append("强保荐人")
        else:
            score += 2
            evidence.append("保荐人已披露")
    else:
        score -= 1
        risks.append("缺保荐人")

    if record.get("hk_public_offer_shares_raw"):
        score += 2
        evidence.append("公开发售字段已披露")
    else:
        risks.append("缺公开发售字段")

    if has_prospectus_or_detail(record):
        score += 4
        evidence.append("可查招股资料")
    elif has_official_listing_report(record):
        score += 2
        evidence.append("可查HKEX年度上市报告")
        risks.append("缺招股书/详情页字段")
    else:
        score -= 3
        risks.append("缺招股资料")

    regime = record.get("market_regime") or {}
    regime_label = regime.get("label")
    if regime_label == "偏热":
        evidence.append("近期新股市场偏热")
    elif regime_label == "偏冷":
        risks.append("近期新股市场偏冷，降低融资强度")

    listing_price = record.get("listing_price_hkd")
    if isinstance(listing_price, (int, float)) and listing_price >= 80 and not (scarce or hot):
        score -= 7
        risks.append("高价非稀缺行业")

    if is_b and (scarce or medical_quality or strong_sponsor) and isinstance(entry_fee, (int, float)) and entry_fee <= 10_000:
        score += 3
        evidence.append("B/P不直接跳过：低入场费且有质量信号")

    score = max(0, min(100, score))
    action = "建议申购" if score >= 72 else "可选观察" if score >= 58 else "暂不参与"
    if (
        action == "建议申购"
        and regime_label in {"中性", "偏冷"}
        and generic_tech
        and not hard_tech
    ):
        action = "可选观察"
        risks.append("非热市下泛软件/泛IT题材先降为观察")
    if (
        action == "暂不参与"
        and regime_label == "偏热"
        and score >= 52
        and isinstance(entry_fee, (int, float))
        and entry_fee <= 10_000
        and has_official_static_source(record)
    ):
        action = "可选观察"
        risks.append("偏热市场下低入场费且有公开资料，先观察而非直接跳过")
    if (
        action == "暂不参与"
        and regime_label == "偏热"
        and score >= 52
        and isinstance(entry_fee, (int, float))
        and entry_fee <= 30_000
        and strong_sponsor
        and has_prospectus_or_detail(record)
    ):
        action = "可选观察"
        risks.append("偏热市场下强保荐且资料完整，先观察而非直接跳过")
    financing = financing_decision(
        record,
        score,
        action,
        scarce=bool(scarce),
        hot=bool(hot),
        strong_sponsor=strong_sponsor,
        risks=risks,
        market_regime=regime_label,
    )
    return {
        "score": score,
        "action": action,
        "evidence": evidence,
        "risks": risks,
        "financing": financing,
    }


def financing_decision(
    record: dict[str, Any],
    score: int,
    action: str,
    *,
    scarce: bool,
    hot: bool,
    strong_sponsor: bool,
    risks: list[str],
    market_regime: str | None = None,
) -> dict[str, Any]:
    entry_fee = record.get("entry_fee_hkd")
    if action == "暂不参与" or not isinstance(entry_fee, (int, float)):
        return {"tier": "不融资", "reason": "推荐级别或入场费不支持融资"}

    high_price_risk = any("高价" in risk or "极高入场费" in risk or "高入场费" in risk for risk in risks)
    if market_regime == "偏冷":
        if action == "建议申购" and score >= 72 and entry_fee <= 30_000 and not high_price_risk:
            return {
                "tier": "甲组候选",
                "reason": "近期新股市场偏冷，乙组暂停执行；仅考虑甲组高位/现金多手",
            }
        if action in {"建议申购", "可选观察"}:
            return {"tier": "现金参与", "reason": "近期新股市场偏冷，现金一手/少量多手优先，不默认融资"}

    if (
        action == "建议申购"
        and score >= 78
        and entry_fee <= 15_000
        and (scarce or hot)
        and strong_sponsor
        and not high_price_risk
    ):
        return {
            "tier": "乙组候选",
            "reason": "事前质量高；仍需在融资截止前确认至少两个需求/额度类热度信号且成本可接受",
        }
    if action == "建议申购" and score >= 72 and entry_fee <= 30_000 and not high_price_risk:
        return {
            "tier": "甲组候选",
            "reason": "适合甲组高位或现金多手；乙组需至少两个需求/额度类热度信号且成本可接受",
        }
    if action in {"建议申购", "可选观察"}:
        return {"tier": "现金参与", "reason": "现金一手/少量多手优先，不默认融资"}
    return {"tier": "不融资", "reason": "风险收益不支持融资"}


def infer_market_regime(
    history: list[dict[str, Any]],
    *,
    window: int = 20,
    min_samples: int = 8,
    strong_threshold: float = 20.0,
) -> dict[str, Any]:
    """Infer IPO market temperature from already-listed previous IPOs only."""

    returns = [
        float(item["first_day_change_pct"])
        for item in history
        if isinstance(item.get("first_day_change_pct"), (int, float))
    ][-window:]
    if len(returns) < min_samples:
        return {
            "label": "样本不足",
            "sample_size": len(returns),
            "median_first_day_pct": None,
            "positive_rate": None,
            "strong_rate": None,
            "break_even_or_down_rate": None,
        }

    positive_rate = sum(1 for value in returns if value > 0) / len(returns)
    strong_rate = sum(1 for value in returns if value >= strong_threshold) / len(returns)
    break_even_or_down_rate = sum(1 for value in returns if value <= 0) / len(returns)
    median_return = statistics.median(returns)

    heat_score = 0
    if median_return >= 15:
        heat_score += 2
    elif median_return >= 8:
        heat_score += 1
    elif median_return <= 3:
        heat_score -= 1

    if positive_rate >= 0.75:
        heat_score += 1
    elif positive_rate < 0.55:
        heat_score -= 1

    if strong_rate >= 0.40:
        heat_score += 1
    elif strong_rate < 0.20:
        heat_score -= 1

    if break_even_or_down_rate >= 0.35:
        heat_score -= 2
    elif break_even_or_down_rate <= 0.20:
        heat_score += 1

    if heat_score >= 3:
        label = "偏热"
    elif heat_score <= -2:
        label = "偏冷"
    else:
        label = "中性"

    return {
        "label": label,
        "sample_size": len(returns),
        "median_first_day_pct": median_return,
        "positive_rate": positive_rate,
        "strong_rate": strong_rate,
        "break_even_or_down_rate": break_even_or_down_rate,
    }


def attach_market_regimes(
    records: list[dict[str, Any]],
    *,
    window: int = 20,
    min_samples: int = 8,
    strong_threshold: float = 20.0,
) -> None:
    dated_records = sorted(records, key=lambda item: to_date(item.get("listing_date")) or dt.date.max)
    for record in dated_records:
        decision_date = to_date(record.get("closing_date")) or to_date(record.get("listing_date"))
        if not decision_date:
            record["market_regime"] = infer_market_regime([], window=window, min_samples=min_samples, strong_threshold=strong_threshold)
            continue
        history = [
            item
            for item in dated_records
            if item is not record
            and (to_date(item.get("listing_date")) or dt.date.max) < decision_date
        ]
        record["market_regime"] = infer_market_regime(
            history,
            window=window,
            min_samples=min_samples,
            strong_threshold=strong_threshold,
        )


def actual_label(first_day: float | None, threshold: float) -> str:
    if first_day is None:
        return "未知"
    if first_day >= threshold:
        return "强收益"
    if first_day > 0:
        return "正收益"
    return "破发/不涨"


def expected_one_lot_gross_pnl(record: dict[str, Any]) -> float | None:
    """Review-only one-lot expected gross P/L proxy.

    This uses final one-lot success rate and first-day move, so it must stay in
    post-listing review metrics and never feed pre-close recommendation scores.
    """

    entry_fee = record.get("entry_fee_hkd")
    first_day = record.get("first_day_change_pct")
    one_lot = record.get("one_lot_success_rate_pct")
    if not all(isinstance(value, (int, float)) for value in [entry_fee, first_day, one_lot]):
        return None
    if float(entry_fee) <= 0:
        return None
    metrics = calculate_return_metrics(
        entry_fee_hkd=float(entry_fee),
        first_day_pct=float(first_day),
        one_lot_success_rate_pct=float(one_lot),
        cash_hkd=float(entry_fee),
        margin_multiple=1.0,
        application_amount_hkd=float(entry_fee),
    )
    value = metrics["returns"]["expected_one_lot_gross_pnl_hkd"]
    return float(value) if value is not None else None


def return_proxy_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        value
        for value in (expected_one_lot_gross_pnl(item) for item in items)
        if isinstance(value, (int, float))
    ]
    return {
        "return_proxy_sample_count": len(values),
        "avg_expected_one_lot_pnl_hkd": statistics.mean(values) if values else None,
        "median_expected_one_lot_pnl_hkd": statistics.median(values) if values else None,
        "positive_expected_pnl_rate": sum(1 for value in values if value > 0) / len(values) if values else None,
    }


def parse_iso_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def capital_lock_window(record: dict[str, Any]) -> tuple[dt.date | None, dt.date | None]:
    start = parse_iso_date(record.get("closing_date"))
    end = parse_iso_date(record.get("refund_date") or record.get("allotment_date") or record.get("listing_date"))
    return start, end


def windows_overlap(
    left: tuple[dt.date | None, dt.date | None],
    right: tuple[dt.date | None, dt.date | None],
) -> bool:
    if not all(left) or not all(right):
        return False
    left_start, left_end = left
    right_start, right_end = right
    return bool(left_start <= right_end and right_start <= left_end)


def backtest_cash_reserve(record: dict[str, Any], *, cash_hkd: float = DEFAULT_BACKTEST_CASH_HKD) -> float:
    entry_fee = record.get("entry_fee_hkd")
    if not isinstance(entry_fee, (int, float)) or entry_fee <= 0:
        return 0.0
    if record.get("recommendation", {}).get("action") != "建议申购":
        return 0.0
    return min(float(cash_hkd), max(float(entry_fee), float(cash_hkd) * 0.5))


def peak_capital_reserved(items: list[dict[str, Any]]) -> float:
    events: list[tuple[dt.date, int, float]] = []
    for item in items:
        start, end = item.get("_capital_window", (None, None))
        required = float(item.get("_capital_required_hkd") or 0.0)
        if start and end and required > 0:
            events.append((start, 1, required))
            events.append((end + dt.timedelta(days=1), 0, -required))
    peak_cash = 0.0
    running_cash = 0.0
    for _, _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        running_cash += delta
        peak_cash = max(peak_cash, running_cash)
    return peak_cash


def capital_priority_key(item: dict[str, Any], *, strategy: str) -> tuple[Any, ...]:
    rec = item.get("recommendation") or {}
    score = int(rec.get("score") or 0)
    entry_fee = item.get("entry_fee_hkd")
    entry_value = float(entry_fee) if isinstance(entry_fee, (int, float)) and entry_fee > 0 else float("inf")
    start_date = item.get("_capital_window", (None, None))[0] or dt.date.max
    name = display_stock(item)
    tier = ((rec.get("financing") or {}).get("tier")) or "不融资"
    tier_rank = CAPITAL_TIER_RANK.get(tier, 9)
    if strategy == "score":
        return (-score, start_date, name)
    if strategy == "score_entry":
        return (-score, entry_value, start_date, name)
    if strategy == "utility_score_entry":
        return (-capital_preclose_utility(item), start_date, name)
    if strategy == "tier_score_entry":
        return (tier_rank, -score, entry_value, start_date, name)
    if strategy == "entry_score":
        return (entry_value, -score, start_date, name)
    return (-score, entry_value, start_date, name)


def capital_lock_days(item: dict[str, Any]) -> int:
    start, end = item.get("_capital_window", (None, None))
    if start and end:
        return (end - start).days + 1
    return 999


def capital_preclose_utility(item: dict[str, Any], *, cash_hkd: float = DEFAULT_BACKTEST_CASH_HKD) -> float:
    rec = item.get("recommendation") or {}
    score = float(rec.get("score") or 0)
    entry_fee = item.get("entry_fee_hkd")
    capped_entry = min(float(entry_fee), float(cash_hkd)) if isinstance(entry_fee, (int, float)) and entry_fee > 0 else 0.0
    # Score dominates. Entry exposure only breaks close-score ties, and shorter lock-up improves reuse.
    return score * 100.0 + capped_entry / 10_000.0 - capital_lock_days(item)


def capital_connected_components(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    components: list[list[dict[str, Any]]] = []
    remaining = set(range(len(records)))
    while remaining:
        start = remaining.pop()
        stack = [start]
        component = {start}
        while stack:
            idx = stack.pop()
            left = records[idx].get("_capital_window") or (None, None)
            for other in list(remaining):
                right = records[other].get("_capital_window") or (None, None)
                if windows_overlap(left, right):
                    remaining.remove(other)
                    component.add(other)
                    stack.append(other)
        components.append([records[index] for index in sorted(component)])
    return components


def utility_best_subset(component: list[dict[str, Any]], *, cash_hkd: float) -> list[dict[str, Any]]:
    best_subset: list[dict[str, Any]] = []
    best_key: tuple[float, int, float, str] | None = None
    size = len(component)
    if size > 22:
        ordered = sorted(component, key=lambda item: capital_priority_key(item, strategy="utility_score_entry"))
        selected: list[dict[str, Any]] = []
        for item in ordered:
            if peak_capital_reserved([*selected, item]) <= cash_hkd + 1e-6:
                selected.append(item)
        return selected
    for mask in range(1 << size):
        subset = [component[index] for index in range(size) if mask & (1 << index)]
        peak = peak_capital_reserved(subset)
        if peak > cash_hkd + 1e-6:
            continue
        utility = sum(capital_preclose_utility(item, cash_hkd=cash_hkd) for item in subset)
        names = "|".join(sorted(display_stock(item) for item in subset))
        key = (utility, len(subset), -peak, names)
        if best_key is None or key > best_key:
            best_key = key
            best_subset = subset
    return best_subset


def select_capital_schedule(
    candidates: list[dict[str, Any]],
    *,
    cash_hkd: float,
    priority_strategy: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if priority_strategy == "utility_score_entry":
        selected: list[dict[str, Any]] = []
        for component in capital_connected_components(candidates):
            selected.extend(utility_best_subset(component, cash_hkd=cash_hkd))
        selected_ids = {item.get("_candidate_index") for item in selected}
        conflicts: list[dict[str, Any]] = []
        for item in candidates:
            if item.get("_candidate_index") in selected_ids:
                continue
            conflict = dict(item)
            conflict["_conflict_with"] = [
                display_stock(chosen)
                for chosen in selected
                if windows_overlap(item["_capital_window"], chosen["_capital_window"])
            ]
            conflicts.append(conflict)
        selected.sort(key=lambda item: capital_priority_key(item, strategy=priority_strategy))
        conflicts.sort(key=lambda item: capital_priority_key(item, strategy=priority_strategy))
        return selected, conflicts

    candidates.sort(key=lambda item: capital_priority_key(item, strategy=priority_strategy))
    selected = []
    conflicts = []
    for item in candidates:
        overlapping = [chosen for chosen in selected if windows_overlap(item["_capital_window"], chosen["_capital_window"])]
        if peak_capital_reserved([*selected, item]) <= cash_hkd + 1e-6:
            selected.append(item)
        else:
            conflict = dict(item)
            conflict["_conflict_with"] = [display_stock(chosen) for chosen in overlapping]
            conflicts.append(conflict)
    return selected, conflicts


def summarize_capital_schedule(
    records: list[dict[str, Any]],
    *,
    cash_hkd: float = DEFAULT_BACKTEST_CASH_HKD,
    priority_strategy: str = "utility_score_entry",
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    missing_window: list[dict[str, Any]] = []
    for record in records:
        required = backtest_cash_reserve(record, cash_hkd=cash_hkd)
        if required <= 0:
            continue
        window = capital_lock_window(record)
        if not all(window):
            missing_window.append(record)
            continue
        item = dict(record)
        item["_capital_required_hkd"] = required
        item["_capital_window"] = window
        item["_candidate_index"] = len(candidates)
        candidates.append(item)

    selected, conflicts = select_capital_schedule(
        candidates,
        cash_hkd=cash_hkd,
        priority_strategy=priority_strategy,
    )

    def expected_values(items: list[dict[str, Any]]) -> list[float]:
        return [
            float(value)
            for value in (expected_one_lot_gross_pnl(item) for item in items)
            if isinstance(value, (int, float))
        ]

    def expected_sum(items: list[dict[str, Any]]) -> float | None:
        values = expected_values(items)
        return sum(values) if values else None

    def expected_avg(items: list[dict[str, Any]]) -> float | None:
        values = expected_values(items)
        return statistics.mean(values) if values else None

    def expected_median(items: list[dict[str, Any]]) -> float | None:
        values = expected_values(items)
        return statistics.median(values) if values else None

    def avg_first_day(items: list[dict[str, Any]]) -> float | None:
        values = [item.get("first_day_change_pct") for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
        return statistics.mean(values) if values else None

    def strong_rate(items: list[dict[str, Any]]) -> float | None:
        values = [item.get("first_day_change_pct") for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
        return sum(1 for value in values if value >= 20.0) / len(values) if values else None

    peak_cash = peak_capital_reserved(selected)

    return {
        "cash_hkd": cash_hkd,
        "priority_strategy": priority_strategy,
        "priority_label": CAPITAL_PRIORITY_LABELS.get(priority_strategy, priority_strategy),
        "priority_description": CAPITAL_PRIORITY_DESCRIPTIONS.get(priority_strategy, "按事前可见字段排序。"),
        "candidate_count": len(candidates) + len(missing_window),
        "selected_count": len(selected),
        "conflict_skipped_count": len(conflicts),
        "missing_window_count": len(missing_window),
        "peak_cash_reserved_hkd": peak_cash,
        "selected_expected_one_lot_pnl_hkd": expected_sum(selected),
        "conflict_expected_one_lot_pnl_hkd": expected_sum(conflicts),
        "selected_avg_expected_one_lot_pnl_hkd": expected_avg(selected),
        "conflict_avg_expected_one_lot_pnl_hkd": expected_avg(conflicts),
        "selected_median_expected_one_lot_pnl_hkd": expected_median(selected),
        "conflict_median_expected_one_lot_pnl_hkd": expected_median(conflicts),
        "selected_expected_one_lot_sample_count": len(expected_values(selected)),
        "conflict_expected_one_lot_sample_count": len(expected_values(conflicts)),
        "selected_avg_first_day_pct": avg_first_day(selected),
        "conflict_avg_first_day_pct": avg_first_day(conflicts),
        "selected_strong_rate": strong_rate(selected),
        "conflict_strong_rate": strong_rate(conflicts),
        "selected_examples": [display_stock(item) for item in selected[:8]],
        "conflict_examples": [
            {
                "stock": display_stock(item),
                "conflict_with": item.get("_conflict_with", []),
                "score": item.get("recommendation", {}).get("score"),
                "entry_fee_hkd": item.get("entry_fee_hkd"),
                "financing_tier": (item.get("recommendation", {}).get("financing") or {}).get("tier"),
                "window": format_window(item.get("_capital_window")),
            }
            for item in conflicts[:8]
        ],
    }


def summarize_capital_schedule_variants(
    records: list[dict[str, Any]],
    *,
    cash_hkd: float = DEFAULT_BACKTEST_CASH_HKD,
) -> list[dict[str, Any]]:
    return [
        summarize_capital_schedule(records, cash_hkd=cash_hkd, priority_strategy=code)
        for code, _, _ in CAPITAL_PRIORITY_STRATEGIES
    ]


def format_window(window: tuple[dt.date | None, dt.date | None] | None) -> str:
    if not window:
        return "待核实"
    start, end = window
    if start and end:
        return f"{start.isoformat()} 至 {end.isoformat()}"
    return "待核实"


def final_heat_label(record: dict[str, Any]) -> str:
    """Review-only final demand label; never feed this into pre-close scoring."""

    oversub = record.get("oversubscription_rate")
    one_lot = record.get("one_lot_success_rate_pct")
    if not isinstance(oversub, (int, float)) and not isinstance(one_lot, (int, float)):
        return "最终热度缺失"
    oversub_value = float(oversub) if isinstance(oversub, (int, float)) else 0.0
    one_lot_value = float(one_lot) if isinstance(one_lot, (int, float)) else 999.0
    if oversub_value >= 1000 and one_lot_value <= 5:
        return "最终强热度"
    if oversub_value < 200 or one_lot_value >= 15:
        return "最终弱热度"
    return "最终热度中性"


def miss_attribution(record: dict[str, Any], *, threshold: float) -> list[str]:
    """Explain review misses without changing the pre-close model."""

    rec = record["recommendation"]
    action = rec.get("action")
    first_day = record.get("first_day_change_pct")
    if not isinstance(first_day, (int, float)):
        return ["首日表现缺失，无法归因"]

    heat_label = final_heat_label(record)
    financing_tier = rec.get("financing", {}).get("tier")
    industry = record.get("industry") or ""
    reasons: list[str] = []

    if action == "建议申购" and first_day <= 0:
        if heat_label == "最终弱热度":
            reasons.append("最终热度弱，事前需用孖展/额度闸门降级融资或转现金")
        elif heat_label == "最终热度缺失":
            reasons.append("缺最终热度数据，需补配售/中签率来源")
        if financing_tier == "乙组候选":
            reasons.append("乙组候选未被证明可执行，需强制融资截止前二次锁单")
        if any(keyword in industry for keyword in SCARCE_SECTOR_KEYWORDS + HARD_TECH_QUALITY_KEYWORDS):
            reasons.append("硬科技/稀缺题材权重偏高，需用估值和需求验证过滤")
        if expected_one_lot_gross_pnl(record) is not None and expected_one_lot_gross_pnl(record) <= 0:
            reasons.append("一手期望不正，资金效率不足")
    elif action != "建议申购" and first_day >= threshold:
        if heat_label == "最终强热度":
            reasons.append("最终强热度，说明事前孖展/额度时间序列应触发升级复核")
        if action == "可选观察":
            reasons.append("可选观察不是放弃，需在T-1/T-0用热度和成本决定是否升级")
        if rec.get("score", 0) >= 65:
            reasons.append("分数接近建议阈值，需增加临界票深挖招股书和舆情")
        if not record.get("industry") or not record.get("sponsor"):
            reasons.append("资料字段缺口导致保守，需补HKEX/招股书摘要")
        if any(keyword in industry for keyword in STRUCTURAL_WEAK_KEYWORDS + DEFENSIVE_INDUSTRY_KEYWORDS):
            reasons.append("偏热市场下非热门行业也可能扩散，不能只按行业静态排除")
        pnl = expected_one_lot_gross_pnl(record)
        if pnl is not None and pnl < 50:
            reasons.append("涨幅高但一手期望低，升级前仍要检查资金效率")

    if not reasons:
        reasons.append(f"{heat_label}；需人工复核估值、基石和申购窗口")
    return list(dict.fromkeys(reasons))


def summarize_miss_attribution(records: list[dict[str, Any]], *, threshold: float) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for record in records:
        for reason in miss_attribution(record, threshold=threshold):
            bucket = counts.setdefault(reason, {"reason": reason, "count": 0, "examples": []})
            bucket["count"] += 1
            if len(bucket["examples"]) < 3:
                bucket["examples"].append(display_stock(record))
    return sorted(counts.values(), key=lambda item: (-item["count"], item["reason"]))


def top_attribution(rows: list[dict[str, Any]], total: int) -> dict[str, Any] | None:
    if not rows or total <= 0:
        return None
    row = rows[0]
    return {
        "reason": row["reason"],
        "count": row["count"],
        "share": row["count"] / total,
        "examples": row.get("examples") or [],
    }


def attribution_recommendation(reason: str | None, *, miss_type: str) -> str:
    text = reason or ""
    if "孖展" in text or "额度" in text or "二次锁单" in text or "乙组" in text:
        return "优先补融资截止前孖展/额度/利率历史，不要用最终超购或首日表现反推乙组执行。"
    if "硬科技" in text or "稀缺题材" in text:
        return "保留题材加分，但新增招股书估值、基石和需求验证；不要简单下调所有硬科技。"
    if "资料字段缺口" in text or "HKEX" in text:
        return "先补 HKEX/招股书/详情页字段，再判断是否需要修改评分规则。"
    if "一手期望" in text or "资金效率" in text:
        return "把一手期望、融资息费和资金窗口作为复盘/锁单检查，不要只优化首日涨幅。"
    if miss_type == "false_negative":
        return "把该类样本纳入临界观察和 T-1/T-0 升级复核，不要直接降低建议阈值。"
    return "先人工复核估值、基石、行业和资金窗口，再决定是否调整规则。"


def summarize_miss_attribution_audit(records: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    false_positive = [
        item
        for item in records
        if (item.get("recommendation") or {}).get("action") == "建议申购"
        and isinstance(item.get("first_day_change_pct"), (int, float))
        and item["first_day_change_pct"] <= 0
    ]
    false_negative = [
        item
        for item in records
        if (item.get("recommendation") or {}).get("action") != "建议申购"
        and isinstance(item.get("first_day_change_pct"), (int, float))
        and item["first_day_change_pct"] >= threshold
    ]
    fp_rows = summarize_miss_attribution(false_positive, threshold=threshold)
    fn_rows = summarize_miss_attribution(false_negative, threshold=threshold)
    fp_top = top_attribution(fp_rows, len(false_positive))
    fn_top = top_attribution(fn_rows, len(false_negative))
    return {
        "false_positive_count": len(false_positive),
        "false_negative_count": len(false_negative),
        "false_positive_top_reasons": fp_rows,
        "false_negative_top_reasons": fn_rows,
        "dominant_false_positive": fp_top,
        "dominant_false_negative": fn_top,
        "false_positive_recommendation": attribution_recommendation(
            fp_top.get("reason") if fp_top else None,
            miss_type="false_positive",
        ),
        "false_negative_recommendation": attribution_recommendation(
            fn_top.get("reason") if fn_top else None,
            miss_type="false_negative",
        ),
        "model_guardrail": "错判归因只使用复盘结果生成改进方向；不得把最终超购、一手中签率、暗盘或首日表现写回申购前评分。",
    }


def borderline_observation_records(records: list[dict[str, Any]], *, min_score: int = 65) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("recommendation", {}).get("action") == "可选观察"
        and int(record.get("recommendation", {}).get("score") or 0) >= min_score
    ]


def summarize_borderline_observation(records: list[dict[str, Any]], *, threshold: float, min_score: int = 65) -> dict[str, Any]:
    items = borderline_observation_records(records, min_score=min_score)
    returns = [item["first_day_change_pct"] for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
    row = {
        "min_score": min_score,
        "count": len(items),
        "positive_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
        "strong_rate": sum(1 for value in returns if value >= threshold) / len(returns) if returns else None,
        "avg_first_day_pct": statistics.mean(returns) if returns else None,
        "median_first_day_pct": statistics.median(returns) if returns else None,
        "final_strong_heat_count": sum(1 for item in items if final_heat_label(item) == "最终强热度"),
        "final_weak_heat_count": sum(1 for item in items if final_heat_label(item) == "最终弱热度"),
        "examples": [display_stock(item) for item in sorted(items, key=lambda rec: -int(rec.get("recommendation", {}).get("score") or 0))[:8]],
    }
    row.update(return_proxy_stats(items))
    return row


def summarize(records: list[dict[str, Any]], *, threshold: float, key: str = "recommendation") -> dict[str, Any]:
    by_action: dict[str, list[dict[str, Any]]] = {"建议申购": [], "可选观察": [], "暂不参与": []}
    for record in records:
        by_action[record[key]["action"]].append(record)
    rows = {}
    for action, items in by_action.items():
        returns = [item["first_day_change_pct"] for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
        rows[action] = {
            "count": len(items),
            "positive_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
            "strong_rate": sum(1 for value in returns if value >= threshold) / len(returns) if returns else None,
            "avg_first_day_pct": statistics.mean(returns) if returns else None,
            "median_first_day_pct": statistics.median(returns) if returns else None,
            "min_first_day_pct": min(returns) if returns else None,
            "max_first_day_pct": max(returns) if returns else None,
        }
        rows[action].update(return_proxy_stats(items))
    apply = by_action["建议申购"]
    apply_returns = [item["first_day_change_pct"] for item in apply if isinstance(item.get("first_day_change_pct"), (int, float))]
    false_positive = [item for item in apply if isinstance(item.get("first_day_change_pct"), (int, float)) and item["first_day_change_pct"] <= 0]
    false_negative = [
        item
        for item in by_action["可选观察"] + by_action["暂不参与"]
        if isinstance(item.get("first_day_change_pct"), (int, float)) and item["first_day_change_pct"] >= threshold
    ]
    return {
        "by_action": rows,
        "apply_positive_rate": sum(1 for value in apply_returns if value > 0) / len(apply_returns) if apply_returns else None,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def summarize_financing(records: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for tier in FINANCING_TIERS:
        items = [record for record in records if record["recommendation"].get("financing", {}).get("tier") == tier]
        returns = [item["first_day_change_pct"] for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
        rows[tier] = {
            "count": len(items),
            "positive_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
            "strong_rate": sum(1 for value in returns if value >= threshold) / len(returns) if returns else None,
            "avg_first_day_pct": statistics.mean(returns) if returns else None,
            "median_first_day_pct": statistics.median(returns) if returns else None,
            "min_first_day_pct": min(returns) if returns else None,
        }
        rows[tier].update(return_proxy_stats(items))
    return rows


def summarize_score_bands(records: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for label, low, high in SCORE_BANDS:
        items = [
            record
            for record in records
            if low <= int(record.get("recommendation", {}).get("score") or 0) <= high
        ]
        returns = [item["first_day_change_pct"] for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
        row = {
            "count": len(items),
            "positive_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
            "strong_rate": sum(1 for value in returns if value >= threshold) / len(returns) if returns else None,
            "avg_first_day_pct": statistics.mean(returns) if returns else None,
            "median_first_day_pct": statistics.median(returns) if returns else None,
            "min_first_day_pct": min(returns) if returns else None,
            "max_first_day_pct": max(returns) if returns else None,
        }
        row.update(return_proxy_stats(items))
        rows[label] = row
    return rows


def score_band_calibration_note(score_band_summary: dict[str, dict[str, Any]]) -> str:
    high = score_band_summary.get("78+") or {}
    middle = score_band_summary.get("72-77") or {}
    high_strong = high.get("strong_rate")
    middle_strong = middle.get("strong_rate")
    high_pnl = high.get("avg_expected_one_lot_pnl_hkd")
    middle_pnl = middle.get("avg_expected_one_lot_pnl_hkd")
    if (
        isinstance(high_strong, (int, float))
        and isinstance(middle_strong, (int, float))
        and isinstance(high_pnl, (int, float))
        and isinstance(middle_pnl, (int, float))
        and (high_strong <= middle_strong or high_pnl <= middle_pnl)
    ):
        note = "高分段没有稳定优于 72-77 分段，不应机械提高建议阈值；更应补招股书估值、融资热度和成本闸门。"
    else:
        note = "评分分层仅用于校准和发现非单调风险；是否升级仍要看招股书、融资热度、成本和资金窗口。"
    low_bands = [score_band_summary.get(label) or {} for label in ["<58", "58-64", "65-71"]]
    if any(0 < int(row.get("count") or 0) < 10 for row in low_bands):
        note += " 低分段样本数偏少，不能反向证明应降低阈值或扩大建议申购。"
    return note


def summarize_heat_gate_proxy(records: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    """Review-only proxy for whether a pre-close heat gate would have helped."""

    def strict_heat(record: dict[str, Any]) -> bool:
        oversub = record.get("oversubscription_rate") or 0
        one_lot = record.get("one_lot_success_rate_pct") or 999
        return oversub >= 1000 and one_lot <= 5

    def weak_heat(record: dict[str, Any]) -> bool:
        oversub = record.get("oversubscription_rate") or 0
        one_lot = record.get("one_lot_success_rate_pct") or 0
        return oversub < 200 or one_lot >= 15

    cohorts = {
        "乙组候选且最终强热度": lambda record: record["recommendation"].get("financing", {}).get("tier") == "乙组候选" and strict_heat(record),
        "乙组候选但最终弱热度": lambda record: record["recommendation"].get("financing", {}).get("tier") == "乙组候选" and weak_heat(record),
        "甲组候选且最终强热度": lambda record: record["recommendation"].get("financing", {}).get("tier") == "甲组候选" and strict_heat(record),
        "现金参与但最终强热度": lambda record: record["recommendation"].get("financing", {}).get("tier") == "现金参与" and strict_heat(record),
    }
    rows: dict[str, dict[str, Any]] = {}
    for label, predicate in cohorts.items():
        items = [record for record in records if predicate(record)]
        returns = [item["first_day_change_pct"] for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
        rows[label] = {
            "count": len(items),
            "positive_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
            "strong_rate": sum(1 for value in returns if value >= threshold) / len(returns) if returns else None,
            "avg_first_day_pct": statistics.mean(returns) if returns else None,
            "median_first_day_pct": statistics.median(returns) if returns else None,
            "min_first_day_pct": min(returns) if returns else None,
        }
        rows[label].update(return_proxy_stats(items))
    return rows


def normalize_margin_heat_payloads(payloads: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not payloads:
        return None
    stocks: list[dict[str, Any]] = []
    for payload in payloads:
        nested = payload.get("stocks") or payload.get("items_by_stock")
        if isinstance(nested, list):
            stocks.extend(item for item in nested if isinstance(item, dict))
        else:
            stocks.append(payload)
    return {"stocks": stocks}


def strict_margin_execution_gate(heat: dict[str, Any] | None) -> bool:
    if not heat:
        return False
    summary = heat.get("summary") or {}
    return strict_execution_ready(summary)


def summarize_margin_history_coverage(
    records: list[dict[str, Any]],
    *,
    margin_heat_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    b_candidates = [
        record
        for record in records
        if (record.get("recommendation") or {}).get("financing", {}).get("tier") == "乙组候选"
    ]
    covered: list[dict[str, Any]] = []
    gate_met: list[dict[str, Any]] = []
    gate_not_met: list[dict[str, Any]] = []
    invalid_timing: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for record in b_candidates:
        heat = margin_heat_for_ipo(record, margin_heat_payload) if margin_heat_payload else None
        if not heat:
            missing.append(record)
            continue
        if not timing_evidence_valid(heat.get("summary") or {}):
            invalid_timing.append(record)
            continue
        covered.append(record)
        if strict_margin_execution_gate(heat):
            gate_met.append(record)
        else:
            gate_not_met.append(record)
    coverage = len(covered) / len(b_candidates) if b_candidates else None
    if not b_candidates:
        verdict = "无乙组候选，无法验证乙组执行闸门。"
    elif coverage is not None and coverage < 0.70:
        verdict = "历史孖展覆盖率低于 70%，乙组执行效果不能被验证；本年只能验证乙组候选选股质量。"
    elif not gate_met:
        verdict = "历史孖展覆盖基本可用，但没有严格闸门满足样本，不能证明乙组可执行收益。"
    else:
        verdict = "历史孖展覆盖基本可用，可进一步比较乙组候选与乙组可执行队列。"

    def example_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(
            items,
            key=lambda item: (
                item.get("closing_date") or item.get("listing_date") or "",
                -int((item.get("recommendation") or {}).get("score") or 0),
                display_stock(item),
            ),
        )
        return [
            {
                "stock": display_stock(item),
                "code": item.get("code"),
                "closing_date": item.get("closing_date"),
                "listing_date": item.get("listing_date"),
                "score": (item.get("recommendation") or {}).get("score"),
            }
            for item in ordered[:12]
        ]

    return {
        "b_group_candidate_count": len(b_candidates),
        "covered_count": len(covered),
        "invalid_timing_count": len(invalid_timing),
        "missing_count": len(missing),
        "gate_met_count": len(gate_met),
        "gate_not_met_count": len(gate_not_met),
        "coverage_rate": coverage,
        "coverage_verdict": verdict,
        "missing_examples": example_rows(missing),
        "invalid_timing_examples": example_rows(invalid_timing),
        "gate_not_met_examples": example_rows(gate_not_met),
        "gate_met_examples": example_rows(gate_met),
    }


def summarize_regime(records: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    labels = ["偏热", "中性", "偏冷", "样本不足"]
    rows: dict[str, dict[str, Any]] = {}
    for label in labels:
        items = [record for record in records if (record.get("market_regime") or {}).get("label") == label]
        returns = [item["first_day_change_pct"] for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
        rows[label] = {
            "count": len(items),
            "positive_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
            "strong_rate": sum(1 for value in returns if value >= threshold) / len(returns) if returns else None,
            "avg_first_day_pct": statistics.mean(returns) if returns else None,
            "median_first_day_pct": statistics.median(returns) if returns else None,
        }
        rows[label].update(return_proxy_stats(items))
    return rows


def summarize_data_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)

    def count_field(key: str) -> int:
        return sum(1 for record in records if record.get(key) not in (None, "", "N/A"))

    def has_hkex_document(record: dict[str, Any]) -> bool:
        documents = record.get("documents") or {}
        return bool(
            record.get("source_urls", {}).get("hkex_listing_information")
            or record.get("source_urls", {}).get("hkex_listing_report")
            or documents.get("prospectus_url")
            or documents.get("listing_announcement_url")
            or documents.get("allotment_result_url")
        )

    return {
        "total": total,
        "detail_ok_count": sum(1 for record in records if record.get("detail_status") == "ok"),
        "detail_retry_ok_count": sum(1 for record in records if record.get("detail_retry_status") == "ok"),
        "hkex_document_count": sum(1 for record in records if has_hkex_document(record)),
        "hkex_listing_report_count": sum(1 for record in records if record.get("hkex_listing_report_match")),
        "industry_count": count_field("industry"),
        "sponsor_count": count_field("sponsor"),
        "entry_fee_count": sum(1 for record in records if isinstance(record.get("entry_fee_hkd"), (int, float))),
        "one_lot_success_count": sum(1 for record in records if isinstance(record.get("one_lot_success_rate_pct"), (int, float))),
        "first_day_count": sum(1 for record in records if isinstance(record.get("first_day_change_pct"), (int, float))),
    }


def render_current_year_expert_audit(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]["by_action"]
    heat_gate_proxy = payload["heat_gate_proxy"]
    year = payload["year"]
    apply_row = summary["建议申购"]
    optional_row = summary["可选观察"]
    skip_row = summary["暂不参与"]
    b_strong = heat_gate_proxy["乙组候选且最终强热度"]
    b_weak = heat_gate_proxy["乙组候选但最终弱热度"]

    lines = [
        "",
        "## 当前年份专家审查",
        f"- 本轮策略以 {year} 年单年样本为主。旧年份只适合做压力测试，不能把早期冷市经验机械套到当前市场。",
    ]
    if apply_row["count"]:
        lines.append(
            f"- `建议申购` 当前样本 {apply_row['count']} 只，正收益率 {ratio(apply_row['positive_rate'])}，"
            f"强收益率 {ratio(apply_row['strong_rate'])}，平均一手期望 {money(apply_row.get('avg_expected_one_lot_pnl_hkd'))}。"
            "这个分层可以保留为优先研究和资金预留名单，但不等于所有票都应直接上乙组。"
        )
    if optional_row["count"]:
        lines.append(
            f"- `可选观察` 仍有 {optional_row['count']} 只，强收益率 {ratio(optional_row['strong_rate'])}。"
            "2026 偏热时，这个分层不应被理解为放弃，而是缺招股书深挖、估值确认或融资热度确认前的候选池。"
        )
    if b_strong["count"] and b_weak["count"]:
        lines.append(
            f"- 乙组候选里，强热度复盘代理的强收益率为 {ratio(b_strong['strong_rate'])}，"
            f"弱热度代理只有 {ratio(b_weak['strong_rate'])}。"
            "最有价值的优化不是继续提高行业/保荐人分数，而是在券商融资截止前强制采集孖展倍数、额度紧张度、利率和截止时间。"
        )
        lines.append(
            "- 上一条里的最终超购/一手中签率只能作为复盘代理，不能泄露进申购前模型；实盘应使用 T-1/T-0 且早于券商融资截止的孖展和额度信号近似它。"
        )
    if skip_row["count"] < 5:
        lines.append(
            f"- `暂不参与` 样本只有 {skip_row['count']} 只，统计意义不足。当前市场下更合理的做法是把弱但有强保荐/低入场费/可查文件的票放入 `可选观察`，"
            "只在文件缺失、结构明显弱、估值/成本不划算或资金窗口冲突时明确跳过。"
        )
    lines.append(
        "- 因此，专家口径应是：2026 选股信号偏有效，融资执行仍必须二次锁单；早期先排现金/甲组预案，只有融资截止前热度和成本同时过关才执行乙组。"
    )
    return lines


def render_margin_history_coverage_section(margin: dict[str, Any]) -> list[str]:
    if not margin:
        return ["", "## 历史孖展覆盖审查", "- 未生成历史孖展覆盖审查。"]
    lines = [
        "",
        "## 历史孖展覆盖审查",
        "该段只审查融资截止前券商孖展、额度、利率和截止时间的历史数据覆盖；不使用最终超购、一手中签率、暗盘或首日表现决定乙组闸门。",
        "| 乙组候选 | 有效覆盖历史孖展 | 时间无效 | 缺历史孖展 | 有效覆盖率 | 严格闸门满足 | 闸门未满足 | 结论 |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
        (
            f"| {margin.get('b_group_candidate_count', 0)} | {margin.get('covered_count', 0)} | "
            f"{margin.get('invalid_timing_count', 0)} | {margin.get('missing_count', 0)} | "
            f"{ratio(margin.get('coverage_rate'))} | "
            f"{margin.get('gate_met_count', 0)} | {margin.get('gate_not_met_count', 0)} | "
            f"{margin.get('coverage_verdict') or '-'} |"
        ),
    ]
    if margin.get("missing_count"):
        lines.append(
            "- 补采命令：`python scripts/prepare_margin_history_template.py --backtest-json backtest-2026.json --markdown`；"
            "补齐 broker、observed_at、source_published_at、preclose_confirmed、broker_cutoff_at、margin_multiple/amount、quota_status、financing_rate_pct、cutoff_note、source 和 excerpt。"
        )
        lines.extend(["", "| 缺历史孖展样本 | 招股截止 | 事前分数 |", "|---|---|---:|"])
        for item in margin.get("missing_examples") or []:
            lines.append(f"| {item.get('stock')} | {item.get('closing_date') or '-'} | {item.get('score') or '-'} |")
    if margin.get("invalid_timing_count"):
        lines.append("- 时间无效样本不计入有效覆盖率；需补早于券商融资截止的 observed_at、source_published_at 和 broker_cutoff_at。")
        lines.extend(["", "| 时间无效样本 | 招股截止 | 事前分数 |", "|---|---|---:|"])
        for item in margin.get("invalid_timing_examples") or []:
            lines.append(f"| {item.get('stock')} | {item.get('closing_date') or '-'} | {item.get('score') or '-'} |")
    if margin.get("gate_not_met_count"):
        lines.extend(["", "| 已覆盖但闸门未满足 | 招股截止 | 事前分数 |", "|---|---|---:|"])
        for item in margin.get("gate_not_met_examples") or []:
            lines.append(f"| {item.get('stock')} | {item.get('closing_date') or '-'} | {item.get('score') or '-'} |")
    lines.append("- 判断口径：覆盖率低于 70% 时，本段只能作为数据缺口审查，不能证明乙组执行策略有效。")
    return lines


def render_capital_schedule_section(capital: dict[str, Any]) -> list[str]:
    if not capital:
        return ["", "## 资金窗口压力测试", "- 未生成资金窗口压力测试。"]
    lines = [
        "",
        "## 资金窗口压力测试",
        (
            f"口径：按事前 `{capital.get('priority_label') or '分数+低入场费优先'}` 排序、默认现金 HKD 55 万、"
            "同一锁定窗口现金不可重复使用做保守复盘；收益仍用一手期望毛利粗略衡量，未扣融资息费。"
        ),
        f"排序说明：{capital.get('priority_description') or '排序只使用事前可见字段。'}",
        "| 默认现金 | 候选数 | 排入数 | 冲突跳过 | 窗口缺失 | 峰值占用 | 排入一手期望合计 | 排入平均一手期望 | 冲突跳过一手期望合计 | 冲突平均一手期望 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {money(capital.get('cash_hkd'))} | {capital.get('candidate_count', 0)} | "
            f"{capital.get('selected_count', 0)} | {capital.get('conflict_skipped_count', 0)} | "
            f"{capital.get('missing_window_count', 0)} | {money(capital.get('peak_cash_reserved_hkd'))} | "
            f"{money(capital.get('selected_expected_one_lot_pnl_hkd'))} | "
            f"{money(capital.get('selected_avg_expected_one_lot_pnl_hkd'))} | "
            f"{money(capital.get('conflict_expected_one_lot_pnl_hkd'))} | "
            f"{money(capital.get('conflict_avg_expected_one_lot_pnl_hkd'))} |"
        ),
        (
            f"- 一手期望覆盖：排入 {capital.get('selected_expected_one_lot_sample_count', 0)}/"
            f"{capital.get('selected_count', 0)}；冲突跳过 {capital.get('conflict_expected_one_lot_sample_count', 0)}/"
            f"{capital.get('conflict_skipped_count', 0)}。平均值只按有一手中签率和首日表现的样本计算。"
        ),
        (
            f"- 排入组合：平均首日 {pct(capital.get('selected_avg_first_day_pct'))}，"
            f"强收益率 {ratio(capital.get('selected_strong_rate'))}。"
        ),
    ]
    if capital.get("conflict_skipped_count"):
        lines.append(
            f"- 冲突跳过组合：平均首日 {pct(capital.get('conflict_avg_first_day_pct'))}，"
            f"强收益率 {ratio(capital.get('conflict_strong_rate'))}。这代表资金窗口取舍的机会成本，不是事前模型错误。"
        )
        selected_strong = capital.get("selected_strong_rate")
        conflict_strong = capital.get("conflict_strong_rate")
        selected_pnl = capital.get("selected_expected_one_lot_pnl_hkd")
        conflict_pnl = capital.get("conflict_expected_one_lot_pnl_hkd")
        selected_avg_pnl = capital.get("selected_avg_expected_one_lot_pnl_hkd")
        conflict_avg_pnl = capital.get("conflict_avg_expected_one_lot_pnl_hkd")
        stronger_avg_pnl = (
            isinstance(selected_avg_pnl, (int, float))
            and isinstance(conflict_avg_pnl, (int, float))
            and conflict_avg_pnl > selected_avg_pnl
        )
        stronger_total_pnl = (
            isinstance(selected_pnl, (int, float))
            and isinstance(conflict_pnl, (int, float))
            and conflict_pnl > selected_pnl
        )
        stronger_strong_rate = (
            isinstance(selected_strong, (int, float))
            and isinstance(conflict_strong, (int, float))
            and conflict_strong > selected_strong
        )
        if stronger_avg_pnl or stronger_total_pnl or stronger_strong_rate:
            if stronger_avg_pnl and stronger_strong_rate:
                diagnostic = "被跳过组合在平均一手期望和强收益率上都更强"
            elif stronger_avg_pnl:
                diagnostic = "被跳过组合平均一手期望更高"
            elif stronger_total_pnl:
                diagnostic = "被跳过组合一手期望合计更高，主要反映资金窗口机会成本"
            else:
                diagnostic = "排入组合一手期望未落后，但强收益率仍低于被跳过组合"
            if capital.get("priority_strategy") == "utility_score_entry":
                lines.append(
                    f"- 窗口取舍警示：{diagnostic}。本轮已使用事前效用组合最优，残余差距更像招股书深挖、"
                    "T-1/T-0 孖展热度、额度紧张度或融资打平幅度缺口；不应继续机械拟合排序代理。"
                )
            else:
                lines.append(
                    f"- 窗口取舍警示：{diagnostic}，说明同窗口内不能只靠基础分数排序；"
                    "下一轮应强制比较招股书深挖、T-1/T-0 孖展热度、额度紧张度和事前占款效率/融资打平幅度后再锁定默认现金。"
                )
        lines.extend(["", "| 冲突跳过股票 | 锁定窗口 | 冲突对象 | 事前分数 |", "|---|---|---|---:|"])
        for item in capital.get("conflict_examples") or []:
            lines.append(
                f"| {item.get('stock')} | {item.get('window')} | "
                f"{'、'.join(item.get('conflict_with') or []) or '-'} | {item.get('score') or '-'} |"
            )
    else:
        lines.append("- 本口径下未发现建议申购之间的默认现金窗口冲突。")
    examples = "、".join(capital.get("selected_examples") or [])
    if examples:
        lines.append(f"- 排入示例：{examples}。")
    return lines


def render_capital_priority_sensitivity_section(variants: list[dict[str, Any]]) -> list[str]:
    if not variants:
        return ["", "## 排期排序敏感性", "- 未生成排期排序敏感性。"]
    lines = [
        "",
        "## 排期排序敏感性",
        "排序只使用事前可见字段；表内首日和一手期望只用于复盘检验，不参与当时排期；平均一手期望只按数据完整样本计算。",
        "| 排序口径 | 排入数 | 冲突跳过 | 排入平均一手期望 | 冲突平均一手期望 | 排入一手期望合计 | 冲突一手期望合计 | 排入平均首日 | 冲突平均首日 | 复盘提示 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    baseline = next((item for item in variants if item.get("priority_strategy") == "score"), variants[0])
    baseline_selected_avg_pnl = baseline.get("selected_avg_expected_one_lot_pnl_hkd")
    baseline_conflict_avg_pnl = baseline.get("conflict_avg_expected_one_lot_pnl_hkd")
    best = None
    for item in variants:
        selected_avg_pnl = item.get("selected_avg_expected_one_lot_pnl_hkd")
        conflict_avg_pnl = item.get("conflict_avg_expected_one_lot_pnl_hkd")
        selected_total_pnl = item.get("selected_expected_one_lot_pnl_hkd")
        conflict_total_pnl = item.get("conflict_expected_one_lot_pnl_hkd")
        note = "中性"
        if (
            item is not baseline
            and isinstance(selected_avg_pnl, (int, float))
            and isinstance(conflict_avg_pnl, (int, float))
            and isinstance(baseline_selected_avg_pnl, (int, float))
            and isinstance(baseline_conflict_avg_pnl, (int, float))
        ):
            if selected_avg_pnl > baseline_selected_avg_pnl and conflict_avg_pnl < baseline_conflict_avg_pnl:
                note = "优于基础分数排序"
                if best is None or selected_avg_pnl > float(best.get("selected_avg_expected_one_lot_pnl_hkd") or -1e18):
                    best = item
            elif selected_avg_pnl < baseline_selected_avg_pnl and conflict_avg_pnl > baseline_conflict_avg_pnl:
                note = "弱于基础分数排序"
        lines.append(
            f"| {item.get('priority_label')} | {item.get('selected_count', 0)} | "
            f"{item.get('conflict_skipped_count', 0)} | {money(selected_avg_pnl)} | {money(conflict_avg_pnl)} | "
            f"{money(selected_total_pnl)} | {money(conflict_total_pnl)} | "
            f"{pct(item.get('selected_avg_first_day_pct'))} | {pct(item.get('conflict_avg_first_day_pct'))} | {note} |"
        )
    if best:
        lines.append(
            f"- 复盘结论：`{best.get('priority_label')}` 在本年样本里改善了默认现金排期结果；"
            "可以作为当前报告的默认 tie-breaker，但仍不能替代招股书深挖和 T-1/T-0 融资热度复核。"
        )
    else:
        lines.append(
            "- 复盘结论：没有发现明显优于基础分数排序的事前排期代理；同窗口取舍仍应逐票复核。"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    records = payload["records"]
    summary = payload["summary"]
    legacy_summary = payload["legacy_summary"]
    review_summary = payload["review_summary"]
    financing_summary = payload["financing_summary"]
    capital_schedule = payload.get("capital_schedule") or {}
    capital_schedule_variants = payload.get("capital_schedule_variants") or []
    margin_history_coverage = payload.get("margin_history_coverage") or {}
    heat_gate_proxy = payload["heat_gate_proxy"]
    score_band_summary = payload.get("score_band_summary") or {}
    borderline_summary = payload.get("borderline_observation") or {}
    regime_summary = payload["regime_summary"]
    data_quality = payload.get("data_quality") or {}
    threshold = payload["strong_threshold_pct"]
    quality_total = data_quality.get("total", len(records))
    lines = [
        f"# {payload['year']} 年港股打新回测",
        "",
        f"生成时间：{payload['generated_at']}",
        f"样本：AASTOCKS 已上市新股 {len(records)} 只；上市日期 {records[0]['listing_date'] if records else '-'} 至 {records[-1]['listing_date'] if records else '-'}。",
        (
            f"数据覆盖：详情页成功 {data_quality.get('detail_ok_count', 0)}/{quality_total}；"
            f"详情页重试修复 {data_quality.get('detail_retry_ok_count', 0)}；"
            f"HKEX文档/报告 {data_quality.get('hkex_document_count', 0)}/{quality_total}"
            f"（年度报告匹配 {data_quality.get('hkex_listing_report_count', 0)}）；"
            f"行业字段 {data_quality.get('industry_count', 0)}/{quality_total}；"
            f"保荐人字段 {data_quality.get('sponsor_count', 0)}/{quality_total}；"
            f"一手中签率 {data_quality.get('one_lot_success_count', 0)}/{quality_total}。"
        ),
        f"强收益定义：首日涨幅 >= {threshold:g}%。",
        "一手期望毛利为复盘口径：一手入场费 × 首日涨跌幅 × 一手中签率，未扣融资成本，不参与事前评分。",
    ]
    if records and data_quality.get("detail_ok_count", 0) / len(records) < 0.7:
        lines.append("数据覆盖提示：详情页成功率偏低，本次推荐分层会更保守；应重试、提高超时或补 HKEX 招股书摘要后再用于调参。")
    lines.extend(
        [
            "",
            "## 优化后事前策略表现",
            "| 推荐分类 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 | 最差 | 最好 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for action in ["建议申购", "可选观察", "暂不参与"]:
        row = summary["by_action"][action]
        lines.append(
            f"| {action} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
            f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | "
            f"{money(row['avg_expected_one_lot_pnl_hkd'])} | {pct(row['min_first_day_pct'])} | {pct(row['max_first_day_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 原策略对照",
            "| 推荐分类 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 | 最差 | 最好 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for action in ["建议申购", "可选观察", "暂不参与"]:
        row = legacy_summary["by_action"][action]
        lines.append(
            f"| {action} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
            f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | "
            f"{money(row['avg_expected_one_lot_pnl_hkd'])} | {pct(row['min_first_day_pct'])} | {pct(row['max_first_day_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 融资预决策分层",
            "该分层只使用申购截止前应能确认的信息框架；历史回测缺少逐日孖展轨迹，因此把孖展热度作为当时需补充的锁单条件，不使用最终超购来决定融资。",
            "| 融资分层 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 | 最差 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for tier in FINANCING_TIERS:
        row = financing_summary[tier]
        lines.append(
            f"| {tier} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
            f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | "
            f"{money(row['avg_expected_one_lot_pnl_hkd'])} | {pct(row['min_first_day_pct'])} |"
        )
    lines.extend(render_margin_history_coverage_section(margin_history_coverage))
    lines.extend(render_capital_schedule_section(capital_schedule))
    lines.extend(render_capital_priority_sensitivity_section(capital_schedule_variants))
    lines.extend(
        [
            "",
            "## 热度闸门复盘代理",
            "下表使用最终超购和一手中签率做复盘代理，不可用于当次融资；它用于验证融资截止前是否值得强制采集孖展热度、额度和利率。",
            "| 复盘队列 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 | 最差 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label in ["乙组候选且最终强热度", "乙组候选但最终弱热度", "甲组候选且最终强热度", "现金参与但最终强热度"]:
        row = heat_gate_proxy[label]
        lines.append(
            f"| {label} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
            f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | "
            f"{money(row['avg_expected_one_lot_pnl_hkd'])} | {pct(row['min_first_day_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 市场温度分层",
            "市场温度只使用该 IPO 申购/融资决策日前已经上市的新股首日表现，不使用当前 IPO 的最终配售或上市表现。",
            "| 市场温度 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label in ["偏热", "中性", "偏冷", "样本不足"]:
        row = regime_summary[label]
        lines.append(
            f"| {label} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
            f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | "
            f"{money(row['avg_expected_one_lot_pnl_hkd'])} |"
        )
    lines.extend(render_current_year_expert_audit(payload))

    if score_band_summary:
        lines.extend(
            [
                "",
                "## 评分分层校准",
                "该表只用于检查事前分数是否单调有效，不作为机械调阈值指令；首日和一手期望仍是复盘数据。",
                "| 分数段 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 | 最差 | 最好 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for label, _, _ in SCORE_BANDS:
            row = score_band_summary[label]
            lines.append(
                f"| {label} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
                f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | "
                f"{money(row['avg_expected_one_lot_pnl_hkd'])} | {pct(row['min_first_day_pct'])} | {pct(row['max_first_day_pct'])} |"
            )
        lines.append(f"- 校准结论：{score_band_calibration_note(score_band_summary)}")

    lines.extend(["", "## 主要错判"])
    fp = summary["false_positive"]
    fn = summary["false_negative"]
    lines.append("**建议申购但首日不涨/破发**")
    if fp:
        for item in sorted(fp, key=lambda rec: rec["first_day_change_pct"])[:10]:
            lines.append(format_miss(item))
    else:
        lines.append("- 无。")
    lines.append("")
    lines.append(f"**未建议申购但首日 >= {threshold:g}%**")
    if fn:
        for item in sorted(fn, key=lambda rec: -rec["first_day_change_pct"])[:15]:
            lines.append(format_miss(item))
    else:
        lines.append("- 无。")

    lines.extend(["", "## 错判归因"])
    lines.append("**建议申购但首日不涨/破发的归因**")
    if fp:
        lines.extend(render_miss_attribution_table(fp, threshold=threshold))
    else:
        lines.append("- 无。")
    lines.append("")
    lines.append(f"**未建议申购但首日 >= {threshold:g}% 的归因**")
    if fn:
        lines.extend(render_miss_attribution_table(fn, threshold=threshold))
    else:
        lines.append("- 无。")
    miss_audit = payload.get("miss_attribution_summary") or {}
    if miss_audit:
        fp_top = miss_audit.get("dominant_false_positive") or {}
        fn_top = miss_audit.get("dominant_false_negative") or {}
        lines.extend(
            [
                "",
                "**归因集中度审计**",
                "| 错判类型 | 样本数 | 最高频归因 | 占比 | 优化动作 |",
                "|---|---:|---|---:|---|",
                (
                    f"| 建议申购但首日不涨/破发 | {miss_audit.get('false_positive_count', 0)} | "
                    f"{fp_top.get('reason') or '-'} | {ratio(fp_top.get('share'))} | "
                    f"{miss_audit.get('false_positive_recommendation') or '-'} |"
                ),
                (
                    f"| 未建议申购但强收益 | {miss_audit.get('false_negative_count', 0)} | "
                    f"{fn_top.get('reason') or '-'} | {ratio(fn_top.get('share'))} | "
                    f"{miss_audit.get('false_negative_recommendation') or '-'} |"
                ),
                f"- 防泄露口径：{miss_audit.get('model_guardrail')}",
            ]
        )

    lines.extend(
        [
            "",
            "## 结果校验标签表现",
            "该标签额外使用最终超购倍数和一手中签率，只适合复盘、卖出纪律和未来参数校准；这些数据通常晚于融资截止，不能用于当次融资决策。",
            "| 推荐分类 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for action in ["建议申购", "可选观察", "暂不参与"]:
        row = review_summary["by_action"][action]
        lines.append(
            f"| {action} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
            f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | "
            f"{money(row['avg_expected_one_lot_pnl_hkd'])} |"
        )

    lines.extend(["", "## 临界观察队列复盘"])
    if borderline_summary.get("count"):
        examples = "、".join(borderline_summary.get("examples") or [])
        lines.extend(
            [
                (
                    f"- 口径：事前推荐为 `可选观察` 且评分 >= {borderline_summary.get('min_score')}。"
                    "这个队列只提示 T-1/T-0 升级复核，不自动变成建议申购或乙组执行。"
                ),
                (
                    f"- 样本 {borderline_summary['count']} 只；正收益率 {ratio(borderline_summary.get('positive_rate'))}；"
                    f"强收益率 {ratio(borderline_summary.get('strong_rate'))}；平均首日 {pct(borderline_summary.get('avg_first_day_pct'))}；"
                    f"平均一手期望 {money(borderline_summary.get('avg_expected_one_lot_pnl_hkd'))}。"
                ),
                (
                    f"- 复盘代理：最终强热度 {borderline_summary.get('final_strong_heat_count', 0)} 只，"
                    f"最终弱热度 {borderline_summary.get('final_weak_heat_count', 0)} 只。实盘只能用融资截止前孖展、额度和利率近似这些信号。"
                ),
                f"- 示例：{examples or '无'}。",
            ]
        )
    else:
        lines.append("- 本年没有满足临界观察口径的样本。")

    lines.extend(
        [
            "",
            "## 策略优化建议",
            "- 事前模型不要因为 `-B`、`-P` 自动重罚到跳过；2026 年强市场下，医药/18C 若有强保荐、低入场费或高关注行业，应先进入 `可选观察`，并在融资截止前用孖展热度和成本确认。",
            "- 低入场费不是充分条件。若行业弱、保荐弱、公开发售信息缺失，即使便宜也只能现金小额，不应默认融资。",
            "- 偏热市场下，低入场费且可查招股资料的数据缺口票不应直接排除；先放入 `可选观察`，再用招股书、保荐/基石和融资截止前热度确认。",
            "- 融资推荐必须在券商融资截止前完成：用孖展认购额、额度紧张程度、利率、券商截止时间和多平台热度决定是否上甲组/乙组。",
            "- 对乙组候选增加热度闸门：没有至少两个融资截止前需求/额度类强热度信号且成本可接受时，只能保留甲组或现金方案。",
            "- 冷市下不直接执行乙组：近期新股破发/不涨比例高时，题材和保荐人加分要降权，默认退回甲组或现金。",
            "- 高价非热门或高入场费标的要新增费用保护线：若没有热门行业/强保荐/基石信息，避免乙组融资。",
            "- 回测报告需要保留错判清单，下一轮调参重点看 `建议申购但破发` 和 `未建议申购但大涨`。",
            "- 不要只按首日涨幅优化。同步检查一手期望毛利和融资盈亏平衡，避免追逐涨幅高但中签概率极低、扣息后无效的样本。",
            "",
            "## 样本明细",
            "| 上市日 | 股票 | 行业 | 市场温度 | 优化后推荐 | 融资分层 | 分数 | 首日 | 一手期望 | 超购 | 一手中签率 |",
            "|---|---|---|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in sorted(records, key=lambda rec: rec["listing_date"], reverse=True):
        financing_tier = item["recommendation"].get("financing", {}).get("tier", "-")
        regime_label = (item.get("market_regime") or {}).get("label", "-")
        lines.append(
            f"| {item['listing_date']} | {display_stock(item)} | {item.get('industry') or '待核实'} | "
            f"{regime_label} | {item['recommendation']['action']} | {financing_tier} | {item['recommendation']['score']} | "
            f"{pct(item.get('first_day_change_pct'))} | {money(expected_one_lot_gross_pnl(item))} | "
            f"{num(item.get('oversubscription_rate'))} | {pct(item.get('one_lot_success_rate_pct'))} |"
        )

    lines.extend(
        [
            "",
            "## 来源",
            f"- AASTOCKS 已上市新股分页：{AASTOCKS_LISTED_URL}",
            f"- AASTOCKS 个股详情页模板：{AASTOCKS_DETAIL_URL}",
            f"- HKEX 新上市资料：{HKEX_MAIN_BOARD_URL}",
            "",
            "**免责声明** 本回测基于公开网页抓取和启发式规则，数据可能延迟或缺失，不构成投资建议。一手期望毛利仍是粗略复盘代理，未覆盖甲组/乙组获配曲线、融资利息、手续费和未中签资金机会成本。",
        ]
    )
    return "\n".join(lines) + "\n"


def ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def num(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.1f}"


def format_miss(item: dict[str, Any]) -> str:
    rec = item["recommendation"]
    reasons = "；".join((rec.get("evidence") or rec.get("risks") or [])[:3])
    return f"- {display_stock(item)}：推荐 {rec['action']}，首日 {pct(item.get('first_day_change_pct'))}，原因/风险：{reasons or '未记录'}。"


def render_miss_attribution_table(records: list[dict[str, Any]], *, threshold: float) -> list[str]:
    rows = ["| 归因 | 次数 | 示例 |", "|---|---:|---|"]
    for item in summarize_miss_attribution(records, threshold=threshold):
        rows.append(f"| {item['reason']} | {item['count']} | {'、'.join(item['examples'])} |")
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    parser.add_argument("--max-pages", type=int, default=13)
    parser.add_argument("--max-details", type=int, help="Limit detail-page fetches for debugging.")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=4, help="Concurrent detail-page workers.")
    parser.add_argument("--strong-threshold-pct", type=float, default=20.0)
    parser.add_argument("--regime-window", type=int, default=20, help="Trailing listed IPO count for market temperature.")
    parser.add_argument("--regime-min-samples", type=int, default=8, help="Minimum trailing samples before applying market temperature.")
    parser.add_argument("--input-json", help="Reuse a previously captured single-year payload.")
    parser.add_argument("--rescore-input", action="store_true", help="Recompute recommendations for --input-json with current rules.")
    parser.add_argument("--margin-heat-json", action="append", help="Historical pre-close margin heat JSON. Can be repeated.")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown.")
    return parser.parse_args(argv)


def load_margin_heat_payload(paths: list[str] | None) -> dict[str, Any] | None:
    if not paths:
        return None
    payloads = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            payloads.append(json.load(handle))
    return normalize_margin_heat_payloads(payloads)


def run_year_backtest(
    *,
    year: int,
    max_pages: int = 13,
    max_details: int | None = None,
    timeout: int = 5,
    retries: int = 0,
    delay: float = 0.0,
    workers: int = 4,
    strong_threshold_pct: float = 20.0,
    regime_window: int = 20,
    regime_min_samples: int = 8,
    margin_heat_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records, sources = fetch_year_listed(year, max_pages, timeout, retries)
    records = enrich_details(
        records,
        timeout=timeout,
        retries=retries,
        delay=delay,
        max_details=max_details,
        workers=workers,
    )
    records = enrich_hkex_documents(records, timeout, retries)
    records, hkex_report_sources = enrich_hkex_listing_reports(records, year=year, timeout=timeout, retries=retries)
    sources.extend(hkex_report_sources)
    return build_year_payload(
        year=year,
        records=records,
        sources=sources,
        strong_threshold_pct=strong_threshold_pct,
        regime_window=regime_window,
        regime_min_samples=regime_min_samples,
        margin_heat_payload=margin_heat_payload,
    )


def build_year_payload(
    *,
    year: int,
    records: list[dict[str, Any]],
    sources: list[dict[str, Any]] | None = None,
    strong_threshold_pct: float = 20.0,
    regime_window: int = 20,
    regime_min_samples: int = 8,
    margin_heat_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attach_market_regimes(
        records,
        window=regime_window,
        min_samples=regime_min_samples,
        strong_threshold=strong_threshold_pct,
    )
    for record in records:
        record["legacy_recommendation"] = static_score(record, optimized=False)
        record["recommendation"] = optimized_preclose_score(record)
        record["review_label"] = static_score(record, optimized=True)
        record["actual_label"] = actual_label(record.get("first_day_change_pct"), strong_threshold_pct)

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "year": year,
        "strong_threshold_pct": strong_threshold_pct,
        "sources": sources or [],
        "records": records,
        "summary": summarize(records, threshold=strong_threshold_pct),
        "legacy_summary": summarize(records, threshold=strong_threshold_pct, key="legacy_recommendation"),
        "review_summary": summarize(records, threshold=strong_threshold_pct, key="review_label"),
        "financing_summary": summarize_financing(records, threshold=strong_threshold_pct),
        "margin_history_coverage": summarize_margin_history_coverage(records, margin_heat_payload=margin_heat_payload),
        "capital_schedule": summarize_capital_schedule(records),
        "capital_schedule_variants": summarize_capital_schedule_variants(records),
        "heat_gate_proxy": summarize_heat_gate_proxy(records, threshold=strong_threshold_pct),
        "score_band_summary": summarize_score_bands(records, threshold=strong_threshold_pct),
        "miss_attribution_summary": summarize_miss_attribution_audit(records, threshold=strong_threshold_pct),
        "borderline_observation": summarize_borderline_observation(records, threshold=strong_threshold_pct),
        "regime_summary": summarize_regime(records, threshold=strong_threshold_pct),
        "data_quality": summarize_data_quality(records),
    }


def rescore_year_payload(
    payload: dict[str, Any],
    *,
    strong_threshold_pct: float | None = None,
    regime_window: int = 20,
    regime_min_samples: int = 8,
    margin_heat_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    threshold = strong_threshold_pct if strong_threshold_pct is not None else float(payload.get("strong_threshold_pct") or 20.0)
    records = [dict(record) for record in payload.get("records") or []]
    return build_year_payload(
        year=int(payload.get("year") or dt.date.today().year),
        records=records,
        sources=payload.get("sources") or [],
        strong_threshold_pct=threshold,
        regime_window=regime_window,
        regime_min_samples=regime_min_samples,
        margin_heat_payload=margin_heat_payload,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    margin_heat_payload = load_margin_heat_payload(args.margin_heat_json)
    if args.input_json:
        with open(args.input_json, encoding="utf-8") as handle:
            payload = json.load(handle)
        if args.rescore_input or margin_heat_payload is not None:
            payload = rescore_year_payload(
                payload,
                strong_threshold_pct=args.strong_threshold_pct,
                regime_window=args.regime_window,
                regime_min_samples=args.regime_min_samples,
                margin_heat_payload=margin_heat_payload,
            )
    else:
        payload = run_year_backtest(
            year=args.year,
            max_pages=args.max_pages,
            max_details=args.max_details,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay,
            workers=args.workers,
            strong_threshold_pct=args.strong_threshold_pct,
            regime_window=args.regime_window,
            regime_min_samples=args.regime_min_samples,
            margin_heat_payload=margin_heat_payload,
        )
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
