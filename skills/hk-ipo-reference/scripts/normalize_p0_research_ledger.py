#!/usr/bin/env python3
"""Normalize filled P0 public research query ledger rows."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

import normalize_conflict_research_input as conflict_input
from normalize_margin_input import clean


def row_has_evidence(row: dict[str, Any]) -> bool:
    return any(clean(row.get(field)) for field in conflict_input.USER_FILLED_FIELDS)


def build_payload(rows: list[dict[str, Any]], *, assume_preclose: bool = False) -> dict[str, Any]:
    payload = conflict_input.normalize_rows(rows, assume_preclose=assume_preclose)
    task_count = len(rows)
    filled_task_count = sum(1 for row in rows if row_has_evidence(row))
    query_types = sorted({clean(row.get("query_type")) for row in rows if clean(row.get("query_type"))})
    payload["ledger_summary"] = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "task_count": task_count,
        "filled_task_count": filled_task_count,
        "blank_task_count": task_count - filled_task_count,
        "query_type_count": len(query_types),
        "query_types": query_types,
        "ready_for_p0_split": (
            (payload.get("summary") or {}).get("review_ready_stock_count", 0)
            + (payload.get("summary") or {}).get("attempted_data_gap_stock_count", 0)
            > 0
        ),
    }
    payload["ledger_guardrail"] = (
        "The P0 research ledger is only a pre-close evidence inbox. Rows with late timing or post-close "
        "evidence remain excluded from recommendation, financing, and scheduling inputs."
    )
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    ledger = payload.get("ledger_summary") or {}
    lines = [
        "# P0 公开检索证据台账质量审查",
        "",
        f"生成时间：{ledger.get('generated_at') or payload.get('generated_at') or '-'}",
        (
            f"检索任务：{ledger.get('task_count', 0)}；已填证据任务：{ledger.get('filled_task_count', 0)}；"
            f"空白任务：{ledger.get('blank_task_count', 0)}；查询类型：{ledger.get('query_type_count', 0)}。"
        ),
        (
            f"股票数：{summary.get('stock_count', 0)}；可复核：{summary.get('review_ready_stock_count', 0)}；"
            f"待填回：{summary.get('pending_input_stock_count', 0)}；缺数据：{summary.get('missing_data_stock_count', 0)}；"
            f"时间无效：{summary.get('timing_invalid_stock_count', 0)}；证据污染：{summary.get('evidence_contaminated_stock_count', 0)}；"
            f"已尝试缺口：{summary.get('attempted_data_gap_stock_count', 0)}。"
        ),
        f"防泄露口径：{payload.get('ledger_guardrail')}",
        "",
        "## 按股审查",
        "| 股票 | 代码 | 状态 | 有效行 | 缺口 | 时间/证据风险 |",
        "|---|---|---|---:|---|---|",
    ]
    groups = payload.get("groups") or []
    if not groups:
        lines.append("| - | - | 暂无台账行 | 0 | - | - |")
    for group in groups:
        for stock in group.get("stocks") or []:
            risks: list[str] = []
            for row in stock.get("rows") or []:
                risks.extend(row.get("timing_risks") or [])
                risks.extend(row.get("evidence_risks") or [])
            if stock.get("research_status") == "待填回":
                risk_text = "等待填回，尚未校验时间"
            else:
                risk_text = "；".join(sorted(set(risks))) or "-"
            missing = "、".join(stock.get("missing_fields") or []) or "-"
            lines.append(
                f"| {stock.get('stock') or '-'} | {stock.get('code') or '-'} | "
                f"{stock.get('research_status') or '-'} | {stock.get('eligible_decision_row_count', 0)} | "
                f"{missing} | {risk_text} |"
            )
    lines.extend(
        [
            "",
            "## 使用结论",
            "- `待填回` 表示检索任务还没有填入任何可审查证据。",
            "- `缺数据` 表示已有申购前证据，但仍缺融资成本、情景配售率、招股书/来源等字段。",
            "- `时间无效` 或 `证据污染` 行不能用于申购前模型，只能保留作复盘线索。",
            "- `已尝试缺口` 表示已记录无污染公开检索尝试但未找到足够申购前证据；只有显式接受数据缺口时才算闭环。",
            "- 可复核股票可作为填回 P0 合并表或分域 CSV 的候选证据来源。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", required=True, help="CSV/JSON/JSONL from prepare_p0_research_queries.py --csv after filling evidence fields.")
    parser.add_argument("--format", choices=["auto", "csv", "jsonl", "json"], default="auto")
    parser.add_argument("--assume-preclose", action="store_true", help="Treat rows without explicit timing as pre-close. Use only for trusted historical data.")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = conflict_input.read_rows(args.input, args.format)
    payload = build_payload(rows, assume_preclose=args.assume_preclose)
    if args.markdown:
        sys.stdout.write(render_markdown(payload))
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
