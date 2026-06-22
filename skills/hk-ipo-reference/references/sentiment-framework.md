# Sentiment Framework

## Scope

Sentiment is an auxiliary signal. It helps identify crowding, hidden risks, and comparable-stock narratives, but it cannot replace HKEX documents, pricing, sponsor quality, financials, or funding economics.

## Platforms

- 小红书: useful for retail heat, broker screenshots, and crowd psychology. High noise level.
- 雪球: useful for valuation debate, comparable companies, and experienced IPO participant estimates.
- 富途牛牛: useful for broker-side subscription heat, financing demand, comments, and grey-market discussion.
- 格隆汇/智通/财联社等: useful for news framing, sponsor/cornerstone narratives, and sector context.
- 知乎: useful for longer-form business or industry explanations, but often slower.

## Normalization

For each excerpt, capture:

- Platform.
- Stock code or Chinese name if present.
- Viewpoint: positive, negative, mixed, or neutral.
- Keywords: subscription heat, valuation, cornerstone, sponsor, business quality, financing cost, grey-market expectation, break-even risk.
- Evidence strength: firsthand data, cited source, broker screenshot, opinion only, or rumor.
- Confidence: high only when multiple independent platforms converge and excerpts contain concrete evidence.

## Noise Checks

Lower confidence when:

- Posts repeat the same slogan without numbers.
- The view depends only on "everyone is applying" or "will definitely pop".
- The post is likely a broker marketing pitch.
- The text omits valuation, pricing, sponsor, or allocation mechanics.
- Comments are based on stale comparable IPOs from a different market regime.

## Report Use

Use sentiment to:

- Explain crowding and financing-cost risk.
- Flag controversy that requires prospectus verification.
- Add confidence when independent discussion aligns with structured evidence.

Do not use sentiment to:

- Override missing HKEX documents.
- Recommend financing by itself.
- Present rumors as facts.
