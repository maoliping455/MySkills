#!/usr/bin/env python3
"""Calculate rough Hong Kong IPO subscription return and financing break-even.

This utility is intentionally stateless. It does not fetch market data; pass in
the offer/entry value, first-day move, allotment probability, and financing
assumptions that are available for the review or scenario being analyzed.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


DEFAULT_CASH_HKD = 550_000.0
DEFAULT_MARGIN_MULTIPLE = 10.0
DEFAULT_FINANCING_DAYS = 7


def money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"HKD {value:,.0f}"


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%"


def financing_interest(
    *,
    application_amount_hkd: float,
    cash_hkd: float,
    financing_rate_pct: float | None,
    financing_days: int,
) -> float:
    if financing_rate_pct is None or financing_days <= 0:
        return 0.0
    borrowed = max(0.0, application_amount_hkd - cash_hkd)
    return borrowed * financing_rate_pct / 100.0 * financing_days / 365.0


def probability_from_pct(one_lot_success_rate_pct: float | None) -> float | None:
    if one_lot_success_rate_pct is None:
        return None
    return max(0.0, min(1.0, one_lot_success_rate_pct / 100.0))


def calculate_return_metrics(
    *,
    entry_fee_hkd: float,
    first_day_pct: float | None = None,
    one_lot_success_rate_pct: float | None = None,
    cash_hkd: float = DEFAULT_CASH_HKD,
    margin_multiple: float = DEFAULT_MARGIN_MULTIPLE,
    application_amount_hkd: float | None = None,
    financing_rate_pct: float | None = None,
    financing_days: int = DEFAULT_FINANCING_DAYS,
    fees_hkd: float = 0.0,
) -> dict[str, Any]:
    if entry_fee_hkd <= 0:
        raise ValueError("entry_fee_hkd must be positive")
    if cash_hkd < 0:
        raise ValueError("cash_hkd cannot be negative")
    if margin_multiple <= 0:
        raise ValueError("margin_multiple must be positive")
    if application_amount_hkd is None:
        application_amount_hkd = cash_hkd * margin_multiple
    if application_amount_hkd < 0:
        raise ValueError("application_amount_hkd cannot be negative")
    if fees_hkd < 0:
        raise ValueError("fees_hkd cannot be negative")

    allotment_probability = probability_from_pct(one_lot_success_rate_pct)
    interest = financing_interest(
        application_amount_hkd=application_amount_hkd,
        cash_hkd=cash_hkd,
        financing_rate_pct=financing_rate_pct,
        financing_days=financing_days,
    )
    total_cost = interest + fees_hkd

    gross_pnl_if_one_lot = None
    expected_one_lot_gross_pnl = None
    expected_one_lot_net_pnl = None
    realized_one_lot_net_pnl = None
    if first_day_pct is not None:
        gross_pnl_if_one_lot = entry_fee_hkd * first_day_pct / 100.0
        realized_one_lot_net_pnl = gross_pnl_if_one_lot - total_cost
        if allotment_probability is not None:
            expected_one_lot_gross_pnl = gross_pnl_if_one_lot * allotment_probability
            expected_one_lot_net_pnl = expected_one_lot_gross_pnl - total_cost

    break_even_if_one_lot_pct = total_cost / entry_fee_hkd * 100.0 if total_cost else 0.0
    expected_break_even_first_day_pct = None
    if allotment_probability and allotment_probability > 0:
        expected_break_even_first_day_pct = total_cost / (entry_fee_hkd * allotment_probability) * 100.0

    return {
        "assumptions": {
            "cash_hkd": cash_hkd,
            "margin_multiple": margin_multiple,
            "application_amount_hkd": application_amount_hkd,
            "entry_fee_hkd": entry_fee_hkd,
            "first_day_pct": first_day_pct,
            "one_lot_success_rate_pct": one_lot_success_rate_pct,
            "allotment_probability": allotment_probability,
            "financing_rate_pct": financing_rate_pct,
            "financing_days": financing_days,
            "fees_hkd": fees_hkd,
        },
        "costs": {
            "borrowed_amount_hkd": max(0.0, application_amount_hkd - cash_hkd),
            "financing_interest_hkd": interest,
            "fees_hkd": fees_hkd,
            "total_cost_hkd": total_cost,
        },
        "returns": {
            "gross_pnl_if_one_lot_hkd": gross_pnl_if_one_lot,
            "expected_one_lot_gross_pnl_hkd": expected_one_lot_gross_pnl,
            "realized_one_lot_net_pnl_hkd": realized_one_lot_net_pnl,
            "expected_one_lot_net_pnl_hkd": expected_one_lot_net_pnl,
            "break_even_if_one_lot_first_day_pct": break_even_if_one_lot_pct,
            "expected_break_even_first_day_pct": expected_break_even_first_day_pct,
        },
        "notes": [
            "一手期望收益使用一手中签率近似，不等同于甲组/乙组实际获配股数。",
            "融资利息按指定申购金额估算；真实成本取决于券商额度、计息天数、手续费和退款时间。",
            "该结果用于复盘或申购前情景分析，不构成投资建议。",
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    assumptions = payload["assumptions"]
    costs = payload["costs"]
    returns = payload["returns"]
    lines = [
        "# 港股打新申购收益测算",
        "",
        "| 项目 | 数值 |",
        "|---|---:|",
        f"| 现金 | {money(assumptions['cash_hkd'])} |",
        f"| 融资倍数 | {assumptions['margin_multiple']:.2f}x |",
        f"| 申购金额 | {money(assumptions['application_amount_hkd'])} |",
        f"| 一手入场费 | {money(assumptions['entry_fee_hkd'])} |",
        f"| 首日涨跌幅 | {pct(assumptions['first_day_pct'])} |",
        f"| 一手中签率 | {pct(assumptions['one_lot_success_rate_pct'])} |",
        f"| 融资年化利率 | {pct(assumptions['financing_rate_pct'])} |",
        f"| 计息天数 | {assumptions['financing_days']} |",
        f"| 融资利息 | {money(costs['financing_interest_hkd'])} |",
        f"| 手续费/其他成本 | {money(costs['fees_hkd'])} |",
        f"| 总成本 | {money(costs['total_cost_hkd'])} |",
        f"| 中一手毛利 | {money(returns['gross_pnl_if_one_lot_hkd'])} |",
        f"| 一手期望毛利 | {money(returns['expected_one_lot_gross_pnl_hkd'])} |",
        f"| 中一手扣成本收益 | {money(returns['realized_one_lot_net_pnl_hkd'])} |",
        f"| 一手期望扣成本收益 | {money(returns['expected_one_lot_net_pnl_hkd'])} |",
        f"| 中一手打平所需首日涨幅 | {pct(returns['break_even_if_one_lot_first_day_pct'])} |",
        f"| 按一手中签率打平所需首日涨幅 | {pct(returns['expected_break_even_first_day_pct'])} |",
        "",
        "## 备注",
    ]
    lines.extend(f"- {note}" for note in payload["notes"])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry-fee-hkd", "--offer-value-hkd", dest="entry_fee_hkd", type=float, required=True)
    parser.add_argument("--first-day-pct", type=float)
    parser.add_argument("--one-lot-success-rate-pct", type=float)
    parser.add_argument("--cash-hkd", type=float, default=DEFAULT_CASH_HKD)
    parser.add_argument("--margin-multiple", type=float, default=DEFAULT_MARGIN_MULTIPLE)
    parser.add_argument("--application-amount-hkd", type=float)
    parser.add_argument("--margin-rate-pct", "--financing-rate-pct", dest="financing_rate_pct", type=float)
    parser.add_argument("--financing-days", type=int, default=DEFAULT_FINANCING_DAYS)
    parser.add_argument("--fees-hkd", type=float, default=0.0)
    parser.add_argument("--markdown", action="store_true", help="Output Markdown instead of JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = calculate_return_metrics(
        entry_fee_hkd=args.entry_fee_hkd,
        first_day_pct=args.first_day_pct,
        one_lot_success_rate_pct=args.one_lot_success_rate_pct,
        cash_hkd=args.cash_hkd,
        margin_multiple=args.margin_multiple,
        application_amount_hkd=args.application_amount_hkd,
        financing_rate_pct=args.financing_rate_pct,
        financing_days=args.financing_days,
        fees_hkd=args.fees_hkd,
    )
    if args.markdown:
        sys.stdout.write(render_markdown(payload))
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
