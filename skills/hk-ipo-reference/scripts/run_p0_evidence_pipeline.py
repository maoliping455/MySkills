#!/usr/bin/env python3
"""Run the P0 evidence ledger -> consolidated worksheet -> expert gate pipeline."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import audit_expert_readiness
import merge_p0_research_ledger
import normalize_conflict_research_input
import normalize_p0_research_ledger
import split_p0_consolidated_input


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def maybe_report_text(path: str | None) -> str | None:
    return Path(path).read_text(encoding="utf-8") if path else None


def run_pipeline(
    *,
    consolidated_path: str,
    ledger_path: str,
    output_dir: str,
    ledger_format: str = "auto",
    overwrite: bool = False,
    assume_preclose: bool = False,
    backtest_json: str | None = None,
    stability_json: str | None = None,
    report_path: str | None = None,
    primary_year: int | None = None,
    cash_hkd: float = 550_000.0,
    brokers_arg: str | None = "",
    accept_p0_data_gaps: bool = False,
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ledger_rows = normalize_conflict_research_input.read_rows(ledger_path, ledger_format)
    ledger_review = normalize_p0_research_ledger.build_payload(ledger_rows, assume_preclose=assume_preclose)
    merged = merge_p0_research_ledger.merge_rows(
        merge_p0_research_ledger.read_consolidated_rows(consolidated_path),
        ledger_rows,
        overwrite=overwrite,
        assume_preclose=assume_preclose,
    )

    merged_path = out / "p0-consolidated-filled.csv"
    merged_path.write_text(merge_p0_research_ledger.render_csv(merged["rows"]), encoding="utf-8")

    split_dir = out / "p0-split"
    split_dir.mkdir(parents=True, exist_ok=True)
    split_paths: dict[str, str] = {}
    for domain in split_p0_consolidated_input.p0_pack.DOMAIN_ORDER:
        output_path = split_dir / split_p0_consolidated_input.DOMAIN_FILENAMES[domain]
        domain_rows = split_p0_consolidated_input.split_rows(merged["rows"], domain=domain)
        output_path.write_text(
            split_p0_consolidated_input.render_csv(domain_rows, domain=domain),
            encoding="utf-8",
        )
        split_paths[domain] = str(output_path)

    expert_payload = None
    if backtest_json:
        resolved_year = primary_year or dt.date.today().year
        backtest_payload = load_json(backtest_json)
        stability_payload = load_json(stability_json) if stability_json else None
        readiness_payloads = {
            domain: audit_expert_readiness.load_p0_readiness_payload(domain, path)
            for domain, path in split_paths.items()
        }
        p0_readiness_args = [
            f"{domain}={split_paths[domain]}"
            for domain in split_p0_consolidated_input.p0_pack.DOMAIN_ORDER
        ]
        expert_payload = audit_expert_readiness.build_payload(
            backtest_payload,
            backtest_json=backtest_json,
            primary_year=resolved_year,
            stability_payload=stability_payload,
            report_text=maybe_report_text(report_path),
            p0_readiness_payloads=readiness_payloads,
            p0_readiness_args=p0_readiness_args,
            cash_hkd=cash_hkd,
            brokers_arg=brokers_arg,
            stability_json_path=stability_json,
            report_path=report_path,
            accept_p0_data_gaps=accept_p0_data_gaps,
        )
        (out / "expert-readiness-after-ledger.json").write_text(
            json.dumps(expert_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(out),
        "paths": {
            "merged_consolidated": str(merged_path),
            "split_dir": str(split_dir),
            "split_paths": split_paths,
            "expert_readiness_json": str(out / "expert-readiness-after-ledger.json") if expert_payload else "",
        },
        "ledger_summary": ledger_review.get("ledger_summary") or {},
        "ledger_quality_summary": ledger_review.get("summary") or {},
        "merge_summary": merged.get("summary") or {},
        "expert_status": (expert_payload or {}).get("status"),
        "expert_summary": (expert_payload or {}).get("summary") or {},
        "guardrail": "Pipeline only merges time-valid uncontaminated pre-close evidence. It does not tune thresholds.",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    ledger = payload.get("ledger_summary") or {}
    quality = payload.get("ledger_quality_summary") or {}
    merge = payload.get("merge_summary") or {}
    expert = payload.get("expert_summary") or {}
    lines = [
        "# P0 证据闭环流水线",
        "",
        f"生成时间：{payload.get('generated_at')}",
        f"输出目录：`{payload.get('output_dir')}`",
        f"防泄露口径：{payload.get('guardrail')}",
        "",
        "## Ledger 审查",
        f"- 检索任务：{ledger.get('task_count', 0)}",
        f"- 已填证据任务：{ledger.get('filled_task_count', 0)}",
        f"- 空白任务：{ledger.get('blank_task_count', 0)}",
        f"- 可复核股票：{quality.get('review_ready_stock_count', 0)}",
        f"- 已尝试缺口股票：{quality.get('attempted_data_gap_stock_count', 0)}",
        f"- 时间无效股票：{quality.get('timing_invalid_stock_count', 0)}",
        f"- 证据污染股票：{quality.get('evidence_contaminated_stock_count', 0)}",
        "",
        "## 合并结果",
        f"- 有效 ledger 行：{merge.get('eligible_row_count', 0)}",
        f"- 已尝试缺口 ledger 行：{merge.get('attempted_gap_row_count', 0)}",
        f"- 空白 ledger 行：{merge.get('blank_row_count', 0)}",
        f"- 时间无效 ledger 行：{merge.get('timing_invalid_row_count', 0)}",
        f"- 证据污染 ledger 行：{merge.get('evidence_contaminated_row_count', 0)}",
        f"- 合并股票：{merge.get('merged_stock_count', 0)}",
        f"- 更新字段：{merge.get('updated_field_count', 0)}",
        f"- 合并表：`{payload['paths']['merged_consolidated']}`",
        f"- 分域目录：`{payload['paths']['split_dir']}`",
    ]
    if payload.get("expert_status"):
        lines.extend(
            [
                "",
                "## 专家闸门",
                f"- 状态：{payload.get('expert_status')}",
                f"- P0 待闭环提及：{expert.get('p0_open_stock_mentions', '-')}",
                f"- P0 可复核提及：{expert.get('p0_review_ready_stock_mentions', '-')}",
                f"- 阻塞性警告：{expert.get('blocking_warning_count', '-')}",
                f"- 结果 JSON：`{payload['paths']['expert_readiness_json']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## 使用结论",
            "- 若合并股票为 0，说明 ledger 仍为空白、时间无效、证据污染，或股票代码无法匹配。",
            "- 若专家闸门仍为 `needs_p0_or_review`，继续按新的 P0 backlog 补申购前证据，不要调阈值。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consolidated", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ledger-format", choices=["auto", "csv", "json", "jsonl"], default="auto")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--assume-preclose", action="store_true")
    parser.add_argument("--backtest-json")
    parser.add_argument("--stability-json")
    parser.add_argument("--report")
    parser.add_argument("--primary-year", type=int)
    parser.add_argument("--cash-hkd", type=float, default=550_000.0)
    parser.add_argument("--brokers", default="")
    parser.add_argument("--accept-p0-data-gaps", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_pipeline(
        consolidated_path=args.consolidated,
        ledger_path=args.ledger,
        output_dir=args.output_dir,
        ledger_format=args.ledger_format,
        overwrite=args.overwrite,
        assume_preclose=args.assume_preclose,
        backtest_json=args.backtest_json,
        stability_json=args.stability_json,
        report_path=args.report,
        primary_year=args.primary_year,
        cash_hkd=args.cash_hkd,
        brokers_arg=args.brokers,
        accept_p0_data_gaps=args.accept_p0_data_gaps,
    )
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
