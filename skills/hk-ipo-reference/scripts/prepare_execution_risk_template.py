#!/usr/bin/env python3
"""Prepare a pre-close execution-risk template for recommended HK IPOs."""

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
HARD_TECH_KEYWORDS = ["半导体", "芯片", "机器人", "智能", "AI", "人工智能", "自动化", "软件", "硬件", "科技"]
CSV_FIELDS = [
    "group_id",
    "stock",
    "code",
    "action",
    "financing_tier",
    "score",
    "window",
    "lock_days",
    "entry_fee_hkd",
    "application_plan_hkd",
    "collection_priority",
    "priority_reasons",
    "required_checks",
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
    "valuation_note",
    "peer_comparable_note",
    "cornerstone_lockup_note",
    "hard_tech_validation",
    "demand_validation",
    "deep_dive_focus",
    "source",
    "excerpt",
    "collection_note",
]


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


def recommendation(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("recommendation") or {}


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


def score(record: dict[str, Any]) -> int:
    try:
        return int(recommendation(record).get("score") or 0)
    except (TypeError, ValueError):
        return 0


def action(record: dict[str, Any]) -> str:
    return clean(recommendation(record).get("action"))


def financing_tier(record: dict[str, Any]) -> str:
    return clean((recommendation(record).get("financing") or {}).get("tier"))


def is_hard_tech(record: dict[str, Any]) -> bool:
    text = " ".join([stock_name(record), clean(record.get("industry")), "；".join(recommendation(record).get("evidence") or [])])
    return any(keyword in text for keyword in HARD_TECH_KEYWORDS)


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


def application_plan(record: dict[str, Any], *, cash_hkd: float, margin_multiple: float) -> float:
    tier = financing_tier(record)
    if tier == "乙组候选":
        return cash_hkd * margin_multiple
    if tier == "甲组候选":
        return min(cash_hkd * margin_multiple, 5_000_000.0)
    return cash_hkd


def candidate_records(payload: dict[str, Any], *, include: str) -> list[dict[str, Any]]:
    rows = []
    for record in records_from_payload(payload):
        tier = financing_tier(record)
        if action(record) != "建议申购":
            continue
        if include == "financing" and tier not in {"乙组候选", "甲组候选"}:
            continue
        if include == "high-risk" and tier not in {"乙组候选", "甲组候选"} and not is_hard_tech(record):
            continue
        rows.append(record)
    return sorted(rows, key=lambda item: (priority_info(item)[0], -score(item), financing_tier(item), stock_name(item)))


def parse_priority_levels(value: str | None) -> set[str] | None:
    if not value:
        return None
    levels = {item.strip().upper() for item in value.split(",") if item.strip()}
    return levels or None


def priority_info(record: dict[str, Any]) -> tuple[str, str]:
    tier = financing_tier(record)
    record_score = score(record)
    reasons: list[str] = []
    if tier == "乙组候选":
        reasons.append("乙组候选需证明可执行")
    if tier == "甲组候选":
        reasons.append("甲组候选需核价")
    if record_score >= 78:
        reasons.append("78+高分段融资效率重点样本")
    elif record_score >= 72:
        reasons.append("接近建议阈值")
    if is_hard_tech(record):
        reasons.append("硬科技/稀缺题材需估值验证")
    entry_fee = record.get("entry_fee_hkd")
    if isinstance(entry_fee, (int, float)) and entry_fee >= 30_000:
        reasons.append("入场费较高，融资成本敏感")

    if tier == "乙组候选" and (record_score >= 78 or is_hard_tech(record)):
        return "P0", "、".join(reasons)
    if tier == "甲组候选" or record_score >= 72 or is_hard_tech(record):
        return "P1", "、".join(reasons)
    return "P2", "、".join(reasons) or "低优先级执行抽查"


def required_checks(record: dict[str, Any]) -> list[str]:
    checks = [
        "融资利率/手续费/计息天数",
        "情景首日涨幅",
        "情景配售率/可信上限",
        "资金窗口占用",
        "孖展热度/额度紧张度",
        "估值/发行市值",
        "基石/禁售",
        "需求验证",
    ]
    if is_hard_tech(record):
        checks.append("硬科技估值和商业化验证")
    return checks


def deep_dive_focus(record: dict[str, Any]) -> str:
    focus = ["估值/发行市值", "收入和利润质量", "基石/禁售", "募资用途", "资金效率"]
    if is_hard_tech(record):
        focus.append("硬科技稀缺性是否足以覆盖估值")
    return "、".join(focus)


def collection_note(record: dict[str, Any]) -> str:
    evidence = "；".join(recommendation(record).get("evidence") or [])
    risks = "；".join(recommendation(record).get("risks") or [])
    parts = [
        "建议申购执行风险补采；用于申购前融资效率和估值闸门，不得用最终一手中签率、配售结果、暗盘或首日涨跌。",
        "情景配售率必须来自申购前同类区间、券商热度或保守假设。",
    ]
    if evidence:
        parts.append(f"事前正面依据：{evidence}")
    if risks:
        parts.append(f"待复核风险：{risks}")
    return " ".join(parts)


def build_rows(
    payload: dict[str, Any],
    *,
    include: str = "high-risk",
    brokers: list[str] | None = None,
    cash_hkd: float = 550_000.0,
    margin_multiple: float = 10.0,
    limit: int | None = None,
    priority_levels: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    broker_values = brokers if brokers is not None else DEFAULT_BROKERS
    candidates = candidate_records(payload, include=include)
    if limit is not None:
        candidates = candidates[:limit]
    for record in candidates:
        priority, priority_reasons = priority_info(record)
        if priority_levels and priority not in priority_levels:
            continue
        for broker in broker_values:
            rows.append(
                {
                    "group_id": "execution-risk",
                    "stock": stock_name(record),
                    "code": code_for(record),
                    "action": action(record),
                    "financing_tier": financing_tier(record),
                    "score": score(record),
                    "window": window(record),
                    "lock_days": lock_days(record),
                    "entry_fee_hkd": record.get("entry_fee_hkd") if isinstance(record.get("entry_fee_hkd"), (int, float)) else "",
                    "application_plan_hkd": application_plan(record, cash_hkd=cash_hkd, margin_multiple=margin_multiple),
                    "collection_priority": priority,
                    "priority_reasons": priority_reasons,
                    "required_checks": "、".join(required_checks(record)),
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
                    "valuation_note": "",
                    "peer_comparable_note": "",
                    "cornerstone_lockup_note": "",
                    "hard_tech_validation": "",
                    "demand_validation": "",
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


def render_markdown(rows: list[dict[str, Any]], *, year: Any, include: str) -> str:
    lines = [
        f"# {year or ''} 建议申购执行风险补采清单".strip(),
        "",
        f"生成时间：{dt.datetime.now().isoformat(timespec='seconds')}",
        f"口径：事前 `建议申购`；include={include}。该清单用于融资截止前核价和估值复核，不是上市后归因表。",
        "",
        "| 优先级 | 股票 | 窗口 | 分数 | 融资层 | 券商 | 预案金额 | 优先原因 | 需补字段 | 深挖重点 |",
        "|---|---|---|---:|---|---|---:|---|---|---|",
    ]
    if not rows:
        lines.append("| - | 暂无执行风险补采候选 | - | - | - | - | - | - | - | - |")
    for row in rows:
        amount = row["application_plan_hkd"]
        amount_text = f"HKD {float(amount):,.0f}" if isinstance(amount, (int, float)) else "-"
        lines.append(
            f"| {row['collection_priority']} | {row['stock']}（{row['code']}） | {row['window'] or '-'} | {row['score']} | "
            f"{row['financing_tier'] or '-'} | {row['broker'] or '自填'} | {amount_text} | {row['priority_reasons'] or '-'} | "
            f"{row['required_checks']} | {row['deep_dive_focus']} |"
        )
    lines.extend(
        [
            "",
            "要求：`observed_at`、`source_published_at`、`broker_cutoff_at`、融资利率、手续费、计息天数和情景配售率必须是申购截止前可设定或可观察的资料。",
            "禁止：不要填最终一手中签率、最终配售结果、暗盘、首日涨跌、现价或累计涨跌作为执行依据。",
            "后续：填回 CSV 后运行 `normalize_conflict_research_input.py`，再把输出同时传给 `audit_financing_efficiency.py --scenario-json` 和 `--margin-heat-json`。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", "-i", required=True, help="Annual/current IPO JSON payload with recommendation fields.")
    parser.add_argument("--include", choices=["high-risk", "financing", "all"], default="high-risk")
    parser.add_argument("--brokers", help="Comma-separated broker names. Omit for 富途,辉立,耀才; pass empty for one blank row.")
    parser.add_argument("--cash-hkd", type=float, default=550_000.0)
    parser.add_argument("--margin-multiple", type=float, default=10.0)
    parser.add_argument("--limit", type=int, help="Only include first N stocks before broker expansion.")
    parser.add_argument("--priority-levels", help="Comma-separated priority levels to include, e.g. P0 or P0,P1.")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = load_json(args.input_json)
    rows = build_rows(
        payload,
        include=args.include,
        brokers=split_brokers(args.brokers),
        cash_hkd=args.cash_hkd,
        margin_multiple=args.margin_multiple,
        limit=args.limit,
        priority_levels=parse_priority_levels(args.priority_levels),
    )
    if args.markdown:
        sys.stdout.write(render_markdown(rows, year=payload.get("year"), include=args.include))
    else:
        sys.stdout.write(render_csv(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
