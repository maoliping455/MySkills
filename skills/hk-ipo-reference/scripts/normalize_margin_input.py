#!/usr/bin/env python3
"""Normalize pre-close broker margin and financing heat excerpts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


BROKER_KEYWORDS = [
    "富途",
    "辉立",
    "耀才",
    "华盛",
    "老虎",
    "长桥",
    "雪盈",
    "盈立",
    "利弗莫尔",
    "尊嘉",
    "复星",
    "招银",
    "中银",
    "国泰君安",
]
QUOTA_TIGHT_PATTERNS = ["额度紧张", "额度不足", "满额", "售罄", "抢完", "无额度", "提前截止", "截止提前", "提早截止"]
ACCELERATION_PATTERNS = ["最后一天", "尾日", "临近截止", "下午加速", "加速", "急增", "飙升", "大幅增加", "追单"]
WEAK_DEMAND_PATTERNS = ["冷清", "降温", "没人申", "未足额", "孖展不足", "融资不足", "额度很松", "认购一般"]
HIGH_COST_PATTERNS = ["融资贵", "利率高", "息费贵", "手续费高"]
COST_SIGNAL_LABELS = {"融资成本可接受"}
SEVERE_RISK_LABELS = {"需求偏弱或热度不足", "融资成本偏高", "融资成本被讨论为风险"}
HEAT_SIGNAL_GROUP_BY_LABEL = {
    "孖展倍数显著领先": "孖展规模",
    "孖展金额高": "孖展规模",
    "多券商热度一致": "多券商一致",
    "额度紧张或截止提前": "额度紧张",
    "最后阶段需求加速": "需求加速",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)(\d{4,5})(?:\.HK)?(?!\d)", value)
    return match.group(1).zfill(5) if match else None


def split_snippets(text: str) -> list[str]:
    candidates = re.split(r"[\n\r]+|(?<=。)|(?<=；)|(?<=;)", text)
    return [clean(item) for item in candidates if clean(item)]


def parse_money_hkd(text: str) -> float | None:
    matches = re.findall(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万|亿)", text)
    values: list[float] = []
    for raw, unit in matches:
        value = float(raw.replace(",", ""))
        if unit == "亿":
            value *= 100_000_000
        elif unit == "万":
            value *= 10_000
        values.append(value)
    raw_amount_matches = re.findall(
        r"(?:孖展金额|孖展额|融资金额|认购金额|margin_amount_hkd|HKD|港元|港币|\$)[^\d]{0,12}(\d[\d,]*(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    for raw in raw_amount_matches:
        value = float(raw.replace(",", ""))
        if value >= 1_000_000:
            values.append(value)
    return max(values) if values else None


def parse_multiple(text: str) -> float | None:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:倍|x|X)", text)
    return max(float(item) for item in matches) if matches else None


def parse_rate_pct(text: str) -> float | None:
    rate_matches = re.findall(r"(?:年化|利率|息|融资息|融资利率)[^\d]{0,8}(\d+(?:\.\d+)?)\s*%", text)
    if not rate_matches:
        rate_matches = re.findall(r"(\d+(?:\.\d+)?)\s*%[^\d]{0,6}(?:年化|利率|息)", text)
    if not rate_matches:
        rate_matches = re.findall(
            r"(?:年化|利率|息|融资息|融资利率|financing_rate_pct|rate_pct)[^\d]{0,12}(\d+(?:\.\d+)?)\b",
            text,
            flags=re.IGNORECASE,
        )
        rate_matches = [item for item in rate_matches if 0 < float(item) <= 100]
    return min(float(item) for item in rate_matches) if rate_matches else None


def detect_brokers(text: str) -> list[str]:
    return [broker for broker in BROKER_KEYWORDS if broker in text]


def normalize_snippet(text: str) -> dict[str, Any]:
    margin_amount_hkd = parse_money_hkd(text)
    margin_multiple = parse_multiple(text)
    rate_pct = parse_rate_pct(text)
    brokers = detect_brokers(text)
    strong_signals: list[str] = []
    heat_signal_groups: list[str] = []
    cost_signals: list[str] = []
    risk_flags: list[str] = []

    if margin_multiple is not None:
        if margin_multiple >= 100:
            strong_signals.append("孖展倍数显著领先")
            heat_signal_groups.append("孖展规模")
        elif margin_multiple < 10:
            risk_flags.append("孖展倍数偏弱")
    if margin_amount_hkd is not None and margin_amount_hkd >= 5_000_000_000:
        strong_signals.append("孖展金额高")
        heat_signal_groups.append("孖展规模")
    if any(pattern in text for pattern in QUOTA_TIGHT_PATTERNS):
        strong_signals.append("额度紧张或截止提前")
        heat_signal_groups.append("额度紧张")
    if any(pattern in text for pattern in ACCELERATION_PATTERNS):
        strong_signals.append("最后阶段需求加速")
        heat_signal_groups.append("需求加速")
    if rate_pct is not None:
        if rate_pct <= 5:
            cost_signals.append("融资成本可接受")
        elif rate_pct >= 8:
            risk_flags.append("融资成本偏高")
    if any(pattern in text for pattern in HIGH_COST_PATTERNS):
        risk_flags.append("融资成本被讨论为风险")
    if any(pattern in text for pattern in WEAK_DEMAND_PATTERNS):
        risk_flags.append("需求偏弱或热度不足")

    return {
        "excerpt": text,
        "brokers": brokers,
        "margin_amount_hkd": margin_amount_hkd,
        "margin_multiple": margin_multiple,
        "financing_rate_pct": rate_pct,
        "strong_signals": sorted(set(strong_signals)),
        "heat_signal_groups": sorted(set(heat_signal_groups)),
        "cost_signals": sorted(set(cost_signals)),
        "risk_flags": sorted(set(risk_flags)),
    }


def heat_signal_groups_from_summary(summary: dict[str, Any]) -> list[str]:
    explicit_groups = summary.get("heat_signal_groups")
    if isinstance(explicit_groups, list):
        return sorted({clean(group) for group in explicit_groups if clean(group)})
    groups = set()
    for signal in summary.get("strong_signals") or []:
        signal_text = clean(signal)
        if not signal_text or signal_text in COST_SIGNAL_LABELS:
            continue
        groups.add(HEAT_SIGNAL_GROUP_BY_LABEL.get(signal_text, signal_text))
    return sorted(groups)


def independent_heat_signal_count(summary: dict[str, Any]) -> int:
    raw_count = summary.get("independent_heat_signal_count")
    if isinstance(raw_count, (int, float)):
        return int(raw_count)
    return len(heat_signal_groups_from_summary(summary))


def normalized_cost_status(summary: dict[str, Any]) -> str:
    cost_status = clean(summary.get("cost_status"))
    if cost_status:
        return cost_status
    raw_signals = set(summary.get("strong_signals") or [])
    cost_signals = set(summary.get("cost_signals") or [])
    cost_signals.update(raw_signals & COST_SIGNAL_LABELS)
    min_rate = summary.get("min_financing_rate_pct")
    if "融资成本可接受" in cost_signals or (isinstance(min_rate, (int, float)) and min_rate <= 5):
        return "可接受"
    if isinstance(min_rate, (int, float)) and min_rate >= 8:
        return "偏高"
    return "未提供"


def timing_evidence_valid(summary: dict[str, Any]) -> bool:
    valid_count = summary.get("timing_valid_row_count")
    invalid_count = summary.get("timing_invalid_row_count")
    if isinstance(valid_count, (int, float)) or isinstance(invalid_count, (int, float)):
        return int(valid_count or 0) > 0
    if summary.get("timing_confidence") == "未确认":
        return False
    return True


def strict_execution_ready(summary: dict[str, Any]) -> bool:
    if summary.get("execution_gate") != "满足":
        return False
    risks = set(summary.get("risk_flags") or [])
    return (
        timing_evidence_valid(summary)
        and
        independent_heat_signal_count(summary) >= 2
        and normalized_cost_status(summary) == "可接受"
        and not (risks & SEVERE_RISK_LABELS)
    )


def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    brokers = sorted({broker for item in items for broker in item.get("brokers") or []})
    signals = sorted({signal for item in items for signal in item.get("strong_signals") or []})
    heat_signal_groups = sorted({group for item in items for group in item.get("heat_signal_groups") or []})
    cost_signals = sorted({signal for item in items for signal in item.get("cost_signals") or []})
    risks = sorted({risk for item in items for risk in item.get("risk_flags") or []})
    multiples = [item["margin_multiple"] for item in items if isinstance(item.get("margin_multiple"), (int, float))]
    rates = [item["financing_rate_pct"] for item in items if isinstance(item.get("financing_rate_pct"), (int, float))]

    if len(brokers) >= 2:
        signals.append("多券商热度一致")
        heat_signal_groups.append("多券商一致")
    signals = sorted(set(signals))
    heat_signal_groups = sorted(set(heat_signal_groups))

    severe_risk = any(risk in risks for risk in ["需求偏弱或热度不足"]) or any(rate >= 10 for rate in rates)
    cost_status = "可接受" if "融资成本可接受" in cost_signals and not severe_risk else "偏高" if any("融资成本" in risk for risk in risks) else "未提供"
    independent_count = len(heat_signal_groups)
    execution_ready = independent_count >= 2 and cost_status == "可接受" and not severe_risk
    confidence = "高" if len(items) >= 3 and len(brokers) >= 2 else "中" if items else "低"
    if severe_risk:
        confidence = "中" if confidence == "高" else "低"

    return {
        "total_snippets": len(items),
        "brokers": brokers,
        "strong_signals": signals,
        "heat_signal_groups": heat_signal_groups,
        "independent_heat_signal_count": independent_count,
        "cost_signals": cost_signals,
        "risk_flags": risks,
        "strong_signal_count": independent_count,
        "cost_status": cost_status,
        "execution_gate": "满足" if execution_ready else "不满足",
        "confidence": confidence,
        "max_margin_multiple": max(multiples) if multiples else None,
        "min_financing_rate_pct": min(rates) if rates else None,
    }


def normalize_text(text: str, *, stock_name: str | None = None, code: str | None = None) -> dict[str, Any]:
    items = [normalize_snippet(snippet) for snippet in split_snippets(text)]
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "stock_name": clean(stock_name) or None,
        "code": canonical_code(code),
        "summary": aggregate(items),
        "items": items,
        "disclaimer": "融资热度仅基于公开或用户提供摘录归一化，不代表券商实际可借额度或最终配售结果。",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-name")
    parser.add_argument("--code")
    parser.add_argument("--text")
    parser.add_argument("--file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    parts: list[str] = []
    if args.text:
        parts.append(args.text)
    if args.file:
        parts.append(Path(args.file).read_text(encoding="utf-8"))
    if not parts and not sys.stdin.isatty():
        parts.append(sys.stdin.read())
    if not parts:
        raise SystemExit("Provide --text, --file, or pipe text to stdin.")
    payload = normalize_text("\n".join(parts), stock_name=args.stock_name, code=args.code)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
