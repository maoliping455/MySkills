# Data Sources

## Source Priority

1. Official issue announcement and issue-result announcement from BSE/issuer/Cninfo/Eastmoney公告/stock exchange disclosure pages.
2. Market data pages: Eastmoney new-stock data, CFi new-stock online, Tonghuashun, Sina new-stock calendar.
3. Structured libraries: AKShare `stock_xgsglb_em(symbol="北交所")` and `stock_ipo_ths(symbol="京市主板")` when local Python and network are available.
4. News and research: Securities Times, 21jingji, CLS, Xinhua, China Securities Journal, New Beijing News.
5. Community estimates: Jisilu, Xueqiu, Zhihu, Xiaohongshu. Use only for market sentiment and freeze-funds/secondary-threshold estimates.

## Fields To Capture

From issue announcement:

- Name, code, subscription code.
- Subscription date and subscription window.
- Issue price.
- Total issue shares.
- Online initial/final issue shares.
- Strategic placement shares/ratio.
- Over-allotment option ratio.
- Online subscription cap.
- P/E and industry context.

From issue-result announcement:

- Valid online subscription shares.
- Valid online subscription amount / frozen funds.
- Valid online subscription accounts.
- Online allotted shares.
- Online allotment rate / subscription multiple.
- Number of allotted accounts if disclosed.

From community estimates:

- Expected total frozen funds.
- Scenario probability or confidence, if the source gives a clear view.
- Expected regular threshold.
- Expected secondary/fractional threshold, including low/consensus/conservative boundary values when available.
- Estimate timestamp and author/source.
- Whether estimates cluster or diverge.

For dynamic secondary-boundary estimation:

- Recent comparable IPO online subscription amount and allotment rate.
- Actual or reconstructed secondary-allocation threshold from result discussions.
- Online shares divided by 100, used as rough secondary lot supply.
- Whether the subscription cap is below the 100-share regular threshold.
- Signs of crowding: hot sector/theme, strong recent BSE IPO first-day performance, small online issue size, and concentrated community attention.

## Useful Search Queries

Use combinations like:

```text
<新股名称> 北交所 发行公告 网上发行数量 申购上限
<新股名称> 发行结果公告 网上有效申购金额 获配比例
<新股名称> 北交所 打新 正股门槛 碎股门槛
<新股名称> site:jisilu.cn 北交所 打新
<新股名称> site:xueqiu.com 北交所 打新
<新股名称> 小红书 北交所 打新 门槛
```

For broader market heat:

```text
北交所 打新 平均冻结资金 中签率 正股门槛 2026
北交所 打新 顶格申购 不稳中 正股门槛
北交所 新股 网上冻结资金 有效申购户数
```

## Validation Checks

- Confirm units: shares vs 万股, yuan vs 万元/亿元.
- Verify that "网上发行股数" is the actual online subscription base, not total planned issue shares.
- If a source reports "中签率(%)", convert to decimal before calculating.
- If both frozen funds and allotment rate are available, recompute one from the other and flag large discrepancies.
- If a data table says "顶格申购需配市值", check whether it is a generic field name inherited from沪深 markets; for BSE, treat the real constraint as cash subscription cap.

## Research Anchors

Use these as orientation only; always re-search for the current IPO:

- BSE allocation rule explainer: https://www.cls.cn/detail/1807095
- 正股/碎股 terminology and examples: https://36kr.com/p/2953601464312195
- Recent market heat examples: https://www.21jingji.com/article/20260323/herald/ccaa28bf5ebe50fd39e6a19df1280f35.html
- 2026 high-threshold example reporting: https://www.stcn.com/article/detail/3963150.html
- AKShare new-stock interface docs: https://akshare.akfamily.xyz/data/stock/stock.html
