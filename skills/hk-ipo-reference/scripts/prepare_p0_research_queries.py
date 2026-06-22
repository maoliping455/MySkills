#!/usr/bin/env python3
"""Build public research queries for unresolved P0 HK IPO evidence backlog."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any


POST_CLOSE_TERMS = [
    "配售结果",
    "分配结果",
    "一手中签率",
    "中签率",
    "暗盘",
    "首日",
    "上市表现",
    "破发",
    "收涨",
    "收跌",
]
BROKERS = ["富途", "辉立", "耀才", "华泰国际", "长桥"]
PRE_CLOSE_TIMING_FIELDS = ["observed_at", "source_published_at", "preclose_confirmed", "broker_cutoff_at"]
CORE_TASK_LABELS = {
    "margin": "孖展热度/融资成本",
    "scenario": "申购前情景涨幅/配售率",
    "prospectus": "招股书/估值/基石摘要",
}
QUERY_TYPE_LABELS = {
    "broker_margin_heat": "综合孖展热度",
    "preclose_return_scenario": "申购前情景",
    "hkex_prospectus_deep_dive": "招股书深挖",
    "public_sentiment_auxiliary": "公开舆情辅助",
}
QUERY_FIELDS = [
    "rank",
    "group_id",
    "stock",
    "code",
    "score",
    "action",
    "financing_tier",
    "entry_fee_hkd",
    "domain_count",
    "open_domain_count",
    "open_domains",
    "missing_fields",
    "priority_reasons",
    "next_action",
    "query_type",
    "query",
    "required_checks",
    "capture_fields",
    "broker",
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
    "evidence_rule",
]


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = clean(value)
        if text and text not in result:
            result.append(text)
    return result


def split_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return unique([clean(item) for item in value])
    text = clean(value)
    if not text:
        return []
    for delimiter in ["、", ";", "；", "|"]:
        text = text.replace(delimiter, ",")
    return unique([item.strip() for item in text.split(",") if item.strip()])


def stock_token(item: dict[str, Any]) -> str:
    stock = clean(item.get("stock"))
    code = clean(item.get("code"))
    return f"{stock} {code}".strip()


def needs_margin(missing: list[str], domains: list[str]) -> bool:
    text = " ".join([*missing, *domains])
    return any(
        keyword in text
        for keyword in [
            "pending_input",
            "observed_at",
            "broker_cutoff_at",
            "preclose_confirmed",
            "margin",
            "孖展",
            "额度",
            "融资",
            "rate",
            "fees",
            "financing",
            "乙组执行验证",
            "同窗口资金取舍",
        ]
    )


def needs_scenario(missing: list[str], domains: list[str]) -> bool:
    text = " ".join([*missing, *domains])
    return any(
        keyword in text
        for keyword in [
            "pending_input",
            "scenario",
            "allotment_rate",
            "情景",
            "配售率",
            "建议申购执行风险",
            "同窗口资金取舍",
        ]
    )


def needs_prospectus(missing: list[str], domains: list[str]) -> bool:
    text = " ".join([*missing, *domains])
    return any(
        keyword in text
        for keyword in [
            "pending_input",
            "prospectus",
            "source",
            "valuation",
            "cornerstone",
            "hard_tech",
            "招股书",
            "估值",
            "基石",
            "临界观察升级",
            "建议申购执行风险",
            "同窗口资金取舍",
        ]
    )


def needs_sentiment(missing: list[str], domains: list[str]) -> bool:
    text = " ".join([*missing, *domains])
    return any(keyword in text for keyword in ["pending_input", "demand", "热度", "临界观察升级", "同窗口资金取舍"])


def broker_from_query_type(query_type: str) -> str:
    prefix = "broker_margin_"
    if query_type.startswith(prefix):
        broker = query_type[len(prefix) :]
        return broker if broker in BROKERS else ""
    return ""


def task_family(query_type: str) -> str:
    if query_type.startswith("broker_margin"):
        return "margin"
    if query_type == "preclose_return_scenario":
        return "scenario"
    if query_type == "hkex_prospectus_deep_dive":
        return "prospectus"
    if query_type == "public_sentiment_auxiliary":
        return "sentiment"
    return ""


def query_type_label(query_type: str) -> str:
    if query_type.startswith("broker_margin_"):
        return f"{broker_from_query_type(query_type) or '券商'}孖展补充"
    return QUERY_TYPE_LABELS.get(query_type, query_type)


def stock_groups(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for row in tasks:
        key = (int(row.get("rank") or 0), clean(row.get("stock")), clean(row.get("code")))
        group = grouped.setdefault(
            key,
            {
                "rank": row.get("rank"),
                "stock": row.get("stock"),
                "code": row.get("code"),
                "open_domains": row.get("open_domains"),
                "priority_reasons": row.get("priority_reasons"),
                "core_requirements": [],
                "core_query_types": [],
                "auxiliary_query_types": [],
                "queries": [],
            },
        )
        family = task_family(clean(row.get("query_type")))
        if family in CORE_TASK_LABELS:
            label = CORE_TASK_LABELS[family]
            if label not in group["core_requirements"]:
                group["core_requirements"].append(label)
            if row["query_type"] not in group["core_query_types"]:
                group["core_query_types"].append(row["query_type"])
        elif row["query_type"] not in group["auxiliary_query_types"]:
            group["auxiliary_query_types"].append(row["query_type"])
        group["queries"].append(
            {
                "query_type": row["query_type"],
                "label": query_type_label(row["query_type"]),
                "query": row["query"],
                "capture_fields": row["capture_fields"],
                "core": family in CORE_TASK_LABELS,
            }
        )
    return [
        grouped[key]
        for key in sorted(grouped, key=lambda item: (item[0], item[1], item[2]))
    ]


def task(
    item: dict[str, Any],
    *,
    rank: int,
    query_type: str,
    query: str,
    capture_fields: list[str],
) -> dict[str, Any]:
    return {
        "rank": rank,
        "group_id": "p0_research_ledger",
        "stock": clean(item.get("stock")),
        "code": clean(item.get("code")),
        "score": clean(item.get("score")),
        "action": clean(item.get("action")),
        "financing_tier": clean(item.get("financing_tier")),
        "entry_fee_hkd": clean(item.get("entry_fee_hkd")),
        "domain_count": clean(item.get("domain_count")),
        "open_domain_count": clean(item.get("open_domain_count")),
        "open_domains": "、".join(split_values(item.get("open_domains"))),
        "missing_fields": "、".join(split_values(item.get("missing_fields"))),
        "priority_reasons": clean(item.get("priority_reasons")),
        "next_action": clean(item.get("next_action")),
        "query_type": query_type,
        "query": query,
        "required_checks": "、".join(capture_fields),
        "capture_fields": "、".join(capture_fields),
        "broker": broker_from_query_type(query_type),
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
        "collection_note": "P0公开检索台账：完成检索后，只在本行填申购截止/券商融资截止前可见证据；若公开资料不可得，填 search_attempted_at、search_source、unavailable_reason、search_note。",
        "evidence_rule": "只接受申购截止/券商融资截止前可见资料；记录 observed_at、source_published_at、broker_cutoff_at、source、excerpt；若来源发布时间晚于融资截止，只能作复盘佐证。不可得缺口必须记录检索尝试，且不能夹带上市后结果。",
    }


def build_tasks(payload: dict[str, Any], *, limit: int | None = None) -> dict[str, Any]:
    backlog = payload.get("p0_backlog") or []
    if limit is not None:
        backlog = backlog[:limit]
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(backlog, start=1):
        token = stock_token(item)
        missing = split_values(item.get("missing_fields"))
        domains = split_values(item.get("open_domains"))
        if needs_margin(missing, domains):
            tasks.append(
                task(
                    item,
                    rank=index,
                    query_type="broker_margin_heat",
                    query=f'"{token}" 孖展 认购 额度 利率 手续费 计息天数 截止 券商',
                    capture_fields=[
                        *PRE_CLOSE_TIMING_FIELDS,
                        "margin_multiple",
                        "margin_amount_hkd",
                        "quota_status",
                        "financing_rate_pct",
                        "fees_hkd",
                        "financing_days",
                        "source",
                        "excerpt",
                    ],
                )
            )
            for broker in BROKERS[:3]:
                tasks.append(
                    task(
                        item,
                        rank=index,
                        query_type=f"broker_margin_{broker}",
                        query=f'"{token}" {broker} 孖展 额度 利率 手续费 计息天数 截止',
                        capture_fields=[
                            *PRE_CLOSE_TIMING_FIELDS,
                            "margin_multiple",
                            "margin_amount_hkd",
                            "quota_status",
                            "financing_rate_pct",
                            "fees_hkd",
                            "financing_days",
                            "source",
                            "excerpt",
                        ],
                    )
                )
        if needs_scenario(missing, domains):
            tasks.append(
                task(
                    item,
                    rank=index,
                    query_type="preclose_return_scenario",
                    query=f'"{token}" 打新 预估 涨幅 孖展 热度 申购',
                    capture_fields=[
                        *PRE_CLOSE_TIMING_FIELDS,
                        "scenario_first_day_pct",
                        "scenario_allotment_rate_pct",
                        "max_credible_allotment_rate_pct",
                        "demand_validation",
                        "source",
                        "excerpt",
                    ],
                )
            )
        if needs_prospectus(missing, domains):
            tasks.append(
                task(
                    item,
                    rank=index,
                    query_type="hkex_prospectus_deep_dive",
                    query=f'"{token}" 招股书 HKEX 估值 基石 禁售 募资用途',
                    capture_fields=[
                        *PRE_CLOSE_TIMING_FIELDS,
                        "prospectus_url",
                        "valuation_note",
                        "peer_comparable_note",
                        "cornerstone_lockup_note",
                        "hard_tech_validation",
                        "source",
                        "excerpt",
                    ],
                )
            )
        if needs_sentiment(missing, domains):
            tasks.append(
                task(
                    item,
                    rank=index,
                    query_type="public_sentiment_auxiliary",
                    query=f'"{token}" 小红书 雪球 富途牛牛 格隆汇 打新 讨论',
                    capture_fields=[
                        *PRE_CLOSE_TIMING_FIELDS,
                        "demand_validation",
                        "source",
                        "excerpt",
                    ],
                )
            )
    return {
        "primary_year": payload.get("primary_year"),
        "source_status": payload.get("status"),
        "backlog_stock_count": len(backlog),
        "task_count": len(tasks),
        "excluded_post_close_terms": POST_CLOSE_TERMS,
        "stock_groups": stock_groups(tasks),
        "tasks": tasks,
        "guardrail": "查询只用于寻找申购截止前证据；配售结果、一手中签率、暗盘、首日或上市后表现只能用于复盘，不能填回 P0 申购前证据。",
    }


def render_csv(tasks: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=QUERY_FIELDS)
    writer.writeheader()
    for row in tasks:
        writer.writerow({field: row.get(field, "") for field in QUERY_FIELDS})
    return output.getvalue()


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload.get('primary_year') or '-'} 港股打新 P0 公开资料检索清单",
        "",
        f"专家闸门状态：{payload.get('source_status') or '-'}",
        f"待检索股票：{payload.get('backlog_stock_count', 0)}；检索任务：{payload.get('task_count', 0)}",
        f"防泄露口径：{payload.get('guardrail')}",
        "",
        "## 使用方式",
        "- 按 `rank` 顺序处理，先补跨领域高分股票。",
        "- 每只股票优先闭环核心证据：孖展热度/融资成本、申购前情景涨幅/配售率、招股书/估值/基石摘要。",
        "- 公开舆情只做辅助，不替代核心证据；券商分行用于交叉验证，至少要有一条时间有效的孖展/成本记录。",
        "- 每条证据必须记录 `observed_at`、`source_published_at`、`broker_cutoff_at`、`source` 和 `excerpt`；资料确实不可得时填 `search_attempted_at`、`search_source`、`unavailable_reason`、`search_note`。",
        "- CSV 输出也是可填证据台账；填好后运行 `normalize_p0_research_ledger.py --input p0-research-queries.csv --markdown`。",
        "- 查询结果若只包含配售后、暗盘或上市后信息，不得填回 P0 表。",
        "",
        "## 按股最小闭环清单",
        "| 序 | 股票 | 代码 | 待闭环领域 | 核心必填 | 辅助查询 |",
        "|---:|---|---|---|---|---|",
    ]
    if not payload.get("stock_groups"):
        lines.append("| - | - | - | - | 暂无待检索股票 | - |")
    for group in payload.get("stock_groups") or []:
        auxiliary = "、".join(query_type_label(value) for value in group.get("auxiliary_query_types") or []) or "-"
        lines.append(
            f"| {group.get('rank')} | {group.get('stock') or '-'} | {group.get('code') or '-'} | "
            f"{group.get('open_domains') or '-'} | {'、'.join(group.get('core_requirements') or []) or '-'} | {auxiliary} |"
        )
    lines.extend(
        [
            "",
        "## 检索任务",
        "| 序 | 股票 | 代码 | 待闭环领域 | 优先原因 | 类型 | 查询语句 | 需填字段 |",
        "|---:|---|---|---|---|---|---|---|",
        ]
    )
    if not payload.get("tasks"):
        lines.append("| - | - | - | - | - | - | 暂无待检索任务 | - |")
    for row in payload.get("tasks") or []:
        lines.append(
            f"| {row['rank']} | {row['stock'] or '-'} | {row['code'] or '-'} | "
            f"{row.get('open_domains') or '-'} | {row.get('priority_reasons') or row.get('next_action') or '-'} | "
            f"{row['query_type']} | `{row['query']}` | {row['capture_fields']} |"
        )
    lines.extend(
        [
            "",
            "## 禁用证据词",
            "这些词出现时通常说明资料偏配售后或上市后，只能作为复盘线索："
            + "、".join(payload.get("excluded_post_close_terms") or POST_CLOSE_TERMS),
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", required=True, help="audit_expert_readiness.py --json output.")
    parser.add_argument("--limit", type=int, help="Optional number of backlog stocks to include. Default: no limit.")
    parser.add_argument("--csv", action="store_true", help="Output task CSV.")
    parser.add_argument("--json", action="store_true", help="Output structured JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_tasks(load_json(args.input), limit=args.limit)
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    elif args.csv:
        sys.stdout.write(render_csv(payload["tasks"]))
    else:
        sys.stdout.write(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
