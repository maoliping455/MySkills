#!/usr/bin/env python3
"""Aggregate expert-readiness gate for HK IPO strategy iteration."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

import audit_backtest_stability
import audit_preclose_leakage
import audit_report_quality
import normalize_conflict_research_input
import normalize_margin_history
import prepare_margin_history_template as margin_template
import prepare_p0_evidence_pack


P0_DOMAINS = {"margin_history", "execution_risk", "borderline_upgrade", "capital_conflict"}
P0_DOMAIN_LABELS = prepare_p0_evidence_pack.DOMAIN_LABELS
P0_RESEARCH_NEXT_BATCH_STOCK_LIMIT = 5


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def shell_join(parts: list[Any]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def number_arg(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def parse_score(value: Any) -> int:
    try:
        return int(float(clean(value) or 0))
    except ValueError:
        return 0


def normalized_code(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    match = re.search(r"(?<!\d)(\d{1,5})(?:\.HK)?(?!\d)", text, flags=re.IGNORECASE)
    return match.group(1).zfill(5) if match else text.upper()


def normalized_stock_name(value: Any) -> str:
    text = clean(value)
    return re.sub(r"[（(]\s*\d{1,5}(?:\.HK)?\s*[）)]$", "", text, flags=re.IGNORECASE).strip()


def stock_index_key(*, code: Any = "", stock: Any = "") -> tuple[str, str]:
    code_key = normalized_code(code)
    return (code_key, "") if code_key else ("", normalized_stock_name(stock))


def severity_counts(payload: dict[str, Any]) -> dict[str, int]:
    findings = payload.get("findings") or []
    return {
        "errors": sum(1 for item in findings if item.get("severity") == "error"),
        "warnings": sum(1 for item in findings if item.get("severity") == "warning"),
        "infos": sum(1 for item in findings if item.get("severity") == "info"),
    }


def component(
    name: str,
    label: str,
    payload: dict[str, Any],
    *,
    blocks_final: bool,
) -> dict[str, Any]:
    counts = severity_counts(payload)
    return {
        "name": name,
        "label": label,
        "errors": counts["errors"],
        "warnings": counts["warnings"],
        "infos": counts["infos"],
        "blocks_final": blocks_final,
        "verdict": clean((payload.get("summary") or {}).get("verdict"))
        or ("通过" if counts["errors"] == 0 and counts["warnings"] == 0 else "需复核"),
    }


def p0_domain_rows(p0_pack: dict[str, Any], closure_by_domain: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    closure_by_domain = closure_by_domain or {}
    rows = []
    for domain in p0_pack.get("domains") or []:
        stock_count = int(domain.get("stock_count") or 0)
        if stock_count <= 0:
            continue
        closure = closure_by_domain.get(clean(domain.get("domain"))) or {}
        rows.append(
            {
                "domain": domain.get("domain"),
                "label": domain.get("label"),
                "stock_count": stock_count,
                "open_stock_count": int(closure["open_stock_count"]) if "open_stock_count" in closure else stock_count,
                "review_ready_stock_count": int(closure.get("review_ready_stock_count") or 0),
                "accepted_gap_stock_count": int(closure.get("accepted_gap_stock_count") or 0),
                "closure_status": clean(closure.get("status")) or "未提供填回审查",
                "readiness_command": domain.get("readiness_command") or "",
                "create_command": domain.get("create_command") or "",
            }
        )
    return rows


def p0_pack_domain_counts(p0_pack: dict[str, Any]) -> dict[str, int]:
    return {
        clean(domain.get("domain")): int(domain.get("stock_count") or 0)
        for domain in p0_pack.get("domains") or []
    }


def consolidated_row_domains(row: dict[str, Any]) -> list[str]:
    text = clean(row.get("domains"))
    domains = [
        domain
        for domain, label in P0_DOMAIN_LABELS.items()
        if domain in text or label in text
    ]
    return domains


def margin_readiness_counts(payload: dict[str, Any]) -> dict[str, int]:
    counts = {"可复核": 0, "待填回": 0, "时间无效": 0, "证据污染": 0, "已尝试缺口": 0}
    for stock in payload.get("stocks") or []:
        status = normalize_margin_history.stock_status(stock)
        counts[status] = counts.get(status, 0) + 1
    return counts


def generic_readiness_counts(payload: dict[str, Any]) -> dict[str, int]:
    summary = payload.get("summary") or {}
    return {
        "可复核": int(summary.get("review_ready_stock_count") or 0),
        "待填回": int(summary.get("pending_input_stock_count") or 0),
        "缺数据": int(summary.get("missing_data_stock_count") or 0),
        "时间无效": int(summary.get("timing_invalid_stock_count") or 0),
        "证据污染": int(summary.get("evidence_contaminated_stock_count") or 0),
        "已尝试缺口": int(summary.get("attempted_data_gap_stock_count") or 0),
    }


def readiness_stock_index(domain: str, payload: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    if payload is None:
        return {}
    index: dict[tuple[str, str], dict[str, Any]] = {}

    def add(stock: dict[str, Any], *, code: Any = "", name: Any = "") -> None:
        key = stock_index_key(code=code, stock=name)
        if key != ("", ""):
            index[key] = stock
        name_key = stock_index_key(stock=name)
        if name_key != ("", ""):
            index.setdefault(name_key, stock)

    if domain == "margin_history":
        for stock in payload.get("stocks") or []:
            add(
                stock,
                code=stock.get("code"),
                name=stock.get("stock_name") or stock.get("name") or stock.get("stock"),
            )
        return index

    for group in payload.get("groups") or []:
        for stock in group.get("stocks") or []:
            add(stock, code=stock.get("code"), name=stock.get("stock"))
    return index


def readiness_stock_status(domain: str, stock: dict[str, Any] | None) -> tuple[str, list[str]]:
    if stock is None:
        return "未出现在填回审查", ["readiness_row_missing"]
    if domain == "margin_history":
        status = normalize_margin_history.stock_status(stock)
        if status == "待填回":
            return status, ["pending_input"]
        if status == "可复核":
            return status, []
        risks = sorted(
            {
                risk
                for row in stock.get("history_rows") or []
                for risk in [*(row.get("timing_risks") or []), *(row.get("evidence_risks") or [])]
            }
        )
        return status, risks or [status]
    return clean(stock.get("research_status")) or "未出现在填回审查", list(stock.get("missing_fields") or [])


def status_is_open(status: str, *, accept_data_gaps: bool) -> bool:
    if status == "可复核":
        return False
    if accept_data_gaps and status == "已尝试缺口":
        return False
    return True


def next_action_for_status(statuses: dict[str, str], missing_fields: list[str]) -> str:
    status_values = set(statuses.values())
    if "未提供填回审查" in status_values or "未出现在填回审查" in status_values:
        return "先用合并表拆分 CSV，并把拆分结果接入 --p0-readiness-json。"
    if "待填回" in status_values:
        return "优先补 observed_at、source_published_at、preclose_confirmed、broker_cutoff_at、融资热度/成本、情景配售率、来源和摘录。"
    if "缺数据" in status_values:
        return "补齐缺字段：" + "、".join(missing_fields[:8])
    if "时间无效" in status_values:
        return "替换为券商融资截止前可解析到分钟的来源；原行只能做复盘备注。"
    if "证据污染" in status_values:
        return "替换包含配售后/暗盘/首日信息的摘录，只保留申购截止前证据。"
    if "已尝试缺口" in status_values:
        return "若已确认公开申购前证据不可得，可用 --accept-p0-data-gaps 接受该已尝试缺口；否则继续补可用来源。"
    return "复核稳定性 warning 对应证据。"


def build_p0_backlog(
    p0_pack: dict[str, Any],
    *,
    readiness_payloads: dict[str, dict[str, Any]] | None,
    accept_data_gaps: bool,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    readiness_payloads = readiness_payloads or {}
    indexes = {
        domain: readiness_stock_index(domain, readiness_payloads.get(domain))
        for domain in P0_DOMAIN_LABELS
    }
    backlog: list[dict[str, Any]] = []
    for row in p0_pack.get("consolidated_rows") or []:
        domains = consolidated_row_domains(row)
        row_key = stock_index_key(code=row.get("code"), stock=row.get("stock"))
        name_key = stock_index_key(stock=row.get("stock"))
        statuses: dict[str, str] = {}
        missing_by_domain: dict[str, list[str]] = {}
        open_domains: list[str] = []
        for domain in domains:
            if domain not in readiness_payloads:
                status = "未提供填回审查"
                missing = prepare_p0_evidence_pack.split_required_checks(row.get("required_checks")) or ["readiness_payload_missing"]
            else:
                stock = indexes[domain].get(row_key) or indexes[domain].get(name_key)
                status, missing = readiness_stock_status(domain, stock)
            label = P0_DOMAIN_LABELS[domain]
            statuses[label] = status
            if missing:
                missing_by_domain[label] = missing
            if status_is_open(status, accept_data_gaps=accept_data_gaps):
                open_domains.append(label)
        if not open_domains:
            continue
        missing_flat = []
        for fields in missing_by_domain.values():
            for field in fields:
                if field not in missing_flat:
                    missing_flat.append(field)
        backlog.append(
            {
                "stock": normalized_stock_name(row.get("stock")) or row.get("stock") or "",
                "code": row.get("code") or "",
                "score": row.get("score") or "",
                "action": row.get("action") or "",
                "financing_tier": row.get("financing_tier") or "",
                "entry_fee_hkd": row.get("entry_fee_hkd") or "",
                "domain_count": int(row.get("domain_count") or len(domains)),
                "open_domain_count": len(open_domains),
                "open_domains": open_domains,
                "statuses": statuses,
                "missing_fields": missing_flat,
                "priority_reasons": row.get("priority_reasons") or "",
                "required_checks": row.get("required_checks") or "",
                "next_action": next_action_for_status(statuses, missing_flat),
            }
        )
    sorted_backlog = sorted(
        backlog,
        key=lambda item: (
            -int(item.get("open_domain_count") or 0),
            -int(item.get("domain_count") or 0),
            -parse_score(item.get("score")),
            clean(item.get("stock")),
        ),
    )
    return sorted_backlog[:limit] if limit is not None else sorted_backlog


def p0_closure_for_domain(
    domain: str,
    *,
    expected_count: int,
    readiness_payload: dict[str, Any] | None,
    accept_data_gaps: bool,
) -> dict[str, Any]:
    if expected_count <= 0:
        return {
            "domain": domain,
            "expected_stock_count": 0,
            "open_stock_count": 0,
            "review_ready_stock_count": 0,
            "accepted_gap_stock_count": 0,
            "status": "无P0样本",
        }
    if readiness_payload is None:
        return {
            "domain": domain,
            "expected_stock_count": expected_count,
            "open_stock_count": expected_count,
            "review_ready_stock_count": 0,
            "accepted_gap_stock_count": 0,
            "status": "未提供填回审查",
            "counts": {},
        }

    counts = margin_readiness_counts(readiness_payload) if domain == "margin_history" else generic_readiness_counts(readiness_payload)
    review_ready = counts.get("可复核", 0)
    pending = counts.get("待填回", 0)
    hard_gap_count = counts.get("缺数据", 0) + counts.get("时间无效", 0) + counts.get("证据污染", 0)
    attempted_gap_count = counts.get("已尝试缺口", 0)
    accepted_gap = attempted_gap_count if accept_data_gaps else 0
    accounted = review_ready + pending + hard_gap_count + attempted_gap_count
    missing_from_readiness = max(expected_count - accounted, 0)
    open_count = pending + missing_from_readiness + hard_gap_count + (0 if accept_data_gaps else attempted_gap_count)
    status = "已闭环" if open_count == 0 else "待闭环"
    return {
        "domain": domain,
        "expected_stock_count": expected_count,
        "open_stock_count": open_count,
        "review_ready_stock_count": review_ready,
        "accepted_gap_stock_count": accepted_gap,
        "missing_from_readiness_count": missing_from_readiness,
        "status": status,
        "counts": counts,
    }


def build_p0_closure(
    p0_pack: dict[str, Any],
    *,
    readiness_payloads: dict[str, dict[str, Any]] | None,
    accept_data_gaps: bool,
) -> dict[str, Any]:
    readiness_payloads = readiness_payloads or {}
    domain_counts = p0_pack_domain_counts(p0_pack)
    domains = {
        domain: p0_closure_for_domain(
            domain,
            expected_count=domain_counts.get(domain, 0),
            readiness_payload=readiness_payloads.get(domain),
            accept_data_gaps=accept_data_gaps,
        )
        for domain in domain_counts
    }
    return {
        "accept_data_gaps": accept_data_gaps,
        "open_stock_mentions": sum(item["open_stock_count"] for item in domains.values()),
        "review_ready_stock_mentions": sum(item["review_ready_stock_count"] for item in domains.values()),
        "accepted_gap_stock_mentions": sum(item["accepted_gap_stock_count"] for item in domains.values()),
        "open_domain_count": sum(1 for item in domains.values() if item["open_stock_count"] > 0),
        "domains": domains,
    }


def top_stability_warnings(stability_payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": clean(item.get("code")),
            "message": clean(item.get("message")),
            "recommendation": clean(item.get("recommendation")),
        }
        for item in stability_payload.get("findings") or []
        if item.get("severity") == "warning"
    ]


def expert_readiness_json_command(
    *,
    backtest_json: str,
    stability_ref: str,
    report_ref: str,
    primary_year: int,
    margin_heat_json_paths: list[str] | None = None,
    p0_readiness_args: list[str] | None = None,
    accept_p0_data_gaps: bool = False,
    cash_hkd: float = 550_000.0,
    brokers_arg: str | None = "",
    min_primary_samples: int = 30,
) -> str:
    parts: list[Any] = [
        "python",
        "scripts/audit_expert_readiness.py",
        "--backtest-json",
        backtest_json,
        "--stability-json",
        stability_ref,
        "--report",
        report_ref,
        "--primary-year",
        primary_year,
    ]
    for path in margin_heat_json_paths or []:
        parts.extend(["--margin-heat-json", path])
    for value in p0_readiness_args or []:
        parts.extend(["--p0-readiness-json", value])
    if accept_p0_data_gaps:
        parts.append("--accept-p0-data-gaps")
    if cash_hkd != 550_000.0:
        parts.extend(["--cash-hkd", number_arg(cash_hkd)])
    if clean(brokers_arg):
        parts.extend(["--brokers", clean(brokers_arg)])
    if min_primary_samples != 30:
        parts.extend(["--min-primary-samples", min_primary_samples])
    parts.append("--json")
    return f"{shell_join(parts)} > expert-readiness-{primary_year}.json"


def p0_evidence_pack_command(
    *,
    backtest_json: str,
    stability_ref: str,
    primary_year: int,
    cash_hkd: float,
    brokers_arg: str | None,
    consolidated_csv: bool = False,
) -> str:
    parts: list[Any] = [
        "python",
        "scripts/prepare_p0_evidence_pack.py",
        "--backtest-json",
        backtest_json,
        "--stability-json",
        stability_ref,
    ]
    if cash_hkd != 550_000.0:
        parts.extend(["--cash-hkd", number_arg(cash_hkd)])
    if clean(brokers_arg):
        parts.extend(["--brokers", clean(brokers_arg)])
    if consolidated_csv:
        parts.append("--consolidated-csv")
        return f"{shell_join(parts)} > p0-consolidated-{primary_year}.csv"
    return shell_join(parts)


def p0_evidence_pipeline_command(
    *,
    backtest_json: str,
    stability_ref: str,
    report_ref: str,
    primary_year: int,
    cash_hkd: float,
    brokers_arg: str | None,
    accept_p0_data_gaps: bool = False,
    limit: int | None = None,
) -> str:
    suffix = f"-next-{limit}" if limit is not None else ""
    parts: list[Any] = [
        "python",
        "scripts/run_p0_evidence_pipeline.py",
        "--consolidated",
        f"p0-consolidated-{primary_year}.csv",
        "--ledger",
        f"p0-research-queries{suffix}-{primary_year}.csv",
        "--output-dir",
        f"p0-evidence-run{suffix}-{primary_year}",
        "--backtest-json",
        backtest_json,
        "--stability-json",
        stability_ref,
        "--report",
        report_ref,
        "--primary-year",
        primary_year,
    ]
    if cash_hkd != 550_000.0:
        parts.extend(["--cash-hkd", number_arg(cash_hkd)])
    if clean(brokers_arg):
        parts.extend(["--brokers", clean(brokers_arg)])
    if accept_p0_data_gaps:
        parts.append("--accept-p0-data-gaps")
    return shell_join(parts)


def preclose_leakage_command(*, backtest_json: str, cash_hkd: float) -> str:
    parts: list[Any] = ["python", "scripts/audit_preclose_leakage.py", "--input-json", backtest_json]
    if cash_hkd != 550_000.0:
        parts.extend(["--cash-hkd", number_arg(cash_hkd)])
    return shell_join(parts)


def backtest_stability_command(*, backtest_json: str, primary_year: int, min_primary_samples: int) -> str:
    parts: list[Any] = [
        "python",
        "scripts/audit_backtest_stability.py",
        "--input-json",
        backtest_json,
        "--primary-year",
        primary_year,
    ]
    if min_primary_samples != 30:
        parts.extend(["--min-primary-samples", min_primary_samples])
    return shell_join(parts)


def report_quality_command(*, report_ref: str) -> str:
    return shell_join(["python", "scripts/audit_report_quality.py", "--input", report_ref, "--type", "backtest"])


def p0_research_queries_command(*, primary_year: int, limit: int | None = None, csv: bool = False) -> str:
    parts: list[Any] = [
        "python",
        "scripts/prepare_p0_research_queries.py",
        "--input",
        f"expert-readiness-{primary_year}.json",
    ]
    suffix = ""
    if limit is not None:
        parts.extend(["--limit", limit])
        suffix = f"-next-{limit}"
    if csv:
        parts.append("--csv")
        return f"{shell_join(parts)} > p0-research-queries{suffix}-{primary_year}.csv"
    return shell_join(parts)


def build_payload(
    backtest_payload: dict[str, Any],
    *,
    backtest_json: str,
    primary_year: int,
    stability_payload: dict[str, Any] | None = None,
    report_text: str | None = None,
    margin_heat_payload: dict[str, Any] | None = None,
    p0_readiness_payloads: dict[str, dict[str, Any]] | None = None,
    p0_readiness_args: list[str] | None = None,
    accept_p0_data_gaps: bool = False,
    cash_hkd: float = 550_000.0,
    brokers_arg: str | None = "",
    min_primary_samples: int = 30,
    stability_json_path: str | None = None,
    report_path: str | None = None,
    margin_heat_json_paths: list[str] | None = None,
) -> dict[str, Any]:
    leakage = audit_preclose_leakage.audit_payload(backtest_payload, cash_hkd=cash_hkd)
    stability = stability_payload or audit_backtest_stability.audit_payload(
        backtest_payload,
        primary_year=primary_year,
        min_primary_samples=min_primary_samples,
    )
    report_quality = (
        audit_report_quality.build_payload(report_text, report_type="backtest")
        if report_text is not None
        else {
            "summary": {"errors": 0, "warnings": 0, "passed": True, "verdict": "未提供报告，跳过显性格式审查"},
            "findings": [],
        }
    )
    p0_pack = prepare_p0_evidence_pack.build_payload(
        backtest_payload,
        backtest_json=backtest_json,
        stability_payload=stability,
        margin_heat_payload=margin_heat_payload,
        year=primary_year,
        cash_hkd=cash_hkd,
        brokers_arg=brokers_arg,
    )
    components = [
        component("preclose_leakage", "申购前泄露审计", leakage, blocks_final=True),
        component("report_quality", "报告质量审查", report_quality, blocks_final=True),
        component("backtest_stability", "回测稳定性审查", stability, blocks_final=True),
    ]
    p0_summary = p0_pack.get("summary") or {}
    p0_closure = build_p0_closure(
        p0_pack,
        readiness_payloads=p0_readiness_payloads,
        accept_data_gaps=accept_p0_data_gaps,
    )
    p0_backlog = build_p0_backlog(
        p0_pack,
        readiness_payloads=p0_readiness_payloads,
        accept_data_gaps=accept_p0_data_gaps,
    )
    open_p0_count = int(p0_closure.get("open_stock_mentions") or 0)
    p0_domains = p0_domain_rows(p0_pack, p0_closure.get("domains") or {})
    stability_warning_count = severity_counts(stability)["warnings"]
    component_error_count = sum(item["errors"] for item in components)
    report_warning_count = severity_counts(report_quality)["warnings"]
    blocking_warning_count = stability_warning_count + report_warning_count
    threshold_allowed = bool((p0_pack.get("iteration_gate") or {}).get("threshold_tuning_allowed"))

    findings: list[dict[str, str]] = []
    if component_error_count:
        findings.append(
            {
                "severity": "error",
                "code": "expert_gate_component_errors",
                "message": "基础审计仍有 error，不能作为专家级结论。",
                "recommendation": "先修复泄露、报告质量或稳定性 error，再重新生成报告。",
            }
        )
    if open_p0_count:
        findings.append(
            {
                "severity": "warning",
                "code": "p0_evidence_open",
                "message": f"仍有 {open_p0_count} 条 P0 证据提及需要申购前证据闭环。",
                "recommendation": "先运行 P0 证据包里的生成、填回质量检查、归一化和复核命令；若已尝试但无法补齐，需显式使用 --accept-p0-data-gaps 作为数据缺口接受口径。",
            }
        )
    if stability_warning_count:
        findings.append(
            {
                "severity": "warning",
                "code": "stability_warnings_open",
                "message": f"稳定性审查仍有 {stability_warning_count} 个 warning，说明仍有专家复核项。",
                "recommendation": "按稳定性 warning 对应领域补数据；不要继续机械调建议阈值。",
            }
        )
    if report_warning_count:
        findings.append(
            {
                "severity": "warning",
                "code": "report_quality_warnings_open",
                "message": f"报告质量审查仍有 {report_warning_count} 个 warning。",
                "recommendation": "先补报告纪律或口径说明，再把报告作为专家复盘材料。",
            }
        )

    if component_error_count:
        status = "not_ready"
        verdict = "不通过：基础审计存在 error。"
    elif open_p0_count or blocking_warning_count or not threshold_allowed:
        status = "needs_p0_or_review"
        verdict = "未达专家终局：仍有 P0 证据或稳定性复核方向，不能宣称没有优化空间。"
    else:
        status = "expert_ready"
        verdict = "专家就绪：自动化审计未发现剩余优化方向，可进入前向测试。"

    stability_ref = stability_json_path or f"stability-{primary_year}.json"
    report_ref = report_path or f"backtest-{primary_year}.md"
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "primary_year": primary_year,
        "status": status,
        "summary": {
            "verdict": verdict,
            "expert_satisfied": status == "expert_ready",
            "component_error_count": component_error_count,
            "blocking_warning_count": blocking_warning_count,
            "p0_unique_stock_count": int(p0_summary.get("p0_unique_stock_count") or 0),
            "p0_generated_unique_stock_count": int(p0_summary.get("p0_unique_stock_count") or 0),
            "p0_open_stock_mentions": open_p0_count,
            "p0_review_ready_stock_mentions": int(p0_closure.get("review_ready_stock_mentions") or 0),
            "p0_accepted_gap_stock_mentions": int(p0_closure.get("accepted_gap_stock_mentions") or 0),
            "p0_open_domain_count": int(p0_closure.get("open_domain_count") or 0),
            "p0_total_stock_mentions": int(p0_summary.get("p0_total_stock_mentions") or 0),
            "p0_overlap_stock_count": int(p0_summary.get("overlap_stock_count") or 0),
            "p0_backlog_stock_count": len(p0_backlog),
            "threshold_tuning_allowed": status == "expert_ready" and threshold_allowed,
        },
        "components": components,
        "findings": findings,
        "p0_closure": p0_closure,
        "p0_domains": p0_domains,
        "p0_backlog": p0_backlog,
        "stability_warnings": top_stability_warnings(stability),
        "commands": {
            "expert_readiness_json": expert_readiness_json_command(
                backtest_json=backtest_json,
                stability_ref=stability_ref,
                report_ref=report_ref,
                primary_year=primary_year,
                margin_heat_json_paths=margin_heat_json_paths,
                p0_readiness_args=p0_readiness_args,
                accept_p0_data_gaps=accept_p0_data_gaps,
                cash_hkd=cash_hkd,
                brokers_arg=brokers_arg,
                min_primary_samples=min_primary_samples,
            ),
            "p0_evidence_pack": p0_evidence_pack_command(
                backtest_json=backtest_json,
                stability_ref=stability_ref,
                primary_year=primary_year,
                cash_hkd=cash_hkd,
                brokers_arg=brokers_arg,
            ),
            "p0_consolidated_csv": p0_evidence_pack_command(
                backtest_json=backtest_json,
                stability_ref=stability_ref,
                primary_year=primary_year,
                cash_hkd=cash_hkd,
                brokers_arg=brokers_arg,
                consolidated_csv=True,
            ),
            "p0_research_queries": p0_research_queries_command(primary_year=primary_year),
            "p0_research_next_batch": p0_research_queries_command(
                primary_year=primary_year,
                limit=P0_RESEARCH_NEXT_BATCH_STOCK_LIMIT,
            ),
            "p0_research_ledger_csv": p0_research_queries_command(primary_year=primary_year, csv=True),
            "p0_research_next_batch_csv": p0_research_queries_command(
                primary_year=primary_year,
                limit=P0_RESEARCH_NEXT_BATCH_STOCK_LIMIT,
                csv=True,
            ),
            "p0_evidence_pipeline": p0_evidence_pipeline_command(
                backtest_json=backtest_json,
                stability_ref=stability_ref,
                report_ref=report_ref,
                primary_year=primary_year,
                cash_hkd=cash_hkd,
                brokers_arg=brokers_arg,
                accept_p0_data_gaps=accept_p0_data_gaps,
            ),
            "p0_next_batch_evidence_pipeline": p0_evidence_pipeline_command(
                backtest_json=backtest_json,
                stability_ref=stability_ref,
                report_ref=report_ref,
                primary_year=primary_year,
                cash_hkd=cash_hkd,
                brokers_arg=brokers_arg,
                accept_p0_data_gaps=accept_p0_data_gaps,
                limit=P0_RESEARCH_NEXT_BATCH_STOCK_LIMIT,
            ),
            "preclose_leakage": preclose_leakage_command(backtest_json=backtest_json, cash_hkd=cash_hkd),
            "backtest_stability": backtest_stability_command(
                backtest_json=backtest_json,
                primary_year=primary_year,
                min_primary_samples=min_primary_samples,
            ),
            "report_quality": report_quality_command(report_ref=report_ref),
        },
        "guardrail": "该闸门只聚合申购前可用证据、报告纪律和稳定性警报；不得把最终超购、一手中签率、配售结果、暗盘或首日表现写回申购前模型。",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        f"# {payload['primary_year']} 港股打新专家就绪审计",
        "",
        f"生成时间：{payload['generated_at']}",
        f"结论：{summary['verdict']}",
        f"防泄露口径：{payload['guardrail']}",
        "",
        "## 总览",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 专家满意 | {'是' if summary['expert_satisfied'] else '否'} |",
        f"| 基础审计错误 | {summary['component_error_count']} |",
        f"| 阻塞性警告 | {summary['blocking_warning_count']} |",
        f"| P0 生成去重股票 | {summary.get('p0_generated_unique_stock_count', summary['p0_unique_stock_count'])} |",
        f"| P0 待闭环提及 | {summary.get('p0_open_stock_mentions', summary['p0_unique_stock_count'])} |",
        f"| P0 可复核提及 | {summary.get('p0_review_ready_stock_mentions', 0)} |",
        f"| P0 已接受缺口提及 | {summary.get('p0_accepted_gap_stock_mentions', 0)} |",
        f"| P0 跨领域重叠 | {summary['p0_overlap_stock_count']} |",
        f"| P0 backlog 股票 | {summary.get('p0_backlog_stock_count', 0)} |",
        f"| 允许继续机械调阈值 | {'是' if summary['threshold_tuning_allowed'] else '否'} |",
        "",
        "## 组件审计",
        "| 组件 | 错误 | 警告 | 结论 |",
        "|---|---:|---:|---|",
    ]
    for item in payload["components"]:
        lines.append(f"| {item['label']} | {item['errors']} | {item['warnings']} | {item['verdict']} |")
    lines.extend(["", "## 专家阻塞项", "| 级别 | 代码 | 说明 | 下一步 |", "|---|---|---|---|"])
    if not payload["findings"]:
        lines.append("| 通过 | - | 未发现阻塞项 | 可进入前向测试 |")
    for item in payload["findings"]:
        lines.append(
            f"| {item['severity']} | {item['code']} | {item['message']} | {item['recommendation']} |"
        )
    lines.extend(["", "## P0 证据领域", "| 领域 | P0股票数 | 待闭环 | 可复核 | 已接受缺口 | 状态 | 生成命令 | 填回检查 |", "|---|---:|---:|---:|---:|---|---|---|"])
    if not payload["p0_domains"]:
        lines.append("| - | 0 | 0 | 0 | 0 | - | - | - |")
    for item in payload["p0_domains"]:
        lines.append(
            f"| {item['label']} | {item['stock_count']} | {item['open_stock_count']} | "
            f"{item['review_ready_stock_count']} | {item['accepted_gap_stock_count']} | {item['closure_status']} | "
            f"`{item['create_command']}` | `{item['readiness_command']}` |"
        )
    lines.extend(
        [
            "",
            "## P0 下一批补证据清单",
            "| 股票 | 代码 | 分数 | 待闭环领域 | 状态 | 缺字段/风险 | 下一步 |",
            "|---|---|---:|---|---|---|---|",
        ]
    )
    if not payload.get("p0_backlog"):
        lines.append("| - | - | - | 无 | - | - | - |")
    for item in payload.get("p0_backlog") or []:
        status_text = "；".join(f"{domain}:{status}" for domain, status in item.get("statuses", {}).items())
        missing = "、".join(item.get("missing_fields") or []) or item.get("required_checks") or "-"
        lines.append(
            f"| {item.get('stock') or '-'} | {item.get('code') or '-'} | {item.get('score') or '-'} | "
            f"{'、'.join(item.get('open_domains') or []) or '-'} | {status_text or '-'} | "
            f"{missing} | {item.get('next_action') or '-'} |"
        )
    lines.extend(["", "## 稳定性 warning", "| 代码 | 说明 | 建议 |", "|---|---|---|"])
    if not payload["stability_warnings"]:
        lines.append("| - | 无 | - |")
    for item in payload["stability_warnings"]:
        lines.append(f"| {item['code']} | {item['message']} | {item['recommendation'] or '-'} |")
    commands = payload["commands"]
    lines.extend(
        [
            "",
            "## 复跑命令",
            f"- 专家闸门 JSON：`{commands['expert_readiness_json']}`",
            f"- P0 证据包：`{commands['p0_evidence_pack']}`",
            f"- P0 合并表 CSV：`{commands['p0_consolidated_csv']}`",
            f"- P0 检索清单：`{commands['p0_research_queries']}`",
            f"- P0 下一批检索清单：`{commands['p0_research_next_batch']}`",
            f"- P0 检索台账 CSV：`{commands['p0_research_ledger_csv']}`",
            f"- P0 下一批台账 CSV：`{commands['p0_research_next_batch_csv']}`",
            f"- P0 证据流水线：`{commands['p0_evidence_pipeline']}`",
            f"- P0 下一批证据流水线：`{commands['p0_next_batch_evidence_pipeline']}`",
            f"- 防泄露审计：`{commands['preclose_leakage']}`",
            f"- 稳定性审计：`{commands['backtest_stability']}`",
            f"- 报告质量审计：`{commands['report_quality']}`",
            "",
            "## 使用结论",
            "- `专家满意=否` 时，结论不是策略失败，而是还存在需要补证据或复核的优化方向。",
            "- P0 未闭环前，不要继续机械调建议阈值，也不要把乙组候选写成默认乙组执行。",
            "- 已填回的 P0 证据应通过 `--p0-readiness-json domain=path` 接入；只有 `--accept-p0-data-gaps` 能把已尝试但不可补齐的缺口视作闭环。",
            "- 只有无 error、无阻塞 warning、无 P0 待补证据时，才可称为没有自动化优化方向并进入前向测试。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest-json", required=True)
    parser.add_argument("--stability-json", help="Optional audit_backtest_stability.py --json output.")
    parser.add_argument("--report", help="Optional Markdown backtest report for report-quality audit.")
    parser.add_argument("--margin-heat-json", action="append", help="Optional normalized margin heat JSON; can be repeated.")
    parser.add_argument(
        "--p0-readiness-json",
        action="append",
        help="Optional DOMAIN=path JSON from a normalizer, or CSV split from split_p0_consolidated_input.py. Domains: margin_history, execution_risk, borderline_upgrade, capital_conflict.",
    )
    parser.add_argument("--accept-p0-data-gaps", action="store_true", help="Treat non-pending P0 missing/invalid/contaminated rows as explicitly accepted data gaps.")
    parser.add_argument("--primary-year", type=int, default=dt.date.today().year)
    parser.add_argument("--cash-hkd", type=float, default=550_000.0)
    parser.add_argument("--brokers", default="", help="Comma-separated broker names. Default is one broker-neutral row.")
    parser.add_argument("--min-primary-samples", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def parse_p0_readiness_args(values: list[str] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values or []:
        if "=" not in value:
            raise SystemExit("--p0-readiness-json must be DOMAIN=path")
        domain, path = value.split("=", 1)
        domain = domain.strip()
        if domain not in P0_DOMAINS:
            raise SystemExit(f"Unsupported P0 domain for --p0-readiness-json: {domain}")
        result[domain] = load_p0_readiness_payload(domain, path)
    return result


def load_p0_readiness_payload(domain: str, path: str) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return load_json(path)
    if domain == "margin_history":
        rows = normalize_margin_history.read_rows(path, "auto")
        return normalize_margin_history.normalize_rows(rows)
    rows = normalize_conflict_research_input.read_rows(path, "auto")
    return normalize_conflict_research_input.normalize_rows(rows)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backtest_payload = load_json(args.backtest_json)
    stability_payload = load_json(args.stability_json) if args.stability_json else None
    report_text = Path(args.report).read_text(encoding="utf-8") if args.report else None
    margin_heat_payload = None
    if args.margin_heat_json:
        margin_heat_payload = margin_template.normalize_heat_payloads([load_json(path) for path in args.margin_heat_json])
    p0_readiness_payloads = parse_p0_readiness_args(args.p0_readiness_json)
    payload = build_payload(
        backtest_payload,
        backtest_json=args.backtest_json,
        primary_year=args.primary_year,
        stability_payload=stability_payload,
        report_text=report_text,
        margin_heat_payload=margin_heat_payload,
        p0_readiness_payloads=p0_readiness_payloads,
        p0_readiness_args=args.p0_readiness_json,
        accept_p0_data_gaps=args.accept_p0_data_gaps,
        cash_hkd=args.cash_hkd,
        brokers_arg=args.brokers,
        min_primary_samples=args.min_primary_samples,
        stability_json_path=args.stability_json,
        report_path=args.report,
        margin_heat_json_paths=args.margin_heat_json,
    )
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
