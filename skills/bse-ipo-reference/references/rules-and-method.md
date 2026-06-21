# Rules And Method

## Rule Summary

- BSE online IPO subscription uses cash subscription, not Shanghai/Shenzhen market-value lottery.
- Investors must subscribe in 100-share lots and normally need sufficient cash before submitting.
- When valid online subscription volume exceeds online shares, shares are allocated by proportion:
  `allotment_rate = online_shares / valid_subscription_shares`.
- The whole 100-share part is commonly called `正股`.
- The fractional part below 100 shares is pooled and secondarily allocated 100 shares at a time by subscription quantity priority; equal quantities are ordered by time priority.
- One investor can only validly subscribe once for the same IPO; repeated or multi-account subscriptions under the same investor identity generally use the first valid order.

## Required Data

For each IPO, collect:

- `P`: issue price, yuan/share.
- `W`: online shares available for subscription, shares.
- `M`: online subscription cap, shares.
- `F`: expected or actual online frozen funds / valid subscription amount, yuan.
- `R`: actual or predicted online allotment rate, decimal. Use percent only for display.
- User cash `C`, yuan.
- Optional secondary-allocation threshold `Y`, yuan, from community estimates or historical analogs.

Use the issue announcement's online shares when available. Do not blindly use "planned issue shares"; strategic placement, over-allotment option, and offline/online clawback can change online shares.

## Core Formulas

If actual or expected frozen funds `F` is known:

```text
valid_subscription_shares = F / P
R = W / valid_subscription_shares = W * P / F
```

If actual allotment rate is known, use it directly:

```text
R = allotment_rate_pct / 100
```

For a user's cash, calculate the internal proportional result first:

```text
subscription_shares = floor(C / P / 100) * 100
if M is known:
  subscription_shares = min(subscription_shares, M)
subscription_amount = subscription_shares * P
raw_allotted_shares = subscription_shares * R
regular_shares = floor(raw_allotted_shares / 100) * 100
fractional_claim = raw_allotted_shares - regular_shares
```

`raw_allotted_shares` is only an internal proportional calculation. Do not include it in user-facing tables and do not call it theoretical allotment. Actual BSE online allotment should be discussed in 100-share lots:

```text
confirmed_regular_shares = regular_shares
possible_total_if_secondary_allocation = regular_shares + 100 when fractional_claim > 0 and the account ranks high enough
```

Lot-adjusted regular-share threshold:

```text
shares_needed_for_N_regular_shares = ceil((N * 100) / R / 100) * 100
cash_needed_for_N_regular_shares = shares_needed_for_N_regular_shares * P
```

The common 100-share threshold is `cash_needed_for_1_regular_share`.

## Secondary Allocation Modeling

Do not present secondary allocation as deterministic unless the final result has been announced and the user's exact order is known.

Use these labels:

- `正股`: `regular_shares >= 100`.
- `碎股候选`: `fractional_claim > 0`; may receive one extra 100-share lot if subscription quantity ranks high enough.
- `碎股门槛未知`: no reliable community or historical threshold exists.
- `碎股可能`: `secondary_threshold_yuan` is provided and `subscription_amount >= secondary_threshold_yuan`.
- `碎股不足`: `secondary_threshold_yuan` is provided and `subscription_amount < secondary_threshold_yuan`.

Important interpretation:

- Secondary allocation ranking uses total subscription quantity, not "remaining cash after regular shares".
- The last boundary can be decided by time priority when many accounts subscribe the same quantity.
- If the subscription cap is lower than the 100-share regular threshold, top subscription cannot reliably receive regular shares.

## Scenario Design

Before result announcement, create at least three scenarios:

- Conservative: lower expected frozen funds, often based on low-heat comparable IPOs.
- Base: median or weighted average of recent comparable BSE IPOs.
- Crowded: high expected frozen funds when the issue is small, sector is hot, recent first-day gains are strong, or community estimates cluster high.

Use expected online subscription amount `F` as the primary scenario variable. This is usually more intuitive than directly guessing the allotment rate because public discussions and comparable IPO result announcements often quote total frozen/subscribed amount.

Give each scenario a subjective probability weight. These probabilities are not facts; they should summarize the analyst's current reading of comparable IPOs, issue size, sector heat, recent BSE IPO performance, and community estimates. If weights do not add to 100 exactly, normalize them before aggregating result probabilities.

For each scenario, show:

- Estimated online subscription amount.
- Implied allotment rate.
- 100-share regular-allotment threshold.
- Whether the subscription cap can cover the 100-share regular threshold.

Use recent issue-result announcements as anchors. Community data can help estimate `F` and secondary-allocation thresholds, but keep it separated from verified data.

## Crowded Scenario Guard

Do not let the base historical estimate dominate a hot IPO. Add a crowded protection scenario before giving funding advice.

Use tiered protection rather than a blanket recent-high estimate. Large online supply alone is not enough for a strong crowded guard, because it can also dilute the allotment rate without attracting proportionally more subscription funds. The strongest guard should require either an unusually high top-subscription cash amount, or both high top-subscription cash pressure and high online-supply pressure.

Use the crowded guard when at least two of these signals are present:

- Current subscription cap cash is above the recent median or near recent high levels.
- Online issue shares are materially above comparable recent IPOs.
- Issue P/E is at a clear discount to industry P/E or the business/theme is getting visible attention.
- Recent BSE IPOs have high first-day returns or community discussions converge on high frozen funds.
- Top subscription would receive multiple regular lots under the base case, so a higher final `F` can materially reduce the expected tier.

Set the crowded `F` to the higher of:

```text
base_F * 1.18 to 1.30 for strong cap+supply pressure
base_F * 1.06 to 1.12 for weak or single-sided pressure
recent_q75_F with a modest premium
community_high_F when credible and timestamped
```

For user-facing bands, treat the crowded threshold as the conservative decision line. A band that only clears the base threshold but not the crowded threshold should be labeled as `0-100股正股边界` or `100-200股正股`, not as stable.

When scenarios disagree on the regular-share tier, show the resulting range directly, for example `100-200股正股` or `300-500股正股`; avoid vague labels such as `有机会正股`.

## Small-Issue Cooling Check

Before applying a crowded guard, check whether the IPO is materially smaller than recent samples. If both the top subscription cash and online issue shares are far below recent levels, do not lift the estimate just because the recent market is hot or valuation looks cheap. In that case:

- Pull the base `F` toward small-size comparable IPOs.
- Keep the generic buffer small unless community estimates cluster high.
- Treat the result as a碎股/顶格博弈 problem if the regular threshold remains above the subscription cap.

## Dynamic Secondary Boundary

Do not hard-code secondary-allocation boundaries such as `500万` or `520万`. Infer a fresh boundary for each IPO, then simplify the final table for users.

Use three evidence layers:

- Recent BSE result data: actual online subscription amount, allotment rate, account count if disclosed, issue size, top-subscription regular-share threshold, and any reconstructed secondary threshold from recent comparable IPOs.
- Community estimate cluster: collect multiple estimates from Jisilu/Xueqiu/Xiaohongshu/Zhihu/Caifuhao or similar sources; note timestamp, author, and whether estimates converge or diverge.
- Current-IPO supply pressure: adjust for online share supply, subscription cap, issue size, sector/theme heat, valuation, recent first-day BSE performance, and whether top subscription is below the 100-share regular threshold.

Use this internal conversion:

```text
secondary_low = lower credible boundary where accounts may start to have a chance
secondary_mid = main community / comparable-result consensus
secondary_high = conservative boundary where the account is more meaningfully in the game
secondary_lot_supply = online_shares / 100
```

Interpret supply pressure qualitatively:

- If `max_subscription_amount < cash_needed_for_1_regular_share`, top subscribers are still competing only for secondary allocation; the boundary is usually tighter.
- If `secondary_lot_supply` is small and market heat is high, move `secondary_mid/high` upward.
- If community estimates are scattered, widen `secondary_low-high` rather than pretending to know a precise cutoff.
- If evidence is weak, say the boundary is uncertain and keep the funding bands broad.

In final output, do not expose the full internal model unless the user asks. Collapse it into simple user-facing bands:

- `< secondary_low`: `预计0股`
- `secondary_low - secondary_high`: `边界博碎股`
- `secondary_high - 顶格`: `博100股碎股`

Apply this priority order when creating bands:

1. Regular-allotment thresholds first. If the band reaches `cash_needed_for_1_regular_share`, label the exact regular-share tier, such as `100股正股`, `200股正股`, `300股正股`, and continue every 100 shares up to the subscription cap or analysis maximum. Do not let the secondary-boundary model overwrite the regular-share result.
2. Secondary-boundary bands only apply below the regular threshold.
3. If `max_subscription_amount` is below both the regular threshold and `secondary_low`, append at most one exact `=顶格` row. Use `顶格博碎股` and note that it is below the inferred boundary and depends on time/ranking.

## Recommendation Logic

Give practical funding bands. Express them as cash ranges and expected results, not raw proportional shares or extra probability columns:

- `陪跑区`: user's cash is far below both the regular threshold and any plausible secondary threshold.
- `博碎股区`: below regular threshold but near/above a credible secondary threshold.
- `稳正股区`: at or above lot-adjusted 100-share regular threshold plus a 5%-10% buffer.
- `多手区`: enough for 200/300+ regular shares; show each reachable 100-share tier instead of collapsing the amount guidance.
- `顶格仍不稳`: max subscription amount is below the 100-share regular threshold.

For each funding band, summarize outcomes as direct user-facing labels such as `预计0股`, `边界博碎股`, `博100股碎股`, `100股正股`, or `100股正股，另有碎股机会`. If outcomes split across scenarios, describe the uncertainty in the result label or note, for example `情景分化，有机会正股`; do not add a separate `正股概率` column by default. Keep the table simple even when the internal boundary estimate uses multiple inputs.

When the user asks "投多少钱", recommend a range, not a single false-precision number. Explain the assumptions behind the range and name the expected online subscription amount scenarios that drive the answer.

## Risk Boundaries

Always state:

- Calculations are references, not investment advice.
- Final allotment depends on final valid subscription amount and account distribution.
- Scenario probabilities are subjective assumptions and can be wrong.
- Secondary allocation depends on subscription ranking and timing, so it cannot be guaranteed.
- The new stock can break or underperform after listing.
- Cash freeze has opportunity cost, especially across weekends or holidays.
