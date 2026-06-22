#!/usr/bin/env python3
"""Audit HK IPO backtest stability and overfitting guardrails."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


ACTIONS = ["建议申购", "可选观察", "暂不参与"]


def clean(value: Any) -> str:
    return str(value or "").strip()


def num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def pct(value: Any) -> str:
    number = num(value)
    return "待核实" if number is None else f"{number:+.2f}%"


def ratio(value: Any) -> str:
    number = num(value)
    return "待核实" if number is None else f"{number * 100:.1f}%"


def money(value: Any) -> str:
    number = num(value)
    return "待核实" if number is None else f"HKD {number:,.0f}"


def finding(code: str, severity: str, message: str, evidence: str = "", recommendation: str = "") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def action_row(payload: dict[str, Any], section: str, action: str) -> dict[str, Any]:
    return (((payload.get(section) or {}).get("by_action") or {}).get(action) or {})


def sample_count(payload: dict[str, Any]) -> int:
    data_quality = payload.get("data_quality") or {}
    return int(data_quality.get("total") or len(payload.get("records") or []))


def data_quality_findings(payload: dict[str, Any], *, min_samples: int) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    total = sample_count(payload)
    if total < min_samples:
        findings.append(
            finding(
                "primary_sample_too_small",
                "error",
                "主评估年份样本数不足，不能作为专家级调参主证据。",
                f"sample_count={total}, required>={min_samples}",
                "先补齐本年样本或降低结论强度，只把结果作为观察。",
            )
        )
    data_quality = payload.get("data_quality") or {}
    if total:
        detail_rate = float(data_quality.get("detail_ok_count") or 0) / total
        industry_rate = float(data_quality.get("industry_count") or 0) / total
        if detail_rate < 0.70 or industry_rate < 0.70:
            findings.append(
                finding(
                    "primary_data_coverage_low",
                    "warning",
                    "主评估年份详情页或行业覆盖不足，评分分层可能偏保守或失真。",
                    f"detail={detail_rate:.1%}, industry={industry_rate:.1%}",
                    "重试 AASTOCKS 详情页，或用 HKEX/招股书摘要补行业、保荐人和发行字段。",
                )
            )
    return findings


def strategy_comparison_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    current = action_row(payload, "summary", "建议申购")
    legacy = action_row(payload, "legacy_summary", "建议申购")
    if not current:
        return [
            finding(
                "missing_apply_summary",
                "error",
                "缺少优化后建议申购摘要，无法审查策略稳定性。",
                "summary.by_action.建议申购 missing",
            )
        ]
    if not legacy:
        findings.append(
            finding(
                "missing_legacy_summary",
                "warning",
                "缺少原策略对照，无法判断本轮优化是否真的优于基线。",
                "legacy_summary.by_action.建议申购 missing",
                "用同一年度 JSON 执行 --rescore-input 后再比较。",
            )
        )
        return findings

    current_first = num(current.get("avg_first_day_pct"))
    legacy_first = num(legacy.get("avg_first_day_pct"))
    current_pnl = num(current.get("avg_expected_one_lot_pnl_hkd"))
    legacy_pnl = num(legacy.get("avg_expected_one_lot_pnl_hkd"))
    first_worse = current_first is not None and legacy_first is not None and current_first + 5 < legacy_first
    pnl_worse = current_pnl is not None and legacy_pnl is not None and current_pnl + 25 < legacy_pnl
    if first_worse and pnl_worse:
        findings.append(
            finding(
                "current_strategy_materially_worse",
                "error",
                "当前策略在主评估年份同时弱于原策略的平均首日和一手期望，不能继续作为优化结论。",
                f"first_day={pct(current_first)} vs {pct(legacy_first)}; one_lot={money(current_pnl)} vs {money(legacy_pnl)}",
                "先回退最近的评分/阈值改动，再用同一 payload 重跑。",
            )
        )
    elif first_worse:
        findings.append(
            finding(
                "current_first_day_worse_than_legacy",
                "warning",
                "当前策略平均首日弱于原策略，需要解释是否换来了更好资金效率。",
                f"first_day={pct(current_first)} vs {pct(legacy_first)}",
                "不要只用近因加权或旧年份掩盖主评估年份退化。",
            )
        )
    elif pnl_worse:
        findings.append(
            finding(
                "current_one_lot_pnl_worse_than_legacy",
                "warning",
                "当前策略一手期望弱于原策略，存在追涨幅而牺牲资金效率的风险。",
                f"one_lot={money(current_pnl)} vs {money(legacy_pnl)}",
                "优先审查资金窗口、回拨概率和融资打平幅度，不要继续放大乙组。",
            )
        )
    else:
        findings.append(
            finding(
                "current_strategy_not_worse_than_legacy",
                "info",
                "当前策略在主评估年份未弱于原策略的核心对照。",
                f"first_day={pct(current_first)} vs {pct(legacy_first)}; one_lot={money(current_pnl)} vs {money(legacy_pnl)}",
            )
        )
    return findings


def bucket_separation_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    apply = action_row(payload, "summary", "建议申购")
    observe = action_row(payload, "summary", "可选观察")
    if not apply or not observe:
        return findings
    apply_first = num(apply.get("avg_first_day_pct"))
    observe_first = num(observe.get("avg_first_day_pct"))
    apply_pnl = num(apply.get("avg_expected_one_lot_pnl_hkd"))
    observe_pnl = num(observe.get("avg_expected_one_lot_pnl_hkd"))
    if (
        apply_first is not None
        and observe_first is not None
        and apply_pnl is not None
        and observe_pnl is not None
        and apply_first <= observe_first
        and apply_pnl <= observe_pnl
    ):
        findings.append(
            finding(
                "recommendation_bucket_not_separated",
                "warning",
                "建议申购没有同时优于可选观察，桶位区分度不足。",
                f"apply={pct(apply_first)}/{money(apply_pnl)}, observe={pct(observe_first)}/{money(observe_pnl)}",
                "不要机械扩大建议申购；先补临界票招股书深挖和 T-1/T-0 热度升级规则。",
            )
        )
    skip = action_row(payload, "summary", "暂不参与")
    if int(skip.get("count") or 0) < 5:
        findings.append(
            finding(
                "skip_bucket_sample_small",
                "warning",
                "暂不参与样本太少，不能用该组收益反推应扩大或缩小跳过范围。",
                f"skip_count={int(skip.get('count') or 0)}",
                "2026 热市下保留观察池，不要用小样本大幅调低或调高跳过阈值。",
            )
        )
    return findings


def score_band_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    bands = payload.get("score_band_summary") or {}
    high = bands.get("78+") or {}
    mid = bands.get("72-77") or {}
    if not high or not mid:
        return [
            finding(
                "score_band_summary_missing",
                "warning",
                "缺少评分分层校准，无法判断是否存在阈值过拟合。",
                "score_band_summary missing",
                "先重跑年度回测并保留 score_band_summary。",
            )
        ]
    findings: list[dict[str, str]] = []
    high_count = int(high.get("count") or 0)
    mid_count = int(mid.get("count") or 0)
    high_proxy_count = high.get("return_proxy_sample_count")
    mid_proxy_count = mid.get("return_proxy_sample_count")
    thin_evidence: list[str] = []
    if min(high_count, mid_count) < 8:
        thin_evidence.append(f"78+ count={high_count}, 72-77 count={mid_count}")
    if isinstance(high_proxy_count, int) and high_count and high_proxy_count / high_count < 0.80:
        thin_evidence.append(f"78+ one_lot_coverage={high_proxy_count}/{high_count}")
    if isinstance(mid_proxy_count, int) and mid_count and mid_proxy_count / mid_count < 0.80:
        thin_evidence.append(f"72-77 one_lot_coverage={mid_proxy_count}/{mid_count}")
    if thin_evidence:
        findings.append(
            finding(
                "score_band_evidence_thin",
                "warning",
                "评分分层样本或一手期望覆盖偏薄，不能据此做大幅阈值调整。",
                "; ".join(thin_evidence),
                "先扩大主评估年份覆盖或补一手期望字段；阈值变化只能小步且需重新跑防泄露审计。",
            )
        )
    high_strong = num(high.get("strong_rate"))
    mid_strong = num(mid.get("strong_rate"))
    high_pnl = num(high.get("avg_expected_one_lot_pnl_hkd"))
    mid_pnl = num(mid.get("avg_expected_one_lot_pnl_hkd"))
    if (
        high_strong is not None
        and mid_strong is not None
        and high_pnl is not None
        and mid_pnl is not None
        and (high_strong <= mid_strong or high_pnl <= mid_pnl)
    ):
        findings.append(
            finding(
                "score_band_non_monotonic",
                "warning",
                "高分段没有稳定优于 72-77 分段，继续调分数阈值有过拟合风险。",
                (
                    f"78+ count={high_count}, strong={ratio(high_strong)}, avg_pnl={money(high_pnl)}; "
                    f"72-77 count={mid_count}, strong={ratio(mid_strong)}, avg_pnl={money(mid_pnl)}"
                ),
                "优先补招股书估值、融资热度、成本和资金窗口规则，而不是机械提高/降低建议阈值。",
            )
        )
    high_median_first = num(high.get("median_first_day_pct"))
    mid_median_first = num(mid.get("median_first_day_pct"))
    high_median_pnl = num(high.get("median_expected_one_lot_pnl_hkd"))
    mid_median_pnl = num(mid.get("median_expected_one_lot_pnl_hkd"))
    if (
        high_median_first is not None
        and mid_median_first is not None
        and high_median_pnl is not None
        and mid_median_pnl is not None
        and high_median_first > mid_median_first + 5
        and high_median_pnl + 25 < mid_median_pnl
    ):
        findings.append(
            finding(
                "score_band_financing_efficiency_divergence",
                "warning",
                "高分段首日中位数更强但一手期望中位数更弱，问题更像配售/融资效率而不是选股阈值。",
                (
                    f"78+ median_first={pct(high_median_first)}, median_one_lot={money(high_median_pnl)}; "
                    f"72-77 median_first={pct(mid_median_first)}, median_one_lot={money(mid_median_pnl)}"
                ),
                "把高分建议申购样本纳入融资成本、情景配售率和打平涨幅复核；不要用首日涨幅中位数直接放大乙组。",
            )
        )
    if findings:
        return findings
    return [
        finding(
            "score_band_calibration_ok",
            "info",
            "评分分层没有触发明显非单调警报。",
            f"78+ strong={ratio(high_strong)}, pnl={money(high_pnl)}; 72-77 strong={ratio(mid_strong)}, pnl={money(mid_pnl)}",
        )
    ]


def margin_coverage_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    coverage = payload.get("margin_history_coverage") or {}
    b_count = int(coverage.get("b_group_candidate_count") or 0)
    if not coverage:
        return [
            finding(
                "margin_history_coverage_missing",
                "warning",
                "缺少历史孖展覆盖审查，乙组执行效果不能被验证。",
                "margin_history_coverage missing",
                "运行 prepare_margin_history_template.py --priority-levels P0 并优先补齐券商时点、额度、利率和截止时间。",
            )
        ]
    rate = num(coverage.get("coverage_rate"))
    if b_count > 0 and (rate is None or rate < 0.70):
        return [
            finding(
                "margin_history_coverage_low",
                "warning",
                "乙组候选缺少足够的申购截止前孖展/额度/利率历史数据，只能验证选股质量，不能证明乙组执行有效。",
                f"b_group={b_count}, coverage={ratio(rate)}",
                "运行 prepare_margin_history_template.py --priority-levels P0，优先补 broker、observed_at、source_published_at、broker_cutoff_at、margin amount/multiple、quota、rate 和 source。",
            )
        ]
    return [
        finding(
            "margin_history_coverage_usable",
            "info",
            "历史孖展覆盖达到基础审查门槛，可进一步比较乙组候选与乙组可执行。",
            f"b_group={b_count}, coverage={ratio(rate)}",
        )
    ]


def capital_window_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    capital = payload.get("capital_schedule") or {}
    if not capital:
        return [
            finding(
                "capital_schedule_missing",
                "warning",
                "缺少资金窗口压力测试，无法验证 55 万现金同窗口不可复用约束。",
                "capital_schedule missing",
                "重跑年度回测并保留 capital_schedule。",
            )
        ]
    selected_avg = num(capital.get("selected_avg_expected_one_lot_pnl_hkd"))
    conflict_avg = num(capital.get("conflict_avg_expected_one_lot_pnl_hkd"))
    selected_strong = num(capital.get("selected_strong_rate"))
    conflict_strong = num(capital.get("conflict_strong_rate"))
    skipped = int(capital.get("conflict_skipped_count") or 0)
    strategy = str(capital.get("priority_strategy") or "").strip()
    if (
        skipped > 0
        and selected_avg is not None
        and conflict_avg is not None
        and conflict_avg > max(selected_avg * 1.25, selected_avg + 50)
    ):
        if strategy == "utility_score_entry":
            return [
                finding(
                    "capital_window_residual_data_gap",
                    "warning",
                    "已使用事前效用组合最优后，被跳过股票平均一手期望仍显著更高；这更像 T-1/T-0 热度、招股书深挖或融资效率数据缺口，不应继续机械调排序代理。",
                    f"strategy={strategy}, selected_avg={money(selected_avg)}, conflict_avg={money(conflict_avg)}, selected_strong={ratio(selected_strong)}, conflict_strong={ratio(conflict_strong)}",
                    "运行 prepare_conflict_research_template.py --priority-levels P0，先补排期边界样本的融资截止前孖展/额度/利率、招股书估值/基石/禁售和融资打平幅度；P0 可复核或明确缺数据后再扩展 P1。",
                )
            ]
        return [
            finding(
                "capital_window_opportunity_cost_high",
                "warning",
                "被资金窗口跳过的股票平均一手期望显著高于排入组合，说明同窗口排序仍有优化空间。",
                f"selected_avg={money(selected_avg)}, conflict_avg={money(conflict_avg)}, selected_strong={ratio(selected_strong)}, conflict_strong={ratio(conflict_strong)}",
                "同窗口冲突时强制比较招股书深挖、T-1/T-0 孖展热度、额度紧张度、利率/手续费和融资打平幅度。",
            )
        ]
    return [
        finding(
            "capital_window_schedule_usable",
            "info",
            "资金窗口压力测试未触发显著机会成本警报。",
            f"selected_avg={money(selected_avg)}, conflict_avg={money(conflict_avg)}, skipped={skipped}",
        )
    ]


def miss_attribution_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    summary = payload.get("miss_attribution_summary") or {}
    if not summary:
        return [
            finding(
                "miss_attribution_summary_missing",
                "warning",
                "缺少结构化错判归因摘要，难以判断下一轮应改融资闸门、资料覆盖还是评分规则。",
                "miss_attribution_summary missing",
                "重跑年度回测，保留 miss_attribution_summary；不要只凭个股错判继续调阈值。",
            )
        ]
    findings: list[dict[str, str]] = []
    fp_count = int(summary.get("false_positive_count") or 0)
    fn_count = int(summary.get("false_negative_count") or 0)
    fp_top = summary.get("dominant_false_positive") or {}
    fn_top = summary.get("dominant_false_negative") or {}
    fp_share = num(fp_top.get("share"))
    fn_share = num(fn_top.get("share"))
    fp_recommendation = clean(summary.get("false_positive_recommendation"))
    fp_reason = clean(fp_top.get("reason"))
    if any(keyword in f"{fp_recommendation} {fp_reason}" for keyword in ["一手期望", "资金效率", "硬科技", "稀缺题材", "估值", "乙组", "融资", "孖展", "额度", "利率"]):
        fp_recommendation = fp_recommendation.rstrip("。；; ")
        if "prepare_execution_risk_template.py" not in fp_recommendation:
            fp_recommendation = (
                f"{fp_recommendation}；运行 prepare_execution_risk_template.py --priority-levels P0 补逐股融资成本、情景配售率和估值验证，"
                "再用 audit_financing_efficiency.py --scenario-json 审计；P0 可复核或明确缺数据后再扩展 P1。"
            )
    fn_recommendation = clean(summary.get("false_negative_recommendation"))
    fn_reason = clean(fn_top.get("reason"))
    if ("临界" in fn_recommendation or "升级" in fn_recommendation or "临界" in fn_reason or "升级" in fn_reason) and "prepare_borderline_upgrade_template.py" not in fn_recommendation:
        fn_recommendation = fn_recommendation.rstrip("。；; ")
        fn_recommendation = (
            f"{fn_recommendation}；运行 prepare_borderline_upgrade_template.py --priority-levels P0 先生成主年份高临界分补采清单，"
            "再用 normalize_conflict_research_input.py 校验申购前证据；P0 可复核或明确缺数据后再扩展 P1。"
        )
    if fp_count >= 3 and fp_share is not None and fp_share >= 0.50:
        findings.append(
            finding(
                "false_positive_attribution_concentrated",
                "warning",
                "建议申购错判集中在同一归因，下一轮应优先修对应执行闸门，而不是机械调建议阈值。",
                f"count={fp_count}, top={clean(fp_top.get('reason'))}, share={ratio(fp_share)}",
                fp_recommendation,
            )
        )
    if fn_count >= 5 and fn_share is not None and fn_share >= 0.40:
        findings.append(
            finding(
                "false_negative_attribution_concentrated",
                "warning",
                "漏掉强收益集中在同一归因，下一轮应优先完善临界观察/升级复核，而不是直接扩大建议申购。",
                f"count={fn_count}, top={clean(fn_top.get('reason'))}, share={ratio(fn_share)}",
                fn_recommendation,
            )
        )
    if not findings:
        findings.append(
            finding(
                "miss_attribution_distribution_usable",
                "info",
                "结构化错判归因未显示单一错因过度集中。",
                f"false_positive={fp_count}, false_negative={fn_count}",
            )
        )
    return findings


def audit_annual_payload(
    payload: dict[str, Any],
    *,
    primary_year: int,
    min_primary_samples: int,
) -> dict[str, Any]:
    year = int(payload.get("year") or primary_year)
    findings: list[dict[str, str]] = []
    if year != primary_year:
        findings.append(
            finding(
                "non_primary_year_input",
                "warning",
                "输入年度不是主评估年份，不能作为当前策略主结论。",
                f"input_year={year}, primary_year={primary_year}",
                "当前市场优化优先看 2026/当前年，旧年份只作压力测试。",
            )
        )
    findings.extend(data_quality_findings(payload, min_samples=min_primary_samples))
    findings.extend(strategy_comparison_findings(payload))
    findings.extend(bucket_separation_findings(payload))
    findings.extend(score_band_findings(payload))
    findings.extend(margin_coverage_findings(payload))
    findings.extend(capital_window_findings(payload))
    findings.extend(miss_attribution_findings(payload))
    return build_result(
        report_kind="annual",
        primary_year=primary_year,
        audited_year=year,
        findings=findings,
        metrics=annual_metrics(payload),
    )


def year_payloads_from_multi(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = payload.get("year_payloads") or {}
    result: dict[int, dict[str, Any]] = {}
    for key, value in rows.items():
        if isinstance(value, dict):
            result[int(key)] = value
    return result


def audit_multi_year_payload(
    payload: dict[str, Any],
    *,
    primary_year: int,
    min_primary_samples: int,
) -> dict[str, Any]:
    effective_primary = int(payload.get("primary_year") or primary_year)
    year_payloads = year_payloads_from_multi(payload)
    if effective_primary not in year_payloads:
        findings = [
            finding(
                "primary_year_payload_missing",
                "error",
                "多年份回测缺少主评估年份的年度 payload，无法审查当前策略主证据。",
                f"primary_year={effective_primary}",
            )
        ]
        return build_result(
            report_kind="multi-year",
            primary_year=effective_primary,
            audited_year=effective_primary,
            findings=findings,
            metrics={},
        )

    primary_result = audit_annual_payload(
        year_payloads[effective_primary],
        primary_year=effective_primary,
        min_primary_samples=min_primary_samples,
    )
    findings = list(primary_result["findings"])
    effective_weights = {int(k): float(v) for k, v in (payload.get("effective_weights") or {}).items()}
    primary_weight = effective_weights.get(effective_primary)
    older_weights = [weight for year, weight in effective_weights.items() if year != effective_primary]
    if primary_weight is None:
        findings.append(
            finding(
                "effective_weight_missing",
                "error",
                "多年份 payload 缺少主评估年份有效权重。",
                f"primary_year={effective_primary}",
            )
        )
    elif older_weights and max(older_weights) > primary_weight:
        findings.append(
            finding(
                "older_year_overweights_primary",
                "error",
                "旧年份有效权重大于主评估年份，违反当前年优先原则。",
                f"primary={primary_weight:.2f}, max_older={max(older_weights):.2f}",
            )
        )
    else:
        findings.append(
            finding(
                "recency_weighting_respects_primary_year",
                "info",
                "近因有效权重没有压过主评估年份。",
                f"primary_weight={primary_weight:.2f}" if primary_weight is not None else "",
            )
        )

    yearly = payload.get("yearly") or []
    primary_rows = [row for row in yearly if int(row.get("year") or 0) == effective_primary]
    primary_b_strong = num(primary_rows[0].get("b_group_strong_rate")) if primary_rows else None
    unstable_years = []
    weak_pnl_years = []
    for row in yearly:
        year = int(row.get("year") or 0)
        if year == effective_primary or int(row.get("b_group_count") or 0) <= 0:
            continue
        b_strong = num(row.get("b_group_strong_rate"))
        b_pnl = num(row.get("b_group_avg_expected_one_lot_pnl_hkd"))
        if primary_b_strong is not None and b_strong is not None and b_strong + 0.10 < primary_b_strong:
            unstable_years.append(str(year))
        if b_pnl is not None and b_pnl < 50:
            weak_pnl_years.append(str(year))
    if unstable_years or weak_pnl_years:
        findings.append(
            finding(
                "cross_cycle_b_group_unstable",
                "warning",
                "旧年份显示乙组候选跨周期不稳定，不能把 2026 热市乙组候选等同于默认乙组执行。",
                f"weak_strong_years={','.join(unstable_years) or '-'}; weak_pnl_years={','.join(weak_pnl_years) or '-'}",
                "保持乙组为候选池，实盘只在融资截止前热度、成本和资金窗口同时通过时执行。",
            )
        )
    return build_result(
        report_kind="multi-year",
        primary_year=effective_primary,
        audited_year=effective_primary,
        findings=findings,
        metrics=primary_result.get("metrics") or {},
    )


def annual_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    current = action_row(payload, "summary", "建议申购")
    legacy = action_row(payload, "legacy_summary", "建议申购")
    observe = action_row(payload, "summary", "可选观察")
    margin = payload.get("margin_history_coverage") or {}
    capital = payload.get("capital_schedule") or {}
    miss = payload.get("miss_attribution_summary") or {}
    return {
        "sample_count": sample_count(payload),
        "apply_count": current.get("count"),
        "apply_positive_rate": current.get("positive_rate"),
        "apply_strong_rate": current.get("strong_rate"),
        "apply_avg_first_day_pct": current.get("avg_first_day_pct"),
        "apply_avg_expected_one_lot_pnl_hkd": current.get("avg_expected_one_lot_pnl_hkd"),
        "legacy_apply_avg_first_day_pct": legacy.get("avg_first_day_pct"),
        "legacy_apply_avg_expected_one_lot_pnl_hkd": legacy.get("avg_expected_one_lot_pnl_hkd"),
        "observe_avg_first_day_pct": observe.get("avg_first_day_pct"),
        "observe_avg_expected_one_lot_pnl_hkd": observe.get("avg_expected_one_lot_pnl_hkd"),
        "b_group_candidate_count": margin.get("b_group_candidate_count"),
        "margin_coverage_rate": margin.get("coverage_rate"),
        "capital_selected_avg_expected_one_lot_pnl_hkd": capital.get("selected_avg_expected_one_lot_pnl_hkd"),
        "capital_conflict_avg_expected_one_lot_pnl_hkd": capital.get("conflict_avg_expected_one_lot_pnl_hkd"),
        "capital_priority_strategy": capital.get("priority_strategy"),
        "false_positive_count": miss.get("false_positive_count"),
        "false_negative_count": miss.get("false_negative_count"),
    }


def build_result(
    *,
    report_kind: str,
    primary_year: int,
    audited_year: int,
    findings: list[dict[str, str]],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    if errors:
        verdict = "不通过：回测证据不足或当前策略相对基线退化。"
    elif warnings:
        verdict = "通过但需继续补数据/人工审查：不建议继续机械调阈值。"
    else:
        verdict = "通过：未发现显著稳定性或过拟合警报。"
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "report_kind": report_kind,
        "primary_year": primary_year,
        "audited_year": audited_year,
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "infos": sum(1 for item in findings if item["severity"] == "info"),
            "passed": not errors,
            "verdict": verdict,
        },
        "metrics": metrics,
        "findings": findings,
    }


def audit_payload(payload: dict[str, Any], *, primary_year: int, min_primary_samples: int) -> dict[str, Any]:
    if "year_payloads" in payload or "weighted_summary" in payload:
        return audit_multi_year_payload(payload, primary_year=primary_year, min_primary_samples=min_primary_samples)
    return audit_annual_payload(payload, primary_year=primary_year, min_primary_samples=min_primary_samples)


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    metrics = payload.get("metrics") or {}
    lines = [
        "# 港股打新回测稳定性审查",
        "",
        f"生成时间：{payload['generated_at']}",
        f"报告类型：{payload['report_kind']}",
        f"主评估年份：{payload['primary_year']}",
        f"结论：{summary['verdict']} 错误 {summary['errors']}；警告 {summary['warnings']}。",
        "",
        "## 核心指标",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 样本数 | {metrics.get('sample_count', '待核实')} |",
        f"| 建议申购数量 | {metrics.get('apply_count', '待核实')} |",
        f"| 建议申购正收益率 | {ratio(metrics.get('apply_positive_rate'))} |",
        f"| 建议申购强收益率 | {ratio(metrics.get('apply_strong_rate'))} |",
        f"| 建议申购平均首日 | {pct(metrics.get('apply_avg_first_day_pct'))} |",
        f"| 建议申购平均一手期望 | {money(metrics.get('apply_avg_expected_one_lot_pnl_hkd'))} |",
        f"| 原策略建议申购平均首日 | {pct(metrics.get('legacy_apply_avg_first_day_pct'))} |",
        f"| 原策略建议申购平均一手期望 | {money(metrics.get('legacy_apply_avg_expected_one_lot_pnl_hkd'))} |",
        f"| 乙组候选历史孖展覆盖 | {ratio(metrics.get('margin_coverage_rate'))} |",
        f"| 资金排期策略 | {metrics.get('capital_priority_strategy') or '待核实'} |",
        f"| 建议申购错判数 | {metrics.get('false_positive_count', '待核实')} |",
        f"| 漏掉强收益数 | {metrics.get('false_negative_count', '待核实')} |",
        "",
        "## 问题清单",
        "| 级别 | 代码 | 说明 | 证据 | 建议 |",
        "|---|---|---|---|---|",
    ]
    if not payload["findings"]:
        lines.append("| 通过 | - | 未发现稳定性审查问题 | - | - |")
    for item in payload["findings"]:
        evidence = clean(item.get("evidence")).replace("|", "\\|") or "-"
        recommendation = clean(item.get("recommendation")).replace("|", "\\|") or "-"
        lines.append(
            f"| {item['severity']} | {item['code']} | {item['message']} | {evidence} | {recommendation} |"
        )
    lines.extend(
        [
            "",
            "## 使用建议",
            "- 该审查只判断回测证据是否足够稳健，不替代招股书阅读、券商融资核价或舆情去噪。",
            "- 出现 `warning` 时可以继续使用策略，但不要继续机械调阈值；优先补数据或把规则转为融资截止前检查项。",
            "- 出现 `error` 时，不应把本次回测作为专家级优化结论。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", "-i", required=True, help="Annual or multi-year backtest JSON.")
    parser.add_argument("--primary-year", type=int, default=dt.date.today().year)
    parser.add_argument("--min-primary-samples", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = audit_payload(payload, primary_year=args.primary_year, min_primary_samples=args.min_primary_samples)
    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
