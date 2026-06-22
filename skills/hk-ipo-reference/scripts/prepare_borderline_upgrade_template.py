#!/usr/bin/env python3
"""Prepare a T-1/T-0 upgrade research template for borderline observation IPOs."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

from build_recommendation_report import chinese_display_alias
from fetch_current_ipos import clean_stock_name


DEFAULT_BROKERS = ["富途", "辉立", "耀才"]
DEFAULT_MIN_SCORE = 65
BORDERLINE_P0_SCORE = 69
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
SCARCE_SIGNAL_KEYWORDS = [
    "稀缺",
    "科技",
    "硬科技",
    "智能",
    "医疗器械",
    "医疗保健",
    "生物",
    "医药",
    "制药",
    "防守行业",
]
CSV_FIELDS = [
    "group_id",
    "stock",
    "code",
    "action",
    "financing_tier",
    "score",
    "preclose_utility",
    "window",
    "lock_days",
    "cash_required_hkd",
    "entry_fee_hkd",
    "collection_priority",
    "priority_reasons",
    "required_checks",
    "upgrade_condition",
    "broker",
    "observed_at",
    "source_published_at",
    "broker_cutoff_at",
    "margin_multiple",
    "margin_amount_hkd",
    "quota_status",
    "financing_rate_pct",
    "fees_hkd",
    "financing_days",
    "scenario_first_day_pct",
    "scenario_allotment_rate_pct",
    "max_credible_allotment_rate_pct",
    "prospectus_url",
    "deep_dive_focus",
    "source",
    "excerpt",
    "collection_note",
]
UPGRADE_CONDITION = (
    "至少两个融资截止前需求/额度类强热度信号且成本可接受；"
    "招股书估值、基石/禁售和主要风险无重大反证；"
    "通过资金窗口和融资效率审计后才可从观察升级到现金/甲组，乙组仍需单独核价。"
)


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def contains_chinese(value: str | None) -> bool:
    return bool(value and re.search(r"[\u4e00-\u9fff]", value))


def split_brokers(value: str | None) -> list[str]:
    if value is None:
        return DEFAULT_BROKERS
    brokers = [item.strip() for item in value.split(",") if item.strip()]
    return brokers or [""]


def records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("records") or payload.get("ipos") or payload.get("items") or []
    return [item for item in rows if isinstance(item, dict)]


def code_for(record: dict[str, Any]) -> str:
    return clean(record.get("code") or record.get("canonical_code"))


def stock_name(record: dict[str, Any]) -> str:
    name = clean_stock_name(record.get("name") or record.get("stock_name") or "")
    if contains_chinese(name):
        return name
    alias = chinese_display_alias(record)
    if alias:
        return alias
    code = code_for(record)
    return f"代码{code}（中文名待核实）" if code else "中文名待核实"


def recommendation(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("recommendation") or {}


def recommendation_score(record: dict[str, Any]) -> int:
    try:
        return int(recommendation(record).get("score") or 0)
    except (TypeError, ValueError):
        return 0


def action(record: dict[str, Any]) -> str:
    return clean(recommendation(record).get("action"))


def financing_tier(record: dict[str, Any]) -> str:
    return clean((recommendation(record).get("financing") or {}).get("tier"))


def preclose_signal_text(record: dict[str, Any]) -> str:
    return " ".join(
        [
            stock_name(record),
            clean(record.get("industry")),
            "；".join(recommendation(record).get("evidence") or []),
            "；".join(recommendation(record).get("risks") or []),
        ]
    )


def has_scarce_signal(record: dict[str, Any]) -> bool:
    text = preclose_signal_text(record)
    return any(keyword in text for keyword in SCARCE_SIGNAL_KEYWORDS)


def is_biotech_or_b_profile(record: dict[str, Any]) -> bool:
    text = preclose_signal_text(record)
    name = stock_name(record)
    return "-B" in name or "－Ｂ" in name or "B/P不直接跳过" in text or any(keyword in text for keyword in ["生物", "医药", "制药"])


def has_strong_sponsor_signal(record: dict[str, Any]) -> bool:
    text = preclose_signal_text(record)
    return "强保荐" in text or "强保荐人" in text


def low_entry_fee_signal(record: dict[str, Any]) -> bool:
    value = record.get("entry_fee_hkd")
    if isinstance(value, (int, float)):
        return value <= 6_000
    return "低入场费" in preclose_signal_text(record) or "入场费较低" in preclose_signal_text(record)


def parse_priority_levels(value: str | None) -> set[str] | None:
    if not value:
        return None
    levels = {item.strip().upper() for item in value.split(",") if item.strip()}
    return levels or None


def priority_info(record: dict[str, Any]) -> tuple[str, str]:
    record_score = recommendation_score(record)
    reasons: list[str] = []
    if record_score >= 72:
        reasons.append("72+接近建议申购阈值")
    elif record_score >= BORDERLINE_P0_SCORE:
        reasons.append(f"{BORDERLINE_P0_SCORE}-71临界高分")
    elif record_score >= DEFAULT_MIN_SCORE:
        reasons.append("65-68观察补采")
    else:
        reasons.append("低于常规临界分，仅在全量观察时抽查")

    if has_scarce_signal(record):
        reasons.append("稀缺/科技/医药或防守题材需验证热度")
    if is_biotech_or_b_profile(record):
        reasons.append("B/P或医药票需确认管线和融资热度")
    if has_strong_sponsor_signal(record):
        reasons.append("强保荐信号需复核兑现")
    if low_entry_fee_signal(record):
        reasons.append("低入场费，适合复核现金参与效率")

    if record_score >= BORDERLINE_P0_SCORE:
        return "P0", "、".join(reasons)
    if record_score >= DEFAULT_MIN_SCORE:
        return "P1", "、".join(reasons)
    return "P2", "、".join(reasons)


def candidate_records(
    payload: dict[str, Any],
    *,
    min_score: int,
    include_all_observation: bool = False,
) -> list[dict[str, Any]]:
    candidates = []
    for record in records_from_payload(payload):
        if action(record) != "可选观察":
            continue
        if not include_all_observation and recommendation_score(record) < min_score:
            continue
        candidates.append(record)
    return sorted(
        candidates,
        key=lambda item: (
            PRIORITY_ORDER.get(priority_info(item)[0], 99),
            -recommendation_score(item),
            clean(item.get("closing_date")),
            stock_name(item),
        ),
    )


def prospectus_url(record: dict[str, Any]) -> str:
    docs = record.get("documents") or {}
    sources = record.get("source_urls") or {}
    return clean(
        docs.get("prospectus_url")
        or docs.get("listing_document_url")
        or sources.get("hkex_listing_information")
        or sources.get("hkex_listing_report")
    )


def lock_days(record: dict[str, Any]) -> str:
    start = clean(record.get("closing_date"))
    end = clean(record.get("refund_date") or record.get("listing_date"))
    if not start or not end:
        return ""
    try:
        return str((dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1)
    except ValueError:
        return ""


def window(record: dict[str, Any]) -> str:
    start = clean(record.get("closing_date"))
    end = clean(record.get("refund_date") or record.get("listing_date"))
    if start and end:
        return f"{start}→{end}"
    return start or end


def required_checks(record: dict[str, Any]) -> list[str]:
    checks = [
        "融资截止前孖展热度",
        "额度紧张度/截止提前",
        "融资利率/手续费/天数",
        "资金窗口/融资效率",
        "招股书估值/发行市值",
        "基石/禁售",
        "募资用途/主要风险",
        "多平台舆情分歧",
    ]
    name = stock_name(record)
    industry = clean(record.get("industry"))
    if "-B" in name or "－Ｂ" in name or "生物" in industry or "医药" in industry:
        checks.append("管线/商业化")
    return checks


def deep_dive_focus(record: dict[str, Any]) -> str:
    focus = ["估值/发行市值", "收入和利润质量", "基石/禁售", "募资用途", "主要风险"]
    name = stock_name(record)
    industry = clean(record.get("industry"))
    if "-B" in name or "－Ｂ" in name or "生物" in industry or "医药" in industry:
        focus.append("管线/商业化")
    if clean(record.get("sponsor")):
        focus.append("保荐质量")
    return "、".join(focus)


def collection_note(record: dict[str, Any]) -> str:
    evidence = "；".join(recommendation(record).get("evidence") or [])
    risks = "；".join(recommendation(record).get("risks") or [])
    parts = [
        "临界观察升级补采；不得用最终超购、一手中签率、配售结果、暗盘或首日涨跌决定升级。",
        "只补券商融资截止前可见材料。",
    ]
    if evidence:
        parts.append(f"事前正面依据：{evidence}")
    if risks:
        parts.append(f"待复核风险：{risks}")
    return " ".join(parts)


def build_rows(
    payload: dict[str, Any],
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    include_all_observation: bool = False,
    brokers: list[str] | None = None,
    limit: int | None = None,
    priority_levels: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    broker_values = brokers if brokers is not None else DEFAULT_BROKERS
    candidates = candidate_records(payload, min_score=min_score, include_all_observation=include_all_observation)
    if limit is not None:
        candidates = candidates[:limit]
    for record in candidates:
        priority, priority_reasons = priority_info(record)
        if priority_levels and priority not in priority_levels:
            continue
        for broker in broker_values:
            rows.append(
                {
                    "group_id": "borderline-upgrade",
                    "stock": stock_name(record),
                    "code": code_for(record),
                    "action": action(record),
                    "financing_tier": financing_tier(record) or "观察待核价",
                    "score": recommendation_score(record),
                    "preclose_utility": "",
                    "window": window(record),
                    "lock_days": lock_days(record),
                    "cash_required_hkd": record.get("entry_fee_hkd") if isinstance(record.get("entry_fee_hkd"), (int, float)) else "",
                    "entry_fee_hkd": record.get("entry_fee_hkd") if isinstance(record.get("entry_fee_hkd"), (int, float)) else "",
                    "collection_priority": priority,
                    "priority_reasons": priority_reasons,
                    "required_checks": "、".join(required_checks(record)),
                    "upgrade_condition": UPGRADE_CONDITION,
                    "broker": broker,
                    "observed_at": "",
                    "source_published_at": "",
                    "broker_cutoff_at": "",
                    "margin_multiple": "",
                    "margin_amount_hkd": "",
                    "quota_status": "",
                    "financing_rate_pct": "",
                    "fees_hkd": "",
                    "financing_days": "",
                    "scenario_first_day_pct": "",
                    "scenario_allotment_rate_pct": "",
                    "max_credible_allotment_rate_pct": "",
                    "prospectus_url": prospectus_url(record),
                    "deep_dive_focus": deep_dive_focus(record),
                    "source": "",
                    "excerpt": "",
                    "collection_note": collection_note(record),
                }
            )
    return rows


def render_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def render_markdown(rows: list[dict[str, Any]], *, year: Any, min_score: int) -> str:
    lines = [
        f"# {year or ''} 临界观察升级补采清单".strip(),
        "",
        f"生成时间：{dt.datetime.now().isoformat(timespec='seconds')}",
        f"口径：事前推荐为 `可选观察` 且评分 >= {min_score}；P0 为 {BORDERLINE_P0_SCORE}+ 临界高分，P1 为 65-68。该清单不是申购指令，只用于融资截止前升级复核。",
        "",
        "| 优先级 | 股票 | 窗口 | 分数 | 融资层 | 券商 | 优先原因 | 需补字段 | 升级条件 | 深挖重点 |",
        "|---|---|---|---:|---|---|---|---|---|---|",
    ]
    if not rows:
        lines.append("| - | 暂无临界观察升级候选 | - | - | - | - | - | - | - | - |")
    for row in rows:
        lines.append(
            f"| {row['collection_priority']} | {row['stock']}（{row['code']}） | {row['window'] or '-'} | {row['score']} | "
            f"{row['financing_tier'] or '-'} | {row['broker'] or '自填'} | {row['priority_reasons'] or '-'} | {row['required_checks']} | "
            f"{row['upgrade_condition']} | {row['deep_dive_focus']} |"
        )
    lines.extend(
        [
            "",
            "要求：`observed_at`、`source_published_at` 和 `broker_cutoff_at` 必须早于券商融资截止；`source` 和 `excerpt` 只能填申购截止前可见资料。",
            "禁止：不要把最终超购、一手中签率、配售结果、暗盘、首日涨跌、现价或累计涨跌作为升级依据。",
            "后续：填回 CSV 后运行 `normalize_conflict_research_input.py`，再把合格的 `items_by_stock` 作为融资热度输入审计。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", "-i", required=True, help="Annual/current IPO JSON payload with recommendation fields.")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--include-all-observation", action="store_true")
    parser.add_argument("--brokers", help="Comma-separated broker names. Omit for 富途,辉立,耀才; pass empty for one blank row.")
    parser.add_argument("--limit", type=int, help="Only include first N borderline stocks before broker expansion.")
    parser.add_argument("--priority-levels", help="Comma-separated priority levels to include, e.g. P0 or P0,P1.")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = load_json(args.input_json)
    rows = build_rows(
        payload,
        min_score=args.min_score,
        include_all_observation=args.include_all_observation,
        brokers=split_brokers(args.brokers),
        limit=args.limit,
        priority_levels=parse_priority_levels(args.priority_levels),
    )
    if args.markdown:
        sys.stdout.write(render_markdown(rows, year=payload.get("year"), min_score=args.min_score))
    else:
        sys.stdout.write(render_csv(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
