#!/usr/bin/env python3
"""Run recency-weighted multi-year backtests for the HK IPO skill."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from backtest_year_ipos import (
    FINANCING_TIERS,
    money,
    ratio,
    rescore_year_payload,
    run_year_backtest,
    pct,
)


ACTIONS = ["建议申购", "可选观察", "暂不参与"]


def parse_years(value: str) -> list[int]:
    years = sorted({int(item.strip()) for item in value.split(",") if item.strip()}, reverse=True)
    if not years:
        raise argparse.ArgumentTypeError("Provide at least one year.")
    return years


def recency_weights(years: list[int], decay: float) -> dict[int, float]:
    ordered = sorted(years, reverse=True)
    return {year: decay**index for index, year in enumerate(ordered)}


def quality_adjusted_weights(
    payloads: dict[int, dict[str, Any]],
    weights: dict[int, float],
    *,
    min_detail_rate: float = 0.70,
    min_industry_rate: float = 0.50,
) -> tuple[dict[int, float], list[str]]:
    adjusted = dict(weights)
    notes: list[str] = []
    for year, payload in sorted(payloads.items(), reverse=True):
        records = payload.get("records") or []
        total = len(records)
        if not total:
            adjusted[year] = 0.0
            notes.append(f"{year} 年无可用样本，有效权重设为 0。")
            continue
        data_quality = payload.get("data_quality") or {}
        quality_total = data_quality.get("total") or total
        detail_ok = data_quality.get("detail_ok_count") or 0
        industry_count = data_quality.get("industry_count") or 0
        detail_rate = detail_ok / quality_total if quality_total else 0.0
        industry_rate = industry_count / quality_total if quality_total else 0.0
        if detail_rate < min_detail_rate or industry_rate < min_industry_rate:
            adjusted[year] = 0.0
            notes.append(
                f"{year} 年详情页/行业覆盖不足（详情 {detail_ok}/{quality_total}，行业 {industry_count}/{quality_total}），"
                "有效权重设为 0，仅保留为数据覆盖和跨周期风险提示。"
            )
    return adjusted, notes


def parse_input_json(values: list[str] | None) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for value in values or []:
        if "=" not in value:
            raise argparse.ArgumentTypeError("--input-json must be YEAR=PATH")
        year_text, path = value.split("=", 1)
        mapping[int(year_text)] = path
    return mapping


def weighted_rows(
    payloads: dict[int, dict[str, Any]],
    *,
    weights: dict[int, float],
    section: str,
    labels: list[str],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for label in labels:
        weighted_count = 0.0
        metric_sums = {
            "positive_rate": [0.0, 0.0],
            "strong_rate": [0.0, 0.0],
            "avg_first_day_pct": [0.0, 0.0],
            "median_first_day_pct": [0.0, 0.0],
            "avg_expected_one_lot_pnl_hkd": [0.0, 0.0],
        }
        for year, payload in payloads.items():
            source = payload[section]["by_action"] if section in {"summary", "legacy_summary", "review_summary"} else payload[section]
            row = source[label]
            count = float(row.get("count") or 0)
            weighted = count * weights[year]
            weighted_count += weighted
            for metric, pair in metric_sums.items():
                value = row.get(metric)
                if value is None or count <= 0:
                    continue
                pair[0] += float(value) * weighted
                pair[1] += weighted
        rows[label] = {"weighted_count": weighted_count}
        for metric, pair in metric_sums.items():
            rows[label][metric] = pair[0] / pair[1] if pair[1] else None
    return rows


def yearly_rows(payloads: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for year in sorted(payloads, reverse=True):
        payload = payloads[year]
        apply_row = payload["summary"]["by_action"]["建议申购"]
        b_row = payload["financing_summary"]["乙组候选"]
        rows.append(
            {
                "year": year,
                "sample_count": len(payload["records"]),
                "apply_count": apply_row["count"],
                "apply_positive_rate": apply_row["positive_rate"],
                "apply_strong_rate": apply_row["strong_rate"],
                "apply_avg_first_day_pct": apply_row["avg_first_day_pct"],
                "apply_avg_expected_one_lot_pnl_hkd": apply_row.get("avg_expected_one_lot_pnl_hkd"),
                "false_positive_count": len(payload["summary"]["false_positive"]),
                "false_negative_count": len(payload["summary"]["false_negative"]),
                "b_group_count": b_row["count"],
                "b_group_positive_rate": b_row["positive_rate"],
                "b_group_strong_rate": b_row["strong_rate"],
                "b_group_avg_first_day_pct": b_row["avg_first_day_pct"],
                "b_group_avg_expected_one_lot_pnl_hkd": b_row.get("avg_expected_one_lot_pnl_hkd"),
            }
        )
    return rows


def build_payload(
    *,
    years: list[int],
    decay: float,
    input_json: dict[int, str] | None = None,
    rescore_input: bool = False,
    max_pages: int,
    max_details: int | None,
    timeout: int,
    retries: int,
    delay: float,
    workers: int,
    strong_threshold_pct: float,
    regime_window: int,
    regime_min_samples: int,
) -> dict[str, Any]:
    payloads: dict[int, dict[str, Any]] = {}
    for year in years:
        if input_json and year in input_json:
            with open(input_json[year], encoding="utf-8") as handle:
                payloads[year] = json.load(handle)
            if rescore_input:
                payloads[year] = rescore_year_payload(
                    payloads[year],
                    strong_threshold_pct=strong_threshold_pct,
                    regime_window=regime_window,
                    regime_min_samples=regime_min_samples,
                )
        else:
            payloads[year] = run_year_backtest(
                year=year,
                max_pages=max_pages,
                max_details=max_details,
                timeout=timeout,
                retries=retries,
                delay=delay,
                workers=workers,
                strong_threshold_pct=strong_threshold_pct,
                regime_window=regime_window,
                regime_min_samples=regime_min_samples,
            )
    weights = recency_weights(years, decay)
    effective_weights, quality_weight_notes = quality_adjusted_weights(payloads, weights)
    primary_year = max(years)
    coverage_warnings: list[str] = []
    for year, year_payload in sorted(payloads.items(), reverse=True):
        records = year_payload.get("records") or []
        if not records:
            coverage_warnings.append(f"{year} 年未抓到 AASTOCKS 已上市新股样本，可能是公开分页覆盖不足；该年不会影响加权指标。")
            continue
        data_quality = year_payload.get("data_quality") or {}
        total = data_quality.get("total") or len(records)
        detail_ok = data_quality.get("detail_ok_count") or 0
        hkex_docs = data_quality.get("hkex_document_count") or 0
        hkex_reports = data_quality.get("hkex_listing_report_count") or 0
        industry_count = data_quality.get("industry_count") or 0
        if total and detail_ok / total < 0.7:
            coverage_warnings.append(
                f"{year} 年详情页成功率偏低（{detail_ok}/{total}，HKEX文档/报告 {hkex_docs}/{total}，年度报告匹配 {hkex_reports}），"
                f"行业字段 {industry_count}/{total}；该年推荐分层可能偏保守，调参前应重试详情页或补充招股书摘要。"
            )
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "years": years,
        "primary_year": primary_year,
        "weights": weights,
        "effective_weights": effective_weights,
        "quality_weight_notes": quality_weight_notes,
        "strong_threshold_pct": strong_threshold_pct,
        "yearly": yearly_rows(payloads),
        "coverage_warnings": coverage_warnings,
        "weighted_summary": weighted_rows(payloads, weights=effective_weights, section="summary", labels=ACTIONS),
        "weighted_legacy_summary": weighted_rows(payloads, weights=effective_weights, section="legacy_summary", labels=ACTIONS),
        "weighted_financing_summary": weighted_rows(payloads, weights=effective_weights, section="financing_summary", labels=FINANCING_TIERS),
        "year_payloads": payloads,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    years_text = "、".join(str(year) for year in payload["years"])
    primary_year = payload.get("primary_year") or max(payload["years"])
    effective_weights = payload.get("effective_weights") or payload["weights"]
    lines = [
        f"# {years_text} 港股打新多年份回测",
        "",
        f"生成时间：{payload['generated_at']}",
        f"主评估年份：{primary_year}；旧年份只作为低权重压力测试，不直接推翻当前市场有效信号；"
        "当用户强调当前市场或 2026 年时，主结论以单年回测为准。",
        f"近因权重：{', '.join(f'{year}={weight:.2f}' for year, weight in payload['weights'].items())}",
        f"有效权重：{', '.join(f'{year}={effective_weights.get(year, 0):.2f}' for year in payload['weights'])}",
        f"强收益定义：首日涨幅 >= {payload['strong_threshold_pct']:g}%。",
        "",
        "## 年度表现",
        "| 年份 | 样本 | 建议申购 | 申购正收益率 | 申购强收益率 | 申购平均首日 | 申购一手期望 | 错判破发 | 漏掉强收益 | 乙组候选 | 乙组强收益率 | 乙组一手期望 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["yearly"]:
        lines.append(
            f"| {row['year']} | {row['sample_count']} | {row['apply_count']} | "
            f"{ratio(row['apply_positive_rate'])} | {ratio(row['apply_strong_rate'])} | "
            f"{pct(row['apply_avg_first_day_pct'])} | {money(row.get('apply_avg_expected_one_lot_pnl_hkd'))} | "
            f"{row['false_positive_count']} | {row['false_negative_count']} | {row['b_group_count']} | "
            f"{ratio(row['b_group_strong_rate'])} | {money(row.get('b_group_avg_expected_one_lot_pnl_hkd'))} |"
        )
    if payload.get("coverage_warnings"):
        lines.extend(["", "## 数据覆盖提示"])
        for warning in payload["coverage_warnings"]:
            lines.append(f"- {warning}")
    if payload.get("quality_weight_notes"):
        lines.extend(["", "## 数据质量权重"])
        for note in payload["quality_weight_notes"]:
            lines.append(f"- {note}")

    lines.extend(
        [
            "",
            "## 近因加权表现",
            "| 分层 | 加权样本 | 正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for action in ACTIONS:
        row = payload["weighted_summary"][action]
        lines.append(format_weighted_row(action, row))

    lines.extend(["", "## 融资分层近因加权", "| 融资分层 | 加权样本 | 正收益率 | 强收益率 | 平均首日 | 中位首日 | 平均一手期望 |", "|---|---:|---:|---:|---:|---:|---:|"])
    for tier in FINANCING_TIERS:
        row = payload["weighted_financing_summary"][tier]
        lines.append(format_weighted_row(tier, row))

    lines.extend(cross_cycle_financing_notes(payload))

    current_apply = payload["weighted_summary"]["建议申购"]
    legacy_apply = payload["weighted_legacy_summary"]["建议申购"]
    lines.extend(["", "## 专家审查结论"])
    primary_comparison = primary_year_apply_comparison(payload)
    if primary_comparison:
        lines.extend(primary_comparison)
    else:
        lines.append(
            f"- {primary_year} 单年审查：本报告未包含可对比的原策略明细；策略调参仍应以主评估年份单年回测为准。"
        )
    current_first_day = current_apply.get("avg_first_day_pct") or 0
    legacy_first_day = legacy_apply.get("avg_first_day_pct") or 0
    current_pnl = current_apply.get("avg_expected_one_lot_pnl_hkd")
    legacy_pnl = legacy_apply.get("avg_expected_one_lot_pnl_hkd")
    pnl_comparable = isinstance(current_pnl, (int, float)) and isinstance(legacy_pnl, (int, float))
    if current_first_day >= legacy_first_day and (not pnl_comparable or current_pnl >= legacy_pnl):
        lines.append(
            "- 近因加权旁证：当前事前策略的平均首日表现和一手期望不弱于原策略，可以保留现有基础框架。"
        )
    elif current_first_day >= legacy_first_day and pnl_comparable and current_pnl < legacy_pnl:
        lines.append(
            "- 近因加权旁证：当前事前策略的平均首日表现不弱于原策略，但一手期望低于原策略；"
            "下一轮不要只按涨幅优化，应优先审查资金效率、回拨概率和融资成本。"
        )
    else:
        lines.append(
            "- 近因加权旁证：当前事前策略的平均首日表现弱于原策略，下一轮应先审查阈值、行业权重和一手期望资金效率。"
        )
    lines.append("- 策略调整以主评估年份为准；旧年份只用于识别跨周期风险，不应因为早期冷市样本直接削弱当前年有效信号。")
    b_group = payload["weighted_financing_summary"]["乙组候选"]
    a_group = payload["weighted_financing_summary"]["甲组候选"]
    if (b_group.get("strong_rate") or 0) >= (a_group.get("strong_rate") or 0):
        lines.append("- 乙组候选在近因加权强收益率上不弱于甲组候选，但仍必须用融资截止前热度闸门决定是否执行。")
    else:
        lines.append("- 乙组候选未稳定优于甲组候选，乙组只能作为观察队列，不应默认执行。")
    lines.append("- 不要把高热年份里的可选观察大涨样本直接升级为建议申购；这类规则容易在冷市中过拟合。")
    lines.append("- 首日涨幅和一手期望毛利要同时看；若涨幅好但一手期望很低，策略更应该关注资金效率和融资成本。")
    lines.append("- 下一轮最有价值的数据仍是券商孖展时间序列、额度售罄、利率和融资截止时间。")

    lines.extend(
        [
            "",
            "## 来源",
            "- AASTOCKS 已上市新股页及个股详情页。",
            "- HKEX 新上市资料页。",
            "",
            "**免责声明** 本回测基于公开网页抓取和启发式规则，数据可能延迟或缺失，不构成投资建议。",
        ]
    )
    return "\n".join(lines) + "\n"


def primary_year_apply_comparison(payload: dict[str, Any]) -> list[str]:
    primary_year = payload.get("primary_year") or max(payload["years"])
    year_payloads = payload.get("year_payloads") or {}
    year_payload = year_payloads.get(primary_year) or year_payloads.get(str(primary_year))
    if not year_payload:
        return []
    current = ((year_payload.get("summary") or {}).get("by_action") or {}).get("建议申购") or {}
    legacy = ((year_payload.get("legacy_summary") or {}).get("by_action") or {}).get("建议申购") or {}
    if not current or not legacy:
        return []
    current_first_day = current.get("avg_first_day_pct")
    legacy_first_day = legacy.get("avg_first_day_pct")
    current_pnl = current.get("avg_expected_one_lot_pnl_hkd")
    legacy_pnl = legacy.get("avg_expected_one_lot_pnl_hkd")
    if not isinstance(current_first_day, (int, float)) or not isinstance(legacy_first_day, (int, float)):
        return [
            f"- {primary_year} 单年审查：缺少可比较的建议申购首日表现；旧年份不得替代当前年作为调参主证据。"
        ]
    pnl_comparable = isinstance(current_pnl, (int, float)) and isinstance(legacy_pnl, (int, float))
    if current_first_day >= legacy_first_day and (not pnl_comparable or current_pnl >= legacy_pnl):
        return [
            f"- {primary_year} 单年审查：当前策略在建议申购桶的平均首日表现"
            f"（{pct(current_first_day)} vs 原策略 {pct(legacy_first_day)}）"
            + (
                f"和一手期望（{money(current_pnl)} vs 原策略 {money(legacy_pnl)}）"
                if pnl_comparable
                else ""
            )
            + "均不弱；主结论以该年单年回测为准，旧年份只做压力测试。"
        ]
    if current_first_day >= legacy_first_day and pnl_comparable and current_pnl < legacy_pnl:
        return [
            f"- {primary_year} 单年审查：平均首日表现不弱于原策略"
            f"（{pct(current_first_day)} vs {pct(legacy_first_day)}），但一手期望低于原策略"
            f"（{money(current_pnl)} vs {money(legacy_pnl)}）；调参应优先修正资金效率，不按涨幅单点放大融资。"
        ]
    return [
        f"- {primary_year} 单年审查：当前策略建议申购桶平均首日弱于原策略"
        f"（{pct(current_first_day)} vs {pct(legacy_first_day)}）；先复查 2026 样本的行业、保荐人、估值和资金效率阈值，"
        "不要用旧年份样本直接覆盖当前年判断。"
    ]


def format_weighted_row(label: str, row: dict[str, Any]) -> str:
    return (
        f"| {label} | {row['weighted_count']:.1f} | {ratio(row.get('positive_rate'))} | "
        f"{ratio(row.get('strong_rate'))} | {pct(row.get('avg_first_day_pct'))} | "
        f"{pct(row.get('median_first_day_pct'))} | {money(row.get('avg_expected_one_lot_pnl_hkd'))} |"
    )


def cross_cycle_financing_notes(payload: dict[str, Any]) -> list[str]:
    primary_year = payload.get("primary_year") or max(payload["years"])
    yearly = payload.get("yearly") or []
    primary_rows = [row for row in yearly if row.get("year") == primary_year]
    primary_b = primary_rows[0] if primary_rows else {}
    primary_strong = primary_b.get("b_group_strong_rate")
    older_rows = [
        row
        for row in yearly
        if row.get("year") != primary_year and int(row.get("b_group_count") or 0) > 0
    ]
    lines = [
        "",
        "## 跨周期融资压力审查",
        "该段只检查乙组候选是否跨年份稳定；旧年份权重低于当前年，不能直接推翻 2026，但可以约束融资强度。",
    ]
    if not older_rows:
        lines.append("- 旧年份乙组候选样本不足，不能证明乙组跨周期有效；继续把乙组视为 T-1/T-0 热度闸门后的执行动作。")
    else:
        for row in older_rows:
            lines.append(
                f"- {row['year']} 年乙组候选 {row.get('b_group_count', 0)} 只，"
                f"强收益率 {ratio(row.get('b_group_strong_rate'))}，"
                f"平均一手期望 {money(row.get('b_group_avg_expected_one_lot_pnl_hkd'))}。"
            )
        unstable_rows = [
            row
            for row in older_rows
            if isinstance(row.get("b_group_strong_rate"), (int, float))
            and isinstance(primary_strong, (int, float))
            and row["b_group_strong_rate"] + 0.10 < primary_strong
        ]
        weak_pnl_rows = [
            row
            for row in older_rows
            if isinstance(row.get("b_group_avg_expected_one_lot_pnl_hkd"), (int, float))
            and row["b_group_avg_expected_one_lot_pnl_hkd"] < 50
        ]
        if unstable_rows or weak_pnl_rows:
            lines.append(
                "- 压力结论：乙组候选跨周期不稳定；不应默认执行乙组。"
                "2026 热市可以保留乙组候选池，但实盘必须等融资截止前孖展/额度热度、利率和资金窗口同时通过。"
            )
        else:
            lines.append(
                "- 压力结论：旧年份未明显否定乙组候选，但样本仍应服从融资热度闸门和成本闸门。"
            )
    skip_row = (payload.get("weighted_summary") or {}).get("暂不参与") or {}
    if float(skip_row.get("weighted_count") or 0.0) < 5:
        lines.append(
            "- `暂不参与` 的近因加权样本偏少，不要把该组复盘收益解读为应扩大跳过或反向降低阈值。"
        )
    return lines


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_years = ",".join(str(dt.date.today().year - offset) for offset in range(3))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=parse_years, default=parse_years(default_years), help="Comma-separated years, e.g. 2026,2025,2024.")
    parser.add_argument(
        "--decay",
        type=float,
        default=0.15,
        help="Recency weight decay for each older year; default keeps older years as stress tests only.",
    )
    parser.add_argument("--input-json", action="append", help="Reuse a single-year payload as YEAR=PATH. Missing years are fetched.")
    parser.add_argument("--rescore-input", action="store_true", help="Recompute recommendation summaries for --input-json payloads with the current rules.")
    parser.add_argument("--max-pages", type=int, default=13)
    parser.add_argument("--max-details", type=int)
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--strong-threshold-pct", type=float, default=20.0)
    parser.add_argument("--regime-window", type=int, default=20)
    parser.add_argument("--regime-min-samples", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(
        years=args.years,
        decay=args.decay,
        input_json=parse_input_json(args.input_json),
        rescore_input=args.rescore_input,
        max_pages=args.max_pages,
        max_details=args.max_details,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
        workers=args.workers,
        strong_threshold_pct=args.strong_threshold_pct,
        regime_window=args.regime_window,
        regime_min_samples=args.regime_min_samples,
    )
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
