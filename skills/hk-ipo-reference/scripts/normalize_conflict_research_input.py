#!/usr/bin/env python3
"""Normalize filled residual same-window conflict research rows."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from normalize_margin_history import (
    evidence_contamination_review,
    parse_date,
    parse_datetime,
    read_rows,
    row_to_excerpt,
    row_value,
    timing_review,
)
from normalize_margin_input import canonical_code, clean, normalize_text


NUMERIC_FIELDS = [
    "score",
    "preclose_utility",
    "lock_days",
    "cash_required_hkd",
    "entry_fee_hkd",
    "margin_multiple",
    "margin_amount_hkd",
    "financing_rate_pct",
    "fees_hkd",
    "financing_days",
    "scenario_first_day_pct",
    "scenario_allotment_rate_pct",
    "max_credible_allotment_rate_pct",
]
USER_FILLED_FIELDS = [
    "observed_at",
    "source_published_at",
    "broker_cutoff_at",
    "preclose_confirmed",
    "margin_multiple",
    "margin_amount_hkd",
    "quota_status",
    "financing_rate_pct",
    "fees_hkd",
    "financing_days",
    "scenario_first_day_pct",
    "scenario_allotment_rate_pct",
    "max_credible_allotment_rate_pct",
    "valuation_note",
    "peer_comparable_note",
    "cornerstone_lockup_note",
    "hard_tech_validation",
    "demand_validation",
    "source",
    "excerpt",
    "search_attempted_at",
    "search_source",
    "unavailable_reason",
    "search_note",
]
P0_QUERY_FAMILIES = {
    "preclose_return_scenario": "scenario",
    "hkex_prospectus_deep_dive": "prospectus",
    "public_sentiment_auxiliary": "sentiment",
}
POST_CLOSE_GUARDRAIL = (
    "Only rows observed before broker financing cutoff can support residual conflict decisions. "
    "Final oversubscription, one-lot success, allotment, grey-market, first-day, current-price, "
    "or cumulative-performance evidence is retained for review but excluded from decision inputs."
)


def parse_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    normalized = (
        text.replace(",", "")
        .replace("HKD", "")
        .replace("港元", "")
        .replace("港币", "")
        .replace("%", "")
    )
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def split_tokens(value: Any) -> list[str]:
    return [item for item in re.split(r"[、,;；|]+", clean(value)) if item]


def stock_name(row: dict[str, Any]) -> str | None:
    return row_value(row, "stock", "stock_name", "name", "股票名称") or None


def stock_code(row: dict[str, Any]) -> str | None:
    raw = row_value(row, "code", "stock_code", "股票代码")
    return canonical_code(raw) or raw or None


def group_key(row: dict[str, Any]) -> str:
    return row_value(row, "group_id", "group", "冲突组") or "未分组"


def stock_key(row: dict[str, Any]) -> tuple[str, str]:
    code = stock_code(row)
    name = stock_name(row)
    if code:
        return ("code", code)
    return ("name", name or "未命名")


def has_explicit_preclose_flag(row: dict[str, Any]) -> bool:
    return bool(row_value(row, "preclose_confirmed", "融资截止前", "pre_close"))


def can_infer_preclose_from_cutoff(row: dict[str, Any]) -> bool:
    observed_raw = row_value(row, "observed_at", "date", "记录时间")
    cutoff_raw = row_value(row, "broker_cutoff_at", "financing_cutoff_at", "融资截止时间")
    if not observed_raw or not cutoff_raw:
        return False

    observed_dt = parse_datetime(observed_raw)
    cutoff_dt = parse_datetime(cutoff_raw)
    if observed_dt and cutoff_dt:
        return observed_dt < cutoff_dt

    observed_date = parse_date(observed_raw)
    cutoff_date = parse_date(cutoff_raw)
    if observed_date and cutoff_date:
        return observed_date < cutoff_date
    return False


def template_unfilled(row: dict[str, Any]) -> bool:
    """Detect generated template rows before the user has filled evidence."""

    return not any(clean(row.get(field)) for field in USER_FILLED_FIELDS)


def attempted_data_gap_row(row: dict[str, Any], *, evidence_eligible: bool) -> bool:
    """Detect a real public-search attempt that found no usable pre-close evidence."""

    if not evidence_eligible:
        return False
    if not row_value(row, "unavailable_reason", "不可得原因"):
        return False
    return bool(
        row_value(row, "search_attempted_at", "检索时间")
        and row_value(row, "search_source", "检索来源", "source", "来源")
        and (row_value(row, "search_note", "检索说明") or row_value(row, "excerpt", "摘录"))
    )


def review_row(row: dict[str, Any], *, assume_preclose: bool) -> dict[str, Any]:
    review_input = dict(row)
    inferred_preclose = False
    if not has_explicit_preclose_flag(review_input) and can_infer_preclose_from_cutoff(review_input):
        review_input["preclose_confirmed"] = "是"
        inferred_preclose = True

    timing = timing_review(review_input, assume_preclose=assume_preclose)
    evidence = evidence_contamination_review(review_input)
    eligible = bool(timing["timing_confirmed"] and evidence["evidence_eligible"])
    template_empty = template_unfilled(row)
    attempted_gap = attempted_data_gap_row(row, evidence_eligible=evidence["evidence_eligible"])
    timing_risks = [] if template_empty or attempted_gap else timing["timing_risks"]

    normalized = {
        "group_id": group_key(row),
        "stock": stock_name(row),
        "code": stock_code(row),
        "action": row_value(row, "action", "recommendation", "建议") or None,
        "financing_tier": row_value(row, "financing_tier", "融资层") or None,
        "required_checks": split_tokens(row_value(row, "required_checks", "需补字段")),
        "query_type": row_value(row, "query_type", "检索类型") or None,
        "broker": row_value(row, "broker", "券商") or None,
        "window": row_value(row, "window", "窗口") or None,
        "observed_at": timing["observed_at"],
        "source_published_at": timing["source_published_at"],
        "broker_cutoff_at": timing["broker_cutoff_at"],
        "preclose_confirmed": timing["preclose_confirmed"],
        "preclose_confirmed_inferred": inferred_preclose,
        "template_unfilled": template_empty,
        "attempted_data_gap": attempted_gap,
        "timing_confirmed": timing["timing_confirmed"],
        "timing_confidence": timing["timing_confidence"],
        "timing_risks": timing_risks,
        "evidence_eligible": evidence["evidence_eligible"],
        "evidence_risks": evidence["evidence_risks"],
        "eligible_for_decision": eligible,
        "quota_status": row_value(row, "quota_status", "额度状态") or None,
        "prospectus_url": row_value(row, "prospectus_url", "招股书链接") or None,
        "deep_dive_focus": row_value(row, "deep_dive_focus", "深挖重点") or None,
        "source": row_value(row, "source", "来源") or None,
        "excerpt": row_value(row, "excerpt", "摘录") or None,
        "search_attempted_at": row_value(row, "search_attempted_at", "检索时间") or None,
        "search_source": row_value(row, "search_source", "检索来源") or None,
        "unavailable_reason": row_value(row, "unavailable_reason", "不可得原因") or None,
        "search_note": row_value(row, "search_note", "检索说明") or None,
        "collection_note": row_value(row, "collection_note", "备注") or None,
    }
    for field in NUMERIC_FIELDS:
        value = parse_float(row.get(field))
        if value is not None:
            normalized[field] = value
    return normalized


def unique_missing(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def query_family(query_type: Any) -> str:
    text = clean(query_type)
    if text.startswith("broker_margin"):
        return "margin"
    return P0_QUERY_FAMILIES.get(text, "")


def has_any_value(rows: list[dict[str, Any]], fields: list[str]) -> bool:
    return any(row.get(field) is not None and clean(row.get(field)) for row in rows for field in fields)


def missing_fields_for_p0_query_rows(all_rows: list[dict[str, Any]], eligible_rows: list[dict[str, Any]]) -> list[str]:
    families = {query_family(row.get("query_type")) for row in all_rows}
    families.discard("")
    missing: list[str] = []

    if "margin" in families:
        margin_rows = [row for row in eligible_rows if query_family(row.get("query_type")) == "margin"]
        if not has_any_value(margin_rows, ["margin_multiple", "margin_amount_hkd", "quota_status"]):
            missing.append("margin_heat")
        if not has_any_value(margin_rows, ["financing_rate_pct", "fees_hkd"]):
            missing.append("financing_rate_or_fees")
        if not has_any_value(margin_rows, ["financing_days"]):
            missing.append("financing_days")

    if "scenario" in families:
        scenario_rows = [row for row in eligible_rows if query_family(row.get("query_type")) == "scenario"]
        if not has_any_value(scenario_rows, ["scenario_first_day_pct"]):
            missing.append("scenario_first_day_pct")
        if not has_any_value(scenario_rows, ["scenario_allotment_rate_pct", "max_credible_allotment_rate_pct"]):
            missing.append("scenario_allotment_rate_pct")

    if "prospectus" in families:
        prospectus_rows = [row for row in eligible_rows if query_family(row.get("query_type")) == "prospectus"]
        if not has_any_value(prospectus_rows, ["prospectus_url", "source"]):
            missing.append("prospectus_or_source")
        if not has_any_value(
            prospectus_rows,
            [
                "valuation_note",
                "peer_comparable_note",
                "cornerstone_lockup_note",
                "hard_tech_validation",
                "excerpt",
            ],
        ):
            missing.append("prospectus_summary_or_excerpt")

    return unique_missing(missing)


def missing_fields_for_stock(all_rows: list[dict[str, Any]], eligible_rows: list[dict[str, Any]]) -> list[str]:
    if not eligible_rows:
        return ["eligible_preclose_rows"]

    if any(clean(row.get("query_type")) for row in all_rows):
        missing = missing_fields_for_p0_query_rows(all_rows, eligible_rows)
        if missing:
            return missing

    rows = eligible_rows
    tier = next((clean(row.get("financing_tier")) for row in rows if clean(row.get("financing_tier"))), "")
    required_text = " ".join(
        " ".join(row.get("required_checks") or []) if isinstance(row.get("required_checks"), list) else clean(row.get("required_checks"))
        for row in rows
    )
    needs_financing_review = (
        "乙组" in tier
        or "甲组" in tier
        or any(keyword in required_text for keyword in ["孖展", "融资", "额度", "利率", "手续费"])
    )
    missing: list[str] = []
    has_margin_heat = any(
        row.get("margin_multiple") is not None
        or row.get("margin_amount_hkd") is not None
        or clean(row.get("quota_status"))
        for row in rows
    )
    has_cost = any(row.get("financing_rate_pct") is not None or row.get("fees_hkd") is not None for row in rows)
    has_days = any(row.get("financing_days") is not None for row in rows)
    has_scenario_return = any(row.get("scenario_first_day_pct") is not None for row in rows)
    has_scenario_allotment = any(
        row.get("scenario_allotment_rate_pct") is not None
        or row.get("max_credible_allotment_rate_pct") is not None
        for row in rows
    )
    has_deep_dive = any(clean(row.get("prospectus_url")) or clean(row.get("source")) for row in rows)

    if needs_financing_review:
        if not has_margin_heat:
            missing.append("margin_heat")
        if not has_cost:
            missing.append("financing_rate_or_fees")
        if not has_days:
            missing.append("financing_days")
        if not has_scenario_return:
            missing.append("scenario_first_day_pct")
        if not has_scenario_allotment:
            missing.append("scenario_allotment_rate_pct")
    if not has_deep_dive:
        missing.append("prospectus_or_source")
    return unique_missing(missing)


def research_status(all_rows: list[dict[str, Any]], eligible_rows: list[dict[str, Any]], missing: list[str]) -> str:
    if not eligible_rows:
        if all(row.get("template_unfilled") for row in all_rows):
            return "待填回"
        if any(row.get("attempted_data_gap") for row in all_rows):
            return "已尝试缺口"
        if any(row.get("evidence_eligible") is False for row in all_rows):
            return "证据污染"
        return "时间无效"
    if missing:
        if any(row.get("attempted_data_gap") for row in all_rows):
            return "已尝试缺口"
        return "缺数据"
    return "可复核"


def stock_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible_rows = [row for row in rows if row["eligible_for_decision"]]
    missing = missing_fields_for_stock(rows, eligible_rows)
    status = research_status(rows, eligible_rows, missing)
    if status == "待填回":
        missing = ["pending_input"]
    return {
        "stock": next((row.get("stock") for row in rows if row.get("stock")), None),
        "code": next((row.get("code") for row in rows if row.get("code")), None),
        "action": next((row.get("action") for row in rows if row.get("action")), None),
        "financing_tier": next((row.get("financing_tier") for row in rows if row.get("financing_tier")), None),
        "window": next((row_value(row, "window", "窗口") for row in rows if row_value(row, "window", "窗口")), None),
        "score": next((row.get("score") for row in rows if row.get("score") is not None), None),
        "preclose_utility": next((row.get("preclose_utility") for row in rows if row.get("preclose_utility") is not None), None),
        "lock_days": next((row.get("lock_days") for row in rows if row.get("lock_days") is not None), None),
        "cash_required_hkd": next((row.get("cash_required_hkd") for row in rows if row.get("cash_required_hkd") is not None), None),
        "entry_fee_hkd": next((row.get("entry_fee_hkd") for row in rows if row.get("entry_fee_hkd") is not None), None),
        "research_status": status,
        "missing_fields": missing,
        "timing_valid_row_count": sum(1 for row in rows if row["timing_confirmed"]),
        "evidence_contaminated_row_count": sum(1 for row in rows if not row["evidence_eligible"]),
        "attempted_data_gap_row_count": sum(1 for row in rows if row.get("attempted_data_gap")),
        "eligible_decision_row_count": len(eligible_rows),
        "financing_assumptions": {
            field: next((row.get(field) for row in eligible_rows if row.get(field) is not None), None)
            for field in [
                "financing_rate_pct",
                "fees_hkd",
                "financing_days",
                "scenario_first_day_pct",
                "scenario_allotment_rate_pct",
                "max_credible_allotment_rate_pct",
            ]
        },
        "sources": [
            {
                "broker": row.get("broker"),
                "source": row.get("source"),
                "prospectus_url": row.get("prospectus_url"),
                "observed_at": row.get("observed_at"),
                "source_published_at": row.get("source_published_at"),
                "eligible_for_decision": row.get("eligible_for_decision"),
            }
            for row in rows
        ],
        "rows": rows,
    }


def build_heat_seed(reviewed_rows: list[dict[str, Any]], raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_raw: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for normalized, raw in zip(reviewed_rows, raw_rows):
        grouped_raw[stock_key(raw)].append((normalized, raw))

    seed: list[dict[str, Any]] = []
    for _, pairs in grouped_raw.items():
        eligible_raw = [raw for normalized, raw in pairs if normalized["eligible_for_decision"]]
        excerpts = [row_to_excerpt(row) for row in eligible_raw if row_to_excerpt(row)]
        if not excerpts:
            continue
        first_raw = pairs[0][1]
        seed.append(
            normalize_text(
                "\n".join(excerpts),
                stock_name=stock_name(first_raw),
                code=stock_code(first_raw),
            )
        )
    return seed


def normalize_rows(rows: list[dict[str, Any]], *, assume_preclose: bool = False) -> dict[str, Any]:
    reviewed_rows = [review_row(row, assume_preclose=assume_preclose) for row in rows]
    group_map: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for normalized, raw in zip(reviewed_rows, rows):
        group_map[normalized["group_id"]][stock_key(raw)].append(normalized)

    groups = []
    stock_payloads = []
    for group_id in sorted(group_map, key=lambda value: (value == "未分组", value)):
        stocks = [stock_payload(stock_rows) for stock_rows in group_map[group_id].values()]
        stocks.sort(key=lambda item: (item.get("stock") or "", item.get("code") or ""))
        groups.append({"group_id": group_id, "stocks": stocks})
        stock_payloads.extend(stocks)

    heat_seed = build_heat_seed(reviewed_rows, rows)
    eligible_count = sum(1 for row in reviewed_rows if row["eligible_for_decision"])
    timing_valid_count = sum(1 for row in reviewed_rows if row["timing_confirmed"])
    contaminated_count = sum(1 for row in reviewed_rows if not row["evidence_eligible"])
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "schema_version": 1,
        "summary": {
            "row_count": len(rows),
            "group_count": len(groups),
            "stock_count": len(stock_payloads),
            "timing_valid_row_count": timing_valid_count,
            "evidence_contaminated_row_count": contaminated_count,
            "eligible_decision_row_count": eligible_count,
            "invalid_or_excluded_row_count": len(rows) - eligible_count,
            "review_ready_stock_count": sum(1 for item in stock_payloads if item["research_status"] == "可复核"),
            "pending_input_stock_count": sum(1 for item in stock_payloads if item["research_status"] == "待填回"),
            "missing_data_stock_count": sum(1 for item in stock_payloads if item["research_status"] == "缺数据"),
            "timing_invalid_stock_count": sum(1 for item in stock_payloads if item["research_status"] == "时间无效"),
            "evidence_contaminated_stock_count": sum(1 for item in stock_payloads if item["research_status"] == "证据污染"),
            "attempted_data_gap_stock_count": sum(1 for item in stock_payloads if item["research_status"] == "已尝试缺口"),
            "margin_heat_seed_stock_count": len(heat_seed),
        },
        "groups": groups,
        "items_by_stock": heat_seed,
        "margin_heat_seed": {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "schema_version": 1,
            "stocks": heat_seed,
            "disclaimer": "Seed generated only from eligible pre-close residual-conflict rows.",
        },
        "disclaimer": POST_CLOSE_GUARDRAIL,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# 补采资料填回质量审查",
        "",
        f"生成时间：{payload.get('generated_at') or '-'}",
        (
            f"填回行数：{summary.get('row_count', 0)}；股票数：{summary.get('stock_count', 0)}；"
            f"可复核股票：{summary.get('review_ready_stock_count', 0)}；待填回：{summary.get('pending_input_stock_count', 0)}；"
            f"缺数据：{summary.get('missing_data_stock_count', 0)}；"
            f"时间无效：{summary.get('timing_invalid_stock_count', 0)}；证据污染：{summary.get('evidence_contaminated_stock_count', 0)}；"
            f"已尝试缺口：{summary.get('attempted_data_gap_stock_count', 0)}。"
        ),
        (
            f"有效决策行：{summary.get('eligible_decision_row_count', 0)}；"
            f"可生成孖展热度种子：{summary.get('margin_heat_seed_stock_count', 0)}。"
        ),
        f"防泄露口径：{payload.get('disclaimer') or POST_CLOSE_GUARDRAIL}",
        "",
        "| 组 | 股票 | 代码 | 建议 | 融资层 | 状态 | 有效行 | 缺口 | 时间/证据风险 |",
        "|---|---|---|---|---|---|---:|---|---|",
    ]
    groups = payload.get("groups") or []
    if not groups:
        lines.append("| - | - | - | - | - | 无填回资料 | 0 | - | - |")
    for group in groups:
        group_id = group.get("group_id") or "-"
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
                f"| {group_id} | {stock.get('stock') or '-'} | {stock.get('code') or '-'} | "
                f"{stock.get('action') or '-'} | {stock.get('financing_tier') or '-'} | "
                f"{stock.get('research_status') or '-'} | {stock.get('eligible_decision_row_count', 0)} | "
                f"{missing} | {risk_text} |"
            )
    lines.extend(
        [
            "",
            "## 使用结论",
        ]
    )
    if summary.get("review_ready_stock_count", 0):
        lines.append("- 只有 `可复核` 股票可进入后续融资效率或同窗口取舍审计。")
    if summary.get("pending_input_stock_count", 0):
        lines.append("- `待填回` 股票只是模板占位，还未提供申购截止前证据；先填 `observed_at`、`source_published_at`、`broker_cutoff_at`、融资成本、情景配售率、来源或摘录。")
    if summary.get("missing_data_stock_count", 0):
        lines.append("- `缺数据` 股票需要补齐融资成本、情景配售率、热度、招股书或来源后再复核。")
    if summary.get("timing_invalid_stock_count", 0):
        lines.append("- `时间无效` 股票不能作为申购前决策证据；补 `observed_at`、`source_published_at` 和 `broker_cutoff_at`。")
    if summary.get("evidence_contaminated_stock_count", 0):
        lines.append("- `证据污染` 股票包含配售后或上市后信息，只能保留作复盘，不能进入申购前模型。")
    if summary.get("attempted_data_gap_stock_count", 0):
        lines.append("- `已尝试缺口` 股票记录了无污染的公开检索尝试，但没有找到足够申购前证据；只有显式接受数据缺口时才算闭环。")
    if not any(
        summary.get(key, 0)
        for key in [
            "review_ready_stock_count",
            "pending_input_stock_count",
            "missing_data_stock_count",
            "timing_invalid_stock_count",
            "evidence_contaminated_stock_count",
            "attempted_data_gap_stock_count",
        ]
    ):
        lines.append("- 暂无可审查股票。")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--format", choices=["auto", "csv", "jsonl", "json"], default="auto")
    parser.add_argument(
        "--assume-preclose",
        action="store_true",
        help="Treat rows without explicit timing as pre-close. Use only for trusted historical data.",
    )
    parser.add_argument("--markdown", action="store_true", help="Output a human-readable readiness report instead of JSON.")
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
