#!/usr/bin/env python3
"""BSE IPO cash subscription allotment calculator.

This script is deterministic and intentionally dependency-free. It does not
fetch market data; pass verified or scenario assumptions from announcements,
data pages, or community estimates.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable


DEFAULT_FUNDS_YUAN = [1_000_000, 3_000_000, 5_000_000, 8_000_000, 10_000_000]
DEFAULT_BOUNDARY_PRECISION_YUAN = 200_000


def lot_floor(shares: float) -> int:
    return max(0, int(math.floor(shares / 100.0)) * 100)


def lot_ceil(shares: float) -> int:
    if shares <= 0:
        return 0
    return int(math.ceil(shares / 100.0)) * 100


def yuan(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.2f}"


def shares_fmt(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}"


def probability_fmt(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value - round(value)) < 0.05:
        return f"{round(value):.0f}%"
    return f"{value:.1f}%"


@dataclass
class FundingRow:
    funds_yuan: float
    subscription_shares: int
    subscription_amount_yuan: float
    regular_shares: int
    possible_with_secondary_shares: int | None
    secondary_status: str


@dataclass
class Calculation:
    name: str | None
    price: float
    online_shares: int
    max_shares: int | None
    allotment_rate: float
    allotment_rate_pct: float
    freeze_funds_yuan: float | None
    regular_100_threshold_yuan: float
    regular_100_threshold_shares: int
    max_subscription_amount_yuan: float | None
    cap_below_100_regular_threshold: bool | None
    secondary_threshold_yuan: float | None
    rows: list[FundingRow]


@dataclass
class ScenarioInput:
    label: str
    freeze_funds_yuan: float
    probability_pct: float


@dataclass
class ScenarioCalculation:
    label: str
    probability_pct: float
    calculation: Calculation


@dataclass
class SecondaryBoundary:
    low_yuan: float
    mid_yuan: float
    high_yuan: float


@dataclass
class FundingBand:
    cash_range: str
    expected_result: str
    note: str


def regular_threshold_yuan(price: float, allotment_rate: float, lots: int) -> float:
    if lots <= 0:
        return 0.0
    return lot_ceil((lots * 100.0) / allotment_rate) * price


def calculate_row(
    *,
    cash: float,
    price: float,
    max_shares: int | None,
    allotment_rate: float,
    secondary_threshold_yuan: float | None,
) -> FundingRow:
    sub_shares = lot_floor(cash / price)
    if max_shares is not None:
        sub_shares = min(sub_shares, max_shares)
    sub_amount = sub_shares * price

    raw = sub_shares * allotment_rate
    regular = lot_floor(raw)
    fractional = max(0.0, raw - regular)

    possible_with_secondary: int | None = None
    if fractional > 1e-9:
        possible_with_secondary = regular + 100

    if fractional <= 1e-9:
        secondary_status = "无碎股尾差"
    elif secondary_threshold_yuan is None:
        secondary_status = "碎股候选，门槛未知"
    elif sub_amount >= secondary_threshold_yuan:
        secondary_status = "达到给定碎股门槛，可能+100股"
    else:
        secondary_status = "低于给定碎股门槛"

    return FundingRow(
        funds_yuan=float(cash),
        subscription_shares=sub_shares,
        subscription_amount_yuan=sub_amount,
        regular_shares=regular,
        possible_with_secondary_shares=possible_with_secondary,
        secondary_status=secondary_status,
    )


def calculate(
    *,
    name: str | None,
    price: float,
    online_shares: int,
    max_shares: int | None,
    funds: Iterable[float],
    freeze_funds_yuan: float | None,
    allotment_rate: float | None,
    secondary_threshold_yuan: float | None,
) -> Calculation:
    if price <= 0:
        raise ValueError("price must be positive")
    if online_shares <= 0:
        raise ValueError("online_shares must be positive")

    if allotment_rate is None:
        if freeze_funds_yuan is None or freeze_funds_yuan <= 0:
            raise ValueError("provide --scenario-yi, --freeze-funds-* or --allotment-rate-pct")
        allotment_rate = online_shares * price / freeze_funds_yuan
    if allotment_rate <= 0:
        raise ValueError("allotment_rate must be positive")

    threshold_shares = lot_ceil(100.0 / allotment_rate)
    threshold_yuan = threshold_shares * price

    max_amount = max_shares * price if max_shares is not None else None
    cap_below = max_amount < threshold_yuan if max_amount is not None else None

    rows = [
        calculate_row(
            cash=float(cash),
            price=price,
            max_shares=max_shares,
            allotment_rate=allotment_rate,
            secondary_threshold_yuan=secondary_threshold_yuan,
        )
        for cash in funds
    ]

    return Calculation(
        name=name,
        price=price,
        online_shares=online_shares,
        max_shares=max_shares,
        allotment_rate=allotment_rate,
        allotment_rate_pct=allotment_rate * 100,
        freeze_funds_yuan=freeze_funds_yuan,
        regular_100_threshold_yuan=threshold_yuan,
        regular_100_threshold_shares=threshold_shares,
        max_subscription_amount_yuan=max_amount,
        cap_below_100_regular_threshold=cap_below,
        secondary_threshold_yuan=secondary_threshold_yuan,
        rows=rows,
    )


def parse_scenario_yi(entries: list[str]) -> list[ScenarioInput]:
    scenarios: list[ScenarioInput] = []
    for entry in entries:
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) != 3:
            raise ValueError("scenario format must be LABEL:FUNDS_YI:PROBABILITY_PCT")
        label, funds_yi_text, probability_text = parts
        if not label:
            raise ValueError("scenario label cannot be empty")
        freeze_funds_yuan = float(funds_yi_text) * 100_000_000
        probability_pct = float(probability_text)
        if freeze_funds_yuan <= 0:
            raise ValueError("scenario funds must be positive")
        if probability_pct < 0:
            raise ValueError("scenario probability cannot be negative")
        scenarios.append(ScenarioInput(label, freeze_funds_yuan, probability_pct))

    total_probability = sum(scenario.probability_pct for scenario in scenarios)
    if total_probability <= 0:
        raise ValueError("scenario probabilities must sum to a positive number")

    return [
        ScenarioInput(
            scenario.label,
            scenario.freeze_funds_yuan,
            scenario.probability_pct * 100.0 / total_probability,
        )
        for scenario in scenarios
    ]


def parse_secondary_boundary(values: list[float] | None) -> SecondaryBoundary | None:
    if values is None:
        return None
    if len(values) != 3:
        raise ValueError("secondary boundary format must be LOW MID HIGH")
    low, mid, high = sorted(float(value) for value in values)
    if low <= 0:
        raise ValueError("secondary boundary values must be positive")
    return SecondaryBoundary(low, mid, high)


def secondary_candidate(row: FundingRow, secondary_threshold_yuan: float | None) -> bool:
    if row.possible_with_secondary_shares is None:
        return False
    if secondary_threshold_yuan is None:
        return True
    return row.subscription_amount_yuan >= secondary_threshold_yuan


def outcome_label(row: FundingRow, secondary_threshold_yuan: float | None) -> str:
    if row.regular_shares > 0:
        label = f"{shares_fmt(row.regular_shares)}股正股"
        if secondary_candidate(row, secondary_threshold_yuan):
            label += "，另有碎股机会"
        return label

    if secondary_candidate(row, secondary_threshold_yuan):
        if secondary_threshold_yuan is None:
            return "碎股候选"
        return "博100股碎股"

    return "预计0股"


def aggregate_outcomes(scenarios: list[ScenarioCalculation], cash: float) -> tuple[str, str]:
    distribution: dict[str, float] = defaultdict(float)
    regular_probability = 0.0
    regular_values: list[int] = []
    has_secondary_candidate = False

    for scenario in scenarios:
        calc = scenario.calculation
        row = calculate_row(
            cash=cash,
            price=calc.price,
            max_shares=calc.max_shares,
            allotment_rate=calc.allotment_rate,
            secondary_threshold_yuan=calc.secondary_threshold_yuan,
        )
        distribution[outcome_label(row, calc.secondary_threshold_yuan)] += scenario.probability_pct
        regular_values.append(row.regular_shares)
        if secondary_candidate(row, calc.secondary_threshold_yuan):
            has_secondary_candidate = True
        if row.regular_shares >= 100:
            regular_probability += scenario.probability_pct

    min_regular = min(regular_values) if regular_values else 0
    max_regular = max(regular_values) if regular_values else 0
    if max_regular >= 100:
        if min_regular == max_regular:
            expected_result = f"{shares_fmt(max_regular)}股正股"
            if has_secondary_candidate:
                expected_result += "，另有碎股机会"
            return expected_result, band_note(expected_result, regular_probability)
        if min_regular >= 100:
            expected_result = f"{shares_fmt(min_regular)}-{shares_fmt(max_regular)}股正股"
            if has_secondary_candidate:
                expected_result += "，另有碎股机会"
            return expected_result, "最终申购金额影响正股档位"
        return f"0-{shares_fmt(max_regular)}股正股边界", "接近正股门槛，需看最终申购金额"

    ordered = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    if len(ordered) == 1:
        expected_result = ordered[0][0]
    elif any("碎股" in label for label, _ in ordered):
        expected_result = "边界博碎股"
    else:
        expected_result = ordered[0][0]

    return expected_result, band_note(expected_result, regular_probability)


def unique_sorted_points(points: Iterable[float]) -> list[float]:
    sorted_points = sorted(round(point, 2) for point in points if point >= 0)
    unique: list[float] = []
    for point in sorted_points:
        if not unique or abs(point - unique[-1]) >= 1.0:
            unique.append(point)
    return unique


def cash_range_label(low: float, high: float) -> str:
    if low <= 0:
        return f"<{yuan(high)}"
    return f"{yuan(low)}-{yuan(high)}"


def band_note(expected_result: str, regular_probability: float) -> str:
    if regular_probability >= 99.5:
        return "各情景均达到正股门槛"
    if regular_probability > 0:
        return "是否有正股取决于最终网上申购金额"
    if "博" in expected_result and "碎股" in expected_result:
        return "主要看碎股二次分配，不保证"
    if "碎股候选" in expected_result:
        return "碎股门槛需另行估计"
    return "低于正股/碎股参考门槛"


def boundary_outcome(cash: float, boundary: SecondaryBoundary) -> tuple[str, str]:
    if cash < boundary.low_yuan:
        return "预计0股", "低于碎股低位参考"
    if cash < boundary.mid_yuan:
        return "低位试探碎股", "只覆盖边界下沿，命中依赖资金分布"
    if cash < boundary.high_yuan:
        return "边界博碎股", "接近主流门槛，仍看资金分布和申购时间"
    return "博100股碎股", "相对更有效，但不保证"


def can_have_regular_share(scenarios: list[ScenarioCalculation], cash: float) -> bool:
    return any(cash >= scenario.calculation.regular_100_threshold_yuan for scenario in scenarios)


def max_regular_lots_for_reference(calc: Calculation, max_reference: float) -> int:
    row = calculate_row(
        cash=max_reference,
        price=calc.price,
        max_shares=calc.max_shares,
        allotment_rate=calc.allotment_rate,
        secondary_threshold_yuan=calc.secondary_threshold_yuan,
    )
    return max(0, row.regular_shares // 100)


def top_band(
    *,
    max_amount: float | None,
    secondary_boundary: SecondaryBoundary | None,
    all_caps_below_regular: bool,
) -> FundingBand | None:
    if max_amount is None or secondary_boundary is None or not all_caps_below_regular:
        return None
    if max_amount >= secondary_boundary.low_yuan:
        return None

    return FundingBand(
        cash_range=f"=顶格{yuan(max_amount)}",
        expected_result="顶格博碎股",
        note="低于推算碎股低位，只能拼时间/排序",
    )


def exact_top_regular_band(
    *,
    max_amount: float | None,
    scenarios: list[ScenarioCalculation],
) -> FundingBand | None:
    if max_amount is None:
        return None

    top_result, top_note = aggregate_outcomes(scenarios, max_amount)
    if "正股" not in top_result:
        return None

    calc0 = scenarios[0].calculation
    if calc0.max_shares is None or calc0.max_shares < 100:
        return None

    previous_top_cash = (calc0.max_shares - 100) * calc0.price
    previous_result, _ = aggregate_outcomes(scenarios, max(0.0, previous_top_cash))
    if previous_result == top_result:
        return None

    note = "顶格刚好达到该正股档"
    if top_note != "各情景均达到正股门槛":
        note = top_note
    return FundingBand(
        cash_range=f"=顶格{yuan(max_amount)}",
        expected_result=top_result,
        note=note,
    )


def compact_secondary_funding_bands(
    *,
    max_amount: float,
    secondary_boundary: SecondaryBoundary,
    precision_yuan: float,
) -> list[FundingBand]:
    if precision_yuan <= 0:
        precision_yuan = DEFAULT_BOUNDARY_PRECISION_YUAN

    if max_amount < secondary_boundary.low_yuan:
        return [
            FundingBand(
                cash_range=f"=顶格{yuan(max_amount)}",
                expected_result="顶格博碎股",
                note="低于推算碎股低位，只能拼时间/排序",
            )
        ]

    half_width = precision_yuan / 2.0
    if secondary_boundary.high_yuan - secondary_boundary.low_yuan <= precision_yuan:
        main_low = secondary_boundary.low_yuan
        main_high = secondary_boundary.high_yuan
    else:
        main_low = max(secondary_boundary.low_yuan, secondary_boundary.mid_yuan - half_width)
        main_high = min(secondary_boundary.high_yuan, secondary_boundary.mid_yuan + half_width)

    main_low = max(0.0, min(main_low, max_amount))
    main_high = max(main_low, min(main_high, max_amount))

    bands: list[FundingBand] = []
    if main_low > 0:
        bands.append(
            FundingBand(
                cash_range=f"<{yuan(main_low)}",
                expected_result="预计0股/低位试探",
                note="低于主边界，不作为目标资金",
            )
        )
    if main_high > main_low:
        bands.append(
            FundingBand(
                cash_range=cash_range_label(main_low, main_high),
                expected_result="边界博碎股",
                note=f"主参考区间，约{yuan(main_high - main_low)}宽",
            )
        )
    if main_high < max_amount:
        bands.append(
            FundingBand(
                cash_range=cash_range_label(main_high, max_amount),
                expected_result="博100股碎股",
                note="高于主边界，仍看碎股排序",
            )
        )
    return bands


def build_funding_bands(
    scenarios: list[ScenarioCalculation],
    funds: Iterable[float],
    secondary_boundary: SecondaryBoundary | None,
    *,
    boundary_precision_yuan: float = DEFAULT_BOUNDARY_PRECISION_YUAN,
) -> list[FundingBand]:
    calc0 = scenarios[0].calculation
    funds_list = [float(fund) for fund in funds]
    max_amount = calc0.max_subscription_amount_yuan
    secondary_threshold = calc0.secondary_threshold_yuan

    max_reference = max(funds_list or DEFAULT_FUNDS_YUAN)
    if max_amount is not None:
        max_reference = max_amount
    else:
        for scenario in scenarios:
            max_reference = max(max_reference, scenario.calculation.regular_100_threshold_yuan)
    if secondary_threshold is not None and max_amount is None:
        max_reference = max(max_reference, secondary_threshold)
    if max_reference <= 0:
        return []

    all_caps_below_regular = all(
        scenario.calculation.cap_below_100_regular_threshold is True for scenario in scenarios
    )
    if max_amount is not None and secondary_boundary is not None and all_caps_below_regular:
        return compact_secondary_funding_bands(
            max_amount=max_amount,
            secondary_boundary=secondary_boundary,
            precision_yuan=boundary_precision_yuan,
        )

    points: list[float] = [0.0, max_reference]
    if secondary_boundary is not None:
        for boundary_value in (
            secondary_boundary.low_yuan,
            secondary_boundary.mid_yuan,
            secondary_boundary.high_yuan,
        ):
            if 0 < boundary_value < max_reference:
                points.append(boundary_value)
    if secondary_threshold is not None and 0 < secondary_threshold < max_reference:
        points.append(secondary_threshold)

    for scenario in scenarios:
        calc = scenario.calculation
        max_regular_lots = max_regular_lots_for_reference(calc, max_reference)
        for lots in range(1, max_regular_lots + 1):
            threshold = regular_threshold_yuan(calc.price, calc.allotment_rate, lots)
            if 0 < threshold < max_reference:
                points.append(threshold)

    points = unique_sorted_points(points)
    bands: list[FundingBand] = []

    for low, high in zip(points, points[1:]):
        if high <= low:
            continue
        sample_cash = (low + high) / 2.0
        if secondary_boundary is not None and not can_have_regular_share(scenarios, sample_cash):
            expected_result, note = boundary_outcome(sample_cash, secondary_boundary)
        else:
            expected_result, note = aggregate_outcomes(scenarios, sample_cash)
        if max_amount is not None and high >= max_amount and all_caps_below_regular:
            if "碎股" in expected_result:
                note = "仍无正股，主要看碎股排序"
        bands.append(
            FundingBand(
                cash_range=cash_range_label(low, high),
                expected_result=expected_result,
                note=note,
            )
        )

    top = top_band(
        max_amount=max_amount,
        secondary_boundary=secondary_boundary,
        all_caps_below_regular=all_caps_below_regular,
    )
    if top is not None:
        bands.append(top)
    else:
        exact_top = exact_top_regular_band(
            max_amount=max_amount,
            scenarios=scenarios,
        )
        if exact_top is not None:
            bands.append(exact_top)

    return bands


def cap_judgement(calc: Calculation) -> str:
    if calc.max_subscription_amount_yuan is None:
        return "-"
    if calc.cap_below_100_regular_threshold:
        return "顶格不稳正股"
    return "顶格覆盖100股正股门槛"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BSE IPO allotment calculator")
    parser.add_argument("--name", help="IPO name", default=None)
    parser.add_argument("--price", type=float, required=True, help="issue price, yuan/share")

    shares = parser.add_mutually_exclusive_group(required=True)
    shares.add_argument("--online-shares", type=float, help="online shares, shares")
    shares.add_argument("--online-shares-wan", type=float, help="online shares, 10k shares")

    cap = parser.add_mutually_exclusive_group()
    cap.add_argument("--max-shares", type=float, help="subscription cap, shares")
    cap.add_argument("--max-shares-wan", type=float, help="subscription cap, 10k shares")

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--freeze-funds-yuan", type=float, help="actual/expected online subscription amount, yuan")
    source.add_argument("--freeze-funds-yi", type=float, help="actual/expected online subscription amount, 100m yuan")
    source.add_argument("--allotment-rate-pct", type=float, help="online allotment rate, percent")

    parser.add_argument(
        "--scenario-yi",
        nargs="+",
        metavar="LABEL:FUNDS_YI:PROBABILITY_PCT",
        help="scenario assumptions, for example 保守:7000:25 基准:8500:45 拥挤:10000:30",
    )
    parser.add_argument(
        "--funds-yuan",
        type=float,
        nargs="+",
        default=DEFAULT_FUNDS_YUAN,
        help="cash amounts to test, yuan; defaults to 100万/300万/500万/800万/1000万",
    )
    secondary = parser.add_mutually_exclusive_group()
    secondary.add_argument("--secondary-threshold-yuan", type=float, default=None, help="optional secondary-allocation threshold, yuan")
    secondary.add_argument(
        "--secondary-boundary-yuan",
        type=float,
        nargs=3,
        metavar=("LOW", "MID", "HIGH"),
        help="internal secondary-allocation boundary estimates; output is compressed into simple funding bands",
    )
    parser.add_argument(
        "--boundary-precision-yuan",
        type=float,
        default=DEFAULT_BOUNDARY_PRECISION_YUAN,
        help="preferred width for the main secondary-allocation boundary band; default 200000",
    )
    parser.add_argument("--json", action="store_true", help="output JSON")

    args = parser.parse_args()
    has_single_source = any(
        value is not None
        for value in (args.freeze_funds_yuan, args.freeze_funds_yi, args.allotment_rate_pct)
    )
    if args.scenario_yi and has_single_source:
        parser.error("--scenario-yi cannot be combined with --freeze-funds-* or --allotment-rate-pct")
    if not args.scenario_yi and not has_single_source:
        parser.error("provide --scenario-yi, --freeze-funds-* or --allotment-rate-pct")
    return args


def main() -> int:
    args = parse_args()
    try:
        secondary_boundary = parse_secondary_boundary(args.secondary_boundary_yuan)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}")
    secondary_threshold_yuan = args.secondary_threshold_yuan
    if secondary_boundary is not None:
        secondary_threshold_yuan = secondary_boundary.high_yuan

    online_shares = int(round(args.online_shares if args.online_shares is not None else args.online_shares_wan * 10_000))
    max_shares = None
    if args.max_shares is not None:
        max_shares = int(round(args.max_shares))
    elif args.max_shares_wan is not None:
        max_shares = int(round(args.max_shares_wan * 10_000))

    scenarios: list[ScenarioCalculation] = []

    if args.scenario_yi:
        try:
            scenario_inputs = parse_scenario_yi(args.scenario_yi)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}")

        for scenario_input in scenario_inputs:
            calc = calculate(
                name=args.name,
                price=args.price,
                online_shares=online_shares,
                max_shares=max_shares,
                funds=args.funds_yuan,
                freeze_funds_yuan=scenario_input.freeze_funds_yuan,
                allotment_rate=None,
                secondary_threshold_yuan=secondary_threshold_yuan,
            )
            scenarios.append(
                ScenarioCalculation(
                    label=scenario_input.label,
                    probability_pct=scenario_input.probability_pct,
                    calculation=calc,
                )
            )
    else:
        freeze = None
        if args.freeze_funds_yuan is not None:
            freeze = args.freeze_funds_yuan
        elif args.freeze_funds_yi is not None:
            freeze = args.freeze_funds_yi * 100_000_000

        rate = args.allotment_rate_pct / 100 if args.allotment_rate_pct is not None else None
        calc = calculate(
            name=args.name,
            price=args.price,
            online_shares=online_shares,
            max_shares=max_shares,
            funds=args.funds_yuan,
            freeze_funds_yuan=freeze,
            allotment_rate=rate,
            secondary_threshold_yuan=secondary_threshold_yuan,
        )
        scenarios.append(ScenarioCalculation(label="给定", probability_pct=100.0, calculation=calc))

    if args.json:
        print(json.dumps({"scenarios": [asdict(scenario) for scenario in scenarios]}, ensure_ascii=False, indent=2))
        return 0

    calc0 = scenarios[0].calculation
    if calc0.name:
        print(f"# {calc0.name}")
    print(f"发行价: {calc0.price:.4f} 元")
    print(f"网上发行股数: {shares_fmt(calc0.online_shares)} 股")
    if calc0.max_subscription_amount_yuan is not None:
        print(f"顶格申购金额: {yuan(calc0.max_subscription_amount_yuan)} ({shares_fmt(calc0.max_shares)} 股)")
    if calc0.secondary_threshold_yuan is not None:
        if secondary_boundary is not None:
            print(
                f"碎股边界参考: 低位{yuan(secondary_boundary.low_yuan)} / "
                f"中位{yuan(secondary_boundary.mid_yuan)} / "
                f"高位{yuan(secondary_boundary.high_yuan)}"
            )
        else:
            print(f"给定碎股门槛: {yuan(calc0.secondary_threshold_yuan)}")

    print()
    print("## 网上申购金额情景概率")
    print("| 情景 | 概率 | 预计/实际网上申购金额 | 配售比例 | 100股正股门槛 | 顶格判断 |")
    print("|---|---:|---:|---:|---:|---|")
    for scenario in scenarios:
        calc = scenario.calculation
        print(
            f"| {scenario.label} | {probability_fmt(scenario.probability_pct)} | "
            f"{yuan(calc.freeze_funds_yuan)} | {calc.allotment_rate_pct:.6f}% | "
            f"{yuan(calc.regular_100_threshold_yuan)} | {cap_judgement(calc)} |"
        )

    print()
    print("## 资金区间参考")
    print("| 资金区间 | 预计结果 | 说明 |")
    print("|---:|---|---|")
    for band in build_funding_bands(
        scenarios,
        args.funds_yuan,
        secondary_boundary,
        boundary_precision_yuan=args.boundary_precision_yuan,
    ):
        print(
            f"| {band.cash_range} | {band.expected_result} | {band.note} |"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
