#!/usr/bin/env python3
"""Prepare a collection template for residual same-window funding conflicts."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import sys
from pathlib import Path
from typing import Any

from audit_capital_conflicts import build_payload as build_conflict_payload


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
    "conflict_role",
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
    "deep_dive_focus",
    "source",
    "excerpt",
    "collection_note",
]

DEFAULT_BROKERS = ["富途", "辉立", "耀才"]
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待核实"
    return f"HKD {float(value):,.0f}"


def split_brokers(value: str | None) -> list[str]:
    if value is None:
        return DEFAULT_BROKERS
    brokers = [item.strip() for item in value.split(",") if item.strip()]
    return brokers or [""]


def parse_priority_levels(value: str | None) -> set[str] | None:
    if not value:
        return None
    levels = {item.strip().upper() for item in value.split(",") if item.strip()}
    return levels or None


def row_key(row: dict[str, Any]) -> tuple[str, str]:
    return clean(row.get("stock")), clean(row.get("code"))


def parse_window(value: Any) -> tuple[dt.date | None, dt.date | None]:
    text = clean(value)
    if not text or text == "待核实":
        return None, None
    if "至" in text:
        left, right = text.split("至", 1)
    elif "→" in text:
        left, right = text.split("→", 1)
    else:
        return None, None
    try:
        return dt.date.fromisoformat(left.strip()), dt.date.fromisoformat(right.strip())
    except ValueError:
        return None, None


def windows_overlap(left: tuple[dt.date | None, dt.date | None], right: tuple[dt.date | None, dt.date | None]) -> bool:
    left_start, left_end = left
    right_start, right_end = right
    if not left_start or not left_end or not right_start or not right_end:
        return False
    return left_start <= right_end and right_start <= left_end


def cash_required(row: dict[str, Any]) -> float:
    value = row.get("cash_required_hkd")
    return float(value) if isinstance(value, (int, float)) and value > 0 else 0.0


def preclose_utility(row: dict[str, Any]) -> float:
    value = row.get("preclose_utility")
    return float(value) if isinstance(value, (int, float)) else 0.0


def row_score(row: dict[str, Any]) -> int:
    try:
        return int(row.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def peak_reserved(rows: list[dict[str, Any]]) -> float:
    events: list[tuple[dt.date, int, float]] = []
    for row in rows:
        start, end = parse_window(row.get("window"))
        required = cash_required(row)
        if not start or not end or required <= 0:
            continue
        events.append((start, 1, required))
        events.append((end + dt.timedelta(days=1), 0, -required))
    running = 0.0
    peak = 0.0
    for _, _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        running += delta
        peak = max(peak, running)
    return peak


def best_preclose_subset(rows: list[dict[str, Any]], *, cash_hkd: float) -> list[dict[str, Any]]:
    if not rows:
        return []
    if len(rows) > 22:
        selected: list[dict[str, Any]] = []
        for row in sorted(rows, key=lambda item: (-preclose_utility(item), clean(item.get("window")), clean(item.get("stock")))):
            if peak_reserved([*selected, row]) <= cash_hkd + 1e-6:
                selected.append(row)
        return selected

    best: list[dict[str, Any]] = []
    best_key: tuple[float, int, float, str] | None = None
    for mask in range(1 << len(rows)):
        subset = [rows[index] for index in range(len(rows)) if mask & (1 << index)]
        peak = peak_reserved(subset)
        if peak > cash_hkd + 1e-6:
            continue
        utility = sum(preclose_utility(row) for row in subset)
        names = "|".join(sorted(clean(row.get("stock")) for row in subset))
        key = (utility, len(subset), -peak, names)
        if best_key is None or key > best_key:
            best_key = key
            best = subset
    return best


def role_and_priority_by_group(group: dict[str, Any]) -> dict[tuple[str, str], tuple[str, str, str]]:
    rows = list(group.get("preclose_priority") or [])
    cash_hkd = float(group.get("cash_hkd") or 550_000.0)
    ordered = sorted(rows, key=lambda item: (-preclose_utility(item), clean(item.get("window")), clean(item.get("stock"))))
    selected = best_preclose_subset(ordered, cash_hkd=cash_hkd)
    selected_keys = {row_key(row) for row in selected}
    selected_floor = min((preclose_utility(row) for row in selected), default=0.0)
    near_utility_gap = 50.0
    frontier_count = max(1, len(selected)) + 1
    skipped_p0_keys: set[tuple[str, str]] = set()
    for rank, row in enumerate(ordered, start=1):
        key = row_key(row)
        if key in selected_keys:
            continue
        if rank <= frontier_count or (selected_floor and preclose_utility(row) >= selected_floor - near_utility_gap) or row_score(row) >= 78:
            skipped_p0_keys.add(key)
    selected_p0_keys = {
        row_key(selected_row)
        for selected_row in selected
        for skipped_row in ordered
        if row_key(skipped_row) in skipped_p0_keys and windows_overlap(parse_window(selected_row.get("window")), parse_window(skipped_row.get("window")))
    }
    result: dict[tuple[str, str], tuple[str, str, str]] = {}
    for rank, row in enumerate(ordered, start=1):
        key = row_key(row)
        role = "默认排入" if key in selected_keys else "边际跳过"
        reasons: list[str] = []
        if role == "默认排入":
            if key in selected_p0_keys:
                reasons.append("与P0边际跳过样本窗口重叠，需验证是否保留")
            else:
                reasons.append("当前事前组合排入，非首轮边界冲突")
        else:
            reasons.append("同窗口边际跳过，可能替换默认排期")
        if rank <= frontier_count:
            reasons.append("位于组内排期边界")
        if role == "边际跳过" and selected_floor and preclose_utility(row) >= selected_floor - near_utility_gap:
            reasons.append("与排入样本事前效用接近")
        if row_score(row) >= 78:
            reasons.append("78+高分冲突样本")
        if clean(row.get("financing_tier")) == "乙组候选":
            reasons.append("乙组候选需融资热度/成本闸门")

        if key in selected_p0_keys or key in skipped_p0_keys:
            priority = "P0"
        elif row_score(row) >= 72:
            priority = "P1"
        else:
            priority = "P2"
        result[key] = (role, priority, "、".join(reasons))
    return result


def required_checks(row: dict[str, Any]) -> list[str]:
    tier = clean(row.get("financing_tier"))
    checks = ["招股书估值/基石/禁售", "同窗口替换理由"]
    if tier == "乙组候选":
        checks.extend(["融资截止前孖展热度", "额度紧张度", "融资利率/手续费", "融资效率情景"])
    elif tier == "甲组候选":
        checks.extend(["甲组资金效率", "融资利率/手续费", "融资效率情景"])
    else:
        checks.append("现金一手/少量多手资金效率")
    if row.get("preclose_risks"):
        checks.append("风险项复核")
    return checks


def deep_dive_focus(row: dict[str, Any]) -> str:
    risks = "；".join(row.get("preclose_risks") or [])
    evidence = "；".join(row.get("preclose_evidence") or [])
    focus = ["估值", "收入/利润质量", "基石/禁售", "募资用途"]
    if "B类" in risks or "-B" in row.get("stock", ""):
        focus.append("管线/商业化")
    if "高价" in risks:
        focus.append("高定价合理性")
    if "强保荐人" in evidence:
        focus.append("保荐/包销质量是否真正转化为需求")
    return "、".join(focus)


def collection_note(row: dict[str, Any], group: dict[str, Any]) -> str:
    return (
        f"残余同窗口冲突组 {group['group_id']}；不得用首日、一手中签率或最终超购决定替换。"
        "补齐融资截止前热度、招股书深挖和融资打平幅度后再决定是否替换默认排期。"
    )


def build_rows(
    source_payload: dict[str, Any],
    *,
    cash_hkd: float,
    include_observation: bool,
    brokers: list[str],
    group_limit: int | None = None,
    priority_levels: set[str] | None = None,
) -> list[dict[str, Any]]:
    conflict_payload = build_conflict_payload(
        source_payload,
        cash_hkd=cash_hkd,
        include_observation=include_observation,
    )
    groups = conflict_payload.get("conflict_groups") or []
    if group_limit is not None:
        groups = groups[:group_limit]
    rows: list[dict[str, Any]] = []
    for group in groups:
        priority_map = role_and_priority_by_group(group)
        for item in group.get("preclose_priority") or []:
            role, priority, priority_reasons = priority_map.get(row_key(item), ("待复核", "P2", "未进入组内排期边界"))
            if priority_levels and priority not in priority_levels:
                continue
            checks = "、".join(required_checks(item))
            focus = deep_dive_focus(item)
            for broker in brokers:
                rows.append(
                    {
                        "group_id": group.get("group_id"),
                        "stock": item.get("stock"),
                        "code": item.get("code"),
                        "action": item.get("action"),
                        "financing_tier": item.get("financing_tier"),
                        "score": item.get("score"),
                        "preclose_utility": item.get("preclose_utility"),
                        "window": item.get("window"),
                        "lock_days": item.get("lock_days"),
                        "cash_required_hkd": item.get("cash_required_hkd"),
                        "entry_fee_hkd": item.get("entry_fee_hkd"),
                        "conflict_role": role,
                        "collection_priority": priority,
                        "priority_reasons": priority_reasons,
                        "required_checks": checks,
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
                        "prospectus_url": "",
                        "deep_dive_focus": focus,
                        "source": "",
                        "excerpt": "",
                        "collection_note": collection_note(item, group),
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
        f"# {year or ''} 同窗口残余冲突补采清单".strip(),
        "",
        f"生成时间：{dt.datetime.now().isoformat(timespec='seconds')}",
        "用途：补齐融资截止前热度、招股书深挖和融资效率情景，用于判断同窗口冲突是否应替换默认排期。",
        "",
        "| 优先级 | 组 | 股票 | 角色 | 窗口 | 分数 | 事前效用 | 融资层 | 券商 | 优先原因 | 需补字段 | 深挖重点 |",
        "|---|---:|---|---|---|---:|---:|---|---|---|---|---|",
    ]
    if not rows:
        lines.append("| - | - | 暂无残余冲突 | - | - | - | - | - | - | - | - | - |")
    for row in rows:
        lines.append(
            f"| {row['collection_priority']} | {row['group_id']} | {row['stock']} | {row['conflict_role']} | "
            f"{row['window']} | {row['score'] or '-'} | "
            f"{float(row.get('preclose_utility') or 0):.1f} | {row['financing_tier'] or '-'} | "
            f"{row['broker'] or '自填'} | {row['priority_reasons'] or '-'} | {row['required_checks']} | {row['deep_dive_focus']} |"
        )
    lines.extend(
        [
            "",
            "要求：`observed_at`、`source_published_at` 和 `broker_cutoff_at` 必须早于券商融资截止；`source` 和 `excerpt` 只能填申购截止前可见资料。",
            "禁止：不要把最终超购、一手中签率、配售结果、暗盘、首日涨跌、现价或累计涨跌作为替换排期的依据。",
            "后续：将孖展/额度记录归一化为 margin heat JSON，再运行融资效率审计和同窗口冲突审计复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", "-i", required=True, help="Backtest/current IPO JSON payload.")
    parser.add_argument("--cash-hkd", type=float, default=550_000.0)
    parser.add_argument("--include-observation", action="store_true", help="Include 可选观察 as conflict candidates.")
    parser.add_argument("--brokers", help="Comma-separated broker names. Omit for 富途,辉立,耀才; pass empty for one blank row.")
    parser.add_argument("--group-limit", type=int, help="Only include the first N conflict groups.")
    parser.add_argument("--priority-levels", help="Comma-separated priority levels to include, e.g. P0 or P0,P1.")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_payload = load_json(args.input_json)
    rows = build_rows(
        source_payload,
        cash_hkd=args.cash_hkd,
        include_observation=args.include_observation,
        brokers=split_brokers(args.brokers),
        group_limit=args.group_limit,
        priority_levels=parse_priority_levels(args.priority_levels),
    )
    if args.markdown:
        sys.stdout.write(render_markdown(rows, year=source_payload.get("year")))
    else:
        sys.stdout.write(render_csv(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
