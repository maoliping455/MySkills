#!/usr/bin/env python3
"""Summarize the P0 evidence pack needed before further HK IPO strategy tuning."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import shlex
import sys
from pathlib import Path
from typing import Any

import plan_backtest_next_actions as next_actions
import prepare_borderline_upgrade_template as borderline_template
import prepare_conflict_research_template as conflict_template
import prepare_execution_risk_template as execution_template
import prepare_margin_history_template as margin_template


DOMAIN_ORDER = [
    "margin_history",
    "execution_risk",
    "borderline_upgrade",
    "capital_conflict",
]
DOMAIN_LABELS = {
    "margin_history": "乙组执行验证",
    "execution_risk": "建议申购执行风险",
    "borderline_upgrade": "临界观察升级",
    "capital_conflict": "同窗口资金取舍",
}
DOMAIN_ARTIFACTS = {
    "margin_history": "margin-history-{year}-p0.csv",
    "execution_risk": "execution-risk-{year}.csv",
    "borderline_upgrade": "borderline-upgrade-{year}-p0.csv",
    "capital_conflict": "conflict-research-{year}-p0.csv",
}
DOMAIN_NORMALIZERS = {
    "margin_history": "python scripts/normalize_margin_history.py --input {artifact} > margin-history-{year}.json",
    "execution_risk": "python scripts/normalize_conflict_research_input.py --input {artifact} > execution-risk-{year}.json",
    "borderline_upgrade": "python scripts/normalize_conflict_research_input.py --input {artifact} > borderline-upgrade-{year}.json",
    "capital_conflict": "python scripts/normalize_conflict_research_input.py --input {artifact} > conflict-research-{year}.json",
}
DOMAIN_READINESS = {
    "margin_history": "python scripts/normalize_margin_history.py --input {artifact} --markdown",
    "execution_risk": "python scripts/normalize_conflict_research_input.py --input {artifact} --markdown",
    "borderline_upgrade": "python scripts/normalize_conflict_research_input.py --input {artifact} --markdown",
    "capital_conflict": "python scripts/normalize_conflict_research_input.py --input {artifact} --markdown",
}
DOMAIN_REVIEW = {
    "margin_history": "python scripts/backtest_margin_gate.py --backtest-json {backtest_json} --margin-heat-json margin-history-{year}.json",
    "execution_risk": "python scripts/audit_financing_efficiency.py --input-json {backtest_json} --scenario-json execution-risk-{year}.json --margin-heat-json execution-risk-{year}.json --include scenario --scenario-profile base",
    "borderline_upgrade": "python scripts/audit_financing_efficiency.py --input-json {backtest_json} --scenario-json borderline-upgrade-{year}.json --margin-heat-json borderline-upgrade-{year}.json --include scenario --scenario-profile base",
    "capital_conflict": "python scripts/audit_financing_efficiency.py --input-json {backtest_json} --scenario-json conflict-research-{year}.json --margin-heat-json conflict-research-{year}.json --include scenario --scenario-profile base",
}
CONSOLIDATED_FIELDS = [
    "code",
    "stock",
    "domains",
    "domain_count",
    "score",
    "action",
    "financing_tier",
    "entry_fee_hkd",
    "closing_date",
    "refund_date",
    "priority_reasons",
    "required_checks",
    "observed_at",
    "source_published_at",
    "preclose_confirmed",
    "broker_cutoff_at",
    "margin_multiple",
    "margin_amount_hkd",
    "quota_status",
    "financing_rate_pct",
    "fees_hkd",
    "financing_days",
    "scenario_first_day_pct",
    "scenario_allotment_rate_pct",
    "max_credible_allotment_rate_pct",
    "prospectus_url",
    "valuation_note",
    "peer_comparable_note",
    "cornerstone_lockup_note",
    "hard_tech_validation",
    "demand_validation",
    "source",
    "excerpt",
    "search_attempted_at",
    "search_source",
    "unavailable_reason",
    "search_note",
    "collection_note",
]
MARGIN_REQUIRED_CHECKS = [
    "observed_at",
    "source_published_at",
    "preclose_confirmed",
    "broker_cutoff_at",
    "margin_multiple",
    "margin_amount_hkd",
    "quota_status",
    "financing_rate_pct",
    "source",
    "excerpt",
]


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def shell_join(parts: list[Any]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def number_arg(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def infer_year(payload: dict[str, Any], explicit_year: int | None = None) -> int:
    if explicit_year is not None:
        return explicit_year
    value = payload.get("year")
    if isinstance(value, int):
        return value
    return dt.date.today().year


def split_brokers(value: str | None) -> list[str]:
    if value is None:
        return [""]
    brokers = [item.strip() for item in value.split(",") if item.strip()]
    return brokers or [""]


def code_for(row: dict[str, Any]) -> str:
    return clean(row.get("code") or row.get("canonical_code"))


def stock_label(row: dict[str, Any]) -> str:
    if clean(row.get("stock")):
        return clean(row.get("stock"))
    name = clean(row.get("stock_name"))
    code = code_for(row)
    if name and code:
        return f"{name}（{code}）"
    return name or code or "待核实"


def stock_key(row: dict[str, Any]) -> tuple[str, str]:
    code = code_for(row)
    return (code, "") if code else ("", stock_label(row))


def parse_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def unique_join(values: list[Any], *, sep: str = "、", limit: int | None = None) -> str:
    result: list[str] = []
    for value in values:
        text = clean(value)
        if text and text not in result:
            result.append(text)
    if limit is not None and len(result) > limit:
        return sep.join(result[:limit]) + f"{sep}另{len(result) - limit}项"
    return sep.join(result)


def split_required_checks(value: Any) -> list[str]:
    text = clean(value)
    if not text:
        return []
    for delimiter in ["、", ";", "；", "|"]:
        text = text.replace(delimiter, ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def build_domain_rows(
    backtest_payload: dict[str, Any],
    *,
    cash_hkd: float,
    brokers: list[str],
    margin_heat_payload: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "margin_history": margin_template.build_rows(
            backtest_payload=backtest_payload,
            heat_payload=margin_heat_payload,
            brokers=brokers,
            priority_levels={"P0"},
        ),
        "execution_risk": execution_template.build_rows(
            backtest_payload,
            brokers=brokers,
            cash_hkd=cash_hkd,
            priority_levels={"P0"},
        ),
        "borderline_upgrade": borderline_template.build_rows(
            backtest_payload,
            brokers=brokers,
            priority_levels={"P0"},
        ),
        "capital_conflict": conflict_template.build_rows(
            backtest_payload,
            cash_hkd=cash_hkd,
            include_observation=False,
            brokers=brokers,
            priority_levels={"P0"},
        ),
    }


def consolidated_rows(domain_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for domain in DOMAIN_ORDER:
        for row in domain_rows.get(domain) or []:
            key = stock_key(row)
            item = grouped.setdefault(
                key,
                {
                    "code": code_for(row),
                    "stock": stock_label(row),
                    "domain_keys": [],
                    "domains": [],
                    "scores": [],
                    "actions": [],
                    "financing_tiers": [],
                    "entry_fees": [],
                    "closing_dates": [],
                    "refund_dates": [],
                    "priority_reasons": [],
                    "required_checks": [],
                },
            )
            if domain not in item["domain_keys"]:
                item["domain_keys"].append(domain)
                item["domains"].append(DOMAIN_LABELS[domain])
            item["scores"].append(row.get("score"))
            item["actions"].append(row.get("action"))
            item["financing_tiers"].append(row.get("financing_tier"))
            item["entry_fees"].append(row.get("entry_fee_hkd"))
            item["closing_dates"].append(row.get("closing_date"))
            item["refund_dates"].append(row.get("refund_date"))
            item["priority_reasons"].append(row.get("priority_reasons") or row.get("collection_note"))
            if domain == "margin_history":
                item["required_checks"].extend(MARGIN_REQUIRED_CHECKS)
            else:
                item["required_checks"].extend(split_required_checks(row.get("required_checks")))

    rows: list[dict[str, Any]] = []
    for item in grouped.values():
        score = max([parse_int(value) for value in item["scores"]] or [0])
        entry_fee_values = [value for value in item["entry_fees"] if isinstance(value, (int, float))]
        domain_labels = unique_join(item["domains"])
        required_checks = unique_join(item["required_checks"])
        rows.append(
            {
                "code": item["code"],
                "stock": item["stock"],
                "domains": domain_labels,
                "domain_count": len(item["domain_keys"]),
                "score": score or "",
                "action": unique_join(item["actions"], limit=2),
                "financing_tier": unique_join(item["financing_tiers"], limit=2),
                "entry_fee_hkd": max(entry_fee_values) if entry_fee_values else "",
                "closing_date": unique_join(item["closing_dates"], limit=2),
                "refund_date": unique_join(item["refund_dates"], limit=2),
                "priority_reasons": unique_join(item["priority_reasons"], sep="；", limit=4),
                "required_checks": required_checks,
                "observed_at": "",
                "source_published_at": "",
                "preclose_confirmed": "",
                "broker_cutoff_at": "",
                "margin_multiple": "",
                "margin_amount_hkd": "",
                "quota_status": "",
                "financing_rate_pct": "",
                "fees_hkd": "",
                "financing_days": "",
                "scenario_first_day_pct": "",
                "scenario_allotment_rate_pct": "",
                "max_credible_allotment_rate_pct": "",
                "prospectus_url": "",
                "valuation_note": "",
                "peer_comparable_note": "",
                "cornerstone_lockup_note": "",
                "hard_tech_validation": "",
                "demand_validation": "",
                "source": "",
                "excerpt": "",
                "search_attempted_at": "",
                "search_source": "",
                "unavailable_reason": "",
                "search_note": "",
                "collection_note": "合并P0补采工作表：先按股票填一次申购前时间、来源、融资热度/成本、情景配售率和招股书证据，再拆回对应域模板归一化。",
            }
        )
    return sorted(rows, key=lambda row: (-int(row["domain_count"]), -parse_int(row["score"]), row["stock"]))


def render_consolidated_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CONSOLIDATED_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in CONSOLIDATED_FIELDS})
    return output.getvalue()


def unique_stock_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(stock_key(row), row)
    return unique


def command_for(domain: str, *, year: int, backtest_json: str, cash_hkd: float, brokers_arg: str | None) -> str:
    artifact = DOMAIN_ARTIFACTS[domain].format(year=year)
    if domain == "margin_history":
        parts: list[Any] = [
            "python",
            "scripts/prepare_margin_history_template.py",
            "--backtest-json",
            backtest_json,
            "--priority-levels",
            "P0",
        ]
    elif domain == "execution_risk":
        parts = [
            "python",
            "scripts/prepare_execution_risk_template.py",
            "--input-json",
            backtest_json,
            "--priority-levels",
            "P0",
            "--cash-hkd",
            number_arg(cash_hkd),
        ]
    elif domain == "borderline_upgrade":
        parts = [
            "python",
            "scripts/prepare_borderline_upgrade_template.py",
            "--input-json",
            backtest_json,
            "--priority-levels",
            "P0",
        ]
    else:
        parts = [
            "python",
            "scripts/prepare_conflict_research_template.py",
            "--input-json",
            backtest_json,
            "--priority-levels",
            "P0",
            "--cash-hkd",
            number_arg(cash_hkd),
        ]
    if brokers_arg is not None:
        parts.extend(["--brokers", brokers_arg])
    return f"{shell_join(parts)} > {artifact}"


def readiness_command_for(domain: str, *, year: int) -> str:
    artifact = DOMAIN_ARTIFACTS[domain].format(year=year)
    if domain == "margin_history":
        parts: list[Any] = ["python", "scripts/normalize_margin_history.py", "--input", artifact, "--markdown"]
    else:
        parts = ["python", "scripts/normalize_conflict_research_input.py", "--input", artifact, "--markdown"]
    return shell_join(parts)


def normalize_command_for(domain: str, *, year: int) -> str:
    artifact = DOMAIN_ARTIFACTS[domain].format(year=year)
    if domain == "margin_history":
        parts: list[Any] = ["python", "scripts/normalize_margin_history.py", "--input", artifact]
        output = f"margin-history-{year}.json"
    elif domain == "execution_risk":
        parts = ["python", "scripts/normalize_conflict_research_input.py", "--input", artifact]
        output = f"execution-risk-{year}.json"
    elif domain == "borderline_upgrade":
        parts = ["python", "scripts/normalize_conflict_research_input.py", "--input", artifact]
        output = f"borderline-upgrade-{year}.json"
    else:
        parts = ["python", "scripts/normalize_conflict_research_input.py", "--input", artifact]
        output = f"conflict-research-{year}.json"
    return f"{shell_join(parts)} > {output}"


def review_command_for(domain: str, *, year: int, backtest_json: str) -> str:
    if domain == "margin_history":
        return shell_join(
            [
                "python",
                "scripts/backtest_margin_gate.py",
                "--backtest-json",
                backtest_json,
                "--margin-heat-json",
                f"margin-history-{year}.json",
            ]
        )
    json_name = {
        "execution_risk": f"execution-risk-{year}.json",
        "borderline_upgrade": f"borderline-upgrade-{year}.json",
        "capital_conflict": f"conflict-research-{year}.json",
    }[domain]
    return shell_join(
        [
            "python",
            "scripts/audit_financing_efficiency.py",
            "--input-json",
            backtest_json,
            "--scenario-json",
            json_name,
            "--margin-heat-json",
            json_name,
            "--include",
            "scenario",
            "--scenario-profile",
            "base",
        ]
    )


def domain_summary(domain: str, rows: list[dict[str, Any]], *, year: int, backtest_json: str, cash_hkd: float, brokers_arg: str | None) -> dict[str, Any]:
    unique = unique_stock_rows(rows)
    artifact = DOMAIN_ARTIFACTS[domain].format(year=year)
    return {
        "domain": domain,
        "label": DOMAIN_LABELS[domain],
        "artifact": artifact,
        "row_count": len(rows),
        "stock_count": len(unique),
        "stocks": [
            {
                "code": code_for(row),
                "stock": stock_label(row),
                "score": row.get("score") or "",
                "financing_tier": row.get("financing_tier") or "",
                "priority_reasons": row.get("priority_reasons") or row.get("collection_note") or "",
            }
            for key, row in sorted(unique.items(), key=lambda item: (-(int(item[1].get("score") or 0) if str(item[1].get("score") or "").isdigit() else 0), item[0][1]))
        ],
        "create_command": command_for(domain, year=year, backtest_json=backtest_json, cash_hkd=cash_hkd, brokers_arg=brokers_arg),
        "readiness_command": readiness_command_for(domain, year=year),
        "normalize_command": normalize_command_for(domain, year=year),
        "review_command": review_command_for(domain, year=year, backtest_json=backtest_json),
    }


def overlap_rows(summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_stock: dict[tuple[str, str], list[str]] = {}
    labels: dict[tuple[str, str], str] = {}
    reasons: dict[tuple[str, str], list[str]] = {}
    for domain, summary in summaries.items():
        for stock in summary["stocks"]:
            key = (stock["code"], "") if stock.get("code") else ("", stock["stock"])
            by_stock.setdefault(key, []).append(domain)
            labels.setdefault(key, stock["stock"])
            if clean(stock.get("priority_reasons")):
                reasons.setdefault(key, []).append(clean(stock["priority_reasons"]))
    rows = []
    for key, domains in by_stock.items():
        if len(domains) < 2:
            continue
        rows.append(
            {
                "code": key[0],
                "stock": labels.get(key) or key[1],
                "domains": domains,
                "domain_labels": [DOMAIN_LABELS[domain] for domain in domains],
                "priority_reasons": "；".join(reasons.get(key, [])[:3]),
            }
        )
    return sorted(rows, key=lambda row: (-len(row["domains"]), row["stock"]))


def build_payload(
    backtest_payload: dict[str, Any],
    *,
    backtest_json: str,
    stability_payload: dict[str, Any] | None = None,
    margin_heat_payload: dict[str, Any] | None = None,
    year: int | None = None,
    cash_hkd: float = 550_000.0,
    brokers_arg: str | None = "",
) -> dict[str, Any]:
    resolved_year = infer_year(backtest_payload, year)
    brokers = split_brokers(brokers_arg)
    domain_rows = build_domain_rows(
        backtest_payload,
        cash_hkd=cash_hkd,
        brokers=brokers,
        margin_heat_payload=margin_heat_payload,
    )
    summaries = {
        domain: domain_summary(
            domain,
            domain_rows[domain],
            year=resolved_year,
            backtest_json=backtest_json,
            cash_hkd=cash_hkd,
            brokers_arg=brokers_arg,
        )
        for domain in DOMAIN_ORDER
    }
    consolidated = consolidated_rows(domain_rows)
    unique_stocks = {
        ((stock["code"], "") if stock.get("code") else ("", stock["stock"]))
        for summary in summaries.values()
        for stock in summary["stocks"]
    }
    plan_payload = None
    if stability_payload is not None:
        plan_payload = next_actions.build_payload(
            stability_payload,
            year=resolved_year,
            backtest_json=backtest_json,
            backtest_report=f"backtest-{resolved_year}.md",
        )
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "year": resolved_year,
        "cash_hkd": cash_hkd,
        "broker_rows": brokers,
        "summary": {
            "domain_count": len(DOMAIN_ORDER),
            "p0_unique_stock_count": len(unique_stocks),
            "p0_total_stock_mentions": sum(summary["stock_count"] for summary in summaries.values()),
            "overlap_stock_count": len(overlap_rows(summaries)),
            "consolidated_row_count": len(consolidated),
            "consolidation_reduction": sum(summary["stock_count"] for summary in summaries.values()) - len(consolidated),
        },
        "domains": [summaries[domain] for domain in DOMAIN_ORDER],
        "consolidated_rows": consolidated,
        "consolidated_csv_fields": CONSOLIDATED_FIELDS,
        "overlaps": overlap_rows(summaries),
        "iteration_gate": (plan_payload or {}).get("iteration_gate") or {
            "status": "未提供稳定性审计",
            "threshold_tuning_allowed": False,
            "next_step": "先生成并填回 P0 证据，再重跑稳定性审计。",
        },
        "guardrail": "P0 证据包只组织申购截止前证据。最终超购、一手中签率、配售结果、暗盘和首日表现只能作为复盘标签，不能作为填回依据。",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['year']} 港股打新 P0 证据包",
        "",
        f"生成时间：{payload['generated_at']}",
        f"默认现金：HKD {float(payload['cash_hkd']):,.0f}",
        f"券商行：{','.join(payload['broker_rows']) if any(payload['broker_rows']) else '自填'}",
        f"迭代闸门：{payload['iteration_gate'].get('status')}；允许继续机械调阈值：{'是' if payload['iteration_gate'].get('threshold_tuning_allowed') else '否'}",
        f"防泄露口径：{payload['guardrail']}",
        "",
        "## 总览",
        "| 领域 | P0股票数 | 模板行数 | 生成命令 | 填回检查/归一化 |",
        "|---|---:|---:|---|---|",
    ]
    for domain in payload["domains"]:
        lines.append(
            f"| {domain['label']} | {domain['stock_count']} | {domain['row_count']} | "
            f"`{domain['create_command']}` | `{domain['readiness_command']}` |"
        )
    summary = payload["summary"]
    lines.extend(
        [
            "",
            f"P0 去重股票数：{summary['p0_unique_stock_count']}；跨领域重叠股票：{summary['overlap_stock_count']}；领域内股票提及合计：{summary['p0_total_stock_mentions']}。",
            f"合并补采工作表：{summary['consolidated_row_count']} 行，较领域内提及减少 {summary['consolidation_reduction']} 行。",
            "",
            "## 合并补采工作表",
            "用途：按股票去重收集申购前证据，减少重复录入；填完后仍需拆回对应 P0 域模板并用各自 normalizer 校验。",
            "",
            "| 股票 | 代码 | 领域 | 事前分数 | 需补字段 |",
            "|---|---|---|---:|---|",
        ]
    )
    if not payload["consolidated_rows"]:
        lines.append("| - | - | 暂无 P0 样本 | - | - |")
    for row in payload["consolidated_rows"][:20]:
        lines.append(
            f"| {row['stock']} | {row['code'] or '-'} | {row['domains']} | {row['score'] or '-'} | {row['required_checks'] or '-'} |"
        )
    if len(payload["consolidated_rows"]) > 20:
        lines.append(f"| ... | ... | 另 {len(payload['consolidated_rows']) - 20} 行见 CSV | ... | ... |")
    lines.extend(
        [
            "",
            "## 跨领域重叠",
            "| 股票 | 代码 | 领域 | 主要原因 |",
            "|---|---|---|---|",
        ]
    )
    if not payload["overlaps"]:
        lines.append("| - | - | 暂无重叠 | - |")
    for row in payload["overlaps"]:
        lines.append(
            f"| {row['stock']} | {row['code'] or '-'} | {'、'.join(row['domain_labels'])} | {row['priority_reasons'] or '-'} |"
        )
    lines.extend(["", "## 证据闭环"])
    for domain in payload["domains"]:
        lines.append(f"### {domain['label']}")
        lines.append(f"- 生成 CSV：`{domain['create_command']}`")
        if domain["readiness_command"] != domain["normalize_command"]:
            lines.append(f"- 填回质量检查：`{domain['readiness_command']}`")
        lines.append(f"- 填回后归一化：`{domain['normalize_command']}`")
        lines.append(f"- 复核命令：`{domain['review_command']}`")
    lines.extend(
        [
            "",
            "## 使用结论",
            "- 若 P0 证据仍为 `待填回` 或覆盖率不足，不要继续调建议阈值。",
            "- 若 P0 行被判为 `时间无效` 或 `证据污染`，只能作为复盘备注，不能进入申购前模型。",
            "- P0 可复核或明确是数据缺口后，再扩展 P1；旧年份只做低权重压力测试。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest-json", required=True)
    parser.add_argument("--stability-json", help="Optional audit_backtest_stability.py JSON output.")
    parser.add_argument("--margin-heat-json", action="append", help="Optional normalized margin heat JSON; can be repeated.")
    parser.add_argument("--year", type=int)
    parser.add_argument("--cash-hkd", type=float, default=550_000.0)
    parser.add_argument("--brokers", default="", help="Comma-separated broker names. Default is one blank broker-neutral row.")
    parser.add_argument("--consolidated-csv", action="store_true", help="Output one deduplicated P0 collection row per stock as CSV.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backtest_payload = load_json(args.backtest_json)
    stability_payload = load_json(args.stability_json) if args.stability_json else None
    heat_payload = None
    if args.margin_heat_json:
        heat_payload = margin_template.normalize_heat_payloads([load_json(path) for path in args.margin_heat_json])
    payload = build_payload(
        backtest_payload,
        backtest_json=args.backtest_json,
        stability_payload=stability_payload,
        margin_heat_payload=heat_payload,
        year=args.year,
        cash_hkd=args.cash_hkd,
        brokers_arg=args.brokers,
    )
    if args.consolidated_csv:
        sys.stdout.write(render_consolidated_csv(payload["consolidated_rows"]))
    elif args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
