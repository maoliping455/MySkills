#!/usr/bin/env python3
"""Normalize user-provided Hong Kong IPO sentiment excerpts.

This script does not scrape logged-in platforms. Pass public snippets, copied
posts, search-result text, or a text file. It writes normalized JSON to stdout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


PLATFORM_PATTERNS = {
    "小红书": [r"小红书", r"xiaohongshu", r"xhs"],
    "雪球": [r"雪球", r"xueqiu"],
    "富途牛牛": [r"富途", r"牛牛", r"moomoo", r"futubull", r"futu"],
    "格隆汇": [r"格隆汇", r"gelonghui", r"glh"],
    "知乎": [r"知乎", r"zhihu"],
    "集思录": [r"集思录", r"jisilu"],
}

POSITIVE_KEYWORDS = [
    "热门",
    "热度高",
    "抢",
    "值得申",
    "建议申",
    "看好",
    "稀缺",
    "龙头",
    "高增长",
    "盈利",
    "基石强",
    "超购",
    "暗盘看涨",
    "首日看涨",
    "估值合理",
    "低估",
    "中签率低",
]

NEGATIVE_KEYWORDS = [
    "破发",
    "不申",
    "不建议",
    "避开",
    "太贵",
    "估值高",
    "亏损",
    "没有盈利",
    "无基石",
    "基石弱",
    "保荐人差",
    "冷门",
    "抽飞",
    "融资贵",
    "息费高",
    "一手党",
    "风险大",
    "高负债",
]

RISK_KEYWORDS = [
    "估值",
    "亏损",
    "-B",
    "无基石",
    "禁售",
    "老股",
    "客户集中",
    "毛利率",
    "现金流",
    "融资成本",
    "破发",
    "暗盘",
    "超购",
    "回拨",
]


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+", " ", text).strip()


def split_snippets(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    chunks = re.split(r"\n\s*\n|^-{3,}$", text, flags=re.M)
    snippets: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if len(lines) > 1 and all(len(line) <= 140 for line in lines):
            snippets.extend(lines)
        else:
            snippets.append(" ".join(lines))
    return snippets


def detect_platform(text: str) -> str:
    lowered = text.lower()
    for platform, patterns in PLATFORM_PATTERNS.items():
        if any(re.search(pattern, lowered, re.I) for pattern in patterns):
            return platform
    return "未标注"


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    hits = []
    for keyword in keywords:
        if keyword.lower() in lowered:
            hits.append(keyword)
    return hits


def classify_viewpoint(text: str) -> tuple[str, int, list[str], list[str], list[str]]:
    positive = keyword_hits(text, POSITIVE_KEYWORDS)
    negative = keyword_hits(text, NEGATIVE_KEYWORDS)
    risks = keyword_hits(text, RISK_KEYWORDS)
    score = len(positive) - len(negative)
    if positive and negative:
        viewpoint = "分歧"
    elif score >= 2:
        viewpoint = "偏正面"
    elif score == 1:
        viewpoint = "略正面"
    elif score <= -2:
        viewpoint = "偏负面"
    elif score == -1:
        viewpoint = "略负面"
    else:
        viewpoint = "中性/信息不足"
    return viewpoint, score, positive, negative, risks


def confidence_label(total: int, platform_count: int, evidence_hits: int) -> str:
    if total >= 8 and platform_count >= 3 and evidence_hits >= 8:
        return "高"
    if total >= 3 and platform_count >= 2 and evidence_hits >= 3:
        return "中"
    return "低"


def normalize_text(
    text: str,
    *,
    stock_name: str | None = None,
    code: str | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    snippets = split_snippets(text)
    items: list[dict[str, Any]] = []
    platform_counts: dict[str, int] = {}
    total_score = 0
    evidence_hits = 0
    positive_terms: dict[str, int] = {}
    negative_terms: dict[str, int] = {}
    risk_terms: dict[str, int] = {}

    for index, snippet in enumerate(snippets, start=1):
        platform = source_label or detect_platform(snippet)
        viewpoint, score, positive, negative, risks = classify_viewpoint(snippet)
        total_score += score
        evidence_hits += len(positive) + len(negative) + len(risks)
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
        for keyword in positive:
            positive_terms[keyword] = positive_terms.get(keyword, 0) + 1
        for keyword in negative:
            negative_terms[keyword] = negative_terms.get(keyword, 0) + 1
        for keyword in risks:
            risk_terms[keyword] = risk_terms.get(keyword, 0) + 1
        items.append(
            {
                "id": index,
                "platform": platform,
                "stock_name": stock_name,
                "code": code,
                "viewpoint": viewpoint,
                "score": score,
                "positive_keywords": positive,
                "negative_keywords": negative,
                "risk_keywords": risks,
                "excerpt": snippet[:500],
            }
        )

    if total_score >= 3:
        tilt = "偏正面"
    elif total_score <= -3:
        tilt = "偏负面"
    elif any(item["viewpoint"] == "分歧" for item in items):
        tilt = "分歧"
    elif total_score > 0:
        tilt = "略正面"
    elif total_score < 0:
        tilt = "略负面"
    else:
        tilt = "中性/信息不足"

    confidence = confidence_label(len(items), len(platform_counts), evidence_hits)

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds"),
        "input_type": "user_provided",
        "stock_name": stock_name,
        "code": code,
        "items": items,
        "summary": {
            "total_snippets": len(items),
            "platforms": platform_counts,
            "tilt": tilt,
            "score": total_score,
            "confidence": confidence,
        },
        "signals": {
            "positive_keywords": sorted(
                positive_terms.items(), key=lambda item: (-item[1], item[0])
            ),
            "negative_keywords": sorted(
                negative_terms.items(), key=lambda item: (-item[1], item[0])
            ),
            "risk_keywords": sorted(risk_terms.items(), key=lambda item: (-item[1], item[0])),
        },
        "notes": [
            "舆情为辅助证据，不直接决定申购建议。",
            "未登录平台或验证码后的内容不应尝试绕过；可由用户粘贴摘录。",
        ],
    }


def load_input(args: argparse.Namespace) -> str:
    chunks: list[str] = []
    if args.text:
        chunks.append(args.text)
    if args.file:
        chunks.append(Path(args.file).read_text(encoding="utf-8"))
    if not chunks and not sys.stdin.isatty():
        chunks.append(sys.stdin.read())
    return "\n\n".join(chunks)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="Raw copied discussion text.")
    parser.add_argument("--file", help="UTF-8 text file containing discussion excerpts.")
    parser.add_argument("--stock-name", help="Chinese stock name, if known.")
    parser.add_argument("--code", help="HK stock code, if known.")
    parser.add_argument("--source-label", help="Force a platform/source label for all snippets.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = load_input(args)
    payload = normalize_text(
        text,
        stock_name=args.stock_name,
        code=args.code,
        source_label=args.source_label,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
