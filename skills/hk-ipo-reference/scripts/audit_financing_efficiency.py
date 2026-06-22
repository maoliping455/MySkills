#!/usr/bin/env python3
"""Audit pre-close financing efficiency under explicit scenario assumptions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from build_recommendation_report import chinese_display_alias, margin_heat_for_ipo
from calculate_subscription_return import calculate_return_metrics
from fetch_current_ipos import clean_stock_name
from normalize_margin_input import independent_heat_signal_count, normalized_cost_status, strict_execution_ready


DEFAULT_CASH_HKD = 550_000.0
DEFAULT_MARGIN_MULTIPLE = 10.0
DEFAULT_FINANCING_DAYS = 7
DEFAULT_SCENARIO_FIRST_DAY_PCT = 20.0
DEFAULT_SCENARIO_ONE_LOT_SUCCESS_RATE_PCT = 5.0
DEFAULT_MAX_CREDIBLE_EXPECTED_LOTS = None
A_GROUP_LIMIT_HKD = 5_000_000.0
DEFAULT_SCENARIO_PROFILE = "base"
SCENARIO_PROFILE_CHOICES = ["off", "strict", "base", "hot"]
PROFILE_RATE_RANGES = {
    "strict": {
        "weak": (0.08, 0.15),
        "partial": (0.15, 0.25),
        "ready": (0.30, 0.45),
        "hot": (0.45, 0.70),
    },
    "base": {
        "weak": (0.15, 0.25),
        "partial": (0.25, 0.40),
        "ready": (0.60, 0.90),
        "hot": (0.80, 1.20),
    },
    "hot": {
        "weak": (0.25, 0.40),
        "partial": (0.40, 0.65),
        "ready": (0.90, 1.35),
        "hot": (1.20, 1.80),
    },
}
HEAT_GRADE_LABELS = {
    "missing": "未提供",
    "weak": "偏弱/高成本",
    "partial": "不完整",
    "ready": "闸门满足",
    "hot": "强热",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_code(value: Any) -> str | None:
    match = re.search(r"(?<!\d)(\d{4,5})(?:\.HK)?(?!\d)", clean(value))
    return match.group(1).zfill(5) if match else None


def contains_chinese(value: str | None) -> bool:
    return bool(value and re.search(r"[\u4e00-\u9fff]", value))


def stock_title(record: dict[str, Any]) -> str:
    code = clean(record.get("code")) or (f"{record.get('canonical_code')}.HK" if record.get("canonical_code") else "")
    name = clean_stock_name(record.get("name") or record.get("stock_name") or "")
    if contains_chinese(name):
        return f"{name}（{code}）" if code else name
    alias = chinese_display_alias(record)
    if alias:
        return f"{alias}（{code}）" if code else alias
    return f"代码{code}（中文名待核实）" if code else "未命名新股（中文名待核实）"


def money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待核实"
    return f"HKD {float(value):,.0f}"


def pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待核实"
    return f"{float(value):+.2f}%"


def lots(value: Any) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "待核实"
    number = float(value)
    if number == 0:
        return "0"
    if number < 1:
        return f"{number:.2f}"
    return f"{number:.1f}"


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_heat_payload(paths: list[str] | None) -> dict[str, Any] | None:
    if not paths:
        return None
    payloads = [load_json(path) for path in paths]
    if len(payloads) == 1:
        return payloads[0]
    return {"items_by_stock": payloads}


def load_scenario_payload(paths: list[str] | None) -> dict[str, Any] | None:
    if not paths:
        return None
    payloads = [load_json(path) for path in paths]
    if len(payloads) == 1:
        return payloads[0]
    return {"items_by_stock": payloads}


def normalize_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("records") or payload.get("ipos") or payload.get("items") or []
    return [item for item in rows if isinstance(item, dict)]


def scenario_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    items: list[dict[str, Any]] = []
    for group in payload.get("groups") or []:
        if isinstance(group, dict):
            items.extend(item for item in group.get("stocks") or [] if isinstance(item, dict))
    for key in ["items_by_stock", "stocks"]:
        nested = payload.get(key)
        if isinstance(nested, list):
            items.extend(item for item in nested if isinstance(item, dict))
    if not items and (payload.get("code") or payload.get("stock") or payload.get("stock_name")):
        items.append(payload)
    return items


def scenario_stock_name(item: dict[str, Any]) -> str:
    return clean_stock_name(item.get("stock") or item.get("stock_name") or item.get("name") or "")


def scenario_for_record(record: dict[str, Any], scenario_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    record_code = canonical_code(record.get("code") or record.get("canonical_code"))
    record_name = clean_stock_name(record.get("name") or record.get("stock_name") or "")
    fallback: dict[str, Any] | None = None
    for item in scenario_items(scenario_payload):
        item_code = canonical_code(item.get("code") or item.get("canonical_code"))
        item_name = scenario_stock_name(item)
        matched = bool(
            (item_code and record_code and item_code == record_code)
            or (item_name and record_name and (item_name in record_name or record_name in item_name))
        )
        if not matched:
            continue
        item_assumptions = item.get("financing_assumptions") or {}
        has_numeric_assumption = any(isinstance(value, (int, float)) for value in item_assumptions.values())
        if has_numeric_assumption:
            return item
        if fallback is None:
            fallback = item
    return fallback


def scenario_assumptions(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    assumptions = {
        key: value
        for key, value in (item.get("financing_assumptions") or {}).items()
        if isinstance(value, (int, float))
    }
    for key in [
        "scenario_first_day_pct",
        "scenario_one_lot_success_rate_pct",
        "scenario_expected_lots",
        "scenario_allotment_rate_pct",
        "max_credible_expected_lots",
        "max_credible_allotment_rate_pct",
        "financing_rate_pct",
        "financing_days",
        "fees_hkd",
    ]:
        if key in item and item.get(key) is not None and key not in assumptions:
            assumptions[key] = item.get(key)
    return assumptions


def override_number(assumptions: dict[str, Any], key: str, fallback: float | None) -> float | None:
    value = assumptions.get(key)
    return float(value) if isinstance(value, (int, float)) else fallback


def override_int(assumptions: dict[str, Any], key: str, fallback: int) -> int:
    value = assumptions.get(key)
    return int(value) if isinstance(value, (int, float)) else fallback


def financing_tier(record: dict[str, Any]) -> str:
    return clean(((record.get("recommendation") or {}).get("financing") or {}).get("tier"))


def recommendation_action(record: dict[str, Any]) -> str:
    return clean((record.get("recommendation") or {}).get("action"))


def application_amount(record: dict[str, Any], *, cash_hkd: float, margin_multiple: float) -> float:
    tier = financing_tier(record)
    if tier == "乙组候选":
        return cash_hkd * margin_multiple
    if tier == "甲组候选":
        return min(A_GROUP_LIMIT_HKD, cash_hkd * margin_multiple)
    return cash_hkd


def valid_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def heat_grade(margin_heat: dict[str, Any] | None) -> dict[str, Any]:
    if not margin_heat:
        return {
            "grade": "missing",
            "label": HEAT_GRADE_LABELS["missing"],
            "strict_gate": False,
            "independent_signal_count": 0,
            "cost_status": "未提供",
            "risk_flags": [],
        }
    summary = margin_heat.get("summary") or {}
    signal_count = independent_heat_signal_count(summary)
    cost_status = normalized_cost_status(summary)
    risks = [clean(item) for item in summary.get("risk_flags") or [] if clean(item)]
    strict_gate = strict_execution_ready(summary)
    grade = "weak"
    if strict_gate:
        grade = "hot" if signal_count >= 3 or summary.get("confidence") == "高" else "ready"
    elif cost_status == "偏高" or any("需求偏弱" in risk or "成本" in risk for risk in risks):
        grade = "weak"
    elif signal_count > 0 or cost_status == "可接受":
        grade = "partial"
    return {
        "grade": grade,
        "label": HEAT_GRADE_LABELS[grade],
        "strict_gate": strict_gate,
        "independent_signal_count": signal_count,
        "cost_status": cost_status,
        "risk_flags": risks,
    }


def derive_profile_rates(
    *,
    margin_heat: dict[str, Any] | None,
    scenario_profile: str,
) -> dict[str, Any] | None:
    if scenario_profile == "off" or not margin_heat:
        return None
    profile = PROFILE_RATE_RANGES.get(scenario_profile, PROFILE_RATE_RANGES[DEFAULT_SCENARIO_PROFILE])
    grade = heat_grade(margin_heat)
    scenario_rate, max_rate = profile[grade["grade"] if grade["grade"] != "missing" else "weak"]
    return {
        "scenario_allotment_rate_pct": scenario_rate,
        "max_credible_allotment_rate_pct": max_rate,
        "source": f"profile:{scenario_profile}:{grade['grade']}",
        "heat_grade": grade,
    }


def include_record(record: dict[str, Any], include: str) -> bool:
    tier = financing_tier(record)
    action = recommendation_action(record)
    if include == "b-group":
        return tier == "乙组候选"
    if include == "financing":
        return tier in {"乙组候选", "甲组候选"}
    if include == "recommended":
        return action == "建议申购"
    if include == "observation":
        return action == "可选观察"
    if include == "all":
        return bool(action)
    return True


def audit_record(
    record: dict[str, Any],
    *,
    cash_hkd: float,
    margin_multiple: float,
    scenario_first_day_pct: float,
    scenario_one_lot_success_rate_pct: float,
    scenario_expected_lots: float | None,
    scenario_allotment_rate_pct: float | None,
    max_credible_expected_lots: float | None,
    max_credible_allotment_rate_pct: float | None,
    financing_rate_pct: float | None,
    financing_days: int,
    fees_hkd: float,
    margin_heat: dict[str, Any] | None = None,
    margin_heat_expected: bool = False,
    scenario_profile: str = DEFAULT_SCENARIO_PROFILE,
) -> dict[str, Any] | None:
    entry_fee = record.get("entry_fee_hkd")
    if not isinstance(entry_fee, (int, float)) or entry_fee <= 0:
        return None
    amount = application_amount(record, cash_hkd=cash_hkd, margin_multiple=margin_multiple)
    metrics = calculate_return_metrics(
        entry_fee_hkd=float(entry_fee),
        first_day_pct=scenario_first_day_pct,
        one_lot_success_rate_pct=scenario_one_lot_success_rate_pct,
        cash_hkd=cash_hkd,
        margin_multiple=margin_multiple,
        application_amount_hkd=amount,
        financing_rate_pct=financing_rate_pct,
        financing_days=financing_days,
        fees_hkd=fees_hkd,
    )
    application_lots = amount / float(entry_fee)
    profile_rates = derive_profile_rates(margin_heat=margin_heat, scenario_profile=scenario_profile)
    heat = heat_grade(margin_heat)
    resolved_scenario_rate = scenario_allotment_rate_pct
    resolved_scenario_rate_source = "explicit_allotment_rate" if valid_positive(scenario_allotment_rate_pct) else "not_set"
    if not valid_positive(resolved_scenario_rate) and profile_rates:
        resolved_scenario_rate = profile_rates["scenario_allotment_rate_pct"]
        resolved_scenario_rate_source = profile_rates["source"]
    resolved_max_rate = max_credible_allotment_rate_pct
    resolved_max_rate_source = "explicit_allotment_rate" if valid_positive(max_credible_allotment_rate_pct) else "not_set"
    if not valid_positive(resolved_max_rate) and profile_rates:
        resolved_max_rate = profile_rates["max_credible_allotment_rate_pct"]
        resolved_max_rate_source = profile_rates["source"]

    resolved_expected_lots = scenario_expected_lots
    expected_lots_source = "explicit_lots" if valid_positive(scenario_expected_lots) else "one_lot_probability"
    if not valid_positive(resolved_expected_lots) and valid_positive(resolved_scenario_rate):
        resolved_expected_lots = application_lots * float(resolved_scenario_rate) / 100.0
        expected_lots_source = "application_lots_x_allotment_rate"
    resolved_max_lots = max_credible_expected_lots
    max_lots_source = "explicit_lots" if valid_positive(max_credible_expected_lots) else "not_set"
    if not valid_positive(resolved_max_lots) and valid_positive(resolved_max_rate):
        resolved_max_lots = application_lots * float(resolved_max_rate) / 100.0
        max_lots_source = "application_lots_x_allotment_rate"

    returns = metrics["returns"]
    costs = metrics["costs"]
    expected_break_even = returns.get("expected_break_even_first_day_pct")
    scenario_expected_net = returns.get("expected_one_lot_net_pnl_hkd")
    scenario_break_even = expected_break_even
    if valid_positive(resolved_expected_lots):
        scenario_gross = float(entry_fee) * scenario_first_day_pct / 100.0 * float(resolved_expected_lots)
        scenario_expected_net = scenario_gross - costs["total_cost_hkd"]
        scenario_break_even = costs["total_cost_hkd"] / (float(entry_fee) * float(resolved_expected_lots)) * 100.0
    one_lot_break_even = returns.get("break_even_if_one_lot_first_day_pct")
    required_expected_lots = None
    required_allotment_rate_pct = None
    if scenario_first_day_pct > 0:
        required_expected_lots = costs["total_cost_hkd"] / (float(entry_fee) * scenario_first_day_pct / 100.0)
        required_allotment_rate_pct = required_expected_lots / application_lots * 100.0 if application_lots > 0 else None
    flags: list[str] = []
    if financing_rate_pct is None:
        flags.append("融资利率缺失，不能执行乙组/大额甲组")
    if margin_heat_expected and not margin_heat:
        flags.append("未匹配该股申购前融资热度，需补券商孖展/额度/成本证据")
    if margin_heat and not heat["strict_gate"]:
        if heat["grade"] == "weak":
            flags.append("融资热度偏弱或成本风险，不能执行乙组/大额甲组")
        else:
            flags.append("融资热度闸门未满足，需补券商孖展/额度/成本证据")
    if (
        isinstance(required_expected_lots, (int, float))
        and valid_positive(resolved_max_lots)
        and required_expected_lots > float(resolved_max_lots)
    ):
        flags.append("打平所需获配手数高于可信上限，需降级融资或重估获配")
    if isinstance(scenario_break_even, (int, float)) and scenario_break_even > scenario_first_day_pct:
        flags.append("按情景假设计算，打平所需首日涨幅高于目标涨幅")
    if (
        not valid_positive(resolved_expected_lots)
        and isinstance(one_lot_break_even, (int, float))
        and one_lot_break_even > scenario_first_day_pct
    ):
        flags.append("即使中一手，目标涨幅也不足以覆盖融资息费")
    if isinstance(scenario_expected_net, (int, float)) and scenario_expected_net <= 0:
        flags.append("情景期望扣成本不正")
    status = "通过"
    if flags:
        status = (
            "不通过"
            if any("不正" in flag or "高于目标" in flag or "可信上限" in flag or "不能执行" in flag for flag in flags)
            else "需补数据"
        )
    return {
        "stock": stock_title(record),
        "code": clean(record.get("code")) or (f"{record.get('canonical_code')}.HK" if record.get("canonical_code") else None),
        "action": recommendation_action(record),
        "financing_tier": financing_tier(record),
        "entry_fee_hkd": float(entry_fee),
        "application_amount_hkd": amount,
        "application_lots": application_lots,
        "financing_interest_hkd": costs["financing_interest_hkd"],
        "total_cost_hkd": costs["total_cost_hkd"],
        "expected_one_lot_net_pnl_hkd": returns.get("expected_one_lot_net_pnl_hkd"),
        "scenario_expected_lots": resolved_expected_lots,
        "scenario_expected_lots_source": expected_lots_source,
        "scenario_allotment_rate_pct": resolved_scenario_rate,
        "scenario_allotment_rate_source": resolved_scenario_rate_source,
        "required_expected_lots_to_break_even": required_expected_lots,
        "required_allotment_rate_to_break_even_pct": required_allotment_rate_pct,
        "max_credible_expected_lots": resolved_max_lots,
        "max_credible_expected_lots_source": max_lots_source,
        "max_credible_allotment_rate_pct": resolved_max_rate,
        "max_credible_allotment_rate_source": resolved_max_rate_source,
        "scenario_expected_net_pnl_hkd": scenario_expected_net,
        "break_even_if_one_lot_first_day_pct": one_lot_break_even,
        "expected_break_even_first_day_pct": expected_break_even,
        "scenario_break_even_first_day_pct": scenario_break_even,
        "scenario_profile": scenario_profile,
        "heat_grade": heat["label"],
        "heat_grade_code": heat["grade"],
        "heat_strict_gate": heat["strict_gate"],
        "heat_independent_signal_count": heat["independent_signal_count"],
        "heat_cost_status": heat["cost_status"],
        "status": status,
        "flags": flags,
    }


def build_payload(
    source_payload: dict[str, Any],
    *,
    cash_hkd: float = DEFAULT_CASH_HKD,
    margin_multiple: float = DEFAULT_MARGIN_MULTIPLE,
    scenario_first_day_pct: float = DEFAULT_SCENARIO_FIRST_DAY_PCT,
    scenario_one_lot_success_rate_pct: float = DEFAULT_SCENARIO_ONE_LOT_SUCCESS_RATE_PCT,
    scenario_expected_lots: float | None = None,
    scenario_allotment_rate_pct: float | None = None,
    max_credible_expected_lots: float | None = DEFAULT_MAX_CREDIBLE_EXPECTED_LOTS,
    max_credible_allotment_rate_pct: float | None = None,
    financing_rate_pct: float | None = None,
    financing_days: int = DEFAULT_FINANCING_DAYS,
    fees_hkd: float = 0.0,
    include: str = "financing",
    margin_heat_payload: dict[str, Any] | None = None,
    scenario_payload: dict[str, Any] | None = None,
    scenario_profile: str = DEFAULT_SCENARIO_PROFILE,
) -> dict[str, Any]:
    rows = []
    skipped_missing_entry = 0
    scenario_override_count = 0
    for record in normalize_records(source_payload):
        scenario_item = scenario_for_record(record, scenario_payload)
        if include == "scenario":
            if scenario_item is None:
                continue
        elif not include_record(record, include):
            continue
        overrides = scenario_assumptions(scenario_item)
        if overrides:
            scenario_override_count += 1
        row = audit_record(
            record,
            cash_hkd=cash_hkd,
            margin_multiple=margin_multiple,
            scenario_first_day_pct=override_number(overrides, "scenario_first_day_pct", scenario_first_day_pct) or scenario_first_day_pct,
            scenario_one_lot_success_rate_pct=override_number(
                overrides,
                "scenario_one_lot_success_rate_pct",
                scenario_one_lot_success_rate_pct,
            )
            or scenario_one_lot_success_rate_pct,
            scenario_expected_lots=override_number(overrides, "scenario_expected_lots", scenario_expected_lots),
            scenario_allotment_rate_pct=override_number(overrides, "scenario_allotment_rate_pct", scenario_allotment_rate_pct),
            max_credible_expected_lots=override_number(overrides, "max_credible_expected_lots", max_credible_expected_lots),
            max_credible_allotment_rate_pct=override_number(
                overrides,
                "max_credible_allotment_rate_pct",
                max_credible_allotment_rate_pct,
            ),
            financing_rate_pct=override_number(overrides, "financing_rate_pct", financing_rate_pct),
            financing_days=override_int(overrides, "financing_days", financing_days),
            fees_hkd=override_number(overrides, "fees_hkd", fees_hkd) or 0.0,
            margin_heat=margin_heat_for_ipo(record, margin_heat_payload),
            margin_heat_expected=margin_heat_payload is not None,
            scenario_profile=scenario_profile,
        )
        if row is None:
            skipped_missing_entry += 1
        else:
            row["scenario_override_applied"] = bool(overrides)
            row["scenario_override_fields"] = sorted(overrides) if overrides else []
            rows.append(row)
    status_counts = {
        "通过": sum(1 for row in rows if row["status"] == "通过"),
        "需补数据": sum(1 for row in rows if row["status"] == "需补数据"),
        "不通过": sum(1 for row in rows if row["status"] == "不通过"),
    }
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "assumptions": {
            "cash_hkd": cash_hkd,
            "margin_multiple": margin_multiple,
            "scenario_first_day_pct": scenario_first_day_pct,
            "scenario_one_lot_success_rate_pct": scenario_one_lot_success_rate_pct,
            "scenario_expected_lots": scenario_expected_lots,
            "scenario_allotment_rate_pct": scenario_allotment_rate_pct,
            "max_credible_expected_lots": max_credible_expected_lots,
            "max_credible_allotment_rate_pct": max_credible_allotment_rate_pct,
            "financing_rate_pct": financing_rate_pct,
            "financing_days": financing_days,
            "fees_hkd": fees_hkd,
            "include": include,
            "scenario_profile": scenario_profile,
            "margin_heat_supplied": margin_heat_payload is not None,
            "scenario_json_supplied": scenario_payload is not None,
            "scenario_override_count": scenario_override_count,
        },
        "summary": {
            "candidate_count": len(rows),
            "skipped_missing_entry_fee": skipped_missing_entry,
            "passed_count": status_counts["通过"],
            "needs_data_count": status_counts["需补数据"],
            "failed_count": status_counts["不通过"],
            "passed": status_counts["不通过"] == 0 and status_counts["需补数据"] == 0,
        },
        "items": sorted(rows, key=lambda row: (row["status"] != "不通过", row["status"] != "需补数据", row["stock"])),
        "guardrail": "本审计只使用申购前可设定的情景假设、申购前融资热度、入场费、申购金额、融资利率、费用和计息天数；不得把最终一手中签率或首日涨跌作为锁单输入。",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    assumptions = payload["assumptions"]
    summary = payload["summary"]
    lines = [
        "# 港股打新融资资金效率审计",
        "",
        f"生成时间：{payload['generated_at']}",
        f"口径：现金 {money(assumptions['cash_hkd'])}，融资倍数 {assumptions['margin_multiple']:.2f}x，"
        f"情景首日 {pct(assumptions['scenario_first_day_pct'])}，"
        f"情景一手中签率 {pct(assumptions['scenario_one_lot_success_rate_pct'])}，"
        f"情景预期获配手数 {assumptions.get('scenario_expected_lots') if assumptions.get('scenario_expected_lots') is not None else '未设'}，"
        f"情景配售率 {pct(assumptions.get('scenario_allotment_rate_pct'))}，"
        f"可信获配上限 {assumptions.get('max_credible_expected_lots') if assumptions.get('max_credible_expected_lots') is not None else '未设'} 手，"
        f"可信配售率上限 {pct(assumptions.get('max_credible_allotment_rate_pct'))}，"
        f"融资利率 {pct(assumptions.get('financing_rate_pct'))}，计息 {assumptions['financing_days']} 天，"
        f"费用 {money(assumptions['fees_hkd'])}，情景档 {assumptions['scenario_profile']}。",
        f"逐股情景覆盖：{'已提供' if assumptions.get('scenario_json_supplied') else '未提供'}；"
        f"匹配 {assumptions.get('scenario_override_count', 0)} 只。",
        f"结论：候选 {summary['candidate_count']}；通过 {summary['passed_count']}；需补数据 {summary['needs_data_count']}；不通过 {summary['failed_count']}。",
        f"防泄露：{payload['guardrail']}",
        "",
        "| 股票 | 推荐 | 融资层 | 热度档 | 情景来源 | 申购金额 | 申购手数 | 融资息费 | 情景获配 | 情景期望净额 | 打平需获配 | 打平配售率 | 中一手打平 | 情景打平 | 状态 | 旗标 |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    if not payload["items"]:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | 无候选 |")
    for item in payload["items"]:
        lines.append(
            f"| {item['stock']} | {item['action'] or '-'} | {item['financing_tier'] or '-'} | "
            f"{item['heat_grade']} | {item['scenario_allotment_rate_source']} | "
            f"{money(item['application_amount_hkd'])} | {lots(item['application_lots'])} | "
            f"{money(item['total_cost_hkd'])} | {lots(item['scenario_expected_lots'])} | "
            f"{money(item['scenario_expected_net_pnl_hkd'])} | {lots(item['required_expected_lots_to_break_even'])} | "
            f"{pct(item['required_allotment_rate_to_break_even_pct'])} | "
            f"{pct(item['break_even_if_one_lot_first_day_pct'])} | "
            f"{pct(item['scenario_break_even_first_day_pct'])} | {item['status']} | {'；'.join(item['flags']) or '-'} |"
        )
    lines.extend(
        [
            "",
            "## 使用口径",
            "- 该审计用于融资截止前的情景压力测试，不替代券商实际额度、利率和手续费确认。",
            "- 当传入 `--margin-heat-json` 且未显式给出配售率时，`--scenario-profile` 会把申购前热度闸门转换为保守/基准/偏热配售率情景；这只是压力测试假设，不是配售预测。",
            "- 若 `情景期望净额` 不正、打平涨幅高于目标涨幅，或打平所需获配手数高于可信上限，不应把乙组候选当成可执行指令。",
            "- 情景一手中签率、预期获配手数或配售率必须来自申购前可解释假设、券商热度或历史同类区间，不能使用本 IPO 最终配售结果。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", "-i", required=True, help="Current IPO or backtest JSON payload.")
    parser.add_argument("--cash-hkd", type=float, default=DEFAULT_CASH_HKD)
    parser.add_argument("--margin-multiple", type=float, default=DEFAULT_MARGIN_MULTIPLE)
    parser.add_argument("--scenario-first-day-pct", type=float, default=DEFAULT_SCENARIO_FIRST_DAY_PCT)
    parser.add_argument("--scenario-one-lot-success-rate-pct", type=float, default=DEFAULT_SCENARIO_ONE_LOT_SUCCESS_RATE_PCT)
    parser.add_argument("--scenario-expected-lots", type=float, help="Optional expected allotted lots under the pre-close scenario.")
    parser.add_argument("--scenario-allotment-rate-pct", type=float, help="Optional expected allotment rate; converted into expected lots per stock.")
    parser.add_argument("--max-credible-expected-lots", type=float, default=DEFAULT_MAX_CREDIBLE_EXPECTED_LOTS)
    parser.add_argument("--max-credible-allotment-rate-pct", type=float, help="Optional credible upper allotment rate; converted into max expected lots per stock.")
    parser.add_argument("--financing-rate-pct", type=float)
    parser.add_argument("--financing-days", type=int, default=DEFAULT_FINANCING_DAYS)
    parser.add_argument("--fees-hkd", type=float, default=0.0)
    parser.add_argument("--include", choices=["b-group", "financing", "recommended", "observation", "all", "scenario"], default="financing")
    parser.add_argument("--margin-heat-json", action="append", help="Optional normalized pre-close margin heat JSON; repeatable.")
    parser.add_argument("--scenario-json", action="append", help="Optional per-stock pre-close scenario JSON from normalized research templates; repeatable.")
    parser.add_argument("--scenario-profile", choices=SCENARIO_PROFILE_CHOICES, default=DEFAULT_SCENARIO_PROFILE)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(
        load_json(args.input_json),
        cash_hkd=args.cash_hkd,
        margin_multiple=args.margin_multiple,
        scenario_first_day_pct=args.scenario_first_day_pct,
        scenario_one_lot_success_rate_pct=args.scenario_one_lot_success_rate_pct,
        scenario_expected_lots=args.scenario_expected_lots,
        scenario_allotment_rate_pct=args.scenario_allotment_rate_pct,
        max_credible_expected_lots=args.max_credible_expected_lots,
        max_credible_allotment_rate_pct=args.max_credible_allotment_rate_pct,
        financing_rate_pct=args.financing_rate_pct,
        financing_days=args.financing_days,
        fees_hkd=args.fees_hkd,
        include=args.include,
        margin_heat_payload=load_heat_payload(args.margin_heat_json),
        scenario_payload=load_scenario_payload(args.scenario_json),
        scenario_profile=args.scenario_profile,
    )
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
