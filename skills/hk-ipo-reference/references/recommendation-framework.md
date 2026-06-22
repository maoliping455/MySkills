# Recommendation Framework

## Buckets

Use exactly three user-facing buckets:

- `建议申购`: structured evidence is strong enough to consider applying. Financing is considered only when expected edge and data confidence justify the cost.
- `可选观察`: data is mixed, subscription has closed, pricing is incomplete, or the stock needs prospectus/sentiment confirmation before committing meaningful cash.
- `暂不参与`: risk/reward is weak, critical data is missing, funding window conflicts are severe, or the stock is primarily useful as a review sample.

## Core Factors

Positive factors:

- Clear HKEX prospectus and listing announcement links.
- Parsed prospectus deep-dive evidence showing durable revenue growth, credible profitability or cash-flow quality, reasonable valuation versus peers, and credible cornerstone/lock-up support.
- Reasonable valuation versus listed peers or recent IPO comparables.
- Profitable or improving financial profile, unless the sector is explicitly valued on pipeline or strategic scarcity.
- Strong sponsor or underwriter record in similar Hong Kong IPOs.
- High-quality cornerstone investors with meaningful lock-up.
- Scarce sector exposure such as semiconductor equipment, AI infrastructure, high-end manufacturing, quality consumer, or high-growth software, when valuation is not excessive.
- Healthy but not irrational subscription demand.
- Low one-lot entry fee for cash participation, or a clear case where financing cost is likely justified.
- Complete enough issuance evidence for an actionable recommendation: sponsor and Hong Kong public-offer structure should be known. If either is missing, keep the stock in `可选观察` until prospectus or detail-page checks fill the gap.

Negative factors:

- Missing HKEX documents or unverifiable pricing.
- Prospectus deep-dive risk signals such as expensive valuation, ongoing losses without a credible path, negative operating cash flow, customer concentration, related-party transactions, or weak use of proceeds.
- Expensive valuation, weak revenue quality, high customer concentration, or heavy related-party transactions.
- -B biotech or pre-profit profile without enough pipeline, catalyst, or cornerstone support.
- Weak sponsor record, thin cornerstone support, or excessive pre-IPO investor overhang.
- Crowded financing demand where interest cost and allotment dilution may erase the expected edge.
- Subscription or refund windows that overlap with stronger IPOs and consume the same cash.
- Community hype without structured evidence.
- Generic software, IT consulting, application software, or telecom-equipment labels in a neutral/cold IPO market without hard-tech scarcity or prospectus-level support.

## Funding Rules

Default cash assumption: HKD 550,000.

Default financing assumption: 10x buying power, i.e. approximately HKD 5,500,000 gross application capacity before broker-specific limits, fees, and haircut rules.

Funding logic:

- Do not limit the number of IPOs by default. Limit only by actual cash lock-up overlap and confidence.
- The same cash cannot be reused across overlapping subscription/refund/listing windows.
- Apply cash-window allocation only to still-actionable subscriptions or to positions the user actually entered. A stock whose public subscription has already closed should move to review/grey-market monitoring and should not consume future cash in the default plan.
- For default cash scheduling, sort first by recommendation category and pre-close score, then review the whole overlapping window rather than only one stock at a time. In backtests, use the `事前效用组合最优` schedule to maximize pre-close score, bounded entry exposure, and shorter lock-up under the HKD 550,000 cash cap. Low entry fee improves flexibility, but it is only a tie-breaker and can underuse cash exposure when scores are otherwise similar. Same-window conflicts still require prospectus, T-1/T-0 heat, quota, rate, and cost review before replacing or confirming an allocation.
- Maintain a financing lock timeline for still-actionable candidates. T-2 should finish prospectus valuation and broker quote preparation; T-1 should collect margin amount/multiple, quota tightness, rate, fees, and broker cutoff; T-0 should only use already-confirmed financing evidence. If the heat/cost gate is still incomplete at T-0, downgrade to甲组/现金 or skip instead of waiting for allotment, grey-market, or first-day data.
- Estimate recent IPO market temperature from already-listed IPOs before sizing financing. Use market temperature to control leverage and confidence, not to replace company-level evidence.
- Financing decisions must be made before the broker financing cutoff, not after allotment results. Build a T-2/T-1 financing decision using only information visible before the IPO closes.
- For high-conviction names, compare `甲组顶格` and `乙组低位` economics. Entering乙组 only makes sense when financing cost, estimated allotment probability, pre-close demand signals, and expected first-day/grey-market edge are all defensible.
- A stock can be an `乙组候选` before the financing heat gate is satisfied, but it is not an executable B-group order. In the default funding schedule, reserve only the cash/甲组 fallback amount until the heat gate is satisfied; reserve full 10x B-group cash only after the gate passes.
- Maintain a financing pricing checklist for still-actionable candidates. Before any leveraged order, verify broker margin demand, quota, annualized rate, handling fee, financing cutoff, loan days, and cash-window conflicts in one place.
- Run a financing efficiency scenario audit before treating乙组/大额甲组 as executable. Use pre-close assumptions for target first-day move, expected one-lot probability, expected allotted lots or expected allotment-rate range, maximum credible expected lots/rate, financing rate, fees, and loan days. Prefer allotment-rate scenarios when comparing several IPOs because the script converts application lots into stock-specific expected lots. If the user does not have a defensible allotment-rate assumption yet, use the pre-close margin heat profile (`strict`, `base`, or `hot`) as a pressure-test scenario only; it is not a prediction. If expected net P/L is negative, the break-even move is above the target scenario, required expected lots exceed the credible range, or the heat/cost gate is not satisfied before cutoff, downgrade to甲组/现金 or skip even when the first-pass score is high.
- When annual false positives concentrate in one-lot expected P/L, capital efficiency, hard-tech valuation, or weak demand, use `prepare_execution_risk_template.py --priority-levels P0` first to collect per-stock pre-close financing cost, scenario allotment-rate range, valuation, cornerstone/lock-up, and demand validation for high-score B-group and score-band financing-efficiency samples. Normalize the filled rows and run `audit_financing_efficiency.py --scenario-json` so each stock uses its own assumptions. Expand to P1 only after P0 is review-ready or explicitly accepted as a data gap. Do not globally penalize all hard-tech or all high-score stocks from a small set of misses.
- When several P0 workflows are active at once, run `prepare_p0_evidence_pack.py` before filling CSVs. Use the overlap table to collect one stock's broker heat, valuation, scenario allotment-rate, and same-window notes together instead of treating each workflow as an unrelated task.
- Do not optimize on first-day percentage alone. For review or scenario analysis, calculate `one-lot expected gross P/L = one-lot entry fee × first-day move × one-lot success rate` and compare it with financing interest, fees, and the break-even first-day move.
- For same-window funding conflicts, use only pre-close capital-efficiency proxies: entry fee, planned application amount, expected financing interest/fees, loan days, and the break-even move if one lot is received. One-lot success rate, allotment result, grey market, and first-day move are review data and must not choose the pre-close schedule. When residual conflicts need extra evidence, collect the排期边界 first with `prepare_conflict_research_template.py --priority-levels P0` and normalize the filled rows with `normalize_conflict_research_input.py` before letting the data affect scheduling or financing-gate backtests. Expand to P1 only after P0 is review-ready or explicitly accepted as a data gap.
- For medium-conviction names, prefer cash one-lot/multi-lot or small financing only if fee drag is low.
- For low-conviction names, do not recommend financing.
- If financing rate, handling fee, or loan days are unknown, state that融资成本未核实 and avoid presenting leveraged application as the default action.

## Decision Timeline

Use three separate decisions:

- `T-3/T-2 初评`: use prospectus, sponsor, sector, valuation, cornerstone, entry fee, and capital-window overlap to decide whether the stock is eligible for cash or financing.
- `T-1/T-0 融资锁单`: before the broker financing deadline, refresh pre-close signals: broker margin subscription totals, margin multiple changes, quota exhaustion, broker financing rate, application cutoff, retail discussion, and comparable IPO demand. Decide cash/甲组/乙组 here.
- `配售后/暗盘/首日复盘`: use final oversubscription, one-lot success rate, allotment result, grey market, and first-day move only for review, sell discipline, and future strategy calibration. These data are too late for initial financing decisions.

Before T-1/T-0, maintain a prospectus deep-dive queue. P0 is still-actionable `建议申购`; P1 is borderline `可选观察`. Deep dive should verify valuation, revenue/profit quality, cornerstone/lock-up, use of proceeds, key risks, and -B/-P pipeline/commercialization, then feed the findings back into reasons, risks, and financing intensity.

When prospectus deep-dive JSON is available, merge it into the recommendation report rather than leaving it as a separate note. Positive snippets can raise confidence and support a cash/甲组 decision, but they must not by themselves unlock乙组 execution. Two or more serious negative deep-dive signals, or a large negative deep-dive score adjustment, should downgrade `建议申购` to `可选观察` until valuation and funding economics are rechecked.

Treat `乙组候选` as a pre-close watchlist, not an execution instruction. Execute乙组 only after the T-1/T-0 financing checkpoint confirms demand and cost; otherwise downgrade to甲组 or cash.

When recent IPO market temperature is `偏冷`, do not execute乙组 by default even for high-scoring stocks. Keep the stock-level bucket based on fundamentals and documents, but downgrade financing to甲组/现金 unless pre-close heat and cost evidence is unusually strong.

乙组执行前至少满足两个相互独立的融资截止前需求/额度类强热度信号，并且融资成本可接受。低利率或低手续费是成本条件，不算作热度信号:

- 多家券商显示孖展认购额或孖展倍数明显领先。
- 融资额度紧张、券商截止时间提前，且利率/手续费后仍有足够预期收益空间。
- 最后申购日、且早于券商融资截止前，申购需求明显加速。
- 公开新闻、券商点评和社区讨论方向一致，而不是单一截图或孤立传闻。

独立信号按类别计数，不按同一截图里的标签个数计数。`孖展倍数显著领先` 和 `孖展金额高` 同属 `孖展规模`，只能算一个独立热度类别；还需要多券商一致、额度紧张/截止提前、尾日需求加速或其它可交叉验证的需求信号。

Use `normalize_margin_input.py` when the user provides broker margin or financing excerpts. Treat `execution_gate=满足` as evidence that the heat gate is satisfied, but still require cash-window, broker-specific quota, rate, and cutoff checks before presenting乙组 as executable.

Pre-close heat proxies:

- Broker disclosed margin subscription amount or margin multiple, especially whether it accelerates into the final day.
- Financing quota exhaustion, rate hikes, or broker cutoff being pulled forward.
- Multiple brokers showing high subscription demand, not just one promotional screenshot.
- Public news about cornerstone quality, final pricing, and market-wide IPO risk appetite.
- Community sentiment can support the signal, but should not replace structured demand or cost checks.

## Review Rules

When grey-market or first-day data is available:

- Compare recommendation bucket against actual move.
- Compare headline first-day move with one-lot expected P/L and financing break-even. A stock can rise sharply but still be a weak subscription if allotment probability is tiny or financing cost is too high.
- Separate errors caused by missing data, valuation judgment, sentiment noise, and market regime.
- Attribute false positives and false negatives into actionable buckets: final demand/heat miss, financing gate not confirmed, sector/sponsor over-weighting, data-field gaps, valuation/prospectus gaps, market-regime diffusion, and low capital efficiency.
- Update reasoning qualitatively in the report, but do not persist model state or write a database.

## Backtest-Derived Adjustments

The 2026 year-to-date backtest as of 2026-06-21 showed a strong IPO regime: many `可选观察` names had large first-day gains, while several `建议申购` names still broke or were flat. Use these adjustments:

- Do not automatically skip `-B` or `-P` stocks in a hot market. Penalize them, but keep them in `可选观察` when they have strong sponsors, low entry fee, high-quality cornerstone signals, or scarce sector narratives.
- Do not treat low entry fee as enough for financing. Low entry fee only supports participation flexibility; financing requires a separate edge check.
- Add a pre-close financing checkpoint. If broker margin subscription is strong, quota tightens, and multiple sources converge before cutoff, the stock can be upgraded from cash/甲组 to乙组 candidate. If this signal is absent, do not wait for allotment results; keep the financing decision conservative.
- Add a market-temperature checkpoint. 2024/2025/2026 backtests showed that using market temperature to change recommendation buckets is unstable; using it to cap融资强度 is more robust and less prone to overfitting.
- Exception: in a clearly hot IPO market, a low-entry-fee stock with available prospectus/listing documents but incomplete aggregator fields may be kept in `可选观察` instead of `暂不参与`. This is an observation protection rule only; it must not upgrade the stock to `建议申购` or justify financing without prospectus and pre-close heat evidence.
- In the 2026 hot-market regime, avoid prematurely excluding high-price but non-extreme stocks when they have a strong sponsor, complete public detail/prospectus fields, and entry fee within ordinary cash capacity. Keep them in `可选观察` with a `现金参与` default; do not upgrade them to `建议申购` unless valuation, scarcity, and pre-close heat also support it.
- Add a narrow generic-tech guard. 2024/2025/2026 recency-weighted backtests showed that neutral/cold-market generic software or broad IT names should start in `可选观察` unless they have hard-tech scarcity, exceptional prospectus evidence, or strong pre-close heat. This improved cold-market false positives without adopting a blanket cold-market downgrade.
- Use final public-offer oversubscription and one-lot success rate only as a review label. If final oversubscription is low or one-lot success rate is high, ask why the pre-close heat signal failed or was ignored.
- When backtesting without historical broker-margin time series, report `乙组候选` separately from actual乙组 execution. Candidate performance tests stock selection quality, not whether financing should have been executed.
- When historical pre-close margin heat is available, use `backtest_margin_gate.py` to split `乙组候选` into `乙组闸门满足`, `乙组闸门不满足`, and `乙组缺热度数据`. Only the first group approximates executable乙组.
- In annual backtests, always show historical margin-heat coverage before discussing executable B-group quality. Final oversubscription or one-lot success can justify collecting pre-close margin data, but it cannot replace broker margin history. If B-group pre-close heat coverage is below 70%, treat B-group execution as unvalidated. For 2026-led optimization, P0 margin-history collection must cover high-score B-group candidates with missing or not-met heat gates even when their entry fee is not high.
- Treat high-price or high-entry-fee non-hot-sector IPOs cautiously. Without strong sponsor/cornerstone support, avoid乙组 financing.
- Add a return-economics check to every strategy iteration. A rule that improves average first-day gain but lowers one-lot expected P/L or pushes financing break-even above plausible first-day gains should not be adopted.
- Use HKEX annual New Listing Reports to reconstruct static fields in historical backtests, especially sponsor and offer price. Do not use those reports as a substitute for prospectus/industry quality: if industry, valuation, cornerstone, or risk-factor fields are missing, keep recommendations conservative and prefer `可选观察` over `建议申购`.
- In multi-year backtests, distinguish raw recency weights from effective weights. If a year has weak detail-page or industry coverage, assign it zero effective weight and keep it only as a data-quality and cross-cycle risk note; otherwise missing-field conservatism can masquerade as a market signal.
- Track false positives and false negatives in every backtest report, then summarize miss attribution instead of only listing names. The most useful errors are `建议申购但首日不涨/破发` and `未建议申购但首日大涨`.
- Read `miss_attribution_summary` from annual backtest JSON before changing rules. If one reason dominates, adjust that workflow gate first: financing heat/cost, data-field coverage, hard-tech valuation filter, borderline-observation upgrade, or capital-efficiency review. Do not mechanically move recommendation thresholds because a few individual names were wrong.
- Track a `临界观察` queue: stocks that are `可选观察` but close to the recommendation threshold. They should trigger T-1/T-0 checks for margin heat, quota, rate, prospectus valuation, cornerstone quality, and sentiment divergence, but they must not auto-upgrade to `建议申购` or乙组 execution. When annual miss attribution says false negatives are concentrated in this queue, use `prepare_borderline_upgrade_template.py --priority-levels P0` first to collect primary-year high临界分 evidence and `normalize_conflict_research_input.py` to reject late or contaminated rows before any upgrade backtest. Expand to P1 only after P0 is review-ready or explicitly accepted as a data gap.
- Track score-band calibration in every annual backtest. If `78+` scores do not clearly beat `72-77` on strong-return rate and one-lot expected P/L, do not mechanically raise the recommendation threshold; treat the score as a queueing signal and rely on prospectus valuation, pre-close heat, financing cost, and cash-window checks for final sizing.
- If `78+` has stronger median first-day performance but weaker median one-lot expected P/L than `72-77`, treat it as a financing/allotment-efficiency warning rather than proof that the high-score bucket is wrong. Keep the recommendation threshold stable and force high-score names through融资成本、情景配售率、打平涨幅 and broker-heat checks before乙组 execution.
- Track capital-schedule priority sensitivity in every annual backtest. Compare selected and skipped groups on average expected one-lot P/L first, then total expected one-lot P/L as opportunity-cost context. If a pre-close tie-breaker such as `分数+低入场费优先` improves selected average expected one-lot P/L and lowers skipped-conflict average P/L versus pure score sorting, use it as the current default cash-scheduling tie-breaker; do not treat it as proof that low entry fee alone justifies subscription or financing.
- For 2026/current-market strategy tuning, use the current year as the primary evidence and use older years only as low-weight stress tests. If the user explicitly wants to focus on 2026 because older regimes may differ, do not run or cite older-year tuning unless asked for a stress test. In multi-year stress tests, keep the first older year at a small weight such as 0.15 by default, and do not let older cold-market samples directly override a signal that is demonstrably working in the current regime.
- Before applying 2026 backtest conclusions to a current report, run a strategy-alignment audit on the same IPO payload. Count only still-actionable samples as real strategy drift; closed, grey-market, or listed samples can differ because the current report must move them into review context while the backtest model represents a pre-close decision.
- Avoid one-year overfitting by requiring economic logic, not only backtest lift. A rule that improves 2026 should still make sense in terms of sponsor quality, scarcity, valuation, funding heat, and financing cost.
