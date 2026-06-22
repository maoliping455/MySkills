#!/usr/bin/env python3
"""Extract a focused IPO prospectus deep-dive summary.

Use for stocks that are already in the `建议申购` bucket or explicitly named
by the user. The script accepts pasted text, a text file, a local PDF, or a
public HKEX PDF URL. PDF text extraction uses optional pypdf when available;
otherwise the script reports what it can and asks for pasted text.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


USER_AGENT = "Mozilla/5.0 (compatible; hk-ipo-reference/0.1)"


SECTION_PATTERNS = {
    "业务": [r"業務", r"业务", r"概覽", r"概要"],
    "财务": [r"財務資料", r"财务资料", r"收入", r"毛利", r"淨利", r"净利"],
    "估值": [r"市值", r"估值", r"每股", r"發售價", r"发售价"],
    "募资用途": [r"所得款項用途", r"所得款项用途", r"募集資金", r"募资"],
    "风险因素": [r"風險因素", r"风险因素", r"我們面臨", r"我们面临"],
    "基石/禁售": [r"基石投資者", r"基石投资者", r"禁售", r"鎖定", r"锁定"],
}


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_url_to_temp(url: str) -> Path:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urlopen(req, timeout=30) as response:
        data = response.read()
    suffix = ".pdf" if url.lower().split("?")[0].endswith(".pdf") else ".bin"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(data)
        return Path(handle.name)
    finally:
        handle.close()


def extract_pdf_text(path: Path, max_pages: int) -> tuple[str, str | None]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return "", f"当前环境未安装 pypdf，无法直接抽取 PDF 文本：{exc}"

    try:
        reader = PdfReader(str(path))
        pages = reader.pages[:max_pages]
        text_parts = [page.extract_text() or "" for page in pages]
        return clean_text("\n".join(text_parts)), None
    except Exception as exc:  # noqa: BLE001
        return "", f"PDF 文本抽取失败：{exc}"


def read_input(args: argparse.Namespace) -> tuple[str, list[str]]:
    notes: list[str] = []
    chunks: list[str] = []
    if args.text:
        chunks.append(args.text)
    if args.text_file:
        chunks.append(Path(args.text_file).read_text(encoding="utf-8"))
    pdf_path: Path | None = None
    if args.url:
        try:
            pdf_path = fetch_url_to_temp(args.url)
            notes.append(f"已下载 HKEX PDF：{args.url}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"PDF 下载失败：{exc}")
    if args.pdf:
        pdf_path = Path(args.pdf)
    if pdf_path:
        text, error = extract_pdf_text(pdf_path, max_pages=args.max_pages)
        if text:
            chunks.append(text)
        if error:
            notes.append(error)
    if not chunks and not sys.stdin.isatty():
        chunks.append(sys.stdin.read())
    return clean_text("\n\n".join(chunks)), notes


def extract_snippets(text: str, patterns: list[str], limit: int = 4) -> list[str]:
    snippets: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            start = max(0, match.start() - 220)
            end = min(len(text), match.end() + 420)
            snippet = clean_text(text[start:end])
            if snippet and snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= limit:
                return snippets
    return snippets


def analyze_text(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section, patterns in SECTION_PATTERNS.items():
        result[section] = extract_snippets(text, patterns)
    return result


def has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def prospectus_signals(text: str, analysis: dict[str, Any]) -> dict[str, Any]:
    positive: list[str] = []
    risks: list[str] = []
    missing: list[str] = []

    if has_any(text, [r"收入.*(增加|增长|上升)", r"收益.*(增加|增长|上升)", r"毛利率.*(上升|提升)"]):
        positive.append("收入或毛利率呈改善迹象，需进一步核实持续性和同业估值。")
    if has_any(text, [r"盈利", r"淨利", r"净利", r"經營活動.*現金流入", r"经营活动.*现金流入"]):
        positive.append("招股书片段出现盈利或经营现金流入线索，优先核实利润质量。")
    if has_any(text, [r"基石投資者", r"基石投资者"]):
        positive.append("招股书披露基石投资者，需核实占比、锁定期和质量。")

    if has_any(text, [r"虧損", r"亏损", r"淨虧損", r"净亏损", r"尚未盈利"]):
        risks.append("招股书出现亏损或未盈利线索，融资前需核实现金消耗和商业化路径。")
    if has_any(text, [r"經營活動.*現金流出", r"经营活动.*现金流出", r"現金流.*負", r"现金流.*负"]):
        risks.append("经营现金流可能承压，需核实现金转换和融资后资金用途。")
    if has_any(text, [r"客戶集中", r"客户集中", r"五大客戶", r"五大客户", r"最大客戶", r"最大客户"]):
        risks.append("存在客户集中线索，需核实前五大客户占比和续约稳定性。")
    if has_any(text, [r"關聯交易", r"关联交易", r"關連交易", r"关连交易"]):
        risks.append("存在关联/关连交易线索，需核实交易定价和独立性。")
    if has_any(text, [r"估值偏高", r"市銷率.*高", r"市销率.*高", r"市盈率.*高", r"發行市值.*高", r"发行市值.*高"]):
        risks.append("存在估值偏高线索，需与同业和近期新股定价比较后再考虑融资。")
    if has_any(text, [r"所得款項.*償還", r"所得款项.*偿还", r"募資.*償還", r"募资.*偿还"]):
        risks.append("募资用途可能包含偿债，需确认是否削弱成长投入叙事。")

    for section in ["财务", "估值", "募资用途", "风险因素", "基石/禁售"]:
        if not analysis.get(section):
            missing.append(f"{section}片段未定位，需人工核对招股书。")

    modifier = min(6, len(positive) * 2) - min(10, len(risks) * 3)
    if len(risks) >= 3:
        confidence = "高"
    elif positive or risks:
        confidence = "中"
    else:
        confidence = "低"
    return {
        "score_modifier": modifier,
        "confidence": confidence,
        "positive_flags": positive,
        "risk_flags": risks,
        "missing_checks": missing,
    }


def build_payload(
    *,
    stock_name: str | None,
    code: str | None,
    source: str | None,
    analysis: dict[str, Any],
    notes: list[str],
    text: str,
) -> dict[str, Any]:
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "stock_name": stock_name,
        "code": code,
        "source": source,
        "text_available": bool(text),
        "notes": notes,
        "sections": analysis,
        "signals": prospectus_signals(text, analysis) if text else {
            "score_modifier": 0,
            "confidence": "低",
            "positive_flags": [],
            "risk_flags": [],
            "missing_checks": ["未取得可解析招股书文本。"],
        },
    }


def render_markdown(
    *,
    stock_name: str | None,
    code: str | None,
    source: str | None,
    analysis: dict[str, Any],
    notes: list[str],
    text_available: bool,
) -> str:
    title = stock_name or (f"{code}.HK" if code else "指定新股")
    lines = [
        f"# 招股书深度补充：{title}",
        "",
        f"生成时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if source:
        lines.append(f"来源：{source}")
    lines.append("")

    if notes:
        lines.append("## 处理提示")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    if not text_available:
        lines.extend(
            [
                "## 结论",
                "当前未取得可解析文本。请提供 HKEX 招股书文本摘录、安装 pypdf 后重跑，或让 Codex 使用 PDF 读取能力进行深度解析。",
                "",
            ]
        )
    else:
        for section, snippets in analysis.items():
            lines.append(f"## {section}")
            if not snippets:
                lines.append("- 未在可解析文本中定位到明确片段，需要人工查看招股书对应章节。")
            else:
                for snippet in snippets[:3]:
                    compact = re.sub(r"\s+", " ", snippet)
                    lines.append(f"- {compact[:500]}")
            lines.append("")

    lines.extend(
        [
            "## 应补入推荐报告的检查点",
            "- 财务：收入增速、毛利率、净利/亏损、经营现金流和客户集中度。",
            "- 估值：发行市值、同业市销率/市盈率、A/H 或可比公司折溢价。",
            "- 交易结构：基石、禁售、老股、绿鞋、回拨机制和公开发售比例。",
            "- 风险：监管、技术替代、商业化、关联交易、供应链和融资成本。",
            "",
            "**免责声明** 该摘要只用于公开资料研究，不构成投资建议。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-name", help="Chinese stock name.")
    parser.add_argument("--code", help="HK stock code.")
    parser.add_argument("--url", help="Public HKEX prospectus PDF URL.")
    parser.add_argument("--pdf", help="Local PDF path.")
    parser.add_argument("--text", help="Pasted prospectus text.")
    parser.add_argument("--text-file", help="UTF-8 text file containing prospectus text.")
    parser.add_argument("--max-pages", type=int, default=80, help="Maximum PDF pages to extract when pypdf is available.")
    parser.add_argument("--json", action="store_true", help="Output structured JSON for build_recommendation_report.py.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text, notes = read_input(args)
    analysis = analyze_text(text) if text else {}
    source = args.url or args.pdf or args.text_file or ("pasted text" if args.text else None)
    payload = build_payload(
        stock_name=args.stock_name,
        code=args.code,
        source=source,
        analysis=analysis,
        notes=notes,
        text=text,
    )
    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0
    sys.stdout.write(
        render_markdown(
            stock_name=args.stock_name,
            code=args.code,
            source=source,
            analysis=analysis,
            notes=notes,
            text_available=bool(text),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
