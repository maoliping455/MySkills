# Data Sources

## Source Priority

1. HKEX official new-listing pages and PDF documents.
   - Use for prospectus, listing announcement, allotment result, and official company naming.
   - Use HKEX annual New Listing Report workbooks for historical backtests when AASTOCKS detail pages are incomplete. They can reconstruct official English name, sponsor, listing date, offer price, funds raised, and board.
   - Do not treat annual report backfill as a prospectus deep dive. It does not provide industry quality, valuation detail, cornerstone terms, or risk factors.
   - Prefer Chinese PDF links when available.
   - If HKEX is temporarily unavailable, record the failure and continue with AASTOCKS while marking document confidence lower.

2. AASTOCKS IPO pages.
   - Use for current IPO discovery, offer price, lot size, entry fee, closing date, grey-market date, listing date, industry, sponsor, and public-offer fields.
- Use listed-IPO pages for market-temperature estimation and post-listing review. Only include IPOs already listed before the current decision date.
- Check listed-IPO page coverage before long-history backtests; current public pagination may not expose older years even when HKEX has listing reports.
- Treat AASTOCKS as a structured aggregator, not as the final legal source.
- For long-history strategy iteration, capture the raw single-year JSON once, then rescore the same payload. Repeated live fetching can change detail-field coverage and create false strategy differences.

3. Broker or financial-media data pages.
   - Futubull, Phillip, Bright Smart, Eddid, Eastmoney HK, Futu news, AA news, GLH, Zhitong, and similar public pages can supplement subscription heat, grey-market prices, and first-day performance.
   - User-provided screenshots or text excerpts about broker margin subscription, quota, financing rate, and cutoff should be normalized with `normalize_margin_input.py`.
   - Cross-check material numbers against HKEX announcements whenever possible.

4. Community sentiment.
   - Xiaohongshu, Xueqiu, Futubull community, Jisilu, Gelonghui comments, Zhihu, and Telegram/WeChat screenshots are auxiliary only.
   - Do not use sentiment as the sole reason to recommend financing.

## Fields To Collect

- Stock code and Chinese stock name.
- Board, industry, background flags such as H share, -B, W, or Z.
- Offer price or price range, lot size, and one-lot entry fee.
- Subscription start, closing date, refund date if available, grey-market date, and listing date.
- HK public-offer shares, international placing shares, clawback or reallocation mechanics when available.
- Sponsor, underwriters, cornerstone investors, lock-up arrangements, and use of proceeds.
- Prospectus and listing-announcement links.
- HKEX annual listing report fields: official English name, sponsor, prospectus date, listing date, offer price, funds raised, and board. Use these only as static-field reconstruction in backtests.
- Subscription heat, margin multiple, grey-market result, allotment result, and first-day performance when available.
- One-lot success rate, applied lots for one lot, allotment table/获配曲线, and final public-offer oversubscription for review-only return calculations.
- Recent listed IPO first-day performance for market temperature. This controls financing aggressiveness; it must not replace current-stock evidence.
- Pre-close financing signals: broker margin subscription amount, margin quota status, financing rate, application cutoff, and whether final-day demand accelerates.
- Financing heat gate output: strong signal count, broker count, execution gate, risk flags, and financing rate used for rough interest cost.
- Broker-specific financing costs: annualized rate, handling fee, interest days, refund timing, quota haircut, and whether the user can still lock financing before the broker cutoff.
- Historical margin heat backtests require timestamped broker excerpts. `preclose_confirmed` alone is insufficient when `observed_at` is missing, `source_published_at` is provided but late, or either timestamp contradicts `broker_cutoff_at` or the public closing date. If timing cannot be verified, mark the sample as review-only and do not use it as execution evidence.
- Historical margin excerpts must not contain final oversubscription, one-lot success rate, allotment result, grey-market, first-day, current-price, or cumulative-performance evidence. Such rows are retained for review but excluded from effective financing-heat coverage.
- Time-stamped pre-close forecasts may discuss expected grey-market or first-day ranges when clearly marked as `预计/预测/情景/forecast` and published before the broker cutoff. Treat them as scenario evidence only; actual grey-market, first-day, allotment, one-lot success, or final oversubscription results remain review-only. Apply the same rule to Traditional Chinese terms such as `暗盤`, `中籤率`, and `超額認購`.
- Historical margin rows can be imported from CSV/JSON/JSONL with fields such as `code`, `stock_name`, `broker`, `observed_at`, `source_published_at`, `preclose_confirmed`, `broker_cutoff_at`, `margin_multiple`, `margin_amount_hkd`, `financing_rate_pct`, `quota_status`, `cutoff_note`, `acceleration`, `excerpt`, and `source`.
- For historical margin imports, explicit `code` fields are normalized to five-digit Hong Kong stock codes before grouping. Group by code first, then stock name only when code is absent, so rows like `100`, `0100`, and `00100.HK` are treated as the same IPO.
- `margin_amount_hkd` may be a raw HKD number such as `8000000000` or `8,000,000,000`; Chinese unit text such as `80亿` is also accepted.
- `financing_rate_pct` may be provided as `3.8` or `3.8%`. In free-form text, bare numbers are treated as rates only when they appear near terms such as `年化`, `利率`, or `息`.

## Failure Handling

- If a structured page is unavailable, continue with the other structured source and show the failed source in the report.
- If HKEX document links are missing, lower confidence and avoid a strong recommendation unless the user explicitly provides the prospectus.
- If AASTOCKS lacks current rows, query HKEX directly and mark missing price/entry-fee data as a key risk.
- If AASTOCKS detail-page coverage is low, lower confidence and avoid tuning thresholds from that run. Prefer HKEX annual report backfill for sponsor/listing facts, then rerun details or supplement prospectus summaries for missing industry/quality fields.
- If community platforms require login or captcha, do not attempt to bypass them. Ask the user to paste excerpts or proceed without sentiment.
- Never silently fill missing values with guesses. Use explicit labels such as `未披露`, `待核实`, or `来源暂不可用`.
- If financing cutoff has passed, do not present new融资 participation as actionable. Switch to cash-only if still open, or to review/secondary-market analysis if the IPO has closed.
