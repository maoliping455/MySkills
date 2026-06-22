---
name: hk-ipo-reference
description: Research and analyze Hong Kong IPO subscriptions, recommendation buckets, funding schedules, same-window capital conflict audits, pre-close future-data leakage audits, financing pricing checklists, financing efficiency audits, financing lock timelines, broker margin heat gates, prospectus deep-dive priorities, borderline-observation upgrade checks, P0 evidence backlogs and public research query plans, grey-market or first-day review, 2026-led year-to-date backtests, strategy-alignment audits, backtest stability and overfitting audits, expert-readiness gates, and public sentiment as auxiliary evidence. Use when the user asks about 港股打新, 港股 IPO 推荐, 申购策略, 现金/融资甲组或乙组安排, 同窗口资金冲突, 未来数据泄露, 申购前模型审计, P0证据补采, 孖展热度, 融资额度/利率/截止时间, 融资资金效率, 融资锁单, 招股书深挖, 临界观察复核, 暗盘/首日复盘, 年度回测, 策略一致性审查, 回测稳定性, 过拟合审查, 专家就绪审计, or wants to combine HKEX/AASTOCKS data with 小红书、雪球、富途、格隆汇、知乎等讨论摘录.
---

# 港股打新复盘

## Purpose

Provide a stateless research workflow for Hong Kong IPO subscription decisions and post-listing review. The skill gathers current public data, optionally normalizes user-provided sentiment excerpts, classifies IPOs into recommendation buckets, and produces a Chinese Markdown report with evidence, risks, funding plan, and source links.

This is research-only reference material and does not constitute investment advice. Never promise profit, guaranteed allotment, capital safety, or financing availability.

## Operating Principles

- Keep the skill stateless: do not create a database, do not build a Web UI, do not save reports by default, and do not store account credentials.
- Verify current structured data online before giving a concrete recommendation. Prefer HKEX and AASTOCKS; use community platforms only as auxiliary sentiment evidence.
- Do not bypass login walls, captchas, anti-bot controls, paywalls, or platform access restrictions. If a platform cannot be accessed publicly, ask the user to paste excerpts or proceed without that source.
- Use Chinese stock names in user-facing reports. If a source only exposes an English name, label the stock by code and mark the Chinese name as pending verification rather than presenting the English name as the primary stock name.
- Keep stock names clean. Strip source status suffixes such as `今日暗盘`, `今日上市`, or `跌穿上市价` from the display name and show them as status/review context instead.
- Treat sentiment as supporting context only. It can raise or lower confidence, but it must not directly override weak fundamentals, missing documents, excessive valuation risk, or poor funding economics.
- When prior recommendations or prior report text is available in the current thread, automatically compare listed performance against the earlier recommendation during the new analysis. Do not ask the user to trigger a separate review step.

## Workflow

1. Identify the user objective and capital base.
   - Default to HKD 550,000 cash and 10x financing power when the user does not specify otherwise.
   - Do not impose a default maximum number of IPOs. Instead, check funding lock-up windows and avoid reusing the same cash when subscription periods overlap.
   - If the user asks about actual subscription results, keep interaction lightweight: ask only for stock, applied amount or lots, allotted shares, and known costs if those values are not already present.

2. Gather current structured data.
   - Run `scripts/fetch_current_ipos.py` to fetch current HK IPO rows from AASTOCKS and enrich them with HKEX document links when possible.
   - Run `scripts/estimate_market_regime.py` to estimate the recent Hong Kong IPO market temperature from already-listed IPOs.
   - Read `references/data-sources.md` for source priority, fields to collect, and failure handling.
   - Record source URLs, fetch status, and query date in the report.

3. Add sentiment only when useful.
   - Use public search results or user-provided excerpts from 小红书、雪球、富途牛牛、格隆汇、知乎等 platforms.
   - Run `scripts/normalize_sentiment_input.py` when the user pastes discussion text or when scraped/search snippets need normalization.
   - Read `references/sentiment-framework.md` before interpreting platform chatter.

4. Normalize pre-close financing heat when available.
   - Run `scripts/normalize_margin_input.py` when the user provides broker margin, quota, financing rate, cutoff, or final-day acceleration excerpts.
   - Use the normalized JSON only for the T-1/T-0 financing gate. It can decide whether乙组候选 becomes executable, but it must not override weak company-level evidence.

5. Classify recommendations.
   - Use `scripts/build_recommendation_report.py` to produce the first-pass Markdown report.
   - Pass `--market-regime-json` when market temperature was estimated. Use it to adjust financing intensity, not to replace company-level evidence.
   - Pass `--margin-heat-json` when financing heat was normalized. Treat `execution_gate=满足` as evidence for乙组 execution only when at least two independent demand/quota heat signals are present and cost and cash-window checks pass. Low financing cost is required, but it is not itself a heat signal.
   - Run `scripts/audit_financing_efficiency.py` when a leveraged order is being considered and rate/fee/day assumptions are available. Use explicit scenario assumptions for first-day move, one-lot probability, expected allotted lots or pre-close allotment-rate range, and the maximum credible expected lots/rate. If no reliable allotment-rate assumption is supplied, pass `--margin-heat-json` plus `--scenario-profile strict|base|hot` so the audit derives a conservative pre-close scenario from broker heat; do not use final allotment or first-day data as the lock-order input.
   - Classify IPOs into three sections: `建议申购`, `可选观察`, and `暂不参与`.
   - Show only still-actionable subscriptions in the three recommendation sections. Move closed, grey-market, and listed names into `上市表现复盘` or monitoring notes; do not display their `今日暗盘`, allotment, or first-day status inside pre-close recommendation buckets.
   - For each stock, emphasize why it is or is not recommended, the main risks, what data is missing, and whether financing is worth considering.
   - Use the financing lock timeline in the report to force T-2/T-1/T-0 decisions before broker cutoffs. Never let an乙组候选 wait until allotment, grey market, or first-day data before deciding whether to finance.
   - Read `references/recommendation-framework.md` and `references/report-format.md` when preparing non-trivial reports.

6. Deep dive only where it matters.
   - For `建议申购` stocks, or stocks explicitly requested by the user, run `scripts/deep_dive_prospectus.py` with an HKEX prospectus URL, PDF path, or pasted prospectus text.
   - Use `--json` when the result should feed back into `scripts/build_recommendation_report.py --deep-dive-json`.
   - Use the deep dive to add financial quality, valuation, use of proceeds, cornerstone/lock-up, sponsor, and business-risk evidence. Keep the effect bounded: positive snippets can improve confidence, but serious valuation, loss, cash-flow, customer-concentration, related-party, or use-of-proceeds risks should downgrade a `建议申购` stock to `可选观察` until checked.
   - Do not parse every prospectus by default; focus work on candidates where the result can change the recommendation or funding plan.

7. Review actual listing performance when available.
   - When HKEX/AASTOCKS or other public sources show allotment result, grey-market result, or first-day move, include a self-review section automatically.
   - For current reports with closed, grey-market, or listed names, run `scripts/backtest_year_ipos.py --year YYYY --json` or reuse a cached annual payload, then pass it to `scripts/build_recommendation_report.py --review-json year.json` so current recommendations can be matched against first-day move, oversubscription, one-lot success, and one-lot expected P/L.
   - Compare actual result against the earlier logic if prior recommendation text is available in context.
   - In the current-report review section, include a concise diagnostic action: whether weak heat should have downgraded乙组/cash sizing, whether strong heat should have triggered a T-1/T-0 upgrade check, and whether one-lot expected P/L makes the result capital-efficient.
   - When the user provides actual subscription results in free text, first run `scripts/normalize_actual_subscription_input.py` to normalize stock, applied amount/lots, allotted shares/lots, costs, sell price, and P/L.
   - Use `scripts/calculate_subscription_return.py` when entry fee, first-day move, one-lot success rate, financing rate, or application amount is available. Review first-day move together with one-lot expected gross P/L and financing break-even; do not judge strategy quality by headline first-day percentage alone.
   - Highlight which signals worked, which were noise, and how the next recommendation should be adjusted.

8. Run backtests when the user asks to optimize strategy.
   - Run `scripts/backtest_year_ipos.py --year YYYY` for the current or requested year first. For 2026/current-market tuning, treat this single-year result as the primary evidence because older HK IPO regimes can differ materially.
   - If the user says the current year or 2026 should be the main evidence, do not default to multi-year tuning and do not present older-year metrics as strategy-optimization evidence. If the user explicitly says past regimes may differ and mainly wants 2026, restrict optimization conclusions to 2026; older years can only appear as clearly labeled background risk notes when requested. Run `scripts/backtest_multi_year.py --years YYYY,YYYY,YYYY` only when a cross-cycle stress test is explicitly useful. The default decay is deliberately small so older years remain stress-test signals, not competing evidence against the current-year conclusion; older-year results must not directly dilute or overturn a 2026 single-year conclusion.
   - Before using a 2026 backtest to validate the current report, run `scripts/audit_strategy_alignment.py` on the same current IPO payload and market-regime JSON. If the current report used `--deep-dive-json`, pass the same file to the audit so deep-dive overlays are separated from baseline strategy drift. If still-actionable samples show material bucket drift, explain or fix the drift before treating the backtest as evidence for the current recommendations.
   - Use `scripts/fetch_hkex_listing_reports.py --years YYYY,YYYY --boards Main,GEM` when historical AASTOCKS detail coverage is weak. The annual HKEX reports can backfill official English name, sponsor, listing date, offer price, and funds raised, but not industry quality.
   - In multi-year stress tests, use the report's effective weights, not only the raw recency weights. Years with weak detail-page or industry coverage should be kept as data-risk notes and assigned zero effective weight.
   - Before assigning an older year zero effective weight, retry with full AASTOCKS detail-page enrichment or a cached full-detail payload. If detail and industry coverage become adequate, keep the older year at its small recency weight and use it as a cross-cycle financing stress test.
   - Run `scripts/prepare_margin_history_template.py --backtest-json year.json` when historical broker margin coverage is weak. Use the CSV/Markdown template to collect broker, observed time, source publication time, pre-close confirmation, margin multiple/amount, quota status, rate, cutoff note, and source for B-group candidates. Start with `--priority-levels P0` when the candidate list is large; P0 must cover high-score B-group candidates whose pre-close margin heat is missing or whose strict gate is not met, even when entry fee is not high. Priority uses only pre-close score, entry fee, and heat-coverage status, not first-day or final allotment results.
   - Run `scripts/normalize_margin_history.py --input history.csv --markdown` before JSON normalization to review fill quality. `待填回` means the generated template has no user-supplied timing, margin, quota, rate, source, or excerpt evidence yet. Then run `scripts/normalize_margin_history.py --input history.csv` to convert historical broker margin rows into the margin heat JSON format. Rows whose excerpt or notes contain final oversubscription, one-lot success, allotment, grey-market, first-day, current-price, or cumulative-performance evidence must be retained for review but excluded from effective B-group execution coverage.
   - Historical margin rows must include `observed_at`, `source_published_at` when available, `preclose_confirmed`, and preferably `broker_cutoff_at` with minute-level precision. If `observed_at` or a provided `source_published_at` is later than `broker_cutoff_at` or the public closing date, the row cannot support an executable乙组 gate even when it is marked pre-close.
   - Run `scripts/backtest_margin_gate.py --backtest-json year.json --margin-heat-json heat.json` when historical pre-close margin heat data is available, to separate乙组候选 from乙组可执行. The script rechecks even legacy heat JSON with the current strict gate: at least two independent demand/quota heat signals plus acceptable cost. If B-group heat coverage is below 70%, treat the output as a data-coverage audit rather than proof of B-group execution quality.
   - In margin-gate backtests, read `coverage_rate`, `covered_count`, `missing_count`, `invalid_timing_count`, `gate_met_count`, and `gate_not_met_count` from the JSON output. `coverage_rate=0` is a real finding, not an unknown value; unresolved blank templates or late evidence must keep乙组 execution unvalidated.
   - In every annual backtest, require `历史孖展覆盖审查`. If no historical margin heat JSON is provided, state that乙组执行效果 cannot be validated and list the B-group candidates that need broker margin, quota, rate, broker cutoff timestamp, observation timestamp, source, and pre-close confirmation. If margin heat JSON is provided, report coverage, strict-gate-met count, strict-gate-not-met count, and keep coverage below 70% as a data gap, not strategy proof.
   - When iterating on scoring logic, first capture single-year JSON, then reuse it with `scripts/backtest_year_ipos.py --input-json path --rescore-input` or multi-year `--input-json YEAR=path --rescore-input` so strategy changes are tested on the same samples without repeated network noise.
   - Keep pre-application scoring, pre-close financing decisions, and post-listing review separate. Do not let allotment result, grey-market result, or first-day result leak into the事前申购 recommendation.
   - Run `scripts/audit_preclose_leakage.py --input-json year.json` after any scoring or capital-schedule change. The script mutates final oversubscription, one-lot success, grey-market, first-day, current-price, and cumulative-performance fields to verify that pre-close scoring and same-window scheduling stay unchanged.
   - Use the backtest to update qualitative strategy rules, not to promise that a fitted threshold will keep working.
   - Check score-band calibration before changing recommendation thresholds. If the highest score band is not clearly better than the next band, do not mechanically raise or lower thresholds; use prospectus deep dive, financing heat, cost, and funding-window checks instead.
   - Review the backtest capital-window stress test. It simulates default HKD 550,000 cash against historical `建议申购` lock-up windows using pre-close priority rules, so overlapping IPOs cannot reuse the same cash. Prefer the `事前效用组合最优` schedule for annual review because it optimizes the whole overlapping window using only pre-close score, bounded entry exposure, and lock-up length. Treat skipped conflicts as funding opportunity cost, not automatically as stock-selection errors. If the utility schedule still leaves high opportunity cost, do not keep fitting sort keys; collect T-1/T-0 heat, prospectus deep-dive, and financing break-even evidence for the residual conflict group.
   - When the capital-window stress test shows high opportunity cost or many skipped conflicts, run `scripts/audit_capital_conflicts.py --input-json year.json`. Use it to build same-window decision groups that separate pre-close scheduling fields from review-only first-day and one-lot expected P/L metrics.
   - When the stability audit reports `capital_window_residual_data_gap`, run `scripts/prepare_conflict_research_template.py --input-json year.json --priority-levels P0 --markdown` first. P0 covers the same-window排期边界: the stocks currently selected by the pre-close utility schedule and near-utility skipped challengers that could replace them. Use the output to collect only pre-close broker heat, prospectus deep-dive fields, and financing efficiency assumptions for the residual conflict group. Expand to P1 only after P0 is review-ready or explicitly accepted as a data gap. Do not keep fitting sort keys against final one-lot expected P/L.
   - After generating or filling the residual conflict or execution-risk templates, run `scripts/normalize_conflict_research_input.py --input template.csv --markdown` first to review fill quality, then run JSON normalization for downstream audits. `待填回` means the generated template still has no user-supplied timing, financing, scenario, valuation, source, or excerpt evidence; it is not a failed pre-close row. Use the resulting `items_by_stock` as a margin-heat seed only for rows that pass timing and evidence checks. Rows containing final oversubscription, one-lot success, allotment, grey-market, first-day, current-price, or cumulative-performance evidence must remain excluded from pre-close scheduling decisions.
   - Require `排期排序敏感性` in annual backtests. Compare at least the base score order with pre-close alternatives such as score plus low-entry-fee tie-break, financing-tier priority, and low-entry-fee priority. These alternatives may use only pre-close fields; first-day move and one-lot expected P/L are review metrics for evaluating the sorting rule afterward. Compare average expected one-lot P/L before total expected one-lot P/L, because selected and skipped groups often have different sample counts.
   - Treat expected one-lot P/L and financing break-even as review metrics. They use final allotment/first-day data and must not feed the pre-application score.
   - In multi-year reports, require the expert conclusion to compare the primary year current strategy against the primary year baseline first, using both average first-day move and expected one-lot P/L. The recency-weighted comparison is only supporting evidence. If those two metrics diverge, prefer the one-lot P/L and financing-cost diagnosis over headline first-day gains.
   - In multi-year reports, require a cross-cycle financing pressure review. If older years show weak乙组候选 performance or low one-lot expected P/L, keep乙组 as a current-year watchlist only; do not present it as a default execution action without T-1/T-0 heat, cost, and cash-window confirmation.
   - After generating annual or multi-year JSON, run `scripts/audit_backtest_stability.py --input-json path --primary-year YYYY`. Treat errors as blockers for strategy conclusions. Treat warnings as expert review items: do not keep mechanically tuning score thresholds until the warning is addressed or explicitly accepted as a data gap.
   - Run `scripts/plan_backtest_next_actions.py --stability-json stability.json --backtest-json year.json --backtest-report year.md` after stability audit to convert warnings into a prioritized P0/P1/P2 action plan with commands, guardrails, an iteration gate, and evidence workflows. If the gate says `先补 P0 证据` or `回退策略改动`, do not continue threshold tuning; follow the `证据闭环` steps to generate CSV templates, normalize filled rows, and rerun the listed validation commands before changing strategy.
   - Run `scripts/prepare_p0_evidence_pack.py --backtest-json year.json --stability-json stability.json` before filling templates when multiple P0 workflows are active. Use it to see P0 stock counts, cross-domain overlaps, the deduplicated consolidated collection worksheet, and the exact generation/normalization/review commands in one Markdown report. The pack is stateless and uses broker-neutral rows by default to reduce duplicate data entry; pass `--brokers 富途,辉立,耀才` only when per-broker rows are needed. When the same stock appears in several P0 domains, run `--consolidated-csv` first and collect one stock-level set of pre-close timing, source, broker heat, financing cost, scenario allotment assumptions, and prospectus evidence. After filling it, run `scripts/split_p0_consolidated_input.py --input p0-consolidated.csv --domain all --output-dir p0-split/`, then normalize each split CSV with its domain normalizer.
   - Run `scripts/audit_expert_readiness.py --backtest-json year.json --stability-json stability.json --report year.md --primary-year YYYY` before saying the strategy has no remaining optimization direction. Pass filled P0 review artifacts with `--p0-readiness-json margin_history=path`, `--p0-readiness-json execution_risk=path`, `--p0-readiness-json borderline_upgrade=path`, and `--p0-readiness-json capital_conflict=path`; `path` can be a normalized JSON or a split CSV from `split_p0_consolidated_input.py`, which the gate will normalize internally. This aggregate gate must show no component errors, no blocking warnings, and no open P0 evidence before the Skill can be considered expert-ready. If it says `未达专家终局`, read `P0 下一批补证据清单` and fill stocks in that order: cross-domain, high-score, open evidence rows first. Run `scripts/prepare_p0_research_queries.py --input expert-readiness.json` first to view the per-stock minimum closure checklist, then run `--csv > p0-research-queries.csv` to generate a fillable broker-margin, HKEX prospectus, scenario, and public-sentiment evidence ledger for the unresolved backlog; use the generated queries only to find申购截止前 evidence. A P0 ledger stock is `可复核` only after core generated tasks are covered: at least one time-valid broker-margin/cost row when margin tasks exist, time-valid scenario return and allotment assumptions when scenario tasks exist, and a time-valid prospectus/source summary when prospectus tasks exist. Extra broker rows and public sentiment rows support confidence but do not by themselves close P0. If a public pre-close source truly cannot be found, fill `search_attempted_at`, `search_source`, `unavailable_reason`, and `search_note`; the normalizers will mark this as `已尝试缺口` only when the note is not polluted by allotment, grey-market, or first-day evidence. After filling evidence columns, prefer `scripts/run_p0_evidence_pipeline.py --consolidated p0-consolidated.csv --ledger p0-research-queries.csv --output-dir p0-evidence-run --backtest-json year.json --stability-json stability.json --report year.md --primary-year YYYY` so ledger normalization, eligible-evidence merge, split CSV generation, and expert-gate rerun happen in one guarded workflow. The merge fills blank fields only unless `--overwrite` is explicitly supplied. Continue the P0 evidence loop instead of tuning thresholds. Use `--accept-p0-data-gaps` only for normalized `已尝试缺口`; it must not close ordinary `缺数据`, `时间无效`, `证据污染`, or blank templates.
   - Use the stability audit's structured错判归因 and score-band findings to decide whether the next improvement belongs in financing heat/cost gates, data coverage, hard-tech valuation filters, borderline-observation upgrades, score-band financing-efficiency review, or capital-efficiency review.
   - When the stability audit reports concentrated false positives around一手期望、资金效率、硬科技或估值, run `scripts/prepare_execution_risk_template.py --input-json year.json --priority-levels P0 --markdown` first. P0 covers high-score B-group and score-band financing-efficiency samples. Fill only pre-close financing cost, scenario allotment-rate range, demand/quota heat, valuation, cornerstone/lock-up, and hard-tech commercialization fields. Normalize the filled CSV with `scripts/normalize_conflict_research_input.py`, then pass it to `scripts/audit_financing_efficiency.py --scenario-json normalized.json --margin-heat-json normalized.json`. Expand to P1 only after P0 is review-ready or explicitly accepted as a data gap.
   - When the stability audit reports concentrated false negatives around临界观察升级, run `scripts/prepare_borderline_upgrade_template.py --input-json year.json --priority-levels P0 --markdown` first. P0 covers high临界分 `可选观察` stocks in the primary year, using only pre-close score and IPO attributes; older-year samples remain low-weight stress tests. Fill only pre-close broker heat, financing cost, prospectus, and sentiment-divergence fields, then normalize the filled CSV with `scripts/normalize_conflict_research_input.py` before using it as margin-heat evidence. Expand to P1 only after P0 is review-ready or explicitly accepted as a data gap. Do not directly lower the `建议申购` threshold.
   - Before treating any generated current report or backtest as expert-ready, run `scripts/audit_report_quality.py --input report.md --type current|backtest` and address errors. Warnings may remain only when they are explicit data gaps, such as Chinese names still pending verification.

## Script Quick Start

Fetch current IPO data:

```bash
python scripts/fetch_current_ipos.py --pretty
```

Normalize user-provided community discussion:

```bash
python scripts/normalize_sentiment_input.py --stock-name 示例股份 --text "小红书/雪球/富途讨论摘录..."
```

Normalize broker margin and financing heat excerpts:

```bash
python scripts/normalize_margin_input.py --stock-name 示例股份 --code 01234 --text "富途/辉立/耀才孖展、额度、利率、截止时间摘录..."
```

Normalize historical margin rows for backtesting:

```bash
python scripts/normalize_margin_history.py --input margin-history.csv --markdown
python scripts/normalize_margin_history.py --input margin-history.csv
```

Prepare a historical margin collection template from B-group candidates:

```bash
python scripts/prepare_margin_history_template.py --backtest-json backtest-2026.json > margin-history-template.csv
python scripts/prepare_margin_history_template.py --backtest-json backtest-2026.json --markdown
python scripts/prepare_margin_history_template.py --backtest-json backtest-2026.json --priority-levels P0 --markdown
```

Estimate current IPO market temperature:

```bash
python scripts/estimate_market_regime.py
```

Fetch HKEX annual new-listing reports:

```bash
python scripts/fetch_hkex_listing_reports.py --years 2026,2025,2024 --boards Main,GEM --pretty
```

Build a report with default HKD 550,000 cash and 10x financing:

```bash
python scripts/build_recommendation_report.py --input ipos.json
```

Build a report with market temperature:

```bash
python scripts/build_recommendation_report.py --input ipos.json --market-regime-json market-regime.json
```

Build a report with financing heat gate:

```bash
python scripts/build_recommendation_report.py --input ipos.json --market-regime-json market-regime.json --margin-heat-json margin-heat.json
```

Build a report with automatic listing-performance review data:

```bash
python scripts/backtest_year_ipos.py --year 2026 --json > backtest-2026.json
python scripts/build_recommendation_report.py --input ipos.json --review-json backtest-2026.json
```

Build a report with pasted sentiment JSON:

```bash
python scripts/build_recommendation_report.py --input ipos.json --sentiment-json sentiment.json
```

Build a report with prospectus deep-dive JSON:

```bash
python scripts/deep_dive_prospectus.py --stock-name 示例股份 --code 01234 --url "https://www1.hkexnews.hk/..." --json > deep-dive.json
python scripts/build_recommendation_report.py --input ipos.json --deep-dive-json deep-dive.json
```

Calculate subscription expected return and financing break-even:

```bash
python scripts/calculate_subscription_return.py --entry-fee-hkd 3000 --first-day-pct 20 \
  --one-lot-success-rate-pct 10 --application-amount-hkd 5500000 \
  --cash-hkd 550000 --margin-rate-pct 3.8 --financing-days 7 --markdown
```

Audit financing efficiency for leveraged candidates under pre-close scenario assumptions:

```bash
python scripts/audit_financing_efficiency.py --input-json ipos.json \
  --scenario-first-day-pct 20 --scenario-one-lot-success-rate-pct 5 \
  --scenario-allotment-rate-pct 0.8 --max-credible-allotment-rate-pct 1.2 \
  --financing-rate-pct 3.8 --financing-days 7 --include financing
```

Audit financing efficiency with pre-close margin heat scenarios:

```bash
python scripts/audit_financing_efficiency.py --input-json ipos.json \
  --margin-heat-json margin-heat.json --scenario-profile base \
  --scenario-first-day-pct 20 --financing-rate-pct 3.8 \
  --financing-days 7 --include b-group
```

Prepare a pre-close execution-risk template for recommended stocks:

```bash
python scripts/prepare_execution_risk_template.py --input-json backtest-2026.json --priority-levels P0 --markdown
python scripts/prepare_execution_risk_template.py --input-json backtest-2026.json --priority-levels P0 > execution-risk-template.csv
python scripts/normalize_conflict_research_input.py --input execution-risk-template.csv --markdown
python scripts/normalize_conflict_research_input.py --input execution-risk-template.csv > execution-risk-normalized.json
python scripts/audit_financing_efficiency.py --input-json backtest-2026.json \
  --scenario-json execution-risk-normalized.json \
  --margin-heat-json execution-risk-normalized.json \
  --include scenario --scenario-profile base
```

Normalize a lightweight actual subscription note:

```bash
python scripts/normalize_actual_subscription_input.py \
  --text "科拓股份 02272 申购55万 中签1000股 每手500股 招股价4.5 卖出5.2 融资息300 手续费50" \
  --cash-hkd 550000 --markdown
```

Prospectus deep dive for a recommended stock:

```bash
python scripts/deep_dive_prospectus.py --stock-name 示例股份 --url "https://www1.hkexnews.hk/..."
```

Run a year-to-date backtest:

```bash
python scripts/backtest_year_ipos.py --year 2026
```

Audit whether current recommendations match the 2026-tested pre-close strategy:

```bash
python scripts/audit_strategy_alignment.py --input ipos.json --market-regime-json market-regime.json
# If the current report merged prospectus deep-dive JSON:
python scripts/audit_strategy_alignment.py --input ipos.json --market-regime-json market-regime.json --deep-dive-json deep-dive.json
```

Capture and rescore a single-year payload without refetching:

```bash
python scripts/backtest_year_ipos.py --year 2026 --json > /tmp/backtest-2026.json
python scripts/backtest_year_ipos.py --input-json /tmp/backtest-2026.json --rescore-input
```

Run an optional current-year-led, recency-weighted multi-year stress test only when the user asks for cross-cycle risk. If the user says older markets may differ and 2026 should be the focus, skip this step and keep optimization conclusions on the 2026 single-year audit:

```bash
python scripts/backtest_multi_year.py --years 2026,2025,2024
```

Audit backtest stability and overfitting risk:

```bash
python scripts/audit_backtest_stability.py --input-json backtest-2026.json --primary-year 2026
python scripts/audit_backtest_stability.py --input-json multi-year-backtest.json --primary-year 2026
```

Plan the next optimization actions from stability findings:

```bash
python scripts/audit_backtest_stability.py --input-json backtest-2026.json --primary-year 2026 --json > stability-2026.json
python scripts/plan_backtest_next_actions.py --stability-json stability-2026.json --backtest-json backtest-2026.json --backtest-report backtest-2026.md
python scripts/prepare_p0_evidence_pack.py --backtest-json backtest-2026.json --stability-json stability-2026.json
python scripts/prepare_p0_evidence_pack.py --backtest-json backtest-2026.json --stability-json stability-2026.json --consolidated-csv > p0-consolidated-2026.csv
python scripts/split_p0_consolidated_input.py --input p0-consolidated-2026.csv --domain all --output-dir p0-split-2026
python scripts/audit_expert_readiness.py --backtest-json backtest-2026.json --stability-json stability-2026.json --report backtest-2026.md --primary-year 2026 \
  --p0-readiness-json margin_history=p0-split-2026/margin-history-p0-from-consolidated.csv \
  --p0-readiness-json execution_risk=p0-split-2026/execution-risk-p0-from-consolidated.csv \
  --p0-readiness-json borderline_upgrade=p0-split-2026/borderline-upgrade-p0-from-consolidated.csv \
  --p0-readiness-json capital_conflict=p0-split-2026/conflict-research-p0-from-consolidated.csv \
  --json > expert-readiness-2026.json
python scripts/prepare_p0_research_queries.py --input expert-readiness-2026.json
python scripts/prepare_p0_research_queries.py --input expert-readiness-2026.json --limit 5 --csv > p0-research-queries-next-5-2026.csv
python scripts/prepare_p0_research_queries.py --input expert-readiness-2026.json --csv > p0-research-queries-2026.csv
python scripts/normalize_p0_research_ledger.py --input p0-research-queries-2026.csv --markdown
python scripts/run_p0_evidence_pipeline.py --consolidated p0-consolidated-2026.csv --ledger p0-research-queries-next-5-2026.csv \
  --output-dir p0-evidence-run-next-5-2026 --backtest-json backtest-2026.json --stability-json stability-2026.json \
  --report backtest-2026.md --primary-year 2026
python scripts/merge_p0_research_ledger.py --consolidated p0-consolidated-2026.csv --ledger p0-research-queries-2026.csv > p0-consolidated-2026-filled.csv
python scripts/split_p0_consolidated_input.py --input p0-consolidated-2026-filled.csv --domain all --output-dir p0-split-2026-filled
python scripts/run_p0_evidence_pipeline.py --consolidated p0-consolidated-2026.csv --ledger p0-research-queries-2026.csv \
  --output-dir p0-evidence-run-2026 --backtest-json backtest-2026.json --stability-json stability-2026.json \
  --report backtest-2026.md --primary-year 2026
```

Audit same-window capital conflicts:

```bash
python scripts/audit_capital_conflicts.py --input-json backtest-2026.json
python scripts/audit_capital_conflicts.py --input-json current-ipos.json --include-observation
```

Prepare a residual same-window conflict research template:

```bash
python scripts/prepare_conflict_research_template.py --input-json backtest-2026.json --priority-levels P0 --markdown
python scripts/prepare_conflict_research_template.py --input-json backtest-2026.json --priority-levels P0 > conflict-research-template.csv
```

Normalize filled residual conflict research rows before using them:

```bash
python scripts/normalize_conflict_research_input.py --input conflict-research-template.csv --markdown
python scripts/normalize_conflict_research_input.py --input conflict-research-template.csv > conflict-research-normalized.json
python scripts/backtest_margin_gate.py --backtest-json backtest-2026.json --margin-heat-json conflict-research-normalized.json
```

Prepare a T-1/T-0 upgrade template for borderline observation stocks:

```bash
python scripts/prepare_borderline_upgrade_template.py --input-json backtest-2026.json --markdown
python scripts/prepare_borderline_upgrade_template.py --input-json backtest-2026.json --priority-levels P0 --markdown
python scripts/prepare_borderline_upgrade_template.py --input-json backtest-2026.json --priority-levels P0 > borderline-upgrade-template.csv
python scripts/normalize_conflict_research_input.py --input borderline-upgrade-template.csv --markdown
python scripts/normalize_conflict_research_input.py --input borderline-upgrade-template.csv > borderline-upgrade-normalized.json
```

Audit pre-close future-data leakage:

```bash
python scripts/audit_preclose_leakage.py --input-json backtest-2026.json
python scripts/audit_preclose_leakage.py --input-json current-ipos.json --include-observation
```

Rescore cached single-year payloads after changing strategy:

```bash
python scripts/backtest_multi_year.py --years 2026,2025,2024 --rescore-input \
  --input-json 2026=backtest-2026.json \
  --input-json 2025=backtest-2025.json \
  --input-json 2024=backtest-2024.json
```

Backtest executable B-group decisions with historical margin heat:

```bash
python scripts/backtest_margin_gate.py --backtest-json backtest-2026.json --margin-heat-json margin-history-2026.json
```

Audit a generated report before using it as the final recommendation or strategy review:

```bash
python scripts/audit_report_quality.py --input current-report.md --type current
python scripts/audit_report_quality.py --input backtest-2026.md --type backtest
```

## Report Requirements

Start with a concise conclusion, then show the three recommendation buckets for still-actionable subscriptions only. Closed, grey-market, and listed names must be separated into `上市表现复盘` or monitoring notes and must not appear as status rows inside the pre-close recommendation buckets. For each actionable IPO include:

- Recommendation and confidence.
- Core evidence supporting the recommendation.
- Main risks and missing checks.
- Funding plan: cash, financing need,甲组/乙组 boundary, and overlap constraints.
- Borderline observation checklist when applicable: list `可选观察` stocks near the recommendation threshold and the T-1/T-0 checks needed before any upgrade. When optimizing after a false-negative concentration warning, generate `prepare_borderline_upgrade_template.py` and normalize the filled rows before treating any upgrade signal as evidence.
- Prospectus deep-dive priority queue: list still-actionable `建议申购` stocks as P0 and borderline `可选观察` stocks as P1, with HKEX prospectus links and fields to verify.
- Prospectus deep-dive merge when available: show financial, valuation, cornerstone/lock-up, use-of-proceeds and risk signals from `--deep-dive-json`; serious negative signals can downgrade `建议申购` to `可选观察`, but positive snippets alone should not justify乙组 execution.
- Financing pricing checklist: centralize stocks that need T-1/T-0 broker checks, including margin demand, quota, rate, fee, cutoff, loan days, and cash-window conflict before any leveraged order.
- Financing efficiency audit when using leverage: show scenario first-day move, scenario one-lot probability, expected allotted lots or pre-close allotment-rate range, financing interest/fees, break-even move, required expected lots and required allotment rate to break even, and whether expected net P/L is positive. State clearly that final one-lot success and first-day results cannot be used as lock-order inputs.
- Recommended-stock execution-risk review when optimizing false positives: if `建议申购` misses concentrate in one-lot expected P/L, financing efficiency, hard-tech valuation, or weak demand, generate `prepare_execution_risk_template.py --priority-levels P0`, normalize the filled rows, and rerun `audit_financing_efficiency.py --scenario-json`. Treat failed rows as financing downgrade or valuation deep-dive candidates, not as proof that all hard-tech or all high-score IPOs should be penalized. Expand to P1 only after P0 has time-valid evidence or is explicitly recorded as a data gap.
- Financing lock timeline: show which stocks are T-2/T-1/T-0, what must be done immediately, and what must not be delayed until allotment or grey-market data.
- Same-window funding conflict review: when default HKD 550,000 cash cannot cover overlapping actionable IPO windows, list the skipped/conflicted stocks, the currently scheduled peers, and the pre-close checks needed to replace the schedule. Use pre-close capital-efficiency proxies such as score, bounded entry exposure, planned application amount, lock-up length, financing interest, and break-even move; do not decide this from one-lot success rate, allotment, grey-market, or first-day data.
- Residual conflict research template when optimizing: if `事前效用组合最优` still leaves high opportunity cost, generate a补采清单 for T-1/T-0 broker heat, prospectus deep dive, and financing efficiency assumptions. Normalize the filled template with `normalize_conflict_research_input.py` before using it; treat rejected rows as data gaps, not a reason to tune thresholds again.
- Return economics when reviewing or comparing strategies: one-lot expected gross P/L, financing interest, break-even first-day move, and whether the result is only a review proxy.
- Strategy alignment when optimizing: compare the current-report buckets with the 2026-tested pre-close scoring logic; count only still-actionable samples as true strategy drift, and treat closed/listed samples as context differences.
- Backtest stability when optimizing: run the stability audit and explain any warnings about score-band non-monotonicity, score-band financing-efficiency divergence, B-group margin coverage, capital-window opportunity cost, or current strategy underperformance versus the baseline before changing thresholds again.
- Expert readiness gate when iterating: run `audit_expert_readiness.py` after leakage, report-quality, stability, and P0 evidence-pack checks. Treat `专家满意=否` as evidence that there are still optimization or evidence-collection directions, not as strategy failure. When it returns a P0 backlog, generate `prepare_p0_research_queries.py --csv` output and use it as a fillable ledger to collect only申购截止前 broker-margin, HKEX prospectus, scenario, and auxiliary sentiment evidence. Run `run_p0_evidence_pipeline.py` to normalize the ledger, merge eligible evidence into blank P0 consolidated fields, split back to domain CSVs, and optionally rerun the expert gate. This pipeline closes evidence only; it must not be used as threshold tuning.
- Current-report listing review: when `--review-json` data is available, match by stock code and show actual first-day move, oversubscription, one-lot success rate, one-lot expected gross P/L, and whether the result confirms or challenges the original bucket. Add a diagnostic action for next time, but do not let these review metrics change the pre-close recommendation score.
- Sentiment summary if available, clearly separated from structured evidence.
- Source links and fetch date.
- Data coverage for backtests, especially detail-page success, industry, sponsor, one-lot success rate, and whether low coverage makes recommendations conservative.
- Capital-window stress test for backtests: show how many `建议申购` names default HKD 550,000 cash could schedule without overlap when ranked by pre-close score, how many were skipped because cash was already locked, peak cash reserved, and one-lot expected P/L for selected versus skipped names.
- Score-band calibration for backtests: show whether higher事前 scores actually have better first-day and one-lot expected outcomes, and explicitly warn against mechanical threshold tuning when the relationship is not monotonic.
- Backtest miss attribution: separate `建议申购但首日不涨/破发` and `未建议申购但首日大涨`, then explain whether the miss came from heat-gate failure, sector/sponsor weighting, missing data, valuation/prospectus gaps, market-regime diffusion, or low capital efficiency.

End with a short disclaimer: data may be delayed or incomplete, financing fees and allotment are uncertain, and the report is not investment advice.
