#!/usr/bin/env python3
"""Audit whether current-report buckets align with the backtested pre-close strategy."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from backtest_year_ipos import optimized_preclose_score
from build_recommendation_report import (
    analyze_ipo,
    clean,
    deep_dive_for_ipo,
    load_json,
    parse_iso_date,
    stock_title,
)


BUCKET_ORDER = {"暂不参与": 0, "可选观察": 1, "建议申购": 2}


def market_regime_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return payload.get("market_regime") if "market_regime" in payload else payload


def bucket_gap(left: str, right: str) -> int:
    return BUCKET_ORDER.get(left, -1) - BUCKET_ORDER.get(right, -1)


def explain_row(analysis: dict[str, Any], backtest_score: dict[str, Any], *, actionable: bool) -> tuple[str, str]:
    report_bucket = analysis["category"]
    backtest_bucket = backtest_score["action"]
    if report_bucket == backtest_bucket:
        return "一致", "即时报告桶位与事前回测模型一致。"
    if not actionable:
        return "上下文差异", "即时报告会把已截止/已上市股票转入观察或复盘；回测模型仍按申购截止前信息评分。"
    if analysis.get("deep_dive"):
        return "深挖覆盖差异", "当前报告合并了招股书深挖 JSON；该差异属于新增事前资料覆盖，不代表基础 2026 回测策略漂移。"

    report_text = "；".join(analysis.get("risks", []) + analysis.get("missing", []))
    backtest_text = "；".join(backtest_score.get("risks", []))
    if "关键发行资料" in report_text or "公开发售" in report_text or "保荐人" in report_text:
        return "需解释", "即时报告的关键发行资料闸门更保守；检查回测样本是否也应使用同一闸门。"
    if "泛软件" in report_text or "泛软件" in backtest_text:
        return "需解释", "泛软件/泛IT保护规则触发位置可能不同；检查市场温度输入是否一致。"
    if bucket_gap(report_bucket, backtest_bucket) < 0:
        return "需修正", "即时报告比事前回测模型更保守；若无资料闸门原因，说明两套策略可能漂移。"
    return "需修正", "即时报告比事前回测模型更激进；回测不能直接证明当前推荐质量。"


def audit_payload(
    payload: dict[str, Any],
    *,
    market_regime: dict[str, Any] | None = None,
    deep_dive_payload: dict[str, Any] | list[Any] | None = None,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    effective_as_of = as_of or parse_iso_date(payload.get("as_of_date")) or dt.date.today()
    rows: list[dict[str, Any]] = []
    for ipo in payload.get("ipos") or payload.get("records") or []:
        analysis = analyze_ipo(
            ipo,
            as_of=effective_as_of,
            sentiment=None,
            market_regime=market_regime,
            deep_dive=deep_dive_for_ipo(ipo, deep_dive_payload),
        )
        backtest_record = dict(ipo)
        if market_regime:
            backtest_record["market_regime"] = market_regime
        backtest_score = optimized_preclose_score(backtest_record)
        actionable = not analysis.get("subscription_closed") and not analysis.get("review_due")
        status, explanation = explain_row(analysis, backtest_score, actionable=actionable)
        aligned = analysis["category"] == backtest_score["action"]
        rows.append(
            {
                "stock": stock_title(ipo),
                "code": clean(ipo.get("code") or ipo.get("canonical_code")),
                "actionable": actionable,
                "status": status,
                "explanation": explanation,
                "current_report": {
                    "bucket": analysis["category"],
                    "score": analysis["score"],
                    "confidence": analysis["confidence"],
                    "risks": analysis.get("risks", []),
                    "missing": analysis.get("missing", []),
                },
                "backtest_preclose": {
                    "bucket": backtest_score["action"],
                    "score": backtest_score["score"],
                    "financing_tier": (backtest_score.get("financing") or {}).get("tier"),
                    "risks": backtest_score.get("risks", []),
                },
                "aligned": aligned,
                "score_delta": round(float(analysis["score"]) - float(backtest_score["score"]), 2),
            }
        )

    actionable_rows = [row for row in rows if row["actionable"]]
    deep_dive_mismatches = [row for row in actionable_rows if row["status"] == "深挖覆盖差异"]
    actionable_mismatches = [
        row
        for row in actionable_rows
        if not row["aligned"] and row["status"] != "深挖覆盖差异"
    ]
    contextual_mismatches = [row for row in rows if not row["actionable"] and not row["aligned"]]
    mismatch_rate = len(actionable_mismatches) / len(actionable_rows) if actionable_rows else 0.0
    if mismatch_rate > 0.2:
        verdict = "需修正：可申购样本的不一致率偏高，2026 回测不能直接代表当前报告策略。"
    elif actionable_mismatches:
        verdict = "基本可用：存在少量可申购样本差异，需逐条解释后再引用回测结论。"
    else:
        verdict = "通过：可申购样本中当前报告与事前回测策略桶位一致。"

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "as_of_date": effective_as_of.isoformat(),
        "market_regime": market_regime or {},
        "summary": {
            "total": len(rows),
            "actionable": len(actionable_rows),
            "actionable_mismatches": len(actionable_mismatches),
            "actionable_mismatch_rate": mismatch_rate,
            "deep_dive_mismatches": len(deep_dive_mismatches),
            "contextual_mismatches": len(contextual_mismatches),
            "verdict": verdict,
        },
        "rows": rows,
    }


def pct(value: float | int | None) -> str:
    if value is None:
        return "待核实"
    return f"{float(value) * 100:.1f}%"


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    regime = payload.get("market_regime") or {}
    lines = [
        "# 港股打新策略一致性审查",
        "",
        f"生成时间：{payload['generated_at']}",
        f"评估日期：{payload['as_of_date']}",
        f"市场温度：{clean(regime.get('label')) or '未提供'}",
        "",
        "**结论**",
        f"- {summary['verdict']}",
        "- 该审查只比较申购前可用信号；已截止/已上市样本只作为上下文差异，不计入可申购不一致率。",
        "- 当前市场调参以 2026 单年回测为主，旧年份最多作为低权重压力测试。",
        "",
        "## 摘要",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 总样本 | {summary['total']} |",
        f"| 可申购样本 | {summary['actionable']} |",
        f"| 可申购不一致 | {summary['actionable_mismatches']} |",
        f"| 可申购不一致率 | {pct(summary['actionable_mismatch_rate'])} |",
        f"| 深挖覆盖差异 | {summary.get('deep_dive_mismatches', 0)} |",
        f"| 已截止/复盘上下文差异 | {summary['contextual_mismatches']} |",
        "",
        "## 差异明细",
        "| 股票 | 范围 | 当前报告 | 2026事前回测 | 分数差 | 状态 | 说明 |",
        "|---|---|---|---|---:|---|---|",
    ]
    rows = payload["rows"]
    if not rows:
        lines.append("| 暂无样本 | - | - | - | - | - | - |")
    for row in rows:
        scope = "可申购" if row["actionable"] else "已截止/复盘"
        current = row["current_report"]
        backtest = row["backtest_preclose"]
        lines.append(
            f"| {row['stock']} | {scope} | {current['bucket']} / {current['score']} | "
            f"{backtest['bucket']} / {backtest['score']} | {row['score_delta']:+.2f} | "
            f"{row['status']} | {row['explanation']} |"
        )
    lines.extend(
        [
            "",
            "## 使用建议",
            "- 若可申购不一致率高于 20%，先修正或解释策略漂移，再引用 2026 回测结果优化阈值。",
            "- 若差异来自招股书深挖 JSON，说明当前报告使用了更完整的事前资料；这类差异应单独复核，不应和基础策略漂移混在一起。",
            "- 若差异主要来自已截止/已上市股票，属于报告上下文处理差异，不代表申购前模型失效。",
            "- 若差异来自关键发行资料闸门、泛软件保护规则或市场温度输入，应优先统一规则，再重新跑 2026 回测。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", help="IPO JSON from fetch_current_ipos.py or cached backtest/current payload.")
    parser.add_argument("--market-regime-json", help="Market regime JSON from estimate_market_regime.py.")
    parser.add_argument("--deep-dive-json", help="Prospectus deep-dive JSON used by the current report.")
    parser.add_argument("--as-of", help="Override assessment date, YYYY-MM-DD.")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_payload = load_json(args.input)
    market_regime_payload = (
        json.loads(Path(args.market_regime_json).read_text(encoding="utf-8"))
        if args.market_regime_json
        else None
    )
    deep_dive_payload = (
        json.loads(Path(args.deep_dive_json).read_text(encoding="utf-8"))
        if args.deep_dive_json
        else None
    )
    as_of = parse_iso_date(args.as_of) if args.as_of else None
    if args.as_of and as_of is None:
        raise SystemExit("--as-of must be YYYY-MM-DD")
    payload = audit_payload(
        input_payload,
        market_regime=market_regime_from_payload(market_regime_payload),
        deep_dive_payload=deep_dive_payload,
        as_of=as_of,
    )
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
