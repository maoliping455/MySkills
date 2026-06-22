#!/usr/bin/env python3
"""Backtest executable B-group decisions using historical pre-close margin heat."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from backtest_year_ipos import display_stock, pct, ratio
from build_recommendation_report import margin_heat_for_ipo
from normalize_margin_input import strict_execution_ready, timing_evidence_valid


COHORTS = ["乙组闸门满足", "乙组闸门不满足", "乙组时间无效", "乙组缺热度数据", "非乙组但闸门满足"]


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_heat_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    stocks: list[dict[str, Any]] = []
    for payload in payloads:
        nested = payload.get("stocks") or payload.get("items_by_stock")
        if isinstance(nested, list):
            stocks.extend(item for item in nested if isinstance(item, dict))
        else:
            stocks.append(payload)
    return {"stocks": stocks}


def strict_execution_gate(heat: dict[str, Any] | None) -> bool:
    if not heat:
        return False
    summary = heat.get("summary") or {}
    return strict_execution_ready(summary)


def classify_record(record: dict[str, Any], heat_payload: dict[str, Any]) -> str:
    tier = (record.get("recommendation") or {}).get("financing", {}).get("tier")
    heat = margin_heat_for_ipo(record, heat_payload)
    gate = strict_execution_gate(heat)
    if tier == "乙组候选":
        if gate:
            return "乙组闸门满足"
        if heat:
            if not timing_evidence_valid(heat.get("summary") or {}):
                return "乙组时间无效"
            return "乙组闸门不满足"
        return "乙组缺热度数据"
    if gate:
        return "非乙组但闸门满足"
    return "其他"


def summarize(items: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    returns = [item["first_day_change_pct"] for item in items if isinstance(item.get("first_day_change_pct"), (int, float))]
    return {
        "count": len(items),
        "positive_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
        "strong_rate": sum(1 for value in returns if value >= threshold) / len(returns) if returns else None,
        "avg_first_day_pct": statistics.mean(returns) if returns else None,
        "median_first_day_pct": statistics.median(returns) if returns else None,
        "min_first_day_pct": min(returns) if returns else None,
    }


def build_payload(
    *,
    backtest_payload: dict[str, Any],
    heat_payload: dict[str, Any],
    strong_threshold_pct: float | None = None,
) -> dict[str, Any]:
    threshold = strong_threshold_pct if strong_threshold_pct is not None else float(backtest_payload.get("strong_threshold_pct") or 20.0)
    records = backtest_payload.get("records") or []
    classified: dict[str, list[dict[str, Any]]] = {cohort: [] for cohort in COHORTS}
    for record in records:
        cohort = classify_record(record, heat_payload)
        if cohort in classified:
            classified[cohort].append(record)

    summaries = {cohort: summarize(items, threshold=threshold) for cohort, items in classified.items()}
    b_candidates = [
        record
        for record in records
        if (record.get("recommendation") or {}).get("financing", {}).get("tier") == "乙组候选"
    ]
    missing_heat = summaries["乙组缺热度数据"]["count"]
    invalid_timing = summaries["乙组时间无效"]["count"]
    heat_covered = len(b_candidates) - missing_heat - invalid_timing
    coverage = heat_covered / len(b_candidates) if b_candidates else None
    gate_met = summaries["乙组闸门满足"]["count"]
    if not b_candidates:
        coverage_verdict = "无乙组候选，无法验证乙组执行闸门。"
    elif coverage is not None and coverage < 0.7:
        coverage_verdict = "热度覆盖不足，不能据此判断乙组执行策略有效；只能作为数据采集缺口审查。"
    elif gate_met == 0:
        coverage_verdict = "热度覆盖基本可用，但无闸门满足样本，不能验证乙组可执行收益。"
    else:
        coverage_verdict = "热度覆盖基本可用，可初步比较乙组候选与乙组可执行队列。"
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "year": backtest_payload.get("year"),
        "strong_threshold_pct": threshold,
        "b_group_candidate_count": len(b_candidates),
        "b_group_heat_covered_count": heat_covered,
        "b_group_missing_heat_count": missing_heat,
        "b_group_invalid_timing_count": invalid_timing,
        "b_group_heat_coverage": coverage,
        "covered_count": heat_covered,
        "missing_count": missing_heat,
        "invalid_timing_count": invalid_timing,
        "coverage_rate": coverage,
        "gate_met_count": gate_met,
        "gate_not_met_count": summaries["乙组闸门不满足"]["count"],
        "coverage_verdict": coverage_verdict,
        "summaries": summaries,
        "classified_records": {
            cohort: [
                {
                    "listing_date": item.get("listing_date"),
                    "stock": display_stock(item),
                    "code": item.get("code"),
                    "first_day_change_pct": item.get("first_day_change_pct"),
                    "financing_tier": (item.get("recommendation") or {}).get("financing", {}).get("tier"),
                }
                for item in items
            ]
            for cohort, items in classified.items()
        },
        "missing_heat_records": [
            {
                "listing_date": item.get("listing_date"),
                "stock": display_stock(item),
                "code": item.get("code"),
                "financing_tier": (item.get("recommendation") or {}).get("financing", {}).get("tier"),
            }
            for item in classified["乙组缺热度数据"]
        ],
        "invalid_timing_records": [
            {
                "listing_date": item.get("listing_date"),
                "stock": display_stock(item),
                "code": item.get("code"),
                "financing_tier": (item.get("recommendation") or {}).get("financing", {}).get("tier"),
            }
            for item in classified["乙组时间无效"]
        ],
        "disclaimer": "Only use margin heat captured before broker financing cutoff. Do not use final allotment or first-day data to decide historical execution gates.",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload.get('year') or ''} 港股打新融资闸门回测".strip(),
        "",
        f"生成时间：{payload['generated_at']}",
        f"乙组候选样本：{payload['b_group_candidate_count']}；热度覆盖率：{ratio(payload.get('b_group_heat_coverage'))}",
        f"覆盖率结论：{payload.get('coverage_verdict')}",
        f"强收益定义：首日涨幅 >= {payload['strong_threshold_pct']:g}%。",
        "",
        "## 覆盖率审查",
        "| 乙组候选 | 有效覆盖热度 | 时间无效 | 缺热度 | 有效覆盖率 | 闸门满足 | 结论 |",
        "|---:|---:|---:|---:|---:|---:|---|",
        (
            f"| {payload['b_group_candidate_count']} | {payload.get('b_group_heat_covered_count', 0)} | "
            f"{payload.get('b_group_invalid_timing_count', 0)} | {payload.get('b_group_missing_heat_count', 0)} | "
            f"{ratio(payload.get('b_group_heat_coverage'))} | "
            f"{payload['summaries']['乙组闸门满足']['count']} | {payload.get('coverage_verdict')} |"
        ),
        "",
        "## 闸门表现",
        "| 队列 | 样本数 | 首日正收益率 | 强收益率 | 平均首日 | 中位首日 | 最差 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cohort in COHORTS:
        row = payload["summaries"][cohort]
        lines.append(
            f"| {cohort} | {row['count']} | {ratio(row['positive_rate'])} | {ratio(row['strong_rate'])} | "
            f"{pct(row['avg_first_day_pct'])} | {pct(row['median_first_day_pct'])} | {pct(row['min_first_day_pct'])} |"
        )

    lines.extend(["", "## 专家审查结论"])
    executable = payload["summaries"]["乙组闸门满足"]
    missing_count = payload["summaries"]["乙组缺热度数据"]["count"]
    invalid_count = payload["summaries"]["乙组时间无效"]["count"]
    coverage = payload.get("b_group_heat_coverage")
    if coverage is not None and coverage < 0.7:
        lines.append("- 热度覆盖率低于 70%，本回测不能支持乙组执行结论；优先补券商孖展、额度、利率和截止时间历史数据。")
    elif executable["count"]:
        lines.append("- 已能用历史融资热度数据区分乙组候选和乙组可执行队列。")
    else:
        lines.append("- 尚无乙组候选满足融资闸门的历史样本，不能验证乙组执行收益。")
    if missing_count:
        lines.append(f"- 仍有 {missing_count} 个乙组候选缺少融资热度数据；这些样本只能验证选股质量，不能验证融资执行。")
    if invalid_count:
        lines.append(f"- 另有 {invalid_count} 个乙组候选只有时间无效热度记录；这些记录不得计入有效覆盖率。")
    lines.append("- 该回测要求融资热度数据早于券商融资截止；最终超购、一手中签率、暗盘和首日表现不得用于闸门判断。")
    missing_records = payload.get("missing_heat_records") or []
    if missing_records:
        lines.extend(["", "## 缺热度数据乙组候选", "| 上市日 | 股票 |", "|---|---|"])
        for item in missing_records[:20]:
            lines.append(f"| {item.get('listing_date') or '-'} | {item['stock']} |")
    invalid_records = payload.get("invalid_timing_records") or []
    if invalid_records:
        lines.extend(["", "## 时间无效乙组候选", "| 上市日 | 股票 |", "|---|---|"])
        for item in invalid_records[:20]:
            lines.append(f"| {item.get('listing_date') or '-'} | {item['stock']} |")

    for cohort in COHORTS:
        records = payload["classified_records"][cohort]
        if not records:
            continue
        lines.extend(["", f"## {cohort} 明细", "| 上市日 | 股票 | 首日 |", "|---|---|---:|"])
        for item in records[:20]:
            lines.append(f"| {item.get('listing_date') or '-'} | {item['stock']} | {pct(item.get('first_day_change_pct'))} |")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest-json", required=True, help="Single-year payload from backtest_year_ipos.py --json.")
    parser.add_argument("--margin-heat-json", action="append", required=True, help="Historical pre-close margin heat JSON. Can be repeated.")
    parser.add_argument("--strong-threshold-pct", type=float)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backtest_payload = load_json(args.backtest_json)
    heat_payload = normalize_heat_payloads([load_json(path) for path in args.margin_heat_json])
    payload = build_payload(
        backtest_payload=backtest_payload,
        heat_payload=heat_payload,
        strong_threshold_pct=args.strong_threshold_pct,
    )
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
