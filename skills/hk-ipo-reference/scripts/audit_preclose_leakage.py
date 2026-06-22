#!/usr/bin/env python3
"""Audit that pre-close scoring and scheduling ignore post-close outcome fields."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from audit_capital_conflicts import build_payload as build_conflict_payload
from backtest_year_ipos import DEFAULT_BACKTEST_CASH_HKD, optimized_preclose_score


FUTURE_FIELD_MUTATIONS: dict[str, Any] = {
    "oversubscription_rate": 999_999.0,
    "applied_lots_for_one_lot": "999999手",
    "one_lot_success_rate_pct": 0.01,
    "first_day_change_pct": 999.0,
    "cumulative_change_pct": 999.0,
    "current_price_hkd": 999.0,
    "actual_label": "强收益",
    "grey_market_change_pct": 999.0,
    "grey_market_price_hkd": 999.0,
    "allotment_result_url": "https://example.invalid/future-allotment.pdf",
}
SCORED_FIELDS = {"recommendation", "legacy_recommendation", "review_label", "actual_label"}
FORBIDDEN_RECOMMENDATION_TERMS = [
    "一手中签率",
    "中签率",
    "稳中",
    "超购",
    "配售结果",
    "暗盘",
    "首日",
    "上市表现",
    "现价",
    "累积表现",
]


def clean(value: Any) -> str:
    return str(value or "").strip()


def finding(code: str, severity: str, message: str, evidence: str = "") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


def load_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(record) for record in (payload.get("records") or payload.get("ipos") or [])]


def stock_id(record: dict[str, Any]) -> str:
    return clean(record.get("code") or record.get("canonical_code") or record.get("name") or "unknown")


def strip_scored_fields(record: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record)
    for field in SCORED_FIELDS:
        item.pop(field, None)
    return item


def mutate_future_fields(record: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record)
    for key, value in FUTURE_FIELD_MUTATIONS.items():
        item[key] = value
    raw = item.get("raw")
    if isinstance(raw, dict):
        raw["future_leakage_sentinel"] = "首日+999/超购999999/一手中签0.01"
    return item


def score_signature(record: dict[str, Any]) -> dict[str, Any]:
    score = optimized_preclose_score(strip_scored_fields(record))
    return {
        "score": score.get("score"),
        "action": score.get("action"),
        "evidence": score.get("evidence") or [],
        "risks": score.get("risks") or [],
        "financing": score.get("financing") or {},
    }


def normalize_group_signature(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "stock_count": group.get("stock_count"),
        "peak_cash_required_hkd": group.get("peak_cash_required_hkd"),
        "over_capacity_hkd": group.get("over_capacity_hkd"),
        "window_start": group.get("window_start"),
        "window_end": group.get("window_end"),
        "preclose_priority": [
            {
                "stock": row.get("stock"),
                "code": row.get("code"),
                "window": row.get("window"),
                "lock_days": row.get("lock_days"),
                "cash_required_hkd": row.get("cash_required_hkd"),
                "entry_fee_hkd": row.get("entry_fee_hkd"),
                "score": row.get("score"),
                "action": row.get("action"),
                "financing_tier": row.get("financing_tier"),
                "preclose_evidence": row.get("preclose_evidence") or [],
                "preclose_risks": row.get("preclose_risks") or [],
                "preclose_checklist": row.get("preclose_checklist") or [],
            }
            for row in group.get("preclose_priority") or []
        ],
    }


def conflict_signature(payload: dict[str, Any], *, cash_hkd: float, include_observation: bool) -> dict[str, Any]:
    stripped = {
        "records": [strip_scored_fields(record) for record in load_records(payload)],
        "year": payload.get("year"),
    }
    result = build_conflict_payload(stripped, cash_hkd=cash_hkd, include_observation=include_observation)
    return {
        "summary": result.get("summary") or {},
        "groups": [normalize_group_signature(group) for group in result.get("conflict_groups") or []],
        "missing_window": [
            {
                "stock": row.get("stock"),
                "code": row.get("code"),
                "score": row.get("score"),
                "action": row.get("action"),
                "financing_tier": row.get("financing_tier"),
            }
            for row in result.get("missing_window") or []
        ],
    }


def stored_recommendation_findings(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for record in records:
        recommendation = record.get("recommendation")
        if not isinstance(recommendation, dict):
            continue
        text = "；".join(
            str(item)
            for key in ["evidence", "risks"]
            for item in (recommendation.get(key) or [])
        )
        matched = [term for term in FORBIDDEN_RECOMMENDATION_TERMS if term in text]
        if matched:
            findings.append(
                finding(
                    "stored_recommendation_future_terms",
                    "error",
                    "已存推荐理由/风险疑似包含配售后或上市后字段。",
                    f"{stock_id(record)}: {','.join(matched)}",
                )
            )
    return findings


def audit_payload(
    payload: dict[str, Any],
    *,
    cash_hkd: float = DEFAULT_BACKTEST_CASH_HKD,
    include_observation: bool = False,
    max_examples: int = 10,
) -> dict[str, Any]:
    records = load_records(payload)
    findings = stored_recommendation_findings(records)
    score_changed: list[str] = []
    for record in records:
        base = score_signature(record)
        mutated = score_signature(mutate_future_fields(record))
        if base != mutated:
            score_changed.append(stock_id(record))
            if len(score_changed) <= max_examples:
                findings.append(
                    finding(
                        "preclose_score_changed_by_future_fields",
                        "error",
                        "申购前评分会随最终结果字段变化，存在未来数据泄露。",
                        f"{stock_id(record)}: base={base}, mutated={mutated}",
                    )
                )

    base_payload = {"records": [strip_scored_fields(record) for record in records], "year": payload.get("year")}
    mutated_payload = {
        "records": [mutate_future_fields(strip_scored_fields(record)) for record in records],
        "year": payload.get("year"),
    }
    base_conflicts = conflict_signature(base_payload, cash_hkd=cash_hkd, include_observation=include_observation)
    mutated_conflicts = conflict_signature(mutated_payload, cash_hkd=cash_hkd, include_observation=include_observation)
    if base_conflicts != mutated_conflicts:
        findings.append(
            finding(
                "capital_conflict_schedule_changed_by_future_fields",
                "error",
                "同窗口排期事前顺序会随最终结果字段变化，存在未来数据泄露。",
                "capital conflict preclose signature changed after future-field mutation",
            )
        )

    if not any(item["severity"] == "error" for item in findings):
        findings.append(
            finding(
                "preclose_future_field_invariance_ok",
                "info",
                "申购前评分和同窗口排期未随最终结果字段变化。",
                f"records={len(records)}, conflict_groups={len(base_conflicts.get('groups') or [])}",
            )
        )

    error_count = sum(1 for item in findings if item["severity"] == "error")
    warning_count = sum(1 for item in findings if item["severity"] == "warning")
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "year": payload.get("year"),
        "summary": {
            "records": len(records),
            "errors": error_count,
            "warnings": warning_count,
            "passed": error_count == 0,
            "score_changed_count": len(score_changed),
            "capital_conflict_groups": len(base_conflicts.get("groups") or []),
            "verdict": "通过：未发现申购前评分/排期使用最终结果字段。" if error_count == 0 else "不通过：发现未来数据泄露风险。",
        },
        "findings": findings,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 港股打新申购前数据泄露审计",
        "",
        f"生成时间：{payload['generated_at']}",
        f"结论：{summary['verdict']}",
        "",
        "## 摘要",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 样本数 | {summary['records']} |",
        f"| 错误 | {summary['errors']} |",
        f"| 警告 | {summary['warnings']} |",
        f"| 评分受最终字段影响样本 | {summary['score_changed_count']} |",
        f"| 同窗口冲突组 | {summary['capital_conflict_groups']} |",
        "",
        "## 问题清单",
        "| 级别 | 代码 | 说明 | 证据 |",
        "|---|---|---|---|",
    ]
    for item in payload["findings"]:
        evidence = clean(item.get("evidence")).replace("|", "\\|") or "-"
        lines.append(f"| {item['severity']} | {item['code']} | {item['message']} | {evidence} |")
    lines.extend(
        [
            "",
            "## 审计方法",
            "- 将最终超购、一手中签率、暗盘/首日、现价、累积表现等字段替换为极端值。",
            "- 重新计算申购前评分和同窗口资金冲突事前顺序。",
            "- 若评分、推荐桶位、融资分层、冲突组事前顺序发生变化，则视为未来数据泄露风险。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", "-i", required=True, help="Backtest/current IPO JSON payload.")
    parser.add_argument("--cash-hkd", type=float, default=DEFAULT_BACKTEST_CASH_HKD)
    parser.add_argument("--include-observation", action="store_true", help="Include 可选观察 in the capital-conflict invariance audit.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = audit_payload(payload, cash_hkd=args.cash_hkd, include_observation=args.include_observation)
    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
