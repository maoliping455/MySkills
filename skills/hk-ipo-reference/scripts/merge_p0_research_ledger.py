#!/usr/bin/env python3
"""Merge eligible P0 research ledger evidence back into the consolidated P0 worksheet."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import normalize_conflict_research_input as conflict_input
import prepare_p0_evidence_pack as p0_pack
from normalize_margin_input import clean


MERGE_FIELDS = [
    "observed_at",
    "source_published_at",
    "preclose_confirmed",
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
    "source",
    "excerpt",
    "search_attempted_at",
    "search_source",
    "unavailable_reason",
    "search_note",
]
JOIN_FIELDS = {
    "quota_status",
    "prospectus_url",
    "valuation_note",
    "peer_comparable_note",
    "cornerstone_lockup_note",
    "hard_tech_validation",
    "demand_validation",
    "source",
    "excerpt",
    "search_source",
    "unavailable_reason",
    "search_note",
}


def normalized_code(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    match = re.search(r"(?<!\d)(\d{1,5})(?:\.HK)?(?!\d)", text, flags=re.IGNORECASE)
    return match.group(1).zfill(5) if match else text.upper()


def normalized_stock(value: Any) -> str:
    text = clean(value)
    return re.sub(r"[（(]\s*\d{1,5}(?:\.HK)?\s*[）)]$", "", text, flags=re.IGNORECASE).strip()


def stock_keys(row: dict[str, Any]) -> list[tuple[str, str]]:
    keys = []
    code = normalized_code(row.get("code"))
    stock = normalized_stock(row.get("stock") or row.get("stock_name") or row.get("name"))
    if code:
        keys.append((code, ""))
    if stock:
        keys.append(("", stock))
    return keys


def read_consolidated_rows(path: str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    return [dict(row) for row in csv.DictReader(text.splitlines())]


def unique_join(values: list[Any]) -> str:
    result: list[str] = []
    for value in values:
        text = clean(value)
        if text and text not in result:
            result.append(text)
    return "；".join(result)


def eligible_ledger_rows(rows: list[dict[str, Any]], *, assume_preclose: bool) -> tuple[list[dict[str, Any]], dict[str, int]]:
    eligible = []
    stats = {
        "ledger_row_count": len(rows),
        "blank_row_count": 0,
        "eligible_row_count": 0,
        "attempted_gap_row_count": 0,
        "timing_invalid_row_count": 0,
        "evidence_contaminated_row_count": 0,
    }
    for row in rows:
        reviewed = conflict_input.review_row(row, assume_preclose=assume_preclose)
        if reviewed.get("template_unfilled"):
            stats["blank_row_count"] += 1
            continue
        if reviewed["eligible_for_decision"] or reviewed.get("attempted_data_gap"):
            merged = dict(row)
            merged["_reviewed"] = reviewed
            eligible.append(merged)
            if reviewed["eligible_for_decision"]:
                stats["eligible_row_count"] += 1
            else:
                stats["attempted_gap_row_count"] += 1
        else:
            if reviewed.get("evidence_eligible") is False:
                stats["evidence_contaminated_row_count"] += 1
            else:
                stats["timing_invalid_row_count"] += 1
    return eligible, stats


def ledger_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        for key in stock_keys(row):
            index.setdefault(key, []).append(row)
    return index


def value_from_row(row: dict[str, Any], field: str) -> str:
    reviewed = row.get("_reviewed") or {}
    if field == "preclose_confirmed" and reviewed.get("timing_confirmed"):
        return "是"
    return clean(row.get(field))


def aggregate_field(rows: list[dict[str, Any]], field: str) -> str:
    values = [value_from_row(row, field) for row in rows]
    if field in JOIN_FIELDS:
        return unique_join(values)
    return next((value for value in values if clean(value)), "")


def merge_rows(
    consolidated_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    *,
    overwrite: bool = False,
    assume_preclose: bool = False,
) -> dict[str, Any]:
    eligible_rows, stats = eligible_ledger_rows(ledger_rows, assume_preclose=assume_preclose)
    index = ledger_index(eligible_rows)
    merged_rows: list[dict[str, Any]] = []
    merged_stock_count = 0
    updated_field_count = 0
    for row in consolidated_rows:
        output = dict(row)
        matched: list[dict[str, Any]] = []
        for key in stock_keys(row):
            matched.extend(index.get(key) or [])
        matched = list({id(item): item for item in matched}.values())
        if matched:
            changed = 0
            for field in MERGE_FIELDS:
                value = aggregate_field(matched, field)
                if value and (overwrite or not clean(output.get(field))):
                    if clean(output.get(field)) != value:
                        output[field] = value
                        changed += 1
            if changed:
                merged_stock_count += 1
                updated_field_count += changed
                note = clean(output.get("collection_note"))
                evidence_count = sum(1 for item in matched if (item.get("_reviewed") or {}).get("eligible_for_decision"))
                attempted_gap_count = sum(1 for item in matched if (item.get("_reviewed") or {}).get("attempted_data_gap"))
                merge_note = f"P0公开检索台账合并：{evidence_count}条时间有效证据，{attempted_gap_count}条已尝试缺口。"
                output["collection_note"] = unique_join([note, merge_note])
        merged_rows.append(output)
    summary = {
        **stats,
        "consolidated_row_count": len(consolidated_rows),
        "merged_stock_count": merged_stock_count,
        "updated_field_count": updated_field_count,
        "overwrite": overwrite,
    }
    return {
        "summary": summary,
        "rows": merged_rows,
        "guardrail": "Only eligible pre-close ledger rows are merged. Late or post-close contaminated rows remain excluded.",
    }


def render_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=p0_pack.CONSOLIDATED_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in p0_pack.CONSOLIDATED_FIELDS})
    return output.getvalue()


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# P0 检索台账合并审查",
        "",
        f"合并股票：{summary['merged_stock_count']}；更新字段：{summary['updated_field_count']}；合并表行数：{summary['consolidated_row_count']}。",
        (
            f"台账行：{summary['ledger_row_count']}；有效行：{summary['eligible_row_count']}；"
            f"已尝试缺口：{summary.get('attempted_gap_row_count', 0)}；"
            f"空白：{summary.get('blank_row_count', 0)}；时间无效：{summary['timing_invalid_row_count']}；"
            f"证据污染：{summary['evidence_contaminated_row_count']}。"
        ),
        f"覆盖已有字段：{'是' if summary['overwrite'] else '否'}",
        f"防泄露口径：{payload['guardrail']}",
        "",
        "## 使用结论",
        "- 默认只填空字段，避免覆盖人工已确认的合并表内容。",
        "- 已尝试缺口只记录公开检索不可得，不是申购前决策证据；专家闸门仍需要显式 `--accept-p0-data-gaps` 才会闭环。",
        "- 输出 CSV 后仍需用 `split_p0_consolidated_input.py --domain all` 拆回分域 CSV，再接入专家闸门。",
        "- 如果有效行数大于 0 但合并股票为 0，通常是股票代码或中文名无法匹配。",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consolidated", required=True, help="P0 consolidated worksheet CSV.")
    parser.add_argument("--ledger", required=True, help="Filled p0-research-queries CSV/JSON/JSONL.")
    parser.add_argument("--ledger-format", choices=["auto", "csv", "json", "jsonl"], default="auto")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing consolidated fields. Default fills blanks only.")
    parser.add_argument("--assume-preclose", action="store_true", help="Treat ledger rows without explicit timing as pre-close. Use only for trusted historical data.")
    parser.add_argument("--summary-json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = merge_rows(
        read_consolidated_rows(args.consolidated),
        conflict_input.read_rows(args.ledger, args.ledger_format),
        overwrite=args.overwrite,
        assume_preclose=args.assume_preclose,
    )
    if args.summary_json:
        sys.stdout.write(json.dumps({"summary": payload["summary"], "guardrail": payload["guardrail"]}, ensure_ascii=False, indent=2) + "\n")
    elif args.markdown:
        sys.stdout.write(render_markdown(payload))
    else:
        sys.stdout.write(render_csv(payload["rows"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
