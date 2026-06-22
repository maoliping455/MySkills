#!/usr/bin/env python3
"""Split a filled consolidated P0 worksheet back into domain-specific CSV rows."""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path
from typing import Any

import prepare_margin_history_template as margin_template
import prepare_p0_evidence_pack as p0_pack


DOMAIN_FILENAMES = {
    "margin_history": "margin-history-p0-from-consolidated.csv",
    "execution_risk": "execution-risk-p0-from-consolidated.csv",
    "borderline_upgrade": "borderline-upgrade-p0-from-consolidated.csv",
    "capital_conflict": "conflict-research-p0-from-consolidated.csv",
}
GENERIC_FIELDS = [
    "group_id",
    "stock",
    "code",
    "action",
    "financing_tier",
    "score",
    "window",
    "lock_days",
    "cash_required_hkd",
    "entry_fee_hkd",
    "collection_priority",
    "priority_reasons",
    "required_checks",
    "broker",
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
    "deep_dive_focus",
    "source",
    "excerpt",
    "search_attempted_at",
    "search_source",
    "unavailable_reason",
    "search_note",
    "collection_note",
]


def clean(value: Any) -> str:
    return str(value or "").strip()


def read_rows(path: str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    return [dict(row) for row in csv.DictReader(text.splitlines())]


def domain_matches(row: dict[str, Any], domain: str) -> bool:
    labels = [item.strip() for item in clean(row.get("domains")).replace("|", "、").split("、") if item.strip()]
    return domain in labels or p0_pack.DOMAIN_LABELS[domain] in labels


def stock_name(row: dict[str, Any]) -> str:
    name = clean(row.get("stock") or row.get("stock_name") or row.get("name"))
    return re.sub(r"[（(]\s*\d{1,5}(?:\.HK)?\s*[）)]$", "", name, flags=re.IGNORECASE).strip()


def margin_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": clean(row.get("code")),
        "stock_name": stock_name(row),
        "listing_date": clean(row.get("listing_date")),
        "subscription_start_date": clean(row.get("subscription_start_date")),
        "closing_date": clean(row.get("closing_date")),
        "allotment_date": clean(row.get("allotment_date")),
        "refund_date": clean(row.get("refund_date")),
        "financing_tier": clean(row.get("financing_tier")),
        "score": clean(row.get("score")),
        "entry_fee_hkd": clean(row.get("entry_fee_hkd")),
        "collection_priority": "P0",
        "priority_reasons": clean(row.get("priority_reasons")),
        "broker": clean(row.get("broker")),
        "observed_at": clean(row.get("observed_at")),
        "source_published_at": clean(row.get("source_published_at")),
        "preclose_confirmed": clean(row.get("preclose_confirmed")),
        "broker_cutoff_at": clean(row.get("broker_cutoff_at")),
        "margin_multiple": clean(row.get("margin_multiple")),
        "margin_amount_hkd": clean(row.get("margin_amount_hkd")),
        "quota_status": clean(row.get("quota_status")),
        "financing_rate_pct": clean(row.get("financing_rate_pct")),
        "cutoff_note": clean(row.get("cutoff_note")),
        "acceleration": clean(row.get("acceleration") or row.get("demand_validation")),
        "source": clean(row.get("source")),
        "excerpt": clean(row.get("excerpt")),
        "search_attempted_at": clean(row.get("search_attempted_at")),
        "search_source": clean(row.get("search_source")),
        "unavailable_reason": clean(row.get("unavailable_reason")),
        "search_note": clean(row.get("search_note")),
        "collection_note": clean(row.get("collection_note")),
    }


def generic_row(row: dict[str, Any], *, domain: str) -> dict[str, Any]:
    return {
        "group_id": clean(row.get("group_id")) or domain,
        "stock": stock_name(row),
        "code": clean(row.get("code")),
        "action": clean(row.get("action")),
        "financing_tier": clean(row.get("financing_tier")),
        "score": clean(row.get("score")),
        "window": clean(row.get("window")),
        "lock_days": clean(row.get("lock_days")),
        "cash_required_hkd": clean(row.get("cash_required_hkd")),
        "entry_fee_hkd": clean(row.get("entry_fee_hkd")),
        "collection_priority": "P0",
        "priority_reasons": clean(row.get("priority_reasons")),
        "required_checks": clean(row.get("required_checks")),
        "broker": clean(row.get("broker")),
        "observed_at": clean(row.get("observed_at")),
        "source_published_at": clean(row.get("source_published_at")),
        "preclose_confirmed": clean(row.get("preclose_confirmed")),
        "broker_cutoff_at": clean(row.get("broker_cutoff_at")),
        "margin_multiple": clean(row.get("margin_multiple")),
        "margin_amount_hkd": clean(row.get("margin_amount_hkd")),
        "quota_status": clean(row.get("quota_status")),
        "financing_rate_pct": clean(row.get("financing_rate_pct")),
        "fees_hkd": clean(row.get("fees_hkd")),
        "financing_days": clean(row.get("financing_days")),
        "scenario_first_day_pct": clean(row.get("scenario_first_day_pct")),
        "scenario_allotment_rate_pct": clean(row.get("scenario_allotment_rate_pct")),
        "max_credible_allotment_rate_pct": clean(row.get("max_credible_allotment_rate_pct")),
        "prospectus_url": clean(row.get("prospectus_url")),
        "valuation_note": clean(row.get("valuation_note")),
        "peer_comparable_note": clean(row.get("peer_comparable_note")),
        "cornerstone_lockup_note": clean(row.get("cornerstone_lockup_note")),
        "hard_tech_validation": clean(row.get("hard_tech_validation")),
        "demand_validation": clean(row.get("demand_validation")),
        "deep_dive_focus": clean(row.get("deep_dive_focus")),
        "source": clean(row.get("source")),
        "excerpt": clean(row.get("excerpt")),
        "search_attempted_at": clean(row.get("search_attempted_at")),
        "search_source": clean(row.get("search_source")),
        "unavailable_reason": clean(row.get("unavailable_reason")),
        "search_note": clean(row.get("search_note")),
        "collection_note": clean(row.get("collection_note")),
    }


def split_rows(rows: list[dict[str, Any]], *, domain: str) -> list[dict[str, Any]]:
    if domain not in p0_pack.DOMAIN_ORDER:
        raise ValueError(f"Unsupported domain: {domain}")
    matched = [row for row in rows if domain_matches(row, domain)]
    if domain == "margin_history":
        return [margin_row(row) for row in matched]
    return [generic_row(row, domain=domain) for row in matched]


def fields_for(domain: str) -> list[str]:
    if domain == "margin_history":
        return margin_template.CSV_FIELDS
    return GENERIC_FIELDS


def render_csv(rows: list[dict[str, Any]], *, domain: str) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields_for(domain), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", required=True, help="Filled p0-consolidated CSV.")
    parser.add_argument("--domain", choices=[*p0_pack.DOMAIN_ORDER, "all"], required=True)
    parser.add_argument("--output-dir", help="Required when --domain all. Writes one CSV per domain.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_rows(args.input)
    if args.domain == "all":
        if not args.output_dir:
            raise SystemExit("--output-dir is required when --domain all")
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for domain in p0_pack.DOMAIN_ORDER:
            output_path = output_dir / DOMAIN_FILENAMES[domain]
            output_path.write_text(render_csv(split_rows(rows, domain=domain), domain=domain), encoding="utf-8")
        return 0
    sys.stdout.write(render_csv(split_rows(rows, domain=args.domain), domain=args.domain))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
