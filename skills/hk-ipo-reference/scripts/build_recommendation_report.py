#!/usr/bin/env python3
"""Build a stateless Markdown recommendation report for Hong Kong IPOs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from fetch_current_ipos import clean_stock_name, extract_stock_name_status
from normalize_margin_input import heat_signal_groups_from_summary, independent_heat_signal_count, strict_execution_ready


DEFAULT_CASH_HKD = 550_000.0
DEFAULT_MARGIN_MULTIPLE = 10.0
A_GROUP_LIMIT_HKD = 5_000_000.0
CHINESE_DISPLAY_ALIASES_BY_CODE = {
    "00100": "稀宇科技",
    "00068": "群核科技",
    # HK short name is English-only; Chinese media commonly describes it by issuer profile.
    "08610": "马来西亚土木工程承包商",
    # HK short name is English-only; Chinese media commonly describes it as an Indonesian gold miner.
    "06228": "印尼金矿商",
}

HOT_INDUSTRY_KEYWORDS = [
    "半导体",
    "芯片",
    "人工智能",
    "AI",
    "机器人",
    "自动驾驶",
    "软件",
    "云",
    "高端制造",
    "医疗器械",
    "消费",
]
DEFENSIVE_INDUSTRY_KEYWORDS = ["医药", "设备", "服务", "教育", "公用", "能源"]
WEAK_INDUSTRY_KEYWORDS = ["地产", "物业", "餐饮", "服饰", "传统零售", "建筑"]
GENERIC_TECH_KEYWORDS = ["应用软件", "系统软件", "资讯科技", "电讯及网络"]
HARD_TECH_QUALITY_KEYWORDS = [
    "半导体",
    "先进硬件",
    "新一代信息技术",
    "机器人",
    "AI",
    "人工智能",
    "线路板",
    "电子设备",
    "电器部件",
    "医疗器械",
    "医疗保健设备",
]
STRONG_SPONSOR_KEYWORDS = [
    "中金",
    "中国国际金融",
    "中信",
    "中信证券",
    "华泰",
    "华泰联合",
    "摩根",
    "摩根士丹利",
    "摩根大通",
    "高盛",
    "美银",
    "美国银行",
    "招银",
    "招银国际",
    "建银",
    "建银国际",
    "国泰君安",
    "海通",
    "海通国际",
]


def money(value: float | int | None) -> str:
    if value is None:
        return "待核实"
    value = float(value)
    if abs(value) >= 100_000_000:
        return f"HKD {value / 100_000_000:.2f} 亿"
    if abs(value) >= 10_000:
        return f"HKD {value / 10_000:.2f} 万"
    return f"HKD {value:,.0f}"


def pct_plain(value: float | int | None) -> str:
    if value is None:
        return "待核实"
    return f"{float(value):+.2f}%"


def ratio_plain(value: float | int | None) -> str:
    if value is None:
        return "待核实"
    return f"{float(value) * 100:.1f}%"


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def contains_chinese(value: str | None) -> bool:
    return bool(value and re.search(r"[\u4e00-\u9fff]", value))


def canonical_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)(\d{4,5})(?:\.HK)?(?!\d)", value)
    if not match:
        return None
    return match.group(1).zfill(5)


def chinese_display_alias(record: dict[str, Any]) -> str | None:
    code = canonical_code(clean(record.get("code") or record.get("canonical_code")))
    if code and code in CHINESE_DISPLAY_ALIASES_BY_CODE:
        return CHINESE_DISPLAY_ALIASES_BY_CODE[code]
    return None


def stock_title(ipo: dict[str, Any]) -> str:
    code = ipo.get("code") or (f"{ipo.get('canonical_code')}.HK" if ipo.get("canonical_code") else "")
    name = clean_stock_name(ipo.get("name"))
    if contains_chinese(name):
        return f"{name}（{code}）" if code else name
    alias = chinese_display_alias(ipo)
    if alias:
        return f"{alias}（{code}）" if code else alias
    if code:
        return f"代码{code}（中文名待核实）"
    return "未命名新股（中文名待核实）"


def ipo_status(ipo: dict[str, Any]) -> str:
    status = clean(ipo.get("status"))
    name_status = clean(extract_stock_name_status(ipo.get("name")))
    if status and name_status and name_status not in status:
        return f"{status}；{name_status}"
    return status or name_status


def review_records_lookup(review_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not review_payload:
        return {}
    records = review_payload.get("records") or review_payload.get("ipos") or []
    lookup: dict[str, dict[str, Any]] = {}
    for record in records:
        code = canonical_code(clean(record.get("code") or record.get("canonical_code")))
        if code:
            lookup[code] = record
    return lookup


def attach_review_records(analyses: list[dict[str, Any]], review_payload: dict[str, Any] | None) -> None:
    lookup = review_records_lookup(review_payload)
    if not lookup:
        return
    for analysis in analyses:
        code = canonical_code(clean(analysis["ipo"].get("code") or analysis["ipo"].get("canonical_code")))
        if code and code in lookup:
            analysis["review_record"] = lookup[code]


def deep_dive_records(deep_dive_payload: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if not deep_dive_payload:
        return []
    if isinstance(deep_dive_payload, list):
        return [item for item in deep_dive_payload if isinstance(item, dict)]
    for key in ["records", "stocks", "deep_dives"]:
        items = deep_dive_payload.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if deep_dive_payload.get("signals") or deep_dive_payload.get("sections"):
        return [deep_dive_payload]
    return []


def deep_dive_lookup(deep_dive_payload: dict[str, Any] | list[Any] | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for record in deep_dive_records(deep_dive_payload):
        code = canonical_code(clean(record.get("code")))
        if code:
            lookup[code] = record
        name = clean_stock_name(record.get("stock_name") or record.get("name"))
        if name:
            lookup[f"name:{name}"] = record
    return lookup


def deep_dive_for_ipo(
    ipo: dict[str, Any],
    deep_dive_payload: dict[str, Any] | list[Any] | None,
) -> dict[str, Any] | None:
    lookup = deep_dive_lookup(deep_dive_payload)
    if not lookup:
        return None
    code = canonical_code(clean(ipo.get("code") or ipo.get("canonical_code")))
    if code and code in lookup:
        return lookup[code]
    name = clean_stock_name(ipo.get("name"))
    if name and f"name:{name}" in lookup:
        return lookup[f"name:{name}"]
    return None


def expected_one_lot_review_pnl(ipo: dict[str, Any], review: dict[str, Any]) -> float | None:
    entry_fee = review.get("entry_fee_hkd")
    if not isinstance(entry_fee, (int, float)):
        entry_fee = ipo.get("entry_fee_hkd")
    first_day = review.get("first_day_change_pct")
    one_lot = review.get("one_lot_success_rate_pct")
    if not all(isinstance(value, (int, float)) for value in [entry_fee, first_day, one_lot]):
        return None
    return float(entry_fee) * float(first_day) / 100.0 * float(one_lot) / 100.0


def review_heat_label(review: dict[str, Any]) -> str:
    oversub = review.get("oversubscription_rate")
    one_lot = review.get("one_lot_success_rate_pct")
    if not isinstance(oversub, (int, float)) and not isinstance(one_lot, (int, float)):
        return "最终热度缺失"
    oversub_value = float(oversub) if isinstance(oversub, (int, float)) else 0.0
    one_lot_value = float(one_lot) if isinstance(one_lot, (int, float)) else 999.0
    if oversub_value >= 1000 and one_lot_value <= 5:
        return "最终强热度"
    if oversub_value < 200 or one_lot_value >= 15:
        return "最终弱热度"
    return "最终热度中性"


def review_result_note(analysis: dict[str, Any], review: dict[str, Any]) -> str:
    first_day = review.get("first_day_change_pct")
    category = analysis.get("category")
    heat_label = review_heat_label(review)
    pnl = expected_one_lot_review_pnl(analysis["ipo"], review)
    if not isinstance(first_day, (int, float)):
        if heat_label == "最终强热度":
            return "最终热度已强但首日待核实，应优先补暗盘/首日表现并复核是否错过升级窗口"
        return "实际首日表现待核实"
    if category == "建议申购" and first_day <= 0:
        note = "建议申购但首日不涨/破发，需复盘估值、热度和融资执行"
        if heat_label == "最终弱热度":
            note += "；最终热度偏弱，下次应在融资截止前降级乙组或退回现金"
        if pnl is not None and pnl <= 0:
            note += "；一手期望不正，资金效率不足"
        return note
    if category != "建议申购" and first_day >= 20:
        note = "未列入建议申购但首日强收益，需检查临界观察、孖展热度和招股书深挖是否漏触发"
        if heat_label == "最终强热度":
            note += "；最终强热度说明 T-1/T-0 孖展/额度信号应触发升级复核"
        if pnl is not None and pnl < 50:
            note += "；但一手期望偏低，升级前仍要看资金效率"
        return note
    if category == "建议申购" and first_day > 0:
        note = "方向基本验证，但仍需按一手期望和融资成本评估资金效率"
        if heat_label == "最终弱热度":
            note += "；最终热度弱，正收益不代表乙组值得执行"
        return note
    return "结果与谨慎分类大致一致，继续关注资金效率和是否有漏配机会"


def review_line(analysis: dict[str, Any]) -> str:
    review = analysis.get("review_record") or {}
    if not review:
        status = ipo_status(analysis["ipo"])
        status_text = f"{status}；" if status else ""
        return (
            f"- {analysis['title']}：{status_text}已进入复盘/监控窗口，不进入事前推荐区。"
            "若可取得暗盘、配发结果或首日涨跌幅，应对照本次分类、融资判断和舆情信号复盘。"
        )
    parts = [
        f"- {analysis['title']}：推荐 `{analysis['category']}`",
        f"首日 {pct_plain(review.get('first_day_change_pct'))}",
    ]
    if isinstance(review.get("oversubscription_rate"), (int, float)):
        parts.append(f"公开超购 {float(review['oversubscription_rate']):,.1f}x")
    if isinstance(review.get("one_lot_success_rate_pct"), (int, float)):
        parts.append(f"一手中签率 {float(review['one_lot_success_rate_pct']):.2f}%")
    heat_label = review_heat_label(review)
    if heat_label != "最终热度缺失":
        parts.append(heat_label)
    pnl = expected_one_lot_review_pnl(analysis["ipo"], review)
    if pnl is not None:
        parts.append(f"一手期望毛利 {money(pnl)}")
    parts.append(review_result_note(analysis, review))
    return "；".join(parts) + "。"


def is_pre_close_actionable(analysis: dict[str, Any]) -> bool:
    return not analysis.get("subscription_closed") and not analysis.get("review_due")


def parse_iso_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def add_days(value: dt.date | None, days: int) -> dt.date | None:
    if value is None:
        return None
    return value + dt.timedelta(days=days)


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def load_json(path: str | None) -> dict[str, Any]:
    if path and path != "-":
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if sys.stdin.isatty():
        raise SystemExit("Provide --input or pipe IPO JSON to stdin.")
    return json.loads(sys.stdin.read())


def load_sentiment(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.sentiment_json:
        return json.loads(Path(args.sentiment_json).read_text(encoding="utf-8"))
    text_parts: list[str] = []
    if args.sentiment_text:
        text_parts.append(args.sentiment_text)
    if args.sentiment_file:
        text_parts.append(Path(args.sentiment_file).read_text(encoding="utf-8"))
    if not text_parts:
        return None
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    from normalize_sentiment_input import normalize_text  # type: ignore

    return normalize_text("\n\n".join(text_parts))


def sentiment_for_ipo(ipo: dict[str, Any], sentiment: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sentiment:
        return None
    code = canonical_code(clean(ipo.get("code") or ipo.get("canonical_code")))
    name = clean_stock_name(ipo.get("name"))
    items = sentiment.get("items") or []
    matched: list[dict[str, Any]] = []
    for item in items:
        item_code = canonical_code(clean(item.get("code")))
        item_name = clean(item.get("stock_name"))
        excerpt = clean(item.get("excerpt"))
        if item_code and code and item_code == code:
            matched.append(item)
        elif item_name and name and (item_name in name or name in item_name):
            matched.append(item)
        elif code and code.lstrip("0") and code.lstrip("0") in excerpt:
            matched.append(item)
        elif contains_chinese(name) and name[:4] and name[:4] in excerpt:
            matched.append(item)

    if matched:
        score = sum(float(item.get("score") or 0) for item in matched)
        platforms: dict[str, int] = {}
        for item in matched:
            platform = clean(item.get("platform")) or "未标注"
            platforms[platform] = platforms.get(platform, 0) + 1
        tilt = "偏正面" if score >= 2 else "偏负面" if score <= -2 else "分歧/中性"
        return {"items": matched, "summary": {"tilt": tilt, "score": score, "platforms": platforms}}

    stock_specific = clean(sentiment.get("stock_name") or sentiment.get("code"))
    if not stock_specific:
        return sentiment
    return None


def signal_count_text(margin_heat: dict[str, Any] | None) -> str:
    if not margin_heat:
        return "未提供"
    summary = margin_heat.get("summary") or {}
    signals = summary.get("strong_signals") or []
    groups = heat_signal_groups_from_summary(summary)
    strict_gate = "满足" if strict_execution_ready(summary) else "不满足"
    cost_signals = summary.get("cost_signals") or []
    risks = summary.get("risk_flags") or []
    return (
        f"{strict_gate}；"
        f"独立热度信号 {independent_heat_signal_count(summary)} 类：{'、'.join(groups) or '无'}；"
        f"原始信号 {len(signals)} 项：{'、'.join(signals) or '无'}；"
        f"成本信号：{'、'.join(cost_signals) or summary.get('cost_status') or '未提供'}；"
        f"风险：{'、'.join(risks) or '未见明确风险'}"
    )


def margin_heat_for_ipo(ipo: dict[str, Any], margin_heat_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not margin_heat_payload:
        return None
    payloads = margin_heat_payload.get("items_by_stock") or margin_heat_payload.get("stocks")
    if isinstance(payloads, list):
        for item in payloads:
            matched = margin_heat_for_ipo(ipo, item)
            if matched:
                return matched
        return None

    code = canonical_code(clean(ipo.get("code") or ipo.get("canonical_code")))
    heat_code = canonical_code(clean(margin_heat_payload.get("code")))
    name = clean_stock_name(ipo.get("name"))
    heat_name = clean(margin_heat_payload.get("stock_name"))
    if heat_code and code and heat_code == code:
        return margin_heat_payload
    if heat_name and name and (heat_name in name or name in heat_name):
        return margin_heat_payload
    if not heat_code and not heat_name:
        return margin_heat_payload
    return None


def sentiment_score(sentiment: dict[str, Any] | None) -> tuple[int, list[str]]:
    if not sentiment:
        return 0, ["未提供可归一化舆情，不能把社区热度作为依据。"]
    summary = sentiment.get("summary") or {}
    tilt = clean(summary.get("tilt"))
    confidence = clean(summary.get("confidence"))
    raw_score = float(summary.get("score") or 0)
    modifier = 0
    if "正面" in tilt:
        modifier = 6 if raw_score >= 3 else 3
    elif "负面" in tilt:
        modifier = -6 if raw_score <= -3 else -3
    elif "分歧" in tilt:
        modifier = -1
    if confidence == "低":
        modifier = int(modifier / 2)
    note = f"舆情倾向：{tilt or '未明'}，置信度：{confidence or '未标注'}，只作为辅助信号。"
    return modifier, [note]


def deep_dive_score(deep_dive: dict[str, Any] | None) -> tuple[int, list[str], list[str], list[str]]:
    if not deep_dive:
        return 0, [], [], []
    signals = deep_dive.get("signals") or {}
    modifier = signals.get("score_modifier")
    if not isinstance(modifier, (int, float)):
        modifier = 0
    modifier = max(-10, min(6, int(modifier)))
    evidence = [
        f"招股书深挖：{clean(item)}"
        for item in (signals.get("positive_flags") or [])[:3]
        if clean(item)
    ]
    risks = [
        f"招股书深挖：{clean(item)}"
        for item in (signals.get("risk_flags") or [])[:4]
        if clean(item)
    ]
    missing = [
        f"招股书深挖：{clean(item)}"
        for item in (signals.get("missing_checks") or [])[:3]
        if clean(item)
    ]
    if deep_dive.get("text_available") is False:
        missing.append("招股书深挖：未取得可解析招股书文本。")
    return modifier, evidence, risks, missing


def analyze_ipo(
    ipo: dict[str, Any],
    *,
    as_of: dt.date,
    sentiment: dict[str, Any] | None,
    market_regime: dict[str, Any] | None = None,
    deep_dive: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score = 50
    evidence: list[str] = []
    risks: list[str] = []
    missing: list[str] = []

    docs = ipo.get("documents") or {}
    if docs.get("prospectus_url"):
        score += 8
        evidence.append("已找到 HKEX 招股书链接，具备进一步核验财务、估值和风险章节的基础。")
    else:
        score -= 8
        risks.append("未找到 HKEX 招股书链接，强推荐前需要补齐官方文件。")

    if docs.get("listing_announcement_url"):
        score += 3
        evidence.append("已找到 HKEX 新上市公告链接。")

    entry_fee = ipo.get("entry_fee_hkd")
    if isinstance(entry_fee, (int, float)):
        if entry_fee <= 5_000:
            score += 6
            evidence.append(f"一手入场费较低（{money(entry_fee)}），适合现金参与和灵活排期。")
        elif entry_fee <= 30_000:
            score += 3
            evidence.append(f"一手入场费可控（{money(entry_fee)}）。")
        elif entry_fee >= 100_000:
            score -= 6
            risks.append(f"一手入场费偏高（{money(entry_fee)}），资金容错较低。")
    else:
        score -= 4
        missing.append("一手入场费缺失，无法测算现金/融资手数。")

    industry = clean(ipo.get("industry"))
    industry_hit = [kw for kw in HOT_INDUSTRY_KEYWORDS if kw.lower() in industry.lower()]
    weak_hit = [kw for kw in WEAK_INDUSTRY_KEYWORDS if kw in industry]
    defensive_hit = [kw for kw in DEFENSIVE_INDUSTRY_KEYWORDS if kw in industry]
    generic_tech_hit = [kw for kw in GENERIC_TECH_KEYWORDS if kw in industry]
    hard_tech_hit = [kw for kw in HARD_TECH_QUALITY_KEYWORDS if kw.lower() in industry.lower()]
    if industry_hit:
        score += 7
        evidence.append(f"行业具备打新关注度：{', '.join(industry_hit[:3])}。")
    elif defensive_hit:
        score += 2
        evidence.append(f"行业属性相对稳健：{', '.join(defensive_hit[:2])}。")
    if weak_hit:
        score -= 5
        risks.append(f"行业题材偏弱或近期市场偏谨慎：{', '.join(weak_hit[:2])}。")
    if not industry:
        missing.append("行业字段缺失，需补充同业比较。")

    sponsor = clean(ipo.get("sponsor"))
    strong_sponsor = False
    if sponsor:
        if any(keyword in sponsor for keyword in STRONG_SPONSOR_KEYWORDS):
            strong_sponsor = True
            score += 6
            evidence.append(f"保荐人/承销团队包含较强机构：{sponsor[:80]}。")
        else:
            score += 1
            evidence.append(f"已披露保荐人：{sponsor[:80]}。")
    else:
        score -= 3
        missing.append("保荐人信息缺失，需核验保荐历史和近期同类项目表现。")

    name_and_background = f"{clean_stock_name(ipo.get('name'))} {ipo.get('listing_background') or ''}"
    is_b = "-B" in name_and_background or "－Ｂ" in name_and_background or "生物科技" in industry
    is_p = "-P" in name_and_background or "－Ｐ" in name_and_background
    if is_b:
        score -= 4
        risks.append("-B/生物科技不直接跳过，但需要在融资截止前核验管线、现金消耗、保荐质量和孖展热度。")
        if strong_sponsor and isinstance(entry_fee, (int, float)) and entry_fee <= 10_000:
            score += 2
            evidence.append("-B/生物科技具备强保荐和低入场费，先保留为可选观察或现金参与候选。")
    if is_p:
        score -= 3
        risks.append("-P/18C 商业化不确定，不默认融资。")

    public_offer = clean(ipo.get("hk_public_offer_shares_raw"))
    if public_offer:
        evidence.append(f"香港公开发售字段：{public_offer}。")
        pct_match = re.search(r"\((\d+(?:\.\d+)?)%\)", public_offer)
        if pct_match and float(pct_match.group(1)) < 10:
            score -= 2
            risks.append("香港公开发售初始占比低于常见 10% 水平，需留意回拨和中签率。")
    else:
        missing.append("香港公开发售比例/股数缺失。")

    close_date = parse_iso_date(ipo.get("closing_date"))
    listing_date = parse_iso_date(ipo.get("listing_date"))
    subscription_closed = bool(close_date and close_date < as_of)
    review_due = bool(listing_date and listing_date <= as_of)
    if close_date and as_of <= close_date:
        score += 4
        evidence.append(f"仍在申购窗口内，截止日 {close_date.isoformat()}。")
        days_to_close = (close_date - as_of).days
        if days_to_close <= 1:
            risks.append("距招股截止不足两天，融资额度、券商截止时间和利率需要立即确认。")
    elif subscription_closed:
        score -= 10
        risks.append(f"申购已于 {close_date.isoformat()} 截止，不能作为新的申购动作。")
    else:
        missing.append("招股截止日缺失，无法确认是否仍可申购。")

    if review_due:
        risks.append("已到或已过上市日，应优先做暗盘/首日复盘而不是新申购推荐。")

    sent_modifier, sent_notes = sentiment_score(sentiment)
    score += sent_modifier
    if sent_modifier > 0:
        evidence.extend(sent_notes)
    else:
        risks.extend(sent_notes)

    deep_modifier, deep_evidence, deep_risks, deep_missing = deep_dive_score(deep_dive)
    score += deep_modifier
    evidence.extend(deep_evidence)
    risks.extend(deep_risks)
    missing.extend(deep_missing)

    score = max(0, min(100, score))
    confidence_points = 20
    confidence_points += 20 if docs.get("prospectus_url") else 0
    confidence_points += 15 if isinstance(entry_fee, (int, float)) else 0
    confidence_points += 10 if close_date else 0
    confidence_points += 10 if listing_date else 0
    confidence_points += 10 if sponsor else 0
    confidence_points += 10 if sentiment else 0
    confidence_points += 10 if deep_dive and deep_dive.get("text_available") else 0
    confidence = "高" if confidence_points >= 75 else "中" if confidence_points >= 50 else "低"

    regime_label = clean((market_regime or {}).get("label"))
    generic_tech_guard = bool(
        generic_tech_hit
        and not hard_tech_hit
        and regime_label in {"中性", "偏冷"}
    )
    if generic_tech_guard:
        risks.append("非热市下泛软件/泛IT题材不直接建议申购，需等待招股书深度核验和融资截止前热度确认。")

    if close_date and close_date < as_of:
        category = "可选观察" if score >= 60 else "暂不参与"
    elif generic_tech_guard and score >= 55:
        category = "可选观察"
    elif score >= 70 and confidence != "低":
        category = "建议申购"
    elif score >= 55:
        category = "可选观察"
    else:
        category = "暂不参与"
    if category == "建议申购" and (not sponsor or not public_offer):
        category = "可选观察"
        risks.insert(0, "关键发行资料未完整披露，先降为观察，补齐保荐人和公开发售结构后再决定是否申购。")
    deep_signals = (deep_dive or {}).get("signals") or {}
    deep_risk_count = len(deep_signals.get("risk_flags") or [])
    if category == "建议申购" and (deep_modifier <= -6 or deep_risk_count >= 2):
        category = "可选观察"
        risks.insert(0, "招股书深挖出现估值、财务或结构性风险，先降为观察；融资前必须完成估值和资金效率复核。")

    return {
        "ipo": ipo,
        "title": stock_title(ipo),
        "score": score,
        "confidence": confidence,
        "category": category,
        "evidence": evidence[:6],
        "risks": risks[:6],
        "missing": missing[:6],
        "sentiment": sentiment,
        "deep_dive": deep_dive,
        "subscription_closed": subscription_closed,
        "review_due": review_due,
    }


def funding_window(ipo: dict[str, Any]) -> tuple[dt.date | None, dt.date | None]:
    close_date = parse_iso_date(ipo.get("closing_date"))
    listing_date = parse_iso_date(ipo.get("listing_date"))
    start_date = first_present(
        parse_iso_date(ipo.get("subscription_start_date")),
        close_date,
        listing_date,
    )
    end_date = first_present(
        parse_iso_date(ipo.get("refund_date")),
        listing_date,
        add_days(close_date, 3),
        start_date,
    )
    if start_date and end_date and end_date < start_date:
        end_date = start_date
    return start_date, end_date


def overlaps(a: tuple[dt.date | None, dt.date | None], b: tuple[dt.date | None, dt.date | None]) -> bool:
    if not all(a) or not all(b):
        return False
    a_start, a_end = a
    b_start, b_end = b
    return bool(a_start <= b_end and b_start <= a_end)


def lock_days(window: tuple[dt.date | None, dt.date | None]) -> int:
    start, end = window
    if start and end:
        return (end - start).days + 1
    return 999


def peak_reserved_cash(items: list[dict[str, Any]]) -> float:
    events: list[tuple[dt.date, int, float]] = []
    for item in items:
        window = item.get("_schedule_window") or (None, None)
        required = float(item.get("_schedule_required") or 0.0)
        start, end = window
        if start and end and required > 0:
            events.append((start, 1, required))
            events.append((end + dt.timedelta(days=1), 0, -required))
    running = 0.0
    peak = 0.0
    for _, _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        running += delta
        peak = max(peak, running)
    return peak


def funding_preclose_utility(item: dict[str, Any], *, cash_hkd: float) -> float:
    ipo = item.get("ipo") or {}
    entry_fee = ipo.get("entry_fee_hkd")
    capped_entry = min(float(entry_fee), cash_hkd) if isinstance(entry_fee, (int, float)) and entry_fee > 0 else 0.0
    return float(item.get("score") or 0) * 100.0 + capped_entry / 10_000.0 - lock_days(item.get("_schedule_window") or (None, None))


def schedule_components(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    remaining = set(range(len(items)))
    while remaining:
        start = remaining.pop()
        stack = [start]
        component = {start}
        while stack:
            idx = stack.pop()
            left = items[idx].get("_schedule_window") or (None, None)
            for other in list(remaining):
                right = items[other].get("_schedule_window") or (None, None)
                if overlaps(left, right):
                    remaining.remove(other)
                    component.add(other)
                    stack.append(other)
        groups.append([items[index] for index in sorted(component)])
    return groups


def best_schedule_subset(component: list[dict[str, Any]], *, cash_hkd: float) -> list[dict[str, Any]]:
    def objective(subset: list[dict[str, Any]]) -> tuple[int, int, float, int, float, str]:
        recommended = sum(1 for item in subset if item.get("category") == "建议申购")
        observation = sum(1 for item in subset if item.get("category") == "可选观察")
        utility = sum(funding_preclose_utility(item, cash_hkd=cash_hkd) for item in subset)
        names = "|".join(sorted(item.get("title") or "" for item in subset))
        return (recommended, observation, utility, len(subset), -peak_reserved_cash(subset), names)

    if len(component) > 22:
        ordered = sorted(
            component,
            key=lambda item: (
                item.get("category") != "建议申购",
                item.get("category") != "可选观察",
                -funding_preclose_utility(item, cash_hkd=cash_hkd),
                item.get("title") or "",
            ),
        )
        selected: list[dict[str, Any]] = []
        for item in ordered:
            if peak_reserved_cash([*selected, item]) <= cash_hkd + 1e-6:
                selected.append(item)
        return selected

    best_subset: list[dict[str, Any]] = []
    best_key: tuple[int, int, float, int, float, str] | None = None
    size = len(component)
    for mask in range(1 << size):
        subset = [component[index] for index in range(size) if mask & (1 << index)]
        if peak_reserved_cash(subset) > cash_hkd + 1e-6:
            continue
        key = objective(subset)
        if best_key is None or key > best_key:
            best_key = key
            best_subset = subset
    return best_subset


def choose_scheduled_titles(analyses: list[dict[str, Any]], *, cash_hkd: float) -> set[str]:
    candidates = [
        item
        for item in analyses
        if float((item.get("funding_plan") or {}).get("cash_required_hkd") or 0.0) > 0
        and all(item.get("_schedule_window") or (None, None))
    ]
    selected: list[dict[str, Any]] = []
    for component in schedule_components(candidates):
        selected.extend(best_schedule_subset(component, cash_hkd=cash_hkd))
    return {item["title"] for item in selected}


def build_funding_plan(
    analysis: dict[str, Any],
    *,
    cash_hkd: float,
    margin_multiple: float,
    margin_rate_pct: float | None,
    financing_days: int,
    market_regime: dict[str, Any] | None = None,
    margin_heat: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ipo = analysis["ipo"]
    entry_fee = ipo.get("entry_fee_hkd")
    if analysis.get("subscription_closed") or analysis.get("review_due"):
        return {
            "summary": "申购已截止或已进入上市复盘窗口，不做新的申购/融资安排；若已参与，只复核中签、成本和暗盘/首日卖出纪律。",
            "cash_required_hkd": 0.0,
            "uses_margin": False,
        }
    if not isinstance(entry_fee, (int, float)) or entry_fee <= 0:
        return {
            "summary": "入场费缺失，暂不做现金/融资手数建议。",
            "cash_required_hkd": 0.0,
            "uses_margin": False,
        }

    buying_power = cash_hkd * margin_multiple
    cash_lots = max(0, math.floor(cash_hkd / entry_fee))
    margin_lots = max(0, math.floor(buying_power / entry_fee))
    a_group_lots = max(0, math.floor(A_GROUP_LIMIT_HKD / entry_fee))
    can_enter_b_group = buying_power > A_GROUP_LIMIT_HKD and margin_lots > a_group_lots
    regime_label = clean((market_regime or {}).get("label"))
    heat_summary = (margin_heat or {}).get("summary") or {}
    heat_gate_ready = strict_execution_ready(heat_summary)
    heat_note = signal_count_text(margin_heat)

    if regime_label == "偏冷" and analysis["category"] == "建议申购":
        return {
            "summary": (
                f"近期新股市场偏冷，不直接执行乙组融资；优先甲组较高档或现金多手。"
                f"现金约 {cash_lots} 手，甲组上限约 {a_group_lots} 手。融资热度闸门：{heat_note}。"
            ),
            "cash_required_hkd": min(cash_hkd, max(entry_fee, cash_hkd * 0.5)),
            "uses_margin": False,
            "cash_lots": cash_lots,
            "margin_lots": margin_lots,
        }

    if analysis["category"] == "建议申购" and analysis["score"] >= 75 and can_enter_b_group:
        target_amount = margin_lots * entry_fee
        fallback_cash = min(cash_hkd, max(entry_fee, cash_hkd * 0.5))
        loan_amount = max(0.0, target_amount - cash_hkd)
        cost_note = "未输入融资利率，需自行核实券商息费。"
        effective_rate_pct = margin_rate_pct
        if effective_rate_pct is None and isinstance(heat_summary.get("min_financing_rate_pct"), (int, float)):
            effective_rate_pct = float(heat_summary["min_financing_rate_pct"])
        if effective_rate_pct is not None and effective_rate_pct > 0:
            cost = loan_amount * effective_rate_pct / 100.0 * financing_days / 365.0
            cost_note = f"按年化 {effective_rate_pct:.2f}%、{financing_days} 天粗算融资息约 {money(cost)}。"
        if not heat_gate_ready:
            return {
                "summary": (
                    f"列为乙组候选：10x 约可申购 {money(target_amount)}（约 {margin_lots} 手）。"
                    f"乙组仅列入候选，当前不可直接执行；默认排期先按现金/甲组预案预留 {money(fallback_cash)}。"
                    f"融资热度闸门未满足（至少两个独立需求/额度热度信号且成本可接受）：{heat_note}。若信号不足，退回甲组顶格/现金多手。"
                    f"若后续执行乙组，{cost_note}"
                ),
                "cash_required_hkd": fallback_cash,
                "conditional_margin_amount_hkd": target_amount,
                "uses_margin": False,
                "cash_lots": cash_lots,
                "margin_lots": margin_lots,
            }
        gate_note = (
            f"融资热度闸门已满足：{heat_note}。可进入乙组执行核价。"
        )
        return {
            "summary": (
                f"列为乙组候选：10x 约可申购 {money(target_amount)}（约 {margin_lots} 手）。"
                + gate_note
                + cost_note
            ),
            "cash_required_hkd": cash_hkd,
            "uses_margin": True,
            "cash_lots": cash_lots,
            "margin_lots": margin_lots,
        }

    if analysis["category"] == "建议申购" and margin_lots > cash_lots:
        return {
            "summary": (
                f"优先现金多手或甲组较高档；现金约 {cash_lots} 手，"
                f"10x 融资最多约 {margin_lots} 手。融资热度闸门：{heat_note}。"
            ),
            "cash_required_hkd": min(cash_hkd, max(entry_fee, cash_hkd * 0.5)),
            "uses_margin": False,
            "cash_lots": cash_lots,
            "margin_lots": margin_lots,
        }

    if analysis["category"] == "可选观察":
        lots = min(max(cash_lots, 1), 3) if cash_lots else 0
        return {
            "summary": (
                f"不默认融资；若仍想参与，倾向现金一手到少量多手（约 {lots} 手以内），"
                f"融资截止前若闸门满足再上调到甲组候选。融资热度闸门：{heat_note}。"
            ),
            "cash_required_hkd": min(cash_hkd, entry_fee * max(lots, 1)),
            "uses_margin": False,
            "cash_lots": cash_lots,
            "margin_lots": margin_lots,
        }

    return {
        "summary": f"不建议占用融资额度；若券商融资截止前没有强孖展热度和成本优势，维持不参与。融资热度闸门：{heat_note}。",
        "cash_required_hkd": 0.0,
        "uses_margin": False,
        "cash_lots": cash_lots,
        "margin_lots": margin_lots,
    }


def attach_funding_and_schedule(
    analyses: list[dict[str, Any]],
    *,
    cash_hkd: float,
    margin_multiple: float,
    margin_rate_pct: float | None,
    financing_days: int,
    market_regime: dict[str, Any] | None = None,
    margin_heat_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    priority = {"建议申购": 0, "可选观察": 1, "暂不参与": 2}
    ordered = sorted(
        analyses,
        key=lambda item: (
            priority[item["category"]],
            -item["score"],
            item["title"],
            funding_window(item["ipo"])[0] or dt.date.max,
        ),
    )

    for analysis in ordered:
        plan = build_funding_plan(
            analysis,
            cash_hkd=cash_hkd,
            margin_multiple=margin_multiple,
            margin_rate_pct=margin_rate_pct,
            financing_days=financing_days,
            market_regime=market_regime,
            margin_heat=margin_heat_for_ipo(analysis["ipo"], margin_heat_payload),
        )
        window = funding_window(analysis["ipo"])
        plan["lock_window"] = window
        analysis["funding_plan"] = plan
        analysis["_schedule_window"] = window
        analysis["_schedule_required"] = float(plan.get("cash_required_hkd") or 0.0)

    selected_titles = choose_scheduled_titles(ordered, cash_hkd=cash_hkd)

    for analysis in ordered:
        plan = analysis["funding_plan"]
        window = plan.get("lock_window", (None, None))
        required = float(plan.get("cash_required_hkd") or 0.0)
        if required <= 0:
            schedule_status = "不占用默认现金。"
            schedule_decision = "不占用"
        elif not all(window):
            schedule_status = "锁定窗口缺失，不能确认是否与其他新股冲突。"
            schedule_decision = "窗口缺失"
        elif analysis["title"] in selected_titles:
            schedule_status = "按事前组合效用排入默认资金。"
            schedule_decision = "已排入默认资金"
        else:
            peers = [
                item
                for item in ordered
                if item["title"] in selected_titles and overlaps(window, item["funding_plan"].get("lock_window", (None, None)))
            ]
            names = "、".join(item["title"] for item in peers)
            schedule_status = (
                f"与 {names or '已排入股票'} 的资金锁定窗口重叠；同一笔 {money(cash_hkd)} 现金不能重复使用。"
            )
            schedule_decision = "资金冲突待取舍"

        plan["schedule_status"] = schedule_status
        plan["schedule_decision"] = schedule_decision

    return analyses


def markdown_sources(ipo: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    labels = {
        "aastocks_summary": "AASTOCKS 当前新股",
        "aastocks_detail": "AASTOCKS 个股详情",
        "hkex_listing_information": "HKEX 新上市资料",
        "listing_announcement_url": "HKEX 新上市公告",
        "prospectus_url": "HKEX 招股书",
        "allotment_result_url": "HKEX 配发结果",
    }
    for key, url in (ipo.get("source_urls") or {}).items():
        if url:
            lines.append(f"- {labels.get(key, key)}：{url}")
    for key, url in (ipo.get("documents") or {}).items():
        if url:
            lines.append(f"- {labels.get(key, key)}：{url}")
    return lines or ["- 来源链接缺失。"]


def format_date_range(window: tuple[dt.date | None, dt.date | None]) -> str:
    start, end = window
    if start and end:
        return f"{start.isoformat()} 至 {end.isoformat()}"
    return "待核实"


def funding_action_label(analysis: dict[str, Any]) -> str:
    plan = analysis["funding_plan"]
    if plan.get("cash_required_hkd") == 0:
        if analysis.get("subscription_closed") or analysis.get("review_due"):
            return "转复盘"
        return "不参与"
    if plan.get("conditional_margin_amount_hkd") and not plan.get("uses_margin"):
        return "现金/甲组预案；乙组待闸门"
    if analysis["category"] == "建议申购" and plan.get("uses_margin"):
        return "乙组可执行核价"
    if analysis["category"] == "建议申购":
        return "现金/甲组优先"
    if analysis["category"] == "可选观察":
        return "少量现金观察"
    return "不参与"


def funding_schedule_section(analyses: list[dict[str, Any]]) -> list[str]:
    actionable = [
        item
        for item in analyses
        if item["funding_plan"].get("schedule_decision") != "不占用"
    ]
    if not actionable:
        return ["- 暂无仍需占用默认现金的新申购安排。"]

    lines = [
        "排序口径：默认资金分配使用事前组合效用；推荐分类优先，分数占主导，入场敞口只作近分样本的资金利用度代理，仍需在同窗口取舍复核中用招股书和 T-1/T-0 热度确认。",
        "| 优先级 | 股票 | 推荐 | 资金动作 | 预计占用现金 | 锁定窗口 | 排期结论 |",
        "|---:|---|---|---|---:|---|---|",
    ]
    priority_rank = {"已排入默认资金": 0, "资金冲突待取舍": 1, "窗口缺失": 2}
    ordered = sorted(
        actionable,
        key=lambda item: (
            priority_rank.get(item["funding_plan"].get("schedule_decision"), 9),
            item["funding_plan"].get("lock_window", (None, None))[0] or dt.date.max,
            -item["score"],
        ),
    )
    for index, analysis in enumerate(ordered, start=1):
        plan = analysis["funding_plan"]
        lines.append(
            f"| {index} | {analysis['title']} | {analysis['category']} | {funding_action_label(analysis)} | "
            f"{money(plan.get('cash_required_hkd'))} | {format_date_range(plan.get('lock_window', (None, None)))} | "
            f"{plan.get('schedule_decision')} |"
        )
    return lines


def funding_conflict_review_section(analyses: list[dict[str, Any]]) -> list[str]:
    conflicts = [
        item
        for item in analyses
        if item["funding_plan"].get("schedule_decision") == "资金冲突待取舍"
        and not item.get("subscription_closed")
        and not item.get("review_due")
    ]
    if not conflicts:
        return ["- 暂无同一默认现金窗口内的待取舍冲突。"]

    selected = [
        item
        for item in analyses
        if item["funding_plan"].get("schedule_decision") == "已排入默认资金"
        and not item.get("subscription_closed")
        and not item.get("review_due")
    ]
    lines = [
        "同窗口冲突不能只靠基础分数拍板；融资截止前必须用事前可见信息复核，必要时替换默认排期。",
        "",
        "| 待取舍股票 | 当前冲突对象 | 锁定窗口 | 预计占用现金 | 事前复核动作 |",
        "|---|---|---|---:|---|",
    ]
    for analysis in sorted(
        conflicts,
        key=lambda item: (
            item["funding_plan"].get("lock_window", (None, None))[0] or dt.date.max,
            -item["score"],
        ),
    ):
        plan = analysis["funding_plan"]
        peers = [
            item
            for item in selected
            if overlaps(plan.get("lock_window", (None, None)), item["funding_plan"].get("lock_window", (None, None)))
        ]
        if peers:
            peer_text = "、".join(
                f"{item['title']}（{item['category']}，{item['score']}分）"
                for item in sorted(peers, key=lambda item: -item["score"])[:3]
            )
            if len(peers) > 3:
                peer_text += f"等{len(peers)}只"
        else:
            peer_text = "未匹配到已排入股票；先补锁定窗口"
        review_action = (
            "比较招股书深挖、T-1/T-0 孖展热度、额度紧张度、利率/手续费、"
            "事前占款效率（入场费、拟申购金额、融资息费打平幅度）和舆情分歧；"
            "不得使用一手中签率、配售结果、暗盘或首日涨跌；若冲突票证据明显更强，可在融资截止前替换默认排期，"
            "否则不追加占用同一笔现金。"
        )
        lines.append(
            f"| {analysis['title']}（{analysis['category']}，{analysis['score']}分） | "
            f"{peer_text} | {format_date_range(plan.get('lock_window', (None, None)))} | "
            f"{money(plan.get('cash_required_hkd'))} | {review_action} |"
        )
    return lines


def review_triggers(analysis: dict[str, Any]) -> str:
    triggers: list[str] = []
    if analysis["score"] >= 65:
        triggers.append("评分接近建议阈值")
    evidence_text = "；".join(analysis.get("evidence") or [])
    risk_text = "；".join((analysis.get("risks") or []) + (analysis.get("missing") or []))
    if "强保荐" in evidence_text or "较强机构" in evidence_text:
        triggers.append("保荐质量可复核")
    if "低入场费" in evidence_text or "入场费较低" in evidence_text:
        triggers.append("低入场费")
    if "行业具备打新关注度" in evidence_text:
        triggers.append("题材有关注度")
    if "关键发行资料未完整披露" in risk_text or "缺失" in risk_text:
        triggers.append("资料缺口需补齐")
    return "、".join(triggers[:4]) or "临界观察"


def borderline_review_section(analyses: list[dict[str, Any]]) -> list[str]:
    candidates = [
        item
        for item in analyses
        if item["category"] == "可选观察"
        and item["score"] >= 65
        and not item.get("subscription_closed")
        and not item.get("review_due")
    ]
    if not candidates:
        return ["- 暂无临界观察票。"]

    lines = [
        "| 股票 | 评分 | 触发原因 | T-1/T-0 复核项 | 升级条件 |",
        "|---|---:|---|---|---|",
    ]
    for analysis in sorted(candidates, key=lambda item: -item["score"]):
        lines.append(
            f"| {analysis['title']} | {analysis['score']} | {review_triggers(analysis)} | "
            "孖展倍数/金额、额度紧张度、利率手续费、券商融资截止、招股书估值/基石、舆情分歧 | "
            "至少两个融资截止前需求/额度类强热度信号且成本可接受，才从观察升级到现金/甲组；乙组仍需单独核价 |"
        )
    return lines


def prospectus_url_for(analysis: dict[str, Any]) -> str | None:
    ipo = analysis["ipo"]
    docs = ipo.get("documents") or {}
    return docs.get("prospectus_url")


def deep_dive_priority(analysis: dict[str, Any]) -> str | None:
    if analysis.get("subscription_closed") or analysis.get("review_due"):
        return None
    if analysis["category"] == "建议申购":
        return "P0"
    if analysis["category"] == "可选观察" and analysis["score"] >= 65:
        return "P1"
    return None


def deep_dive_focus(analysis: dict[str, Any]) -> str:
    focus = ["估值/发行市值", "收入和利润质量", "基石/禁售", "募资用途"]
    risk_text = "；".join((analysis.get("risks") or []) + (analysis.get("missing") or []))
    if "-B" in risk_text or "生物科技" in risk_text:
        focus.insert(0, "管线/商业化和现金消耗")
    if "高入场费" in risk_text or "高价" in risk_text:
        focus.insert(0, "高价合理性")
    if "缺" in risk_text:
        focus.append("缺失发行字段")
    return "、".join(list(dict.fromkeys(focus))[:5])


def prospectus_deep_dive_section(analyses: list[dict[str, Any]]) -> list[str]:
    candidates = [
        item
        for item in analyses
        if deep_dive_priority(item)
    ]
    if not candidates:
        return ["- 暂无仍可申购且需要立即深挖招股书的股票。"]

    lines = [
        "| 优先级 | 股票 | 推荐 | 触发原因 | 招股书 | 必查重点 |",
        "|---|---|---|---|---|---|",
    ]
    priority_rank = {"P0": 0, "P1": 1}
    for analysis in sorted(candidates, key=lambda item: (priority_rank.get(deep_dive_priority(item) or "", 9), -item["score"])):
        url = prospectus_url_for(analysis)
        if url:
            source = f"[HKEX招股书]({url})"
        else:
            source = "缺招股书；先补HKEX文件"
        trigger = "建议申购需深挖" if analysis["category"] == "建议申购" else "临界观察需复核"
        lines.append(
            f"| {deep_dive_priority(analysis)} | {analysis['title']} | {analysis['category']} | "
            f"{trigger} | {source} | {deep_dive_focus(analysis)} |"
        )
    lines.append("")
    lines.append("运行深挖脚本示例：`python scripts/deep_dive_prospectus.py --stock-name 股票中文名 --code 01234 --url HKEX招股书URL`")
    return lines


def financing_pricing_status(analysis: dict[str, Any]) -> str:
    plan = analysis["funding_plan"]
    if plan.get("uses_margin"):
        return "乙组可执行核价"
    if plan.get("conditional_margin_amount_hkd"):
        return "乙组待闸门"
    if analysis["category"] == "建议申购":
        return "现金/甲组核价"
    return "不核融资"


def financing_pricing_decision(analysis: dict[str, Any]) -> str:
    plan = analysis["funding_plan"]
    if plan.get("uses_margin"):
        return "已过热度闸门；仍需核实利率、手续费、额度、截止时间和占款冲突后才下单"
    if plan.get("conditional_margin_amount_hkd"):
        return "乙组不可直接执行；至少两个独立需求/额度热度信号且成本可接受后再核价"
    return "优先现金/甲组；没有强热度和成本优势时不升级乙组"


def financing_lock_urgency(analysis: dict[str, Any], *, as_of: dt.date) -> tuple[int, str, str, str]:
    close_date = parse_iso_date(analysis["ipo"].get("closing_date"))
    if not close_date:
        return (
            99,
            "日期缺失",
            "先补招股截止日和券商融资截止时间",
            "不确认截止时间前，不做乙组或大额甲组安排。",
        )
    days_left = (close_date - as_of).days
    if days_left <= 0:
        return (
            0,
            "T-0/今日截止",
            "只使用已经确认的额度、利率、费用和券商截止；热度闸门未满足则退回现金/甲组或放弃。",
            "不要等配售结果或暗盘再决定是否融资。",
        )
    if days_left == 1:
        return (
            1,
            "T-1",
            "今天完成孖展倍数/金额、额度紧张度、利率手续费、券商融资截止和占款冲突核实。",
            "乙组候选若仍缺两个需求/额度类热度信号或成本不可接受，默认降为甲组/现金。",
        )
    if days_left == 2:
        return (
            2,
            "T-2",
            "完成招股书估值、基石/禁售、同业比较和券商核价预案；准备 T-1 热度复核。",
            "不要因为题材或低入场费提前锁死乙组。",
        )
    return (
        3,
        f"T-{days_left}",
        "先做招股书深挖和资金窗口预排；融资动作等 T-2/T-1 热度与成本复核。",
        "不要提前占满融资额度，避免与后续更强票冲突。",
    )


def financing_lock_decision(analysis: dict[str, Any]) -> str:
    plan = analysis["funding_plan"]
    if plan.get("uses_margin"):
        return "已过热度闸门，进入乙组下单前最终核价"
    if plan.get("conditional_margin_amount_hkd"):
        return "乙组候选但未可执行，最晚 T-1/T-0 决定是否退回甲组/现金"
    if analysis["category"] == "建议申购":
        return "现金/甲组优先，融资只做成本敏感的加仓选项"
    if analysis["category"] == "可选观察":
        return "观察升级复核，未满足条件不占用融资额度"
    return "不融资"


def financing_lock_timeline_section(analyses: list[dict[str, Any]], *, as_of: dt.date) -> list[str]:
    candidates = [
        item
        for item in analyses
        if not item.get("subscription_closed")
        and not item.get("review_due")
        and (
            item["category"] == "建议申购"
            or item["funding_plan"].get("conditional_margin_amount_hkd")
            or item["funding_plan"].get("uses_margin")
            or (item["category"] == "可选观察" and item["score"] >= 65)
        )
    ]
    if not candidates:
        return ["- 暂无需要融资锁单跟踪的新申购票。"]

    lines = [
        "| 股票 | 阶段 | 当前状态 | 必须马上做 | 最晚约束/禁止动作 |",
        "|---|---|---|---|---|",
    ]
    ranked: list[tuple[int, int, dict[str, Any], str, str, str]] = []
    for analysis in candidates:
        rank, stage, action, guardrail = financing_lock_urgency(analysis, as_of=as_of)
        ranked.append((rank, -analysis["score"], analysis, stage, action, guardrail))
    for _, _, analysis, stage, action, guardrail in sorted(ranked, key=lambda item: (item[0], item[1])):
        lines.append(
            f"| {analysis['title']} | {stage} | {financing_lock_decision(analysis)} | "
            f"{action} | {guardrail} |"
        )
    lines.append("")
    lines.append("原则：融资锁单只能使用券商融资截止前可见信息；配售结果、暗盘和首日表现只能用于复盘。")
    return lines


def financing_pricing_section(analyses: list[dict[str, Any]]) -> list[str]:
    candidates = [
        item
        for item in analyses
        if not item.get("subscription_closed")
        and not item.get("review_due")
        and (
            item["category"] == "建议申购"
            or item["funding_plan"].get("conditional_margin_amount_hkd")
            or item["funding_plan"].get("uses_margin")
        )
    ]
    if not candidates:
        return ["- 暂无需要融资核价的新申购票。"]

    lines = [
        "| 股票 | 推荐 | 当前融资状态 | 核价金额 | 必核数据 | 执行结论 |",
        "|---|---|---|---:|---|---|",
    ]
    for analysis in sorted(candidates, key=lambda item: (0 if item["funding_plan"].get("uses_margin") else 1, -item["score"])):
        plan = analysis["funding_plan"]
        amount = plan.get("conditional_margin_amount_hkd") or plan.get("cash_required_hkd")
        lines.append(
            f"| {analysis['title']} | {analysis['category']} | {financing_pricing_status(analysis)} | "
            f"{money(amount)} | 孖展倍数/金额、额度紧张度、利率和手续费、券商融资截止、占款天数、资金窗口冲突 | "
            f"{financing_pricing_decision(analysis)} |"
        )
    return lines


def report_data_coverage(analyses: list[dict[str, Any]]) -> str:
    total = len(analyses)
    if total == 0:
        return "数据覆盖：未抓到新股样本。"
    actionable = sum(1 for item in analyses if not item.get("subscription_closed") and not item.get("review_due"))
    review_or_closed = total - actionable
    prospectus = 0
    hkex_docs = 0
    details = 0
    industry = 0
    sponsor = 0
    public_offer = 0
    entry_fee = 0
    review_match = 0
    review_first_day = 0
    deep_dive_count = 0
    for item in analyses:
        ipo = item["ipo"]
        docs = ipo.get("documents") or {}
        source_urls = ipo.get("source_urls") or {}
        if docs.get("prospectus_url"):
            prospectus += 1
        if docs.get("prospectus_url") or docs.get("listing_announcement_url") or source_urls.get("hkex_listing_information"):
            hkex_docs += 1
        if source_urls.get("aastocks_detail") or ipo.get("aastocks_detail_fields"):
            details += 1
        if clean(ipo.get("industry")):
            industry += 1
        if clean(ipo.get("sponsor")):
            sponsor += 1
        if clean(ipo.get("hk_public_offer_shares_raw")):
            public_offer += 1
        if isinstance(ipo.get("entry_fee_hkd"), (int, float)):
            entry_fee += 1
        review = item.get("review_record") or {}
        if review:
            review_match += 1
        if isinstance(review.get("first_day_change_pct"), (int, float)):
            review_first_day += 1
        if item.get("deep_dive"):
            deep_dive_count += 1
    return (
        f"数据覆盖：可申购 {actionable}/{total}；已截止/复盘 {review_or_closed}/{total}；"
        f"招股书 {prospectus}/{total}；HKEX文档 {hkex_docs}/{total}；详情页 {details}/{total}；"
        f"行业 {industry}/{total}；保荐人 {sponsor}/{total}；公开发售结构 {public_offer}/{total}；"
        f"入场费 {entry_fee}/{total}；深挖 {deep_dive_count}/{total}；"
        f"上市复盘匹配 {review_match}/{total}；首日表现 {review_first_day}/{total}"
    )


def deep_dive_brief_lines(analysis: dict[str, Any]) -> list[str]:
    deep_dive = analysis.get("deep_dive")
    if not deep_dive:
        return []
    signals = deep_dive.get("signals") or {}
    lines = ["", "**招股书深挖补充**"]
    modifier = signals.get("score_modifier")
    confidence = clean(signals.get("confidence")) or "未标注"
    if isinstance(modifier, (int, float)):
        lines.append(f"- 深挖信号调整：{int(modifier):+d} 分；置信度：{confidence}。")
    positives = [clean(item) for item in signals.get("positive_flags") or [] if clean(item)]
    risks = [clean(item) for item in signals.get("risk_flags") or [] if clean(item)]
    missing = [clean(item) for item in signals.get("missing_checks") or [] if clean(item)]
    def joined_flags(items: list[str]) -> str:
        return "；".join(item.rstrip("。；; ") for item in items)

    if positives:
        lines.append(f"- 支持点：{joined_flags(positives[:2])}。")
    if risks:
        lines.append(f"- 风险点：{joined_flags(risks[:2])}。")
    if missing:
        lines.append(f"- 仍需核对：{joined_flags(missing[:2])}。")
    if deep_dive.get("source"):
        lines.append(f"- 深挖来源：{deep_dive['source']}")
    return lines


def section_for_analysis(analysis: dict[str, Any]) -> list[str]:
    ipo = analysis["ipo"]
    plan = analysis["funding_plan"]
    lines = [f"### {analysis['title']}"]
    lines.extend(
        [
            "| 项目 | 结论 |",
            "|---|---|",
            f"| 推荐 | {analysis['category']} |",
            f"| 置信度 | {analysis['confidence']}（评分 {analysis['score']}/100） |",
            f"| 状态 | {ipo_status(ipo) or '待核实'} |",
            f"| 行业 | {clean(ipo.get('industry')) or '待核实'} |",
            f"| 一手入场费 | {money(ipo.get('entry_fee_hkd')) if isinstance(ipo.get('entry_fee_hkd'), (int, float)) else '待核实'} |",
            f"| 锁定窗口 | {format_date_range(plan.get('lock_window', (None, None)))} |",
        ]
    )
    lines.append("")
    lines.append("**为什么这样判断**")
    for item in analysis["evidence"] or ["暂无足够正面证据。"]:
        lines.append(f"- {item}")
    if analysis["missing"]:
        for item in analysis["missing"]:
            lines.append(f"- 数据缺口：{item}")
    lines.append("")
    lines.append("**主要风险**")
    for item in analysis["risks"] or ["暂无明确风险，但仍需核实招股书和最终认购热度。"]:
        lines.append(f"- {item}")
    lines.extend(deep_dive_brief_lines(analysis))
    lines.append("")
    lines.append("**融资判断**")
    lines.append(f"- {plan['summary']}")
    lines.append(f"- 资金锁定：{plan['schedule_status']}")
    lines.append("")
    lines.append("**舆情辅助**")
    sentiment = analysis.get("sentiment")
    if sentiment:
        summary = sentiment.get("summary") or {}
        platforms = summary.get("platforms") or {}
        platform_text = "、".join(f"{key}({value})" for key, value in platforms.items()) or "未标注"
        lines.append(
            f"- 倾向：{clean(summary.get('tilt')) or '未明'}；平台：{platform_text}。舆情只调整置信度，不单独决定推荐。"
        )
    else:
        lines.append("- 未提供或未匹配到舆情摘录。")
    lines.append("")
    lines.append("**来源**")
    lines.extend(markdown_sources(ipo))
    lines.append("")
    return lines


def build_report(
    payload: dict[str, Any],
    *,
    cash_hkd: float,
    margin_multiple: float,
    margin_rate_pct: float | None,
    financing_days: int,
    sentiment: dict[str, Any] | None,
    market_regime_payload: dict[str, Any] | None = None,
    margin_heat_payload: dict[str, Any] | None = None,
    review_payload: dict[str, Any] | None = None,
    deep_dive_payload: dict[str, Any] | list[Any] | None = None,
) -> str:
    as_of = parse_iso_date(payload.get("as_of_date")) or dt.date.today()
    ipos = payload.get("ipos") or []
    analyses = [
        analyze_ipo(
            ipo,
            as_of=as_of,
            sentiment=sentiment_for_ipo(ipo, sentiment),
            market_regime=(market_regime_payload or {}).get("market_regime") if market_regime_payload else None,
            deep_dive=deep_dive_for_ipo(ipo, deep_dive_payload),
        )
        for ipo in ipos
    ]
    attach_review_records(analyses, review_payload)
    analyses = attach_funding_and_schedule(
        analyses,
        cash_hkd=cash_hkd,
        margin_multiple=margin_multiple,
        margin_rate_pct=margin_rate_pct,
        financing_days=financing_days,
        market_regime=(market_regime_payload or {}).get("market_regime") if market_regime_payload else None,
        margin_heat_payload=margin_heat_payload,
    )

    actionable_analyses = [item for item in analyses if is_pre_close_actionable(item)]
    review_or_closed_count = len(analyses) - len(actionable_analyses)
    counts = {
        bucket: sum(1 for item in actionable_analyses if item["category"] == bucket)
        for bucket in ["建议申购", "可选观察", "暂不参与"]
    }
    regime = (market_regime_payload or {}).get("market_regime") or {}
    regime_label = clean(regime.get("label")) or "未提供"
    regime_detail = ""
    if regime:
        regime_detail = (
            f"（最近 {regime.get('sample_size')} 只样本；"
            f"中位首日 {pct_plain(regime.get('median_first_day_pct'))}；"
            f"不涨/破发率 {ratio_plain(regime.get('break_even_or_down_rate'))}）"
        )
    lines = [
        "# 港股打新参考报告",
        "",
        f"生成时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"默认资金：现金 {money(cash_hkd)}；融资倍数 {margin_multiple:g}x；不主动限制票数",
        f"市场温度：{regime_label}{regime_detail}",
        report_data_coverage(analyses),
        "",
        "**一句话结论**",
        (
            f"本次共纳入 {len(analyses)} 只新股，事前推荐区只展示仍可申购的 {len(actionable_analyses)} 只："
            f"建议申购 {counts['建议申购']} 只、可选观察 {counts['可选观察']} 只、暂不参与 {counts['暂不参与']} 只；"
            f"已截止/复盘 {review_or_closed_count} 只单列到上市表现复盘/监控，不进入新的申购或融资动作；"
            "真正限制不是票数，而是同一笔现金在重叠锁定窗口内不能重复使用。"
        ),
        "",
    ]

    if payload.get("sources"):
        failed = [source for source in payload["sources"] if source.get("status") != "ok"]
        if failed:
            lines.append("**数据源提示**")
            for source in failed:
                lines.append(
                    f"- {clean(source.get('name')) or '未知来源'} 抓取失败：{clean(source.get('error')) or '未知错误'}"
                )
            lines.append("")

    for bucket in ["建议申购", "可选观察", "暂不参与"]:
        lines.append(f"## {bucket}")
        bucket_items = [item for item in actionable_analyses if item["category"] == bucket]
        if not bucket_items:
            lines.append("暂无。")
            lines.append("")
            continue
        for analysis in sorted(bucket_items, key=lambda item: -item["score"]):
            lines.extend(section_for_analysis(analysis))

    lines.append("## 临界观察复核清单")
    lines.append("该清单不自动占用乙组资金；它用于在券商融资截止前快速判断观察票是否需要升级到现金/甲组。")
    lines.extend(borderline_review_section(analyses))
    lines.append("")

    lines.append("## 招股书深挖优先队列")
    lines.append("只列仍可申购且可能改变推荐或资金动作的股票；深挖结论应补回理由、风险和融资判断。")
    lines.extend(prospectus_deep_dive_section(analyses))
    lines.append("")

    lines.append("## 融资核价清单")
    lines.append("该清单用于融资截止前集中核实成本和额度；未补齐利率、手续费、额度和截止时间时，不应把乙组候选当成已执行指令。")
    lines.extend(financing_pricing_section(analyses))
    lines.append("")

    lines.append("## 融资锁单时间表")
    lines.append("按招股截止日倒排 T-2/T-1/T-0 动作；券商融资截止可能早于公开招股截止，实际以下单券商为准。")
    lines.extend(financing_lock_timeline_section(analyses, as_of=as_of))
    lines.append("")

    lines.append("## 默认资金排期建议")
    lines.extend(funding_schedule_section(analyses))
    lines.append("")

    lines.append("## 同窗口取舍复核")
    lines.append("只处理仍可申购且默认现金窗口重叠的股票；复核结论必须在券商融资截止前完成，不得使用一手中签率、配售结果、暗盘或首日涨跌。")
    lines.extend(funding_conflict_review_section(analyses))
    lines.append("")

    lines.append("## 资金锁定检查")
    lines.extend(["| 股票 | 锁定窗口 | 预计占用现金 | 结论 |", "|---|---|---:|---|"])
    for analysis in sorted(analyses, key=lambda item: (item["funding_plan"].get("lock_window", (None, None))[0] or dt.date.max, item["title"])):
        plan = analysis["funding_plan"]
        lines.append(
            f"| {analysis['title']} | {format_date_range(plan.get('lock_window', (None, None)))} | "
            f"{money(plan.get('cash_required_hkd'))} | {plan.get('schedule_status')} |"
        )
    lines.append("")

    review_candidates = [
        item
        for item in analyses
        if item.get("subscription_closed")
        or item.get("review_due")
        or any(keyword in ipo_status(item["ipo"]) for keyword in ["已上市", "暗盘", "今日上市"])
        or item.get("review_record")
        or parse_iso_date(item["ipo"].get("listing_date")) and parse_iso_date(item["ipo"].get("listing_date")) <= as_of
    ]
    lines.append("## 上市表现复盘")
    if review_candidates:
        for item in review_candidates:
            lines.append(review_line(item))
    else:
        lines.append("- 暂未识别到已上市且具备表现数据的新股。")
    lines.append("")

    lines.append("## 数据缺口与下一步")
    if not market_regime_payload:
        lines.append("- 建议先运行市场温度脚本，避免在冷市中机械放大融资。")
    if not margin_heat_payload:
        lines.append("- 融资执行前建议补充券商孖展、额度、利率和截止时间摘录，并用融资热度归一化脚本生成 JSON。")
    if review_candidates and not any(item.get("review_record") for item in review_candidates):
        lines.append("- 已识别复盘窗口股票，但未提供年度已上市复盘 JSON；可运行年度回测脚本生成 JSON 后用 `--review-json` 合并首日表现。")
    if not deep_dive_payload:
        lines.append("- 对 `建议申购` 或用户指定股票，优先运行招股书深挖脚本并用 `--deep-dive-json` 合并估值、财务、基石和风险信号。")
    lines.append("- 若要纳入小红书/雪球/富途等讨论，请粘贴摘录后用舆情归一化脚本生成 JSON 再合并。")
    lines.append("- 融资前必须补充券商实际利率、手续费、可借额度、融资截止时间和占款天数。")
    lines.append("")
    lines.append(
        "**免责声明** 以上为公开资料整理和研究参考，不构成投资建议；新股申购、中签、融资成本、暗盘和上市后涨跌均存在不确定性。"
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", help="IPO JSON from fetch_current_ipos.py. Use - or omit for stdin.")
    parser.add_argument("--sentiment-json", help="Sentiment JSON from normalize_sentiment_input.py.")
    parser.add_argument("--sentiment-text", help="Raw sentiment text to normalize inline.")
    parser.add_argument("--sentiment-file", help="Text file containing sentiment excerpts.")
    parser.add_argument("--market-regime-json", help="Market regime JSON from estimate_market_regime.py.")
    parser.add_argument("--margin-heat-json", help="Margin heat JSON from normalize_margin_input.py.")
    parser.add_argument("--review-json", help="Year/listing review JSON, usually from backtest_year_ipos.py --json.")
    parser.add_argument("--deep-dive-json", help="Prospectus deep-dive JSON from deep_dive_prospectus.py --json.")
    parser.add_argument("--capital", type=float, default=DEFAULT_CASH_HKD, help="Cash capital in HKD.")
    parser.add_argument(
        "--margin-multiple",
        type=float,
        default=DEFAULT_MARGIN_MULTIPLE,
        help="Gross buying-power multiple. Default 10.",
    )
    parser.add_argument("--margin-rate-pct", type=float, help="Annual financing rate for rough cost estimate.")
    parser.add_argument("--financing-days", type=int, default=7, help="Financing days for rough cost estimate.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = load_json(args.input)
    sentiment = load_sentiment(args)
    market_regime_payload = (
        json.loads(Path(args.market_regime_json).read_text(encoding="utf-8"))
        if args.market_regime_json
        else None
    )
    margin_heat_payload = (
        json.loads(Path(args.margin_heat_json).read_text(encoding="utf-8"))
        if args.margin_heat_json
        else None
    )
    review_payload = (
        json.loads(Path(args.review_json).read_text(encoding="utf-8"))
        if args.review_json
        else None
    )
    deep_dive_payload = (
        json.loads(Path(args.deep_dive_json).read_text(encoding="utf-8"))
        if args.deep_dive_json
        else None
    )
    report = build_report(
        payload,
        cash_hkd=args.capital,
        margin_multiple=args.margin_multiple,
        margin_rate_pct=args.margin_rate_pct,
        financing_days=args.financing_days,
        sentiment=sentiment,
        market_regime_payload=market_regime_payload,
        margin_heat_payload=margin_heat_payload,
        review_payload=review_payload,
        deep_dive_payload=deep_dive_payload,
    )
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
