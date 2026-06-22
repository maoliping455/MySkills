#!/usr/bin/env python3
"""Normalize historical broker margin heat rows for gate backtesting."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from normalize_margin_input import clean, normalize_text


TRUE_VALUES = {"1", "true", "yes", "y", "是", "已确认", "确认", "preclose", "before"}
FALSE_VALUES = {"0", "false", "no", "n", "否", "未确认", "未知", "after", "post"}
POST_CLOSE_EVIDENCE_PATTERNS = [
    "一手中签",
    "一手中籤",
    "中签率",
    "中籤率",
    "稳中",
    "穩中",
    "配售结果",
    "配售結果",
    "分配结果",
    "分配結果",
    "暗盘",
    "暗盤",
    "首日",
    "上市表现",
    "上市表現",
    "上市首日",
    "现价",
    "現價",
    "累积表现",
    "累積表現",
    "破发",
    "破發",
    "收涨",
    "收漲",
    "收跌",
    "first day",
    "grey market",
    "allotment",
    "one-lot",
    "one lot",
    "success rate",
    "listedipo",
]
OVERSUBSCRIPTION_EVIDENCE_PATTERNS = [
    "超购",
    "超额认购",
    "超額認購",
    "oversubscription",
]
FIRST_DAY_FORECAST_TERMS = [
    "情景",
    "预估",
    "预计",
    "预测",
    "預估",
    "預計",
    "預測",
    "假设",
    "假設",
    "scenario",
    "forecast",
    "estimate",
]
PRE_CLOSE_FIRST_DAY_CONTEXT_TERMS = [
    "招股首日",
    "招股第一日",
    "申购首日",
    "申購首日",
    "认购首日",
    "認購首日",
    "公开招股首日",
    "公開招股首日",
    "开招首日",
    "開招首日",
    "首日孖展",
    "首日融资",
    "首日融資",
    "首日认购",
    "首日認購",
    "first day of subscription",
    "first subscription day",
]
PRE_CLOSE_DEMAND_CONTEXT_TERMS = [
    "孖展",
    "融资",
    "券商",
    "额度",
    "认购额",
    "申购",
    "招股",
    "公开招股",
    "截至",
    "当前",
    "目前",
    "现时",
    "暂录",
    "申购前",
    "融资截止",
    "券商截止",
    "margin",
    "margin financing",
    "preclose",
    "pre-close",
    "before cutoff",
    "as of",
    "subscription period",
]
CREDIT_CUTOFF_CONTEXT_TERMS = [
    "信贷便利申请认购",
    "信貸便利申請認購",
    "信贷便利申请",
    "信貸便利申請",
    "信贷便利截止",
    "信貸便利截止",
    "融资截止",
    "融資截止",
    "券商融资截止",
    "券商融資截止",
    "credit facility application",
    "credit facility cutoff",
    "financing cutoff",
]
POST_CLOSE_RESULT_TERMS = [
    "一手中签",
    "一手中籤",
    "中签率",
    "中籤率",
    "配售结果",
    "配售結果",
    "分配结果",
    "分配結果",
    "公布售股结果",
    "公布售股結果",
    "暗盘",
    "暗盤",
    "上市表现",
    "上市表現",
    "上市首日",
    "现价",
    "現價",
    "累积表现",
    "累積表現",
    "破发",
    "破發",
    "收涨",
    "收漲",
    "收跌",
    "listedipo",
    "allotment",
    "grey market",
    "success rate",
    "current price",
    "cumulative performance",
]
GUARDRAIL_REFERENCE_TERMS = [
    "只作复盘",
    "只作覆盤",
    "仅作复盘",
    "僅作覆盤",
    "复盘标签",
    "覆盤標籤",
    "复盘线索",
    "覆盤線索",
    "不填",
    "未填",
    "不得",
    "不能作为",
    "不能作為",
    "无法作为",
    "無法作為",
    "不用于",
    "不用於",
    "不納入",
    "不纳入",
    "不是",
    "非",
    "排除",
    "excluded",
    "review-only",
    "not used",
]
USER_FILLED_FIELD_GROUPS = [
    ("observed_at", "date", "记录时间"),
    ("source_published_at", "published_at", "来源发布时间", "发布时间"),
    ("preclose_confirmed", "融资截止前", "pre_close"),
    ("broker_cutoff_at", "financing_cutoff_at", "融资截止时间"),
    ("margin_multiple", "孖展倍数"),
    ("margin_amount_hkd", "margin_amount", "孖展金额"),
    ("quota_status", "额度状态"),
    ("financing_rate_pct", "rate_pct", "融资利率"),
    ("cutoff_note", "截止备注"),
    ("acceleration", "加速信号"),
    ("source", "来源"),
    ("excerpt", "摘录", "text"),
    ("search_attempted_at", "检索时间"),
    ("search_source", "检索来源"),
    ("unavailable_reason", "不可得原因"),
    ("search_note", "检索说明"),
]


def row_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = clean(row.get(key))
        if value:
            return value
    return ""


def row_has_user_input(row: dict[str, Any]) -> bool:
    return any(row_value(row, *keys) for keys in USER_FILLED_FIELD_GROUPS)


def canonical_history_code(value: Any) -> str | None:
    text = clean(value)
    if not text:
        return None
    match = re.search(r"(?<!\d)(\d{1,5})(?:\.HK)?(?!\d)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).zfill(5)


def parse_bool(value: Any) -> bool | None:
    text = clean(value).lower()
    if not text:
        return None
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def parse_date(value: Any) -> dt.date | None:
    text = clean(value)
    if not text:
        return None
    normalized = text.replace("年", "-").replace("月", "-").replace("日", " ")
    match = re.search(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", normalized)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def parse_datetime(value: Any) -> dt.datetime | None:
    text = clean(value)
    if not text:
        return None
    normalized = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", " ")
        .replace("時", "点")
        .replace("时", "点")
        .replace("點", "点")
    )
    match = re.search(
        r"(?<!\d)(20\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})"
        r"(?:[^\d]{0,24}(上午|下午|早上|晚上|中午)?\s*(\d{1,2})\s*(?::|：|点)\s*(\d{1,2})?)?",
        normalized,
    )
    if not match or not match.group(5):
        return None
    year, month, day = (int(part) for part in match.groups()[:3])
    meridian = match.group(4) or ""
    hour = int(match.group(5))
    minute = int(match.group(6) or 0)
    if meridian in {"下午", "晚上"} and hour < 12:
        hour += 12
    if meridian in {"上午", "早上"} and hour == 12:
        hour = 0
    if meridian == "中午" and hour < 11:
        hour += 12
    try:
        return dt.datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def evidence_timing_text(row: dict[str, Any]) -> str:
    keys = [
        "excerpt",
        "摘录",
        "text",
        "cutoff_note",
        "截止备注",
        "source",
        "来源",
        "collection_note",
        "备注",
    ]
    return " ".join(clean(row.get(key)) for key in keys if clean(row.get(key)))


def contextual_credit_cutoff_datetimes(row: dict[str, Any]) -> list[dt.datetime]:
    text = evidence_timing_text(row)
    if not text:
        return []
    lower_text = text.lower()
    cutoffs: list[dt.datetime] = []
    for term in CREDIT_CUTOFF_CONTEXT_TERMS:
        haystack = lower_text if term == term.lower() else text
        needle = term.lower() if term == term.lower() else term
        start = haystack.find(needle)
        while start >= 0:
            window = text[start : start + 120]
            parsed = parse_datetime(window)
            if parsed:
                cutoffs.append(parsed)
            start = haystack.find(needle, start + len(needle))
    return cutoffs


def timing_review(row: dict[str, Any], *, assume_preclose: bool) -> dict[str, Any]:
    observed_raw = row_value(row, "observed_at", "date", "记录时间")
    published_raw = row_value(row, "source_published_at", "published_at", "来源发布时间", "发布时间")
    closing_raw = row_value(row, "closing_date", "招股截止", "招股截止日")
    allotment_raw = row_value(row, "allotment_date", "公布售股结果日期", "配售结果日期")
    refund_raw = row_value(row, "refund_date", "退票寄发日期")
    listing_raw = row_value(row, "listing_date", "上市日期")
    cutoff_raw = row_value(row, "broker_cutoff_at", "financing_cutoff_at", "融资截止时间")
    preclose_flag = parse_bool(row.get("preclose_confirmed") or row.get("融资截止前") or row.get("pre_close"))

    observed_date = parse_date(observed_raw)
    observed_dt = parse_datetime(observed_raw)
    published_date = parse_date(published_raw)
    published_dt = parse_datetime(published_raw)
    closing_date = parse_date(closing_raw)
    cutoff_date = parse_date(cutoff_raw)
    cutoff_dt = parse_datetime(cutoff_raw)
    contextual_cutoffs = contextual_credit_cutoff_datetimes(row)
    earliest_contextual_cutoff = min(contextual_cutoffs) if contextual_cutoffs else None
    post_close_dates = [parse_date(value) for value in [allotment_raw, refund_raw, listing_raw]]
    post_close_dates = [value for value in post_close_dates if value is not None]

    risks: list[str] = []
    if observed_raw and observed_date is None:
        risks.append("记录时间无法解析")
    if published_raw and published_date is None:
        risks.append("来源发布时间无法解析")
    if not observed_raw and not assume_preclose:
        risks.append("记录时间缺失")
    if preclose_flag is not True and not assume_preclose:
        risks.append("融资截止前时间未确认")
    if cutoff_dt and earliest_contextual_cutoff and cutoff_dt > earliest_contextual_cutoff:
        risks.append("broker_cutoff_at晚于证据文本中的信贷便利截止")

    latest_allowed = cutoff_date or closing_date
    if observed_dt and cutoff_dt and observed_dt > cutoff_dt:
        risks.append("记录时间晚于券商融资截止")
    if observed_dt and earliest_contextual_cutoff and observed_dt > earliest_contextual_cutoff:
        risks.append("记录时间晚于证据文本中的信贷便利截止")
    elif cutoff_dt and observed_date and observed_date == cutoff_dt.date() and observed_dt is None:
        risks.append("记录时间缺少具体时刻，无法确认早于券商融资截止")
    elif observed_date and latest_allowed and observed_date > latest_allowed:
        risks.append("记录时间晚于券商/招股截止")
    elif observed_date and not latest_allowed and post_close_dates and observed_date >= min(post_close_dates):
        risks.append("记录时间不早于配售/退款/上市日")

    if published_dt and cutoff_dt and published_dt > cutoff_dt:
        risks.append("来源发布时间晚于券商融资截止")
    if published_dt and earliest_contextual_cutoff and published_dt > earliest_contextual_cutoff:
        risks.append("来源发布时间晚于证据文本中的信贷便利截止")
    elif cutoff_dt and published_date and published_date == cutoff_dt.date() and published_dt is None:
        risks.append("来源发布时间缺少具体时刻，无法确认早于券商融资截止")
    elif published_date and latest_allowed and published_date > latest_allowed:
        risks.append("来源发布时间晚于券商/招股截止")
    elif published_date and not latest_allowed and post_close_dates and published_date >= min(post_close_dates):
        risks.append("来源发布时间不早于配售/退款/上市日")

    timing_confirmed = not risks and (preclose_flag is True or assume_preclose)
    confidence = "假定" if timing_confirmed and assume_preclose and preclose_flag is not True else "已确认" if timing_confirmed else "未确认"
    return {
        "timing_confirmed": timing_confirmed,
        "timing_confidence": confidence,
        "timing_risks": sorted(set(risks)),
        "observed_at": observed_raw or None,
        "observed_date": observed_date.isoformat() if observed_date else None,
        "observed_datetime": observed_dt.isoformat(timespec="minutes") if observed_dt else None,
        "source_published_at": published_dt.isoformat(timespec="minutes") if published_dt else published_raw or None,
        "source_published_date": published_date.isoformat() if published_date else None,
        "closing_date": closing_date.isoformat() if closing_date else None,
        "broker_cutoff_date": cutoff_date.isoformat() if cutoff_date else None,
        "broker_cutoff_at": cutoff_dt.isoformat(timespec="minutes") if cutoff_dt else cutoff_raw or None,
        "contextual_credit_cutoff_at": earliest_contextual_cutoff.isoformat(timespec="minutes") if earliest_contextual_cutoff else None,
        "preclose_confirmed": preclose_flag,
    }


def contains_any_term(text: str, lower_text: str, terms: list[str]) -> bool:
    return any(term in text or term in lower_text for term in terms)


def has_first_day_forecast_context(text: str, lower_text: str) -> bool:
    return contains_any_term(text, lower_text, FIRST_DAY_FORECAST_TERMS)


def has_preclose_first_day_context(text: str, lower_text: str) -> bool:
    return contains_any_term(text, lower_text, PRE_CLOSE_FIRST_DAY_CONTEXT_TERMS) or bool(
        re.search(r"(招股|公开招股|公開招股|申购|申購|认购|認購).{0,12}首日", text)
        or re.search(r"首日.{0,12}(孖展|融资|融資|认购|認購|申购|申購|招股|公開招股|公开招股)", text)
        or re.search(r"(first day of subscription|first subscription day)", lower_text)
    )


def has_preclose_demand_context(text: str, lower_text: str) -> bool:
    return contains_any_term(
        text,
        lower_text,
        [*PRE_CLOSE_DEMAND_CONTEXT_TERMS, *FIRST_DAY_FORECAST_TERMS],
    )


def has_post_close_result_context(text: str, lower_text: str) -> bool:
    for term in POST_CLOSE_RESULT_TERMS:
        if term not in text and term not in lower_text:
            continue
        if pattern_is_guardrail_reference(text, lower_text, term):
            continue
        if term in {"首日", "上市首日", "暗盘", "暗盤", "grey market"} and (
            has_first_day_forecast_context(text, lower_text)
            or has_preclose_first_day_context(text, lower_text)
        ):
            continue
        return True
    final_oversub = re.search(r"(最终|最後|最后).{0,16}(超购|超額認購|超额认购)", text)
    if final_oversub and not has_first_day_forecast_context(text, lower_text):
        return True
    if re.search(r"final.{0,16}oversubscription", lower_text) and not has_first_day_forecast_context(text, lower_text):
        return True
    return bool(
        re.search(r"(公开发售|香港公开发售|国际发售|国际配售).{0,12}(获|錄得|录得).{0,24}(超购|超額認購|超额认购|认购)", text)
        or re.search(r"(public offer|international placing).{0,24}(recorded|received|was|were).{0,24}oversubscription", lower_text)
    )


def pattern_is_guardrail_reference(text: str, lower_text: str, pattern: str) -> bool:
    lower_mode = pattern == pattern.lower()
    haystack = lower_text if lower_mode else text
    needle = pattern.lower() if lower_mode else pattern
    start = haystack.find(needle)
    while start >= 0:
        window = text[max(0, start - 24) : start + len(pattern) + 24]
        lower_window = window.lower()
        if contains_any_term(window, lower_window, GUARDRAIL_REFERENCE_TERMS) and not re.search(r"\d", window):
            return True
        start = haystack.find(needle, start + len(needle))
    return False


def oversubscription_is_preclose_demand_context(text: str, lower_text: str) -> bool:
    if has_post_close_result_context(text, lower_text):
        return False
    return has_preclose_demand_context(text, lower_text)


def evidence_contamination_review(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "excerpt",
        "摘录",
        "text",
        "quota_status",
        "额度状态",
        "cutoff_note",
        "截止备注",
        "acceleration",
        "加速信号",
        "source",
        "来源",
        "search_source",
        "检索来源",
        "unavailable_reason",
        "不可得原因",
        "search_note",
        "检索说明",
    ]
    evidence_text = " ".join(clean(row.get(key)) for key in keys if clean(row.get(key)))
    evidence_lower = evidence_text.lower()
    matched = []
    for pattern in POST_CLOSE_EVIDENCE_PATTERNS:
        if pattern not in evidence_text and pattern not in evidence_lower:
            continue
        if pattern_is_guardrail_reference(evidence_text, evidence_lower, pattern):
            continue
        if pattern in {"首日", "上市首日", "first day", "暗盘", "暗盤", "grey market"} and (
            has_first_day_forecast_context(evidence_text, evidence_lower)
            or has_preclose_first_day_context(evidence_text, evidence_lower)
        ):
            continue
        matched.append(pattern)
    for pattern in OVERSUBSCRIPTION_EVIDENCE_PATTERNS:
        if pattern not in evidence_text and pattern not in evidence_lower:
            continue
        if pattern_is_guardrail_reference(evidence_text, evidence_lower, pattern):
            continue
        if oversubscription_is_preclose_demand_context(evidence_text, evidence_lower):
            continue
        matched.append(pattern)
    risks = [f"摘录疑似包含配售后/上市后结果：{pattern}" for pattern in matched]
    return {
        "evidence_eligible": not risks,
        "evidence_risks": sorted(set(risks)),
    }


def read_rows(path: str, fmt: str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    detected = fmt
    if detected == "auto":
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            detected = "csv"
        elif suffix in {".jsonl", ".ndjson"}:
            detected = "jsonl"
        else:
            detected = "json"

    if detected == "csv":
        return [dict(row) for row in csv.DictReader(text.splitlines())]
    if detected == "jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if detected == "json":
        payload = json.loads(text)
        if isinstance(payload, list):
            return [dict(item) for item in payload]
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            return [dict(item) for item in payload["rows"]]
        raise SystemExit("JSON input must be a list or an object with rows=[...].")
    raise SystemExit(f"Unsupported format: {fmt}")


def row_stock_key(row: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_code = row_value(row, "code", "stock_code", "股票代码")
    code = canonical_history_code(raw_code) or raw_code or None
    name = row_value(row, "stock_name", "name", "股票名称") or None
    if code:
        return code, None
    return None, name


def row_to_excerpt(row: dict[str, Any]) -> str:
    parts = []
    broker = row_value(row, "broker", "券商")
    if broker:
        parts.append(f"{broker}：")
    excerpt = row_value(row, "excerpt", "摘录", "text")
    if excerpt:
        parts.append(excerpt)
    margin_multiple = row_value(row, "margin_multiple", "孖展倍数")
    if margin_multiple:
        parts.append(f"孖展认购 {margin_multiple}倍。")
    margin_amount = row_value(row, "margin_amount_hkd", "margin_amount", "孖展金额")
    if margin_amount:
        parts.append(f"孖展金额 {margin_amount}。")
    rate = row_value(row, "financing_rate_pct", "rate_pct", "融资利率")
    if rate:
        parts.append(f"年化利率 {rate}%。")
    quota = row_value(row, "quota_status", "额度状态")
    if quota:
        parts.append(quota)
    cutoff = row_value(row, "cutoff_note", "截止备注")
    if cutoff:
        parts.append(cutoff)
    acceleration = row_value(row, "acceleration", "加速信号")
    if acceleration:
        parts.append(acceleration)
    return " ".join(parts)


def row_is_attempted_data_gap(row: dict[str, Any], *, evidence_eligible: bool) -> bool:
    if not evidence_eligible:
        return False
    if not row_value(row, "unavailable_reason", "不可得原因"):
        return False
    return bool(
        row_value(row, "search_attempted_at", "检索时间")
        and row_value(row, "search_source", "检索来源", "source", "来源")
        and (row_value(row, "search_note", "检索说明") or row_value(row, "excerpt", "摘录", "text"))
    )


def display_timing_risks(row: dict[str, Any], timing: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    if not row_has_user_input(row):
        return []
    if row_is_attempted_data_gap(row, evidence_eligible=evidence["evidence_eligible"]):
        return []
    return list(timing["timing_risks"])


def normalize_rows(rows: list[dict[str, Any]], *, assume_preclose: bool = False) -> dict[str, Any]:
    grouped: dict[tuple[str | None, str | None], list[dict[str, Any]]] = {}
    for row in rows:
        key = row_stock_key(row)
        grouped.setdefault(key, []).append(row)

    stocks = []
    for (code, key_name), stock_rows in grouped.items():
        name = key_name or next(
            (row_value(row, "stock_name", "name", "股票名称") for row in stock_rows if row_value(row, "stock_name", "name", "股票名称")),
            None,
        )
        reviewed_rows = [
            (
                row,
                timing_review(row, assume_preclose=assume_preclose),
                evidence_contamination_review(row),
            )
            for row in stock_rows
        ]
        eligible_rows = [
            row
            for row, timing, evidence in reviewed_rows
            if timing["timing_confirmed"] and evidence["evidence_eligible"]
        ]
        excerpts = [row_to_excerpt(row) for row in eligible_rows if row_to_excerpt(row)]
        payload = normalize_text("\n".join(excerpts), stock_name=name, code=code)
        timing_confirmed = bool(eligible_rows)
        summary = payload["summary"]
        timing_risks = sorted(
            {
                risk
                for row, timing, evidence in reviewed_rows
                for risk in display_timing_risks(row, timing, evidence)
            }
        )
        evidence_risks = sorted({risk for _, _, evidence in reviewed_rows for risk in evidence["evidence_risks"]})
        if not timing_confirmed:
            risks = list(summary.get("risk_flags") or [])
            risks.extend(timing_risks)
            risks.extend(evidence_risks)
            if not timing_risks and not evidence_risks:
                risks.append("融资截止前时间未确认")
            summary["risk_flags"] = sorted(set(risks))
            summary["execution_gate"] = "不满足"
            summary["timing_confidence"] = "未确认"
        else:
            risks = list(summary.get("risk_flags") or [])
            if timing_risks:
                risks.append("部分历史行未通过时间校验")
            if evidence_risks:
                risks.append("部分历史行疑似包含配售后/上市后结果，已排除")
            summary["risk_flags"] = sorted(set(risks))
            confidences = {
                timing["timing_confidence"]
                for _, timing, evidence in reviewed_rows
                if timing["timing_confirmed"] and evidence["evidence_eligible"]
            }
            summary["timing_confidence"] = "已确认" if "已确认" in confidences else "假定"
        summary["timing_valid_row_count"] = len(eligible_rows)
        summary["timing_invalid_row_count"] = len(stock_rows) - len(eligible_rows)
        summary["evidence_contaminated_row_count"] = sum(
            1 for _, _, evidence in reviewed_rows if not evidence["evidence_eligible"]
        )
        summary["pending_input_row_count"] = sum(1 for row in stock_rows if not row_has_user_input(row))
        summary["attempted_data_gap_row_count"] = sum(
            1 for row, _, evidence in reviewed_rows if row_is_attempted_data_gap(row, evidence_eligible=evidence["evidence_eligible"])
        )
        payload["history_rows"] = [
            {
                "broker": row_value(row, "broker", "券商") or None,
                "input_pending": not row_has_user_input(row),
                "attempted_data_gap": row_is_attempted_data_gap(row, evidence_eligible=evidence["evidence_eligible"]),
                "observed_at": timing["observed_at"],
                "source_published_at": timing["source_published_at"],
                "source_published_date": timing["source_published_date"],
                "observed_date": timing["observed_date"],
                "observed_datetime": timing["observed_datetime"],
                "closing_date": timing["closing_date"],
                "broker_cutoff_date": timing["broker_cutoff_date"],
                "broker_cutoff_at": timing["broker_cutoff_at"],
                "contextual_credit_cutoff_at": timing["contextual_credit_cutoff_at"],
                "preclose_confirmed": timing["preclose_confirmed"],
                "timing_confirmed": timing["timing_confirmed"],
                "timing_confidence": timing["timing_confidence"],
                "timing_risks": display_timing_risks(row, timing, evidence),
                "evidence_eligible": evidence["evidence_eligible"],
                "evidence_risks": evidence["evidence_risks"],
                "source": row_value(row, "source", "来源") or None,
                "search_attempted_at": row_value(row, "search_attempted_at", "检索时间") or None,
                "search_source": row_value(row, "search_source", "检索来源") or None,
                "unavailable_reason": row_value(row, "unavailable_reason", "不可得原因") or None,
                "search_note": row_value(row, "search_note", "检索说明") or None,
            }
            for row, timing, evidence in reviewed_rows
        ]
        stocks.append(payload)

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "schema_version": 1,
        "stocks": stocks,
        "disclaimer": "Historical margin heat must be captured before broker financing cutoff to support execution-gate backtests.",
    }


def stock_status(stock: dict[str, Any]) -> str:
    rows = stock.get("history_rows") or []
    summary = stock.get("summary") or {}
    if rows and all(row.get("input_pending") for row in rows):
        return "待填回"
    if int(summary.get("timing_valid_row_count") or 0) > 0:
        return "可复核"
    if int(summary.get("attempted_data_gap_row_count") or 0) > 0:
        return "已尝试缺口"
    if int(summary.get("evidence_contaminated_row_count") or 0) > 0:
        return "证据污染"
    return "时间无效"


def stock_display(stock: dict[str, Any]) -> str:
    name = clean(stock.get("stock_name"))
    code = clean(stock.get("code"))
    if name and code:
        return f"{name}（{code}）"
    return name or code or "待核实"


def short_text(values: list[str], *, limit: int = 4) -> str:
    cleaned = [clean(value) for value in values if clean(value)]
    if not cleaned:
        return "-"
    text = "；".join(cleaned[:limit])
    if len(cleaned) > limit:
        text += f"；另{len(cleaned) - limit}项"
    return text


def render_markdown(payload: dict[str, Any]) -> str:
    stocks = payload.get("stocks") or []
    statuses = {status: 0 for status in ["可复核", "待填回", "时间无效", "证据污染", "已尝试缺口"]}
    gate_met = 0
    gate_not_met = 0
    for stock in stocks:
        status = stock_status(stock)
        statuses[status] = statuses.get(status, 0) + 1
        gate = (stock.get("summary") or {}).get("execution_gate")
        if gate == "满足":
            gate_met += 1
        elif status == "可复核":
            gate_not_met += 1

    lines = [
        "# 历史孖展填回质量审查",
        "",
        f"生成时间：{payload.get('generated_at') or '-'}",
        (
            f"股票数：{len(stocks)}；可复核：{statuses.get('可复核', 0)}；待填回：{statuses.get('待填回', 0)}；"
            f"时间无效：{statuses.get('时间无效', 0)}；证据污染：{statuses.get('证据污染', 0)}；"
            f"已尝试缺口：{statuses.get('已尝试缺口', 0)}。"
        ),
        f"严格闸门满足：{gate_met}；可复核但闸门未满足：{gate_not_met}。",
        "防泄露口径：Historical margin heat must be captured before broker financing cutoff. Final oversubscription, one-lot success, allotment, grey-market, first-day, current-price, or cumulative-performance evidence is retained for review but excluded from execution gates.",
        "",
        "| 股票 | 代码 | 状态 | 有效行 | 闸门 | 强热度 | 成本 | 时间/证据风险 |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    if not stocks:
        lines.append("| - | - | 暂无历史孖展行 | 0 | - | - | - | - |")
    for stock in stocks:
        summary = stock.get("summary") or {}
        status = stock_status(stock)
        if status == "待填回":
            risk_text = "等待填回，尚未校验时间"
        else:
            row_risks = sorted(
                {
                    risk
                    for row in stock.get("history_rows") or []
                    for risk in [*(row.get("timing_risks") or []), *(row.get("evidence_risks") or [])]
                }
            )
            risk_text = short_text([*(summary.get("risk_flags") or []), *row_risks], limit=5)
        lines.append(
            f"| {stock_display(stock)} | {clean(stock.get('code')) or '-'} | {status} | "
            f"{summary.get('timing_valid_row_count', 0)} | {summary.get('execution_gate') or '-'} | "
            f"{short_text(summary.get('strong_signals') or [], limit=3)} | "
            f"{summary.get('cost_status') or '-'} | {risk_text} |"
        )
    lines.extend(
        [
            "",
            "## 使用结论",
            "- `待填回` 代表模板还没有任何用户填入的时间、热度、成本、来源或摘录字段；先补 `observed_at`、`source_published_at`、`preclose_confirmed`、`broker_cutoff_at`、孖展倍数/金额、额度、利率和来源。",
            "- 只有 `可复核` 且时间有效的股票可进入 `backtest_margin_gate.py`；`时间无效` 和 `证据污染` 行只能保留为复盘备注。",
            "- `已尝试缺口` 代表已记录无污染公开检索尝试但没有找到历史申购前孖展证据；只有显式接受数据缺口时才算闭环。",
            "- 闸门未满足不等于策略失败，通常说明仍缺第二个独立需求/额度热度信号或成本证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--format", choices=["auto", "csv", "jsonl", "json"], default="auto")
    parser.add_argument("--assume-preclose", action="store_true", help="Treat rows without explicit timing as pre-close. Use only for trusted historical data.")
    parser.add_argument("--markdown", action="store_true", help="Output a fill-quality Markdown review instead of JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_rows(args.input, args.format)
    payload = normalize_rows(rows, assume_preclose=args.assume_preclose)
    if args.markdown:
        sys.stdout.write(render_markdown(payload))
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
