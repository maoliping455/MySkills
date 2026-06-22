#!/usr/bin/env python3
"""Normalize lightweight actual HK IPO subscription results.

The script is stateless. It accepts a short text note such as
"科拓股份 02272 申购55万 中签1000股 招股价4.5 卖出5.2 融资息300 手续费50"
or explicit command-line values, then emits JSON or Markdown for review.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)(\d{4,5})(?:\.HK)?(?!\d)", value, flags=re.I)
    return match.group(1).zfill(5) if match else None


def display_code(code: str | None) -> str | None:
    return f"{code}.HK" if code else None


def parse_number(value: str | None) -> float | None:
    text = clean(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    suffix = text[match.end() : match.end() + 1]
    if suffix == "亿":
        number *= 100_000_000
    elif suffix == "萬" or suffix == "万":
        number *= 10_000
    return number


def parse_money_after(text: str, keywords: list[str]) -> float | None:
    for keyword in keywords:
        match = re.search(rf"{keyword}[^\d\-]*(\-?\d+(?:,\d{{3}})*(?:\.\d+)?|\-?\d+(?:\.\d+)?)([万萬亿]?)", text, flags=re.I)
        if match:
            return parse_number("".join(match.groups()))
    return None


def parse_pct_after(text: str, keywords: list[str]) -> float | None:
    for keyword in keywords:
        match = re.search(rf"{keyword}[^\d\-+]*(\-?\+?\d+(?:\.\d+)?)\s*%", text, flags=re.I)
        if match:
            return float(match.group(1).replace("+", ""))
    return None


def parse_count_after(text: str, keywords: list[str], unit: str) -> int | None:
    for keyword in keywords:
        match = re.search(rf"{keyword}[^\d]*(\d+(?:,\d{{3}})*)\s*{unit}", text, flags=re.I)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def infer_stock_name(text: str, code: str | None) -> str | None:
    cleaned = re.sub(r"(?<!\d)\d{4,5}(?:\.HK)?(?!\d)", " ", text, flags=re.I)
    cleaned = re.sub(r"\d+(?:,\d{3})*(?:\.\d+)?\s*(股|手|万|萬|亿|元|港币|港元|HKD|%)", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(申购|认购|申请|中签|获配|配发|招股价|发行价|卖出|卖价|暗盘|首日|融资息|融资成本|手续费|佣金|成本|HKD|\d|\.|%|\+|\-)", " ", cleaned, flags=re.I)
    parts = [part for part in re.split(r"\s+", cleaned) if re.search(r"[\u4e00-\u9fff]", part)]
    return parts[0] if parts else None


def normalize_actual_subscription(
    *,
    text: str = "",
    stock_name: str | None = None,
    code: str | None = None,
    applied_amount_hkd: float | None = None,
    applied_lots: int | None = None,
    allotted_shares: int | None = None,
    allotted_lots: int | None = None,
    lot_size: int | None = None,
    offer_price_hkd: float | None = None,
    sell_price_hkd: float | None = None,
    first_day_pct: float | None = None,
    financing_interest_hkd: float | None = None,
    fees_hkd: float | None = None,
    cash_hkd: float | None = None,
) -> dict[str, Any]:
    text = clean(text)
    code = canonical_code(code) or canonical_code(text)
    stock_name = clean(stock_name) or infer_stock_name(text, code)

    applied_amount_hkd = first_present_number(applied_amount_hkd, parse_money_after(text, ["申购", "认购", "申请", "申购金额", "认购金额"]))
    applied_lots = first_present_int(applied_lots, parse_count_after(text, ["申购", "认购", "申请"], "手"))
    allotted_shares = first_present_int(allotted_shares, parse_count_after(text, ["中签", "获配", "配发", "分配"], "股"))
    allotted_lots = first_present_int(allotted_lots, parse_count_after(text, ["中签", "获配", "配发", "分配", "中"], "手"))
    lot_size = first_present_int(lot_size, parse_count_after(text, ["每手", "一手"], "股"))
    offer_price_hkd = first_present_number(offer_price_hkd, parse_money_after(text, ["招股价", "发行价", "定价", "offer"]))
    sell_price_hkd = first_present_number(sell_price_hkd, parse_money_after(text, ["卖出", "卖价", "暗盘卖", "首日卖"]))
    first_day_pct = first_present_number(first_day_pct, parse_pct_after(text, ["首日", "暗盘", "涨跌", "涨幅", "跌幅"]))
    financing_interest_hkd = first_present_number(financing_interest_hkd, parse_money_after(text, ["融资息", "融资利息", "利息", "融资成本"]))
    fees_hkd = first_present_number(fees_hkd, parse_money_after(text, ["手续费", "佣金", "其他成本", "成本"]))

    if allotted_shares is None and allotted_lots is not None and lot_size:
        allotted_shares = allotted_lots * lot_size
    if allotted_lots is None and allotted_shares is not None and lot_size:
        allotted_lots = allotted_shares // lot_size if allotted_shares % lot_size == 0 else None
    if applied_amount_hkd is None and applied_lots is not None and lot_size and offer_price_hkd is not None:
        applied_amount_hkd = applied_lots * lot_size * offer_price_hkd

    financing_interest_hkd = financing_interest_hkd or 0.0
    fees_hkd = fees_hkd or 0.0
    total_cost_hkd = financing_interest_hkd + fees_hkd
    gross_pnl_hkd = None
    if allotted_shares is not None and offer_price_hkd is not None:
        if sell_price_hkd is not None:
            gross_pnl_hkd = allotted_shares * (sell_price_hkd - offer_price_hkd)
        elif first_day_pct is not None:
            gross_pnl_hkd = allotted_shares * offer_price_hkd * first_day_pct / 100.0
    net_pnl_hkd = gross_pnl_hkd - total_cost_hkd if gross_pnl_hkd is not None else None

    missing = []
    for key, label, value in [
        ("stock", "股票名称或代码", stock_name or code),
        ("offer_price_hkd", "招股价/定价", offer_price_hkd),
        ("allotted_shares", "中签股数或手数", allotted_shares),
        ("sell_or_move", "卖出价或暗盘/首日涨跌幅", sell_price_hkd if sell_price_hkd is not None else first_day_pct),
    ]:
        if value in (None, ""):
            missing.append({"field": key, "label": label})

    return {
        "stock_name": stock_name,
        "code": display_code(code),
        "input_text": text,
        "actual_subscription": {
            "applied_amount_hkd": applied_amount_hkd,
            "applied_lots": applied_lots,
            "allotted_shares": allotted_shares,
            "allotted_lots": allotted_lots,
            "lot_size": lot_size,
            "offer_price_hkd": offer_price_hkd,
            "sell_price_hkd": sell_price_hkd,
            "first_day_pct": first_day_pct,
            "financing_interest_hkd": financing_interest_hkd,
            "fees_hkd": fees_hkd,
            "cash_hkd": cash_hkd,
        },
        "returns": {
            "gross_trading_pnl_hkd": gross_pnl_hkd,
            "total_cost_hkd": total_cost_hkd,
            "net_pnl_hkd": net_pnl_hkd,
            "return_on_applied_amount_pct": net_pnl_hkd / applied_amount_hkd * 100.0 if net_pnl_hkd is not None and applied_amount_hkd else None,
            "return_on_cash_pct": net_pnl_hkd / cash_hkd * 100.0 if net_pnl_hkd is not None and cash_hkd else None,
        },
        "missing": missing,
        "notes": [
            "该归一化结果只基于用户输入，不联网核对配售结果或成交价。",
            "若未提供卖出价或暗盘/首日涨跌幅，只归一化申购和中签字段，不计算实际收益。",
        ],
    }


def first_present_number(*values: float | int | None) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
    return None


def first_present_int(*values: int | None) -> int | None:
    for value in values:
        if isinstance(value, int):
            return value
    return None


def money(value: float | int | None) -> str:
    if value is None:
        return "待核实"
    return f"HKD {float(value):,.0f}"


def price(value: float | int | None) -> str:
    if value is None:
        return "待核实"
    text = f"{float(value):,.3f}".rstrip("0").rstrip(".")
    return f"HKD {text}"


def pct(value: float | int | None) -> str:
    if value is None:
        return "待核实"
    return f"{float(value):+.2f}%"


def render_markdown(payload: dict[str, Any]) -> str:
    actual = payload["actual_subscription"]
    returns = payload["returns"]
    title = payload.get("stock_name") or payload.get("code") or "未命名新股"
    if payload.get("code") and payload.get("stock_name"):
        title = f"{payload['stock_name']}（{payload['code']}）"
    lines = [
        f"# 实际申购复盘 - {title}",
        "",
        "| 项目 | 数值 |",
        "|---|---:|",
        f"| 申购金额 | {money(actual.get('applied_amount_hkd'))} |",
        f"| 申购手数 | {actual.get('applied_lots') if actual.get('applied_lots') is not None else '待核实'} |",
        f"| 中签股数 | {actual.get('allotted_shares') if actual.get('allotted_shares') is not None else '待核实'} |",
        f"| 中签手数 | {actual.get('allotted_lots') if actual.get('allotted_lots') is not None else '待核实'} |",
        f"| 每手股数 | {actual.get('lot_size') if actual.get('lot_size') is not None else '待核实'} |",
        f"| 招股价/定价 | {price(actual.get('offer_price_hkd'))} |",
        f"| 卖出价 | {price(actual.get('sell_price_hkd'))} |",
        f"| 暗盘/首日涨跌幅 | {pct(actual.get('first_day_pct'))} |",
        f"| 融资利息 | {money(actual.get('financing_interest_hkd'))} |",
        f"| 手续费/其他成本 | {money(actual.get('fees_hkd'))} |",
        f"| 交易毛利 | {money(returns.get('gross_trading_pnl_hkd'))} |",
        f"| 扣成本收益 | {money(returns.get('net_pnl_hkd'))} |",
        f"| 申购金额收益率 | {pct(returns.get('return_on_applied_amount_pct'))} |",
        f"| 现金收益率 | {pct(returns.get('return_on_cash_pct'))} |",
    ]
    if payload["missing"]:
        lines.extend(["", "## 仍需补充"])
        lines.extend(f"- {item['label']}" for item in payload["missing"])
    lines.extend(["", "## 备注"])
    lines.extend(f"- {note}" for note in payload["notes"])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="Raw actual subscription note.")
    parser.add_argument("--input-file", help="Text file containing actual subscription note.")
    parser.add_argument("--stock-name")
    parser.add_argument("--code")
    parser.add_argument("--applied-amount-hkd", type=float)
    parser.add_argument("--applied-lots", type=int)
    parser.add_argument("--allotted-shares", type=int)
    parser.add_argument("--allotted-lots", type=int)
    parser.add_argument("--lot-size", type=int)
    parser.add_argument("--offer-price-hkd", type=float)
    parser.add_argument("--sell-price-hkd", type=float)
    parser.add_argument("--first-day-pct", type=float)
    parser.add_argument("--financing-interest-hkd", type=float)
    parser.add_argument("--fees-hkd", type=float)
    parser.add_argument("--cash-hkd", type=float)
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text_parts = []
    if args.text:
        text_parts.append(args.text)
    if args.input_file:
        text_parts.append(Path(args.input_file).read_text(encoding="utf-8"))
    payload = normalize_actual_subscription(
        text="\n".join(text_parts),
        stock_name=args.stock_name,
        code=args.code,
        applied_amount_hkd=args.applied_amount_hkd,
        applied_lots=args.applied_lots,
        allotted_shares=args.allotted_shares,
        allotted_lots=args.allotted_lots,
        lot_size=args.lot_size,
        offer_price_hkd=args.offer_price_hkd,
        sell_price_hkd=args.sell_price_hkd,
        first_day_pct=args.first_day_pct,
        financing_interest_hkd=args.financing_interest_hkd,
        fees_hkd=args.fees_hkd,
        cash_hkd=args.cash_hkd,
    )
    if args.markdown:
        sys.stdout.write(render_markdown(payload))
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
