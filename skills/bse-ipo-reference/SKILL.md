---
name: bse-ipo-reference
description: Research and analyze Beijing Stock Exchange (北交所/BSE) IPO subscriptions and cash-allotment plans. Use when the user asks about 北交所打新, 新股申购资金, 正股/碎股门槛, 预计中签股数, 申购上限是否稳中, predicted allotment rate, or whether/how much cash to subscribe for a BSE IPO. Always verify current IPO data online before giving a concrete recommendation.
---

# 北交所打新参考

## Purpose

Provide a research-only reference for BSE online IPO subscription plans: data gathering, rule checks, expected online subscription amount scenarios, funding bands, and expected allotted-share outcomes.

Never promise profit, guaranteed allotment, or capital safety. Do not help structure borrowed accounts, nominee holding, pooled capital, off-market financing, guaranteed-return agreements, or any other arrangement intended to bypass securities rules.

## Workflow

1. Identify the IPO and user objective.
   - Extract stock name/code, subscription date, issue price, online shares, subscription cap, and the user's available cash.
   - If the user does not provide cash, answer with funding bands rather than individual cash rows.

2. Verify current data online.
   - Prefer the official issue announcement and issue-result announcement.
   - Then cross-check Eastmoney, CFi, Tonghuashun/AkShare, Sina, Securities Times, 21jingji, CLS, or other reputable public sources.
   - Treat Xiaohongshu, Jisilu, Xueqiu, Zhihu, and other community posts as sentiment or estimate references only.
   - Record source links and the query date.

3. Read reference material only as needed.
   - Read `references/rules-and-method.md` for allocation rules, formulas, and decision logic.
   - Read `references/data-sources.md` for source priority and fields to collect.

4. Use the deterministic calculator for all numeric tables.
   - Run `scripts/bse_ipo_calculator.py` when issue price, online shares, and either expected online subscription amount or an allotment rate are known.
   - Before results are published, treat expected online subscription amount as the primary uncertainty and use at least three weighted scenarios: conservative, base, crowded.
   - When using community estimates, deduplicate repeated reposts and repeated numbers from the same article. Do not treat a top-subscription break-even amount, a recent comparable IPO's actual frozen funds, or a generic threshold as the current IPO's expected online subscription amount.
   - Build the crowded scenario as a protection line, not a cosmetic high case. If the IPO has a high subscription cap, large online supply, clear valuation discount, hot sector/theme, strong recent BSE new-stock returns, or converged community high estimates, set the crowded scenario at least near the recent high-water mark plus a premium.
   - Treat crowded protection as a tiered judgment. Do not raise the base estimate only because online supply is large. Use a strong crowded line only when the subscription cap is very high, or when cap pressure and online supply pressure are both high; use only a mild line for weak mixed signals.
   - For small or near-small issues, apply a cooling check before raising thresholds: if subscription cap cash is below about 800-1000万元 and online issue shares are below about 800-1200万股, pull the base scenario toward small-size comparables instead of blindly using recent high-water marks. For near-small boundary cases, keep a modest decision buffer before calling top subscription stable.
   - Do not call a cash band "稳正股" unless it clears the crowded scenario's regular-share threshold; otherwise label it as a boundary or scenario-split result.
   - Use `--scenario-yi "情景:预计网上申购金额亿元:概率数字"` so the output can show different amount assumptions and their result probabilities.
   - Do not hard-code boundary amounts such as `500万` or `520万`. Derive the secondary-allocation boundary from recent BSE result data, community estimate clusters, and current-IPO supply pressure.
   - Do not make the boundary band wide just to look safer. Balance hit rate and precision: infer a low/mid/high boundary internally, but when at least two credible estimates cluster, compress the main actionable secondary-allocation boundary toward a `20万`量级 range, usually around `mid-10万` to `mid+10万`. Treat this as a target precision, not a hard cap. If evidence is weak or scattered, widen the band and explain why it cannot be responsibly narrowed.
   - Weight newer data more heavily. Use 2025-2026 and the latest 60-90 days as the main calibration window; treat 2020-2023 data as regime history rather than a direct tuning target unless market conditions clearly match.
   - When boundary evidence is available, pass `--secondary-boundary-yuan 低位 中位 高位`; the script keeps the internal model but outputs simple user-facing bands.
   - When analyzing a pure secondary-allocation case where the subscription cap is below the 100-share regular threshold, use the calculator's default `20万`量级 main-boundary precision as a starting point. Do not output broad rows such as `500-550万` as the main decision band unless evidence is too scattered and you explicitly say so.
   - Regular-allotment thresholds take priority over secondary-allocation boundaries. Once a funding band reaches the 100-share regular threshold, label it as regular shares, not just 碎股.
   - For regular allotment bands, list each 100-share tier that is reachable before the subscription cap: `100股`, `200股`, `300股`, and so on. Do not compress reachable regular tiers into a generic `多手` label.
   - If the subscription cap exactly reaches a higher regular-share tier, include one exact `=顶格` row for that edge case.
   - If top subscription is below both the regular threshold and the dynamic secondary boundary, include at most one exact `=顶格` row to explain the top-subscription edge case.
   - Use actual result data after the issue-result announcement is available.

5. Produce the answer in Chinese unless the user requests otherwise.
   - Start with one concise conclusion.
   - Include a key-data table, online-subscription-amount scenario table, and funding-band table.
   - In the funding-band table, use only `资金区间`, `预计结果`, and `说明` columns.
   - Do not include a "指定金额测算" table unless the user explicitly asks to analyze named cash amounts.
   - Separate "actual result", "base estimate", and "community estimate".
   - Explain whether the subscription cap is enough to reliably receive 100 regular shares.
   - State the secondary-allocation uncertainty for 碎股.
   - End with risks and sources.

## Calculator Quick Start

Use yuan and shares unless the option name says otherwise.

```bash
python scripts/bse_ipo_calculator.py \
  --name 示例股份 \
  --price 10.00 \
  --online-shares-wan 1200 \
  --max-shares-wan 50 \
  --scenario-yi "保守:6000:25" "基准:7500:50" "拥挤:9000:25" \
  --secondary-boundary-yuan 4200000 4500000 4800000
```

If a result announcement gives an allotment rate directly:

```bash
python scripts/bse_ipo_calculator.py \
  --price 25.19 \
  --online-shares-wan 640 \
  --max-shares-wan 28.8 \
  --allotment-rate-pct 0.0187 \
  --funds-yuan 3000000 7255000 10000000
```

For secondary-allocation modeling, pass a community or historical estimate:

```bash
python scripts/bse_ipo_calculator.py ... --secondary-boundary-yuan 2800000 3150000 3400000
```

For historical model checks in the local recommender project:

```bash
PYTHONPATH=src python -m bse_ipo_recommender backtest-targets --from-date 2026-01-01 --offline
```

## Output Template

Use this structure for concrete IPO analysis:

```markdown
**一句话结论**
核心看最终网上申购金额。按当前情景，X-Y 万元主要是博碎股，低于 Y 万元偏陪跑；若顶格申购金额低于各情景 100 股正股门槛，不能视为稳中。

**关键数据**
| 项目 | 数值 | 来源 |
|---|---:|---|

**网上申购金额情景概率**
| 情景 | 概率 | 预计网上申购金额 | 配售比例 | 100股正股门槛 | 顶格判断 |
|---|---:|---:|---:|---:|---|

**资金区间参考**
| 资金区间 | 预计结果 | 说明 |
|---:|---|---|

**操作参考**
- ...

**风险**
以上为发行前估算，不构成投资建议；碎股不保证，上市后涨跌不确定。

**来源**
- ...
```
