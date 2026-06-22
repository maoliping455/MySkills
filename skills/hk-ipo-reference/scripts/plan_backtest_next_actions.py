#!/usr/bin/env python3
"""Plan expert next actions from HK IPO backtest stability findings."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
RULES = {
    "primary_sample_too_small": {
        "priority": "P0",
        "order": 0,
        "domain": "样本覆盖",
        "action": "补齐主评估年份样本后再做专家结论",
        "command": "python scripts/backtest_year_ipos.py --year {year} --json > {backtest_json}",
        "guardrail": "样本不足时只作为观察，不作为调参依据。",
    },
    "current_strategy_materially_worse": {
        "priority": "P0",
        "order": 1,
        "domain": "策略回退",
        "action": "回退最近评分/阈值改动并用同一 JSON 重跑",
        "command": "python scripts/backtest_year_ipos.py --input-json {backtest_json} --rescore-input",
        "guardrail": "不要用旧年份或重新抓取样本掩盖主年份退化。",
    },
    "margin_history_coverage_low": {
        "priority": "P0",
        "order": 10,
        "domain": "乙组执行验证",
        "action": "优先补 P0 乙组历史孖展、额度、利率和截止时间",
        "command": "python scripts/prepare_margin_history_template.py --backtest-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "只收券商融资截止前证据；最终超购、一手中签率、暗盘和首日表现不得作为热度依据。",
    },
    "margin_history_coverage_missing": {
        "priority": "P0",
        "order": 10,
        "domain": "乙组执行验证",
        "action": "生成 P0 乙组历史孖展补采清单",
        "command": "python scripts/prepare_margin_history_template.py --backtest-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "覆盖率不足只能说明数据缺口，不能证明乙组执行有效。",
    },
    "false_positive_attribution_concentrated": {
        "priority": "P0",
        "order": 20,
        "domain": "建议申购执行风险",
        "action": "补逐股融资成本、情景配售率、估值和需求验证",
        "command": "python scripts/prepare_execution_risk_template.py --input-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "失败样本用于融资降级/估值深挖，不用于简单惩罚所有高分或硬科技票。",
    },
    "false_negative_attribution_concentrated": {
        "priority": "P0",
        "order": 30,
        "domain": "临界观察升级",
        "action": "补临界观察票 T-1/T-0 升级证据",
        "command": "python scripts/prepare_borderline_upgrade_template.py --input-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "可选观察大涨不等于直接降建议阈值；必须用申购前热度、成本和招股书证据升级。",
    },
    "capital_window_residual_data_gap": {
        "priority": "P1",
        "order": 40,
        "domain": "同窗口资金取舍",
        "action": "补残余同窗口冲突组的热度、招股书和融资效率证据",
        "command": "python scripts/prepare_conflict_research_template.py --input-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "不要继续拟合排序代理；首日和一手期望只能用于复盘检验。",
    },
    "capital_window_opportunity_cost_high": {
        "priority": "P1",
        "order": 41,
        "domain": "同窗口资金取舍",
        "action": "审计同窗口冲突并生成补采清单",
        "command": "python scripts/audit_capital_conflicts.py --input-json {backtest_json}",
        "guardrail": "资金窗口替换只能用事前字段，不得用配售后结果。",
    },
    "score_band_non_monotonic": {
        "priority": "P1",
        "order": 50,
        "domain": "分数分层校准",
        "action": "保持阈值不机械调整，转向执行风险和临界升级复核",
        "command": "python scripts/prepare_execution_risk_template.py --input-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "高分段不单调时，不要直接提高或降低建议阈值。",
    },
    "score_band_financing_efficiency_divergence": {
        "priority": "P1",
        "order": 49,
        "domain": "融资/配售效率校准",
        "action": "把高分样本转入融资成本、情景配售率和打平涨幅复核",
        "command": "python scripts/prepare_execution_risk_template.py --input-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "首日中位数更强不能直接证明乙组可执行；一手期望弱时优先查配售概率和融资成本。",
    },
    "recommendation_bucket_not_separated": {
        "priority": "P1",
        "order": 60,
        "domain": "桶位区分",
        "action": "补临界观察深挖和升级证据，增强桶位区分",
        "command": "python scripts/prepare_borderline_upgrade_template.py --input-json {backtest_json} --priority-levels P0 --markdown",
        "guardrail": "不要把观察池整体升级为建议申购。",
    },
    "primary_data_coverage_low": {
        "priority": "P1",
        "order": 70,
        "domain": "结构化数据覆盖",
        "action": "补 HKEX/AASTOCKS/招股书字段覆盖",
        "command": "python scripts/fetch_hkex_listing_reports.py --years {year} --boards Main,GEM --pretty",
        "guardrail": "字段覆盖不足时，不要从缺失字段导致的保守分类反推规则错误。",
    },
    "skip_bucket_sample_small": {
        "priority": "P2",
        "order": 90,
        "domain": "样本解释",
        "action": "保留观察池，不因暂不参与小样本调整跳过阈值",
        "command": "",
        "guardrail": "2026 热市下小样本跳过桶不支持大幅调参。",
    },
}
VERIFY_COMMANDS = [
    "python scripts/audit_preclose_leakage.py --input-json {backtest_json}",
    "python scripts/audit_report_quality.py --input {backtest_report} --type backtest",
    "python scripts/audit_backtest_stability.py --input-json {backtest_json} --primary-year {year}",
]
WORKFLOW_RULES = {
    "margin_history": {
        "domain": "乙组执行验证",
        "artifact": "margin-history-{year}-p0.csv",
        "create_command": "python scripts/prepare_margin_history_template.py --backtest-json {backtest_json} --priority-levels P0 > margin-history-{year}-p0.csv",
        "normalize_command": "python scripts/normalize_margin_history.py --input margin-history-{year}-p0.csv > margin-history-{year}.json",
        "readiness_command": "python scripts/normalize_margin_history.py --input margin-history-{year}-p0.csv --markdown",
        "review_command": "python scripts/backtest_margin_gate.py --backtest-json {backtest_json} --margin-heat-json margin-history-{year}.json",
        "success_criteria": "时间有效覆盖率达到 70% 以上，且乙组候选能拆成闸门满足/不满足/缺数据三组。",
    },
    "execution_risk": {
        "domain": "建议申购执行风险",
        "artifact": "execution-risk-{year}.csv",
        "create_command": "python scripts/prepare_execution_risk_template.py --input-json {backtest_json} --priority-levels P0 > execution-risk-{year}.csv",
        "normalize_command": "python scripts/normalize_conflict_research_input.py --input execution-risk-{year}.csv > execution-risk-{year}.json",
        "readiness_command": "python scripts/normalize_conflict_research_input.py --input execution-risk-{year}.csv --markdown",
        "review_command": "python scripts/audit_financing_efficiency.py --input-json {backtest_json} --scenario-json execution-risk-{year}.json --margin-heat-json execution-risk-{year}.json --include scenario --scenario-profile base",
        "success_criteria": "P0 高分乙组/融资效率样本有申购截止前融资成本、情景配售率、估值/需求证据；不通过样本降级融资或深挖估值，再扩展 P1。",
    },
    "borderline_upgrade": {
        "domain": "临界观察升级",
        "artifact": "borderline-upgrade-{year}-p0.csv",
        "create_command": "python scripts/prepare_borderline_upgrade_template.py --input-json {backtest_json} --priority-levels P0 > borderline-upgrade-{year}-p0.csv",
        "normalize_command": "python scripts/normalize_conflict_research_input.py --input borderline-upgrade-{year}-p0.csv > borderline-upgrade-{year}.json",
        "readiness_command": "python scripts/normalize_conflict_research_input.py --input borderline-upgrade-{year}-p0.csv --markdown",
        "review_command": "python scripts/audit_financing_efficiency.py --input-json {backtest_json} --scenario-json borderline-upgrade-{year}.json --margin-heat-json borderline-upgrade-{year}.json --include scenario --scenario-profile base",
        "success_criteria": "先只把 P0 临界观察样本补到时间有效、无污染、热度/成本/招股书均通过；P0 可复核或明确缺数据后才扩展 P1。不得降低建议阈值。",
    },
    "capital_conflict": {
        "domain": "同窗口资金取舍",
        "artifact": "conflict-research-{year}-p0.csv",
        "create_command": "python scripts/prepare_conflict_research_template.py --input-json {backtest_json} --priority-levels P0 > conflict-research-{year}-p0.csv",
        "normalize_command": "python scripts/normalize_conflict_research_input.py --input conflict-research-{year}-p0.csv > conflict-research-{year}.json",
        "readiness_command": "python scripts/normalize_conflict_research_input.py --input conflict-research-{year}-p0.csv --markdown",
        "review_command": "python scripts/audit_financing_efficiency.py --input-json {backtest_json} --scenario-json conflict-research-{year}.json --margin-heat-json conflict-research-{year}.json --include scenario --scenario-profile base",
        "success_criteria": "先只补 P0 排期边界样本；同窗口替换只能来自申购截止前热度、招股书和融资效率。P0 可复核或明确缺数据后才扩展 P1，不得继续拟合一手期望排序代理。",
    },
}
WORKFLOW_BY_FINDING = {
    "margin_history_coverage_low": "margin_history",
    "margin_history_coverage_missing": "margin_history",
    "false_positive_attribution_concentrated": "execution_risk",
    "score_band_non_monotonic": "execution_risk",
    "score_band_financing_efficiency_divergence": "execution_risk",
    "false_negative_attribution_concentrated": "borderline_upgrade",
    "recommendation_bucket_not_separated": "borderline_upgrade",
    "capital_window_residual_data_gap": "capital_conflict",
    "capital_window_opportunity_cost_high": "capital_conflict",
}


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def infer_year(payload: dict[str, Any], explicit_year: int | None) -> int:
    if explicit_year is not None:
        return explicit_year
    for key in ["primary_year", "audited_year", "year"]:
        value = payload.get(key)
        if isinstance(value, int):
            return value
    return dt.date.today().year


def render_command(template: str, *, year: int, backtest_json: str, backtest_report: str) -> str:
    if not template:
        return ""
    return template.format(year=year, backtest_json=backtest_json, backtest_report=backtest_report)


def action_from_finding(
    finding: dict[str, Any],
    *,
    year: int,
    backtest_json: str,
    backtest_report: str,
) -> dict[str, Any] | None:
    code = clean(finding.get("code"))
    rule = RULES.get(code)
    if not rule:
        severity = clean(finding.get("severity"))
        if severity != "warning" and severity != "error":
            return None
        rule = {
            "priority": "P1" if severity == "warning" else "P0",
            "order": 80,
            "domain": "人工复核",
            "action": clean(finding.get("recommendation")) or clean(finding.get("message")) or code,
            "command": "",
            "guardrail": "先人工复核，不要据此机械调阈值。",
        }
    return {
        "priority": "P0" if clean(finding.get("severity")) == "error" else rule["priority"],
        "order": int(rule.get("order") or 80),
        "domain": rule["domain"],
        "finding_code": code,
        "finding_message": clean(finding.get("message")),
        "evidence": clean(finding.get("evidence")),
        "action": rule["action"],
        "command": render_command(rule["command"], year=year, backtest_json=backtest_json, backtest_report=backtest_report),
        "guardrail": rule["guardrail"],
    }


def dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for action in sorted(
        actions,
        key=lambda item: (PRIORITY_ORDER.get(item["priority"], 9), int(item.get("order") or 80), item["domain"], item["finding_code"]),
    ):
        key = (action["priority"], action["command"] or action["action"])
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result


def build_iteration_gate(actions: list[dict[str, Any]]) -> dict[str, Any]:
    p0_domains = [action["domain"] for action in actions if action["priority"] == "P0"]
    p1_domains = [action["domain"] for action in actions if action["priority"] == "P1"]
    has_strategy_error = any(action["finding_code"] == "current_strategy_materially_worse" for action in actions)
    has_score_warning = any(
        action["finding_code"] in {"score_band_non_monotonic", "score_band_financing_efficiency_divergence"}
        for action in actions
    )
    has_miss_or_margin_gap = any(
        action["finding_code"]
        in {
            "margin_history_coverage_low",
            "margin_history_coverage_missing",
            "false_positive_attribution_concentrated",
            "false_negative_attribution_concentrated",
            "capital_window_residual_data_gap",
        }
        for action in actions
    )

    if has_strategy_error:
        status = "回退策略改动"
        next_step = "先回退或修复导致主年份退化的评分/排期改动，再用同一 JSON 重跑。"
        threshold_allowed = False
    elif p0_domains:
        status = "先补 P0 证据"
        next_step = "暂停继续调阈值；优先补申购截止前孖展、执行风险、临界升级或同窗口证据。"
        threshold_allowed = False
    elif has_score_warning or has_miss_or_margin_gap:
        status = "人工复核后小步迭代"
        next_step = "只允许围绕已定位的数据缺口或执行闸门做小步改动，并保留防泄露审计。"
        threshold_allowed = False
    elif p1_domains:
        status = "小步复核"
        next_step = "可做有限人工复核；不要把单个 warning 当成机械调参指令。"
        threshold_allowed = False
    else:
        status = "可进入下一轮前向测试"
        next_step = "没有稳定性阻断项；可用当前策略生成新报告并继续前向验证。"
        threshold_allowed = True

    return {
        "status": status,
        "next_step": next_step,
        "threshold_tuning_allowed": threshold_allowed,
        "evidence_collection_required": bool(p0_domains or has_miss_or_margin_gap),
        "p0_domains": p0_domains,
        "p1_domains": p1_domains,
        "guardrail": "除非闸门明确允许，否则不要因单年错判继续调分数阈值。",
    }


def build_evidence_workflows(
    actions: list[dict[str, Any]],
    *,
    year: int,
    backtest_json: str,
    backtest_report: str,
) -> list[dict[str, Any]]:
    workflows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        key = WORKFLOW_BY_FINDING.get(action["finding_code"])
        if not key or key in seen:
            continue
        seen.add(key)
        rule = WORKFLOW_RULES[key]
        workflows.append(
            {
                "domain": rule["domain"],
                "artifact": render_command(rule["artifact"], year=year, backtest_json=backtest_json, backtest_report=backtest_report),
                "create_command": render_command(rule["create_command"], year=year, backtest_json=backtest_json, backtest_report=backtest_report),
                "normalize_command": render_command(rule["normalize_command"], year=year, backtest_json=backtest_json, backtest_report=backtest_report),
                "readiness_command": render_command(rule.get("readiness_command", ""), year=year, backtest_json=backtest_json, backtest_report=backtest_report),
                "review_command": render_command(rule["review_command"], year=year, backtest_json=backtest_json, backtest_report=backtest_report),
                "success_criteria": rule["success_criteria"],
            }
        )
    return workflows


def build_payload(
    stability_payload: dict[str, Any],
    *,
    year: int | None = None,
    backtest_json: str = "backtest-2026.json",
    backtest_report: str = "backtest-2026.md",
) -> dict[str, Any]:
    resolved_year = infer_year(stability_payload, year)
    actions = [
        action
        for finding in stability_payload.get("findings") or []
        if (action := action_from_finding(finding, year=resolved_year, backtest_json=backtest_json, backtest_report=backtest_report))
    ]
    actions = dedupe_actions(actions)
    verify = [
        render_command(command, year=resolved_year, backtest_json=backtest_json, backtest_report=backtest_report)
        for command in VERIFY_COMMANDS
    ]
    iteration_gate = build_iteration_gate(actions)
    evidence_workflows = build_evidence_workflows(
        actions,
        year=resolved_year,
        backtest_json=backtest_json,
        backtest_report=backtest_report,
    )
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "primary_year": resolved_year,
        "source_summary": stability_payload.get("summary") or {},
        "action_count": len(actions),
        "actions": actions,
        "iteration_gate": iteration_gate,
        "evidence_workflows": evidence_workflows,
        "verify_after_changes": verify,
        "guardrail": (
            f"{resolved_year} 是主评估年份；下一步动作只能采集或使用申购截止前证据。"
            "旧年份最多作为低权重压力测试；最终超购、一手中签率、暗盘和首日表现只可作为复盘标签。"
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 港股打新回测下一步动作计划",
        "",
        f"生成时间：{payload['generated_at']}",
        f"主评估年份：{payload['primary_year']}",
        f"稳定性结论：{(payload.get('source_summary') or {}).get('verdict') or '-'}",
        f"防泄露口径：{payload['guardrail']}",
        f"迭代闸门：{payload['iteration_gate']['status']}；{payload['iteration_gate']['next_step']}",
        f"允许继续机械调阈值：{'是' if payload['iteration_gate']['threshold_tuning_allowed'] else '否'}",
        "",
        "| 优先级 | 领域 | 来源 | 动作 | 命令 | 约束 |",
        "|---|---|---|---|---|---|",
    ]
    if not payload["actions"]:
        lines.append("| - | - | - | 暂无下一步动作 | - | - |")
    for item in payload["actions"]:
        command = f"`{item['command']}`" if item.get("command") else "-"
        source = item["finding_code"]
        if item.get("evidence"):
            source = f"{source}: {item['evidence']}"
        lines.append(
            f"| {item['priority']} | {item['domain']} | {source} | {item['action']} | {command} | {item['guardrail']} |"
        )
    lines.extend(["", "## 证据闭环"])
    if not payload.get("evidence_workflows"):
        lines.append("- 暂无需要补采的证据闭环。")
    for item in payload.get("evidence_workflows") or []:
        lines.extend(
            [
                f"### {item['domain']}",
                f"- 生成 CSV：`{item['create_command']}`",
                *([f"- 填回质量检查：`{item['readiness_command']}`"] if item.get("readiness_command") else []),
                f"- 填回后归一化：`{item['normalize_command']}`",
                f"- 复核命令：`{item['review_command']}`",
                f"- 过关标准：{item['success_criteria']}",
            ]
        )
    lines.extend(["", "## 改动后必跑校验"])
    for command in payload["verify_after_changes"]:
        lines.append(f"- `{command}`")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stability-json", "-i", required=True, help="JSON output from audit_backtest_stability.py --json.")
    parser.add_argument("--year", type=int)
    parser.add_argument("--backtest-json", default="backtest-2026.json")
    parser.add_argument("--backtest-report", default="backtest-2026.md")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(
        load_json(args.stability_json),
        year=args.year,
        backtest_json=args.backtest_json,
        backtest_report=args.backtest_report,
    )
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
