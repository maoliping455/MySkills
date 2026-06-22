#!/usr/bin/env python3
"""Audit generated HK IPO reports for expert-review guardrails."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


CURRENT_REQUIRED_SECTIONS = [
    "## 建议申购",
    "## 可选观察",
    "## 暂不参与",
    "## 临界观察复核清单",
    "## 招股书深挖优先队列",
    "## 融资核价清单",
    "## 融资锁单时间表",
    "## 默认资金排期建议",
    "## 同窗口取舍复核",
    "## 资金锁定检查",
    "## 上市表现复盘",
    "## 数据缺口与下一步",
]
BACKTEST_REQUIRED_SECTIONS = [
    "## 资金窗口压力测试",
    "## 排期排序敏感性",
    "## 历史孖展覆盖审查",
    "## 热度闸门复盘代理",
    "## 当前年份专家审查",
    "## 评分分层校准",
]
MULTI_YEAR_REQUIRED_SECTIONS = [
    "## 年度表现",
    "## 近因加权表现",
    "## 融资分层近因加权",
    "## 跨周期融资压力审查",
    "## 专家审查结论",
]
BACKTEST_ATTRIBUTION_HEADINGS = ["## 错误归因", "## 错判归因"]
FORBIDDEN_HEADINGS = ["## 当前新股", "## 当前新股列表", "## 新股列表"]
OLD_MARGIN_GATE_PATTERNS = [
    "至少确认两个强热度信号",
    "两个强热度信号",
    "强信号数量",
]
LEAKAGE_TERMS = ["一手中签率", "配售结果", "暗盘", "首日"]
POST_CLOSE_STATUS_TERMS = ["已截止待上市", "今日暗盘", "暗盘", "今日上市", "已上市"]
SAFE_CONTEXT_TERMS = [
    "不得",
    "不能",
    "不要",
    "只用于",
    "只能用于",
    "复盘",
    "回测",
    "情景",
    "上市表现",
    "市场温度",
    "中位首日",
    "数据覆盖",
    "已上市",
]


def read_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


def section_before(text: str, heading: str) -> str:
    if heading not in text:
        return text
    return text.split(heading, 1)[0]


def finding(code: str, severity: str, message: str, evidence: str = "") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


def missing_sections(text: str, sections: list[str]) -> list[str]:
    return [section for section in sections if section not in text]


def audit_current_report(text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    missing = missing_sections(text, CURRENT_REQUIRED_SECTIONS)
    if missing:
        findings.append(finding("missing_current_sections", "error", "当前推荐报告缺少必备章节。", "、".join(missing)))

    for heading in FORBIDDEN_HEADINGS:
        if heading in text:
            findings.append(finding("raw_current_ipo_dump", "error", "报告不应单独展示当前新股裸列表。", heading))

    header = text.split("**一句话结论**", 1)[0]
    if "现金 HKD 55.00 万" not in header and "现金 HKD 550,000" not in header:
        findings.append(finding("default_cash_missing", "warning", "报告头部未明确默认 HKD 550,000 现金。"))
    if "融资倍数 10x" not in header:
        findings.append(finding("default_margin_missing", "warning", "报告头部未明确默认 10x 融资倍数。"))
    if "不主动限制票数" not in header:
        findings.append(finding("ticket_limit_missing", "warning", "报告头部未明确不主动限制票数。"))

    pre_review = section_before(text, "## 上市表现复盘")
    for pattern in OLD_MARGIN_GATE_PATTERNS:
        if pattern in pre_review:
            findings.append(finding("old_margin_gate_language", "error", "乙组闸门仍使用旧口径，应改为需求/额度类热度信号加成本条件。", pattern))
    if "融资成本可接受" in pre_review and "strong_signals" in pre_review:
        findings.append(finding("cost_as_heat_signal", "error", "报告疑似把融资成本可接受放入热度信号。"))
    if "乙组可执行核价" in pre_review:
        if "热度信号" not in pre_review or "成本信号" not in pre_review:
            findings.append(
                finding(
                    "executable_b_group_without_gate_detail",
                    "error",
                    "出现乙组可执行核价时，必须同时展示需求/额度类热度信号和成本信号。",
                )
            )

    for line in pre_review.splitlines():
        if "| 状态 |" in line and any(term in line for term in POST_CLOSE_STATUS_TERMS):
            findings.append(
                finding(
                    "post_close_status_in_recommendation_bucket",
                    "error",
                    "事前推荐区不应展示已截止、暗盘或已上市状态行，应移入上市表现复盘/监控。",
                    line.strip()[:220],
                )
            )
        if any(term in line for term in LEAKAGE_TERMS) and not any(safe in line for safe in SAFE_CONTEXT_TERMS):
            findings.append(
                finding(
                    "possible_future_data_leakage",
                    "warning",
                    "申购/融资决策区出现配售后或上市后词汇，需确认没有作为事前依据。",
                    line.strip()[:220],
                )
            )

    if "## 同窗口取舍复核" in text and "不得使用一手中签率、配售结果、暗盘或首日涨跌" not in text:
        findings.append(finding("same_window_guardrail_missing", "error", "同窗口取舍复核缺少禁止未来数据的明确提示。"))

    if "中文名待核实" in text:
        findings.append(finding("unverified_chinese_names", "warning", "报告仍有中文名待核实股票，应优先补 HKEX/中文来源名称。"))

    return findings


def audit_backtest_report(text: str) -> list[dict[str, str]]:
    if "多年份回测" in text or "## 近因加权表现" in text:
        return audit_multi_year_report(text)
    findings: list[dict[str, str]] = []
    missing = missing_sections(text, BACKTEST_REQUIRED_SECTIONS)
    if not any(heading in text for heading in BACKTEST_ATTRIBUTION_HEADINGS):
        missing.append("## 错误归因/错判归因")
    if missing:
        findings.append(finding("missing_backtest_sections", "error", "年度回测报告缺少必备章节。", "、".join(missing)))
    if "2026" not in text:
        findings.append(finding("current_year_missing", "error", "回测报告未覆盖 2026。"))
    if "旧年份只" not in text and "主评估年份" not in text:
        findings.append(finding("recency_weighting_missing", "warning", "回测报告未明确近年优先、旧年份低权重压力测试。"))
    if "一手期望毛利为复盘口径" not in text and "一手期望" in text:
        findings.append(finding("review_metric_boundary_missing", "warning", "报告包含一手期望指标，但未明确它是复盘口径。"))
    if "未来数据" not in text and "不能泄露进申购前模型" not in text:
        findings.append(finding("future_leakage_boundary_missing", "warning", "回测报告未明确未来数据不能进入事前模型。"))
    if "资金窗口压力测试" in text and "同一锁定窗口现金不可重复使用" not in text:
        findings.append(finding("capital_window_rule_missing", "error", "资金窗口压力测试缺少同窗口现金不可重复使用口径。"))
    if "资金窗口压力测试" in text and "平均一手期望" not in text:
        findings.append(finding("capital_window_average_pnl_missing", "warning", "资金窗口压力测试应同时展示平均一手期望，避免只看合计造成样本数误读。"))
    if "资金窗口压力测试" in text and "一手期望覆盖" not in text:
        findings.append(finding("capital_window_pnl_coverage_missing", "warning", "资金窗口压力测试应说明一手期望平均值的数据覆盖样本数。"))
    if "中文名待核实" in text:
        findings.append(finding("unverified_chinese_names", "warning", "年度回测报告仍有中文名待核实股票，应补中文别名或来源后再作为复盘口径。"))
    return findings


def audit_multi_year_report(text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    missing = missing_sections(text, MULTI_YEAR_REQUIRED_SECTIONS)
    if missing:
        findings.append(finding("missing_multi_year_sections", "error", "多年份回测报告缺少必备章节。", "、".join(missing)))
    if "2026" not in text:
        findings.append(finding("current_year_missing", "error", "多年份回测报告未覆盖 2026。"))
    if "主评估年份" not in text:
        findings.append(finding("primary_year_missing", "error", "多年份回测未明确主评估年份。"))
    if "近因权重" not in text or "有效权重" not in text:
        findings.append(finding("effective_weight_missing", "error", "多年份回测必须同时展示近因权重和有效权重。"))
    if "旧年份只" not in text or "低权重压力测试" not in text:
        findings.append(finding("recency_weighting_missing", "warning", "多年份回测未明确旧年份只作为低权重压力测试。"))
    if "不能直接推翻当前市场有效信号" not in text and "主结论以单年回测为准" not in text:
        findings.append(finding("current_year_priority_missing", "warning", "多年份回测未明确当前年/2026 主结论优先。"))
    if "不应默认执行乙组" not in text and "乙组只能作为观察队列" not in text:
        findings.append(finding("b_group_cross_cycle_gate_missing", "warning", "多年份回测未明确乙组跨周期不应默认执行。"))
    if "一手期望" in text and "融资成本" not in text:
        findings.append(finding("financing_cost_context_missing", "warning", "多年份回测提到一手期望，但未提示融资成本语境。"))
    if "中文名待核实" in text:
        findings.append(finding("unverified_chinese_names", "warning", "多年份回测报告仍有中文名待核实股票，应补中文别名或来源后再作为复盘口径。"))
    expert_section = text.split("## 专家审查结论", 1)[1] if "## 专家审查结论" in text else ""
    if "单年审查" not in expert_section and "主评估年份" not in expert_section:
        findings.append(
            finding(
                "primary_year_expert_conclusion_missing",
                "warning",
                "多年份专家结论应先给出主评估年份单年审查，再把近因加权作为旁证。",
            )
        )
    return findings


def build_payload(text: str, *, report_type: str) -> dict[str, Any]:
    inferred_type = report_type
    if inferred_type == "auto":
        inferred_type = "backtest" if "## 年度表现" in text or "## 评分分层校准" in text else "current"
    if inferred_type == "current":
        findings = audit_current_report(text)
    elif inferred_type == "backtest":
        findings = audit_backtest_report(text)
    else:
        findings = audit_current_report(text) + audit_backtest_report(text)
    error_count = sum(1 for item in findings if item["severity"] == "error")
    warning_count = sum(1 for item in findings if item["severity"] == "warning")
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "report_type": inferred_type,
        "summary": {
            "errors": error_count,
            "warnings": warning_count,
            "passed": error_count == 0,
        },
        "findings": findings,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 港股打新报告质量审查",
        "",
        f"生成时间：{payload['generated_at']}",
        f"报告类型：{payload['report_type']}",
        f"结论：{'通过' if summary['passed'] else '不通过'}；错误 {summary['errors']}；警告 {summary['warnings']}",
        "",
        "## 问题清单",
        "| 级别 | 代码 | 说明 | 证据 |",
        "|---|---|---|---|",
    ]
    if not payload["findings"]:
        lines.append("| 通过 | - | 未发现质量审查问题 | - |")
    for item in payload["findings"]:
        evidence = item.get("evidence") or "-"
        evidence = evidence.replace("|", "\\|")
        lines.append(f"| {item['severity']} | {item['code']} | {item['message']} | {evidence} |")
    lines.extend(
        [
            "",
            "说明：该审查只检查报告纪律和显性结构，不替代人工阅读招股书、券商孖展来源和估值判断。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", help="Markdown report path. Reads stdin when omitted.")
    parser.add_argument("--type", choices=["auto", "current", "backtest", "both"], default="auto")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(read_text(args.input), report_type=args.type)
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(payload))
    summary = payload["summary"]
    if summary["errors"] or (args.fail_on_warning and summary["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
