#!/usr/bin/env python3
"""Prepare a CSV/Markdown template for historical pre-close margin heat collection."""

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

from backtest_margin_gate import normalize_heat_payloads, strict_execution_gate
from build_recommendation_report import chinese_display_alias, margin_heat_for_ipo
from fetch_current_ipos import clean_stock_name
from normalize_margin_input import timing_evidence_valid


DEFAULT_BROKERS = ["富途", "辉立", "耀才"]
CSV_FIELDS = [
    "code",
    "stock_name",
    "listing_date",
    "subscription_start_date",
    "closing_date",
    "allotment_date",
    "refund_date",
    "financing_tier",
    "score",
    "entry_fee_hkd",
    "collection_priority",
    "priority_reasons",
    "broker",
    "observed_at",
    "source_published_at",
    "preclose_confirmed",
    "broker_cutoff_at",
    "margin_multiple",
    "margin_amount_hkd",
    "quota_status",
    "financing_rate_pct",
    "cutoff_note",
    "acceleration",
    "source",
    "excerpt",
    "search_attempted_at",
    "search_source",
    "unavailable_reason",
    "search_note",
    "collection_note",
]


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def contains_chinese(value: str | None) -> bool:
    return bool(value and re.search(r"[\u4e00-\u9fff]", value))


def stock_name(record: dict[str, Any]) -> str:
    name = clean_stock_name(record.get("name"))
    if contains_chinese(name):
        return name
    alias = chinese_display_alias(record)
    if alias:
        return alias
    code = clean(record.get("code") or record.get("canonical_code"))
    return f"代码{code}（中文名待核实）" if code else "中文名待核实"


def display_stock(row: dict[str, Any]) -> str:
    name = row["stock_name"]
    code = row["code"]
    if "中文名待核实" in name or not code:
        return name
    return f"{name}（{code}）"


def split_brokers(value: str | None) -> list[str]:
    if value is None:
        return DEFAULT_BROKERS
    brokers = [item.strip() for item in value.split(",") if item.strip()]
    return brokers or [""]


def candidate_records(backtest_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        record
        for record in backtest_payload.get("records") or []
        if (record.get("recommendation") or {}).get("financing", {}).get("tier") == "乙组候选"
    ]


def recommendation_score(record: dict[str, Any]) -> int:
    try:
        return int((record.get("recommendation") or {}).get("score") or 0)
    except (TypeError, ValueError):
        return 0


def entry_fee_hkd(record: dict[str, Any]) -> float | None:
    value = record.get("entry_fee_hkd")
    return float(value) if isinstance(value, (int, float)) else None


def collection_status(record: dict[str, Any], heat_payload: dict[str, Any] | None) -> tuple[str, str]:
    if not heat_payload:
        return "缺热度数据", "补融资截止前孖展倍数/金额、额度、利率、截止时间和来源。"
    heat = margin_heat_for_ipo(record, heat_payload)
    if not heat:
        return "缺热度数据", "补融资截止前孖展倍数/金额、额度、利率、截止时间和来源。"
    if not timing_evidence_valid(heat.get("summary") or {}):
        return "时间无效", "已有记录但时间证据无效；补早于券商融资截止的 observed_at、broker_cutoff_at 和来源。"
    if strict_execution_gate(heat):
        return "闸门已满足", "已有至少两个需求/额度类热度信号且成本可接受；仅抽查来源和时间。"
    return "闸门未满足", "已有记录但不满足严格闸门；补第二券商、额度紧张/尾日加速、利率和融资截止前时间。"


def priority_info(record: dict[str, Any], status: str) -> tuple[str, str]:
    score = recommendation_score(record)
    entry_fee = entry_fee_hkd(record)
    reasons: list[str] = []
    if status == "时间无效":
        reasons.append("已有记录时间无效，优先重采")
    if status == "缺热度数据":
        reasons.append("缺申购前孖展热度")
    if status == "闸门未满足":
        reasons.append("已有热度但严格闸门未满足")
    if score >= 78:
        reasons.append("事前高分乙组候选")
    elif score >= 72:
        reasons.append("事前中高分乙组候选")
    high_entry_fee = entry_fee is not None and entry_fee >= 4_000
    if high_entry_fee:
        reasons.append("入场费较高，融资成本敏感")

    if status == "闸门已满足":
        return "P2", "闸门已满足，仅抽查来源"
    high_score_unvalidated = score >= 78 and status in {"缺热度数据", "闸门未满足"}
    if status == "时间无效" or high_score_unvalidated or high_entry_fee:
        return "P0", "、".join(reasons)
    if score >= 72 or status == "闸门未满足":
        return "P1", "、".join(reasons)
    return "P2", "、".join(reasons) or "低优先级补采"


def parse_priority_levels(value: str | None) -> set[str] | None:
    if not value:
        return None
    levels = {item.strip().upper() for item in value.split(",") if item.strip()}
    return levels or None


def build_rows(
    *,
    backtest_payload: dict[str, Any],
    heat_payload: dict[str, Any] | None = None,
    brokers: list[str] | None = None,
    include: str = "missing-or-not-met",
    priority_levels: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    broker_values = brokers if brokers is not None else DEFAULT_BROKERS
    for record in sorted(
        candidate_records(backtest_payload),
        key=lambda item: (priority_info(item, collection_status(item, heat_payload)[0])[0], -recommendation_score(item), clean(item.get("closing_date")), stock_name(item)),
    ):
        status, note = collection_status(record, heat_payload)
        if include == "missing" and status != "缺热度数据":
            continue
        if include == "missing-or-not-met" and status == "闸门已满足":
            continue
        priority, priority_reasons = priority_info(record, status)
        if priority_levels and priority not in priority_levels:
            continue
        tier = (record.get("recommendation") or {}).get("financing", {}).get("tier") or ""
        for broker in broker_values:
            rows.append(
                {
                    "code": clean(record.get("code") or record.get("canonical_code")),
                    "stock_name": stock_name(record),
                    "listing_date": clean(record.get("listing_date")),
                    "subscription_start_date": clean(record.get("subscription_start_date")),
                    "closing_date": clean(record.get("closing_date")),
                    "allotment_date": clean(record.get("allotment_date")),
                    "refund_date": clean(record.get("refund_date")),
                    "financing_tier": tier,
                    "score": recommendation_score(record) or "",
                    "entry_fee_hkd": entry_fee_hkd(record) if entry_fee_hkd(record) is not None else "",
                    "collection_priority": priority,
                    "priority_reasons": priority_reasons,
                    "broker": broker,
                    "observed_at": "",
                    "preclose_confirmed": "",
                    "broker_cutoff_at": "",
                    "margin_multiple": "",
                    "margin_amount_hkd": "",
                    "quota_status": "",
                    "financing_rate_pct": "",
                    "cutoff_note": "",
                    "acceleration": "",
                    "source": "",
                    "excerpt": "",
                    "collection_note": note,
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


def render_markdown(rows: list[dict[str, Any]], *, year: Any) -> str:
    lines = [
        f"# {year or ''} 乙组候选历史孖展补采清单".strip(),
        "",
        f"生成时间：{dt.datetime.now().isoformat(timespec='seconds')}",
        "用途：补齐融资截止前可见的券商孖展、额度、利率和截止时间，用于 `backtest_margin_gate.py` 验证乙组候选是否可执行。",
        "",
        "| 优先级 | 股票 | 事前分数 | 上市日 | 招股截止 | 券商 | 需补字段 | 说明 |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    if not rows:
        lines.append("| - | 暂无待补样本 | - | - | - | - | - | - |")
    for row in rows:
        fields = "observed_at、source_published_at、preclose_confirmed、broker_cutoff_at、margin_multiple、margin_amount_hkd、quota_status、financing_rate_pct、cutoff_note、source"
        lines.append(
            f"| {row['collection_priority']} | {display_stock(row)} | {row['score'] or '-'} | {row['listing_date'] or '-'} | "
            f"{row['closing_date'] or '-'} | {row['broker'] or '自填'} | {fields} | {row['priority_reasons']}；{row['collection_note']} |"
        )
    lines.extend(
        [
            "",
            "要求：`observed_at`、`source_published_at` 和 `broker_cutoff_at` 应尽量精确到分钟；`preclose_confirmed` 必须能证明记录和来源发布时间早于券商融资截止；最终超购、一手中签率、暗盘和首日表现不能填作热度依据。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest-json", required=True, help="Single-year payload from backtest_year_ipos.py --json.")
    parser.add_argument("--margin-heat-json", action="append", help="Existing normalized historical margin heat JSON; can be repeated.")
    parser.add_argument(
        "--include",
        choices=["missing", "missing-or-not-met", "all"],
        default="missing-or-not-met",
        help="Which B-group candidates to include in the collection template.",
    )
    parser.add_argument(
        "--brokers",
        help="Comma-separated broker names to prefill. Omit for 富途,辉立,耀才; pass an empty string for one blank broker row.",
    )
    parser.add_argument("--priority-levels", help="Comma-separated priority levels to include, e.g. P0 or P0,P1.")
    parser.add_argument("--markdown", action="store_true", help="Output Markdown instead of CSV.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backtest_payload = load_json(args.backtest_json)
    heat_payload = None
    if args.margin_heat_json:
        heat_payload = normalize_heat_payloads([load_json(path) for path in args.margin_heat_json])
    rows = build_rows(
        backtest_payload=backtest_payload,
        heat_payload=heat_payload,
        brokers=split_brokers(args.brokers),
        include=args.include,
        priority_levels=parse_priority_levels(args.priority_levels),
    )
    if args.markdown:
        sys.stdout.write(render_markdown(rows, year=backtest_payload.get("year")))
    else:
        sys.stdout.write(render_csv(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
