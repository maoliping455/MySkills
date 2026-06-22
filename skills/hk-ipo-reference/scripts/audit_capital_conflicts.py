#!/usr/bin/env python3
"""Audit same-window IPO funding conflicts without using future data for decisions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from backtest_year_ipos import (
    DEFAULT_BACKTEST_CASH_HKD,
    backtest_cash_reserve,
    capital_lock_window,
    capital_preclose_utility,
    display_stock,
    expected_one_lot_gross_pnl,
    optimized_preclose_score,
    peak_capital_reserved,
    windows_overlap,
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待核实"
    return f"HKD {float(value):,.0f}"


def pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待核实"
    return f"{float(value):+.2f}%"


def format_window(window: tuple[dt.date | None, dt.date | None]) -> str:
    start, end = window
    if not start or not end:
        return "待核实"
    return f"{start.isoformat()} 至 {end.isoformat()}"


def lock_days(window: tuple[dt.date | None, dt.date | None]) -> int | None:
    start, end = window
    if not start or not end:
        return None
    return (end - start).days + 1


def ensure_recommendation(record: dict[str, Any]) -> dict[str, Any]:
    item = dict(record)
    if not isinstance(item.get("recommendation"), dict):
        item["recommendation"] = optimized_preclose_score(item)
    return item


def candidate_records(
    records: list[dict[str, Any]],
    *,
    cash_hkd: float,
    include_observation: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    missing_window: list[dict[str, Any]] = []
    allowed_actions = {"建议申购", "可选观察"} if include_observation else {"建议申购"}
    for raw in records:
        record = ensure_recommendation(raw)
        action = (record.get("recommendation") or {}).get("action")
        if action not in allowed_actions:
            continue
        required = backtest_cash_reserve(record, cash_hkd=cash_hkd)
        if required <= 0 and include_observation and action == "可选观察":
            entry_fee = record.get("entry_fee_hkd")
            if isinstance(entry_fee, (int, float)) and entry_fee > 0:
                required = min(float(cash_hkd), float(entry_fee))
        if required <= 0:
            continue
        window = capital_lock_window(record)
        if not all(window):
            missing_window.append(record)
            continue
        record["_capital_required_hkd"] = required
        record["_capital_window"] = window
        candidates.append(record)
    return candidates, missing_window


def priority_key(record: dict[str, Any]) -> tuple[Any, ...]:
    start = (record.get("_capital_window") or (None, None))[0] or dt.date.max
    return (-capital_preclose_utility(record), start, display_stock(record))


def connected_components(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
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
        groups.append([records[index] for index in sorted(component)])
    return groups


def review_values(records: list[dict[str, Any]]) -> list[float]:
    return [
        value
        for value in (expected_one_lot_gross_pnl(record) for record in records)
        if isinstance(value, (int, float))
    ]


def review_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = review_values(records)
    first_day = [record.get("first_day_change_pct") for record in records if isinstance(record.get("first_day_change_pct"), (int, float))]
    return {
        "avg_expected_one_lot_pnl_hkd": statistics.mean(values) if values else None,
        "expected_one_lot_sample_count": len(values),
        "avg_first_day_pct": statistics.mean(first_day) if first_day else None,
        "first_day_sample_count": len(first_day),
    }


def preclose_checklist(record: dict[str, Any]) -> list[str]:
    rec = record.get("recommendation") or {}
    tier = ((rec.get("financing") or {}).get("tier")) or "不融资"
    checks = ["招股书估值/基石/禁售", "同窗口占款金额和锁定天数"]
    if tier == "乙组候选":
        checks.extend(["T-1/T-0孖展倍数/金额", "额度紧张度", "融资利率/手续费/券商截止"])
    elif tier == "甲组候选":
        checks.extend(["甲组高位资金效率", "是否需要退回现金多手"])
    else:
        checks.append("现金一手/少量多手是否足够")
    if rec.get("risks"):
        checks.append("风险项复核")
    return checks


def record_row(record: dict[str, Any]) -> dict[str, Any]:
    rec = record.get("recommendation") or {}
    financing = rec.get("financing") or {}
    window = record.get("_capital_window") or (None, None)
    return {
        "stock": display_stock(record),
        "code": clean(record.get("code") or record.get("canonical_code")),
        "window": format_window(window),
        "lock_days": lock_days(window),
        "cash_required_hkd": record.get("_capital_required_hkd"),
        "entry_fee_hkd": record.get("entry_fee_hkd"),
        "score": rec.get("score"),
        "action": rec.get("action"),
        "financing_tier": financing.get("tier"),
        "market_regime": clean((record.get("market_regime") or {}).get("label")) or "待核实",
        "preclose_evidence": rec.get("evidence") or [],
        "preclose_risks": rec.get("risks") or [],
        "preclose_checklist": preclose_checklist(record),
        "preclose_utility": capital_preclose_utility(record),
        "review_only": {
            "first_day_change_pct": record.get("first_day_change_pct"),
            "expected_one_lot_pnl_hkd": expected_one_lot_gross_pnl(record),
            "oversubscription_rate": record.get("oversubscription_rate"),
            "one_lot_success_rate_pct": record.get("one_lot_success_rate_pct"),
        },
    }


def group_payload(group: list[dict[str, Any]], *, cash_hkd: float, group_id: int) -> dict[str, Any]:
    ordered = sorted(group, key=priority_key)
    peak = peak_capital_reserved(ordered)
    return {
        "group_id": group_id,
        "stock_count": len(ordered),
        "peak_cash_required_hkd": peak,
        "cash_hkd": cash_hkd,
        "over_capacity_hkd": max(0.0, peak - cash_hkd),
        "window_start": min((item["_capital_window"][0] for item in ordered), default=None).isoformat(),
        "window_end": max((item["_capital_window"][1] for item in ordered), default=None).isoformat(),
        "preclose_priority": [record_row(item) for item in ordered],
        "review_only_stats": review_stats(ordered),
        "decision_rule": "只按事前字段列出优先复核顺序；首日、一手期望、最终超购和中签率仅用于复盘，不得作为当时排期依据。",
    }


def build_payload(
    source_payload: dict[str, Any],
    *,
    cash_hkd: float = DEFAULT_BACKTEST_CASH_HKD,
    include_observation: bool = False,
) -> dict[str, Any]:
    records = list(source_payload.get("records") or source_payload.get("ipos") or [])
    candidates, missing_window = candidate_records(records, cash_hkd=cash_hkd, include_observation=include_observation)
    components = connected_components(candidates)
    raw_conflict_groups = [
        group
        for group in components
        if len(group) > 1 and peak_capital_reserved(group) > cash_hkd + 1e-6
    ]
    conflict_groups = [
        group_payload(group, cash_hkd=cash_hkd, group_id=index + 1)
        for index, group in enumerate(raw_conflict_groups)
    ]
    conflict_groups.sort(key=lambda group: (-group["over_capacity_hkd"], group["window_start"]))
    for index, group in enumerate(conflict_groups, start=1):
        group["group_id"] = index
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "year": source_payload.get("year"),
        "cash_hkd": cash_hkd,
        "include_observation": include_observation,
        "summary": {
            "candidate_count": len(candidates),
            "missing_window_count": len(missing_window),
            "conflict_group_count": len(conflict_groups),
            "conflicted_stock_count": sum(group["stock_count"] for group in conflict_groups),
            "max_over_capacity_hkd": max((group["over_capacity_hkd"] for group in conflict_groups), default=0.0),
        },
        "conflict_groups": conflict_groups,
        "missing_window": [record_row(item) for item in missing_window],
        "guardrail": "同窗口取舍只允许使用申购截止前可见字段；复盘指标必须与决策字段分离。",
    }


def short_list(values: list[Any], limit: int = 3) -> str:
    cleaned = [clean(value) for value in values if clean(value)]
    if not cleaned:
        return "-"
    return "；".join(cleaned[:limit])


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 港股打新同窗口资金冲突审查",
        "",
        f"生成时间：{payload['generated_at']}",
        f"默认现金：{money(payload['cash_hkd'])}",
        f"结论：发现 {summary['conflict_group_count']} 个超出默认现金的重叠资金组，涉及 {summary['conflicted_stock_count']} 只股票；最大超额 {money(summary['max_over_capacity_hkd'])}。",
        "",
        "## 审查口径",
        "- 只把事前可见字段用于排期复核：分数、入场费、融资分层、市场温度、锁定天数、招股书/保荐/风险项。",
        "- 默认顺序使用事前效用：事前分数占主导，入场敞口只作近分样本的资金利用度代理，锁定天数越短越有利。",
        "- 首日涨跌、一手期望、最终超购和一手中签率只作为复盘指标，不能反向决定当时的申购或融资排期。",
        "- 若同窗口现金不足，不自动追加票数；先做招股书深挖和 T-1/T-0 融资核价，再决定是否替换默认排期。",
        "",
        "## 摘要",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 候选数 | {summary['candidate_count']} |",
        f"| 冲突组 | {summary['conflict_group_count']} |",
        f"| 冲突股票数 | {summary['conflicted_stock_count']} |",
        f"| 缺锁定窗口 | {summary['missing_window_count']} |",
        f"| 最大超额 | {money(summary['max_over_capacity_hkd'])} |",
    ]
    if not payload["conflict_groups"]:
        lines.extend(["", "## 冲突组", "暂无超出默认现金的同窗口冲突组。"])
    for group in payload["conflict_groups"]:
        stats = group["review_only_stats"]
        lines.extend(
            [
                "",
                f"## 冲突组 {group['group_id']}：{group['window_start']} 至 {group['window_end']}",
                f"- 峰值占用 {money(group['peak_cash_required_hkd'])}，超出默认现金 {money(group['over_capacity_hkd'])}。",
                f"- 复盘指标：平均首日 {pct(stats.get('avg_first_day_pct'))}；平均一手期望 {money(stats.get('avg_expected_one_lot_pnl_hkd'))}；这些指标不得用于当时排期。",
                "",
                "| 事前顺序 | 股票 | 分数 | 事前效用 | 融资层 | 入场费 | 预留现金 | 锁定 | 事前理由 | 主要风险 | 必查项 | 复盘首日 | 复盘一手期望 |",
                "|---:|---|---:|---:|---|---:|---:|---|---|---|---|---:|---:|",
            ]
        )
        for index, row in enumerate(group["preclose_priority"], start=1):
            review = row["review_only"]
            lines.append(
                f"| {index} | {row['stock']} | {row.get('score') or '-'} | {float(row.get('preclose_utility') or 0):.1f} | {row.get('financing_tier') or '-'} | "
                f"{money(row.get('entry_fee_hkd'))} | {money(row.get('cash_required_hkd'))} | "
                f"{row['window']}（{row.get('lock_days') or '-'}天） | "
                f"{short_list(row.get('preclose_evidence') or [])} | "
                f"{short_list(row.get('preclose_risks') or [])} | "
                f"{short_list(row.get('preclose_checklist') or [], limit=5)} | "
                f"{pct(review.get('first_day_change_pct'))} | {money(review.get('expected_one_lot_pnl_hkd'))} |"
            )
    if payload.get("missing_window"):
        lines.extend(["", "## 缺锁定窗口样本", "| 股票 | 分数 | 融资层 | 必查项 |", "|---|---:|---|---|"])
        for row in payload["missing_window"]:
            lines.append(
                f"| {row['stock']} | {row.get('score') or '-'} | {row.get('financing_tier') or '-'} | "
                f"{short_list(row.get('preclose_checklist') or [], limit=5)} |"
            )
    lines.extend(
        [
            "",
            "## 下一步",
            "- 对冲突组内排名接近或证据互有强弱的股票，优先做招股书深挖和券商融资核价。",
            "- 若乙组候选没有两个独立需求/额度热度信号且成本可接受，退回甲组/现金，不占用乙组资金。",
            "- 若复盘指标显示被跳过股票明显更好，只能说明下一次同窗口复核需要更早补数据，不能把最终结果泄露到申购前模型。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", "-i", required=True, help="Backtest/current IPO JSON payload.")
    parser.add_argument("--cash-hkd", type=float, default=DEFAULT_BACKTEST_CASH_HKD)
    parser.add_argument("--include-observation", action="store_true", help="Include 可选观察 as conflict candidates.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    payload = build_payload(
        source_payload,
        cash_hkd=args.cash_hkd,
        include_observation=args.include_observation,
    )
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
