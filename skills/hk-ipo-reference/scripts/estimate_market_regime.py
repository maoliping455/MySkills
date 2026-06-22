#!/usr/bin/env python3
"""Estimate current Hong Kong IPO market temperature from recent listed IPOs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from backtest_year_ipos import (
    AASTOCKS_LISTED_URL,
    display_stock,
    fetch_listed_page,
    infer_market_regime,
    parse_listed_rows,
    pct,
    to_date,
)


def fetch_recent_listed(
    *,
    as_of: dt.date,
    max_pages: int,
    timeout: int,
    retries: int,
    window: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        url = f"{AASTOCKS_LISTED_URL}?s=3&o=0&page={page}"
        try:
            html_text = fetch_listed_page(page, timeout=timeout, retries=retries)
            page_records = parse_listed_rows(html_text, url)
            sources.append({"name": f"AASTOCKS listed IPO page {page}", "url": url, "status": "ok", "items": len(page_records)})
        except Exception as exc:  # noqa: BLE001
            sources.append({"name": f"AASTOCKS listed IPO page {page}", "url": url, "status": "error", "error": str(exc)})
            break

        for record in page_records:
            code = record.get("canonical_code") or record.get("code")
            listing_date = to_date(record.get("listing_date"))
            if not code or not listing_date or listing_date >= as_of or code in seen:
                continue
            seen.add(str(code))
            records.append(record)
        if len(records) >= window * 2:
            break

    records.sort(key=lambda item: to_date(item.get("listing_date")) or dt.date.min)
    return records, sources


def build_payload(
    *,
    as_of: dt.date,
    records: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    window: int,
    min_samples: int,
    strong_threshold_pct: float,
) -> dict[str, Any]:
    regime = infer_market_regime(
        records,
        window=window,
        min_samples=min_samples,
        strong_threshold=strong_threshold_pct,
    )
    recent = records[-window:]
    return {
        "as_of_date": as_of.isoformat(),
        "market_regime": regime,
        "window": window,
        "min_samples": min_samples,
        "strong_threshold_pct": strong_threshold_pct,
        "recent_listings": [
            {
                "listing_date": item.get("listing_date"),
                "name": item.get("name"),
                "code": item.get("code"),
                "first_day_change_pct": item.get("first_day_change_pct"),
                "oversubscription_rate": item.get("oversubscription_rate"),
                "one_lot_success_rate_pct": item.get("one_lot_success_rate_pct"),
            }
            for item in recent
        ],
        "sources": sources,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    regime = payload["market_regime"]
    lines = [
        "# 港股打新市场温度",
        "",
        f"日期：{payload['as_of_date']}",
        f"结论：{regime['label']}（最近 {regime['sample_size']} 只可用样本）",
        f"中位首日：{pct(regime.get('median_first_day_pct'))}",
        f"首日正收益率：{ratio(regime.get('positive_rate'))}",
        f"强收益率：{ratio(regime.get('strong_rate'))}",
        f"不涨/破发率：{ratio(regime.get('break_even_or_down_rate'))}",
        "",
        "## 最近样本",
        "| 上市日 | 股票 | 首日 | 超购 | 一手中签率 |",
        "|---|---|---:|---:|---:|",
    ]
    for item in reversed(payload["recent_listings"]):
        lines.append(
            f"| {item.get('listing_date') or '-'} | {display_stock(item)} | "
            f"{pct(item.get('first_day_change_pct'))} | {num(item.get('oversubscription_rate'))} | "
            f"{pct(item.get('one_lot_success_rate_pct'))} |"
        )
    lines.append("")
    lines.append("该温度只用于融资强度和风险偏好校准，不直接替代个股基本面判断。")
    return "\n".join(lines) + "\n"


def ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def num(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.1f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=dt.date.today().isoformat(), help="Decision date in YYYY-MM-DD.")
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--window", type=int, default=20)
    parser.add_argument("--min-samples", type=int, default=8)
    parser.add_argument("--strong-threshold-pct", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", help="Output JSON explicitly. JSON is also the default.")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        as_of = dt.date.fromisoformat(args.as_of)
    except ValueError:
        raise SystemExit("--as-of must be YYYY-MM-DD") from None

    records, sources = fetch_recent_listed(
        as_of=as_of,
        max_pages=args.max_pages,
        timeout=args.timeout,
        retries=args.retries,
        window=args.window,
    )
    payload = build_payload(
        as_of=as_of,
        records=records,
        sources=sources,
        window=args.window,
        min_samples=args.min_samples,
        strong_threshold_pct=args.strong_threshold_pct,
    )
    if args.markdown:
        sys.stdout.write(render_markdown(payload))
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
