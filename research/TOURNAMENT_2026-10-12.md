# Strategy tournament: 2026-10-12

> Research output, not investment advice. Backtests are evidence with limits, not proof of future returns.

Run `8c343acd6d` · code `10883c4` (uncommitted changes) · data fingerprint `a0ec28d314ea4d9f` · cost 12.5 bps per side (slippage + half spread; Robinhood commission $0) · 30 strategy/parameter trials

## Method

- **Timing:** signals from data up to day *t*'s close; trades at day *t+1*'s open. Long-only, no leverage, and no buys beyond cash.
- **Prices:** Robinhood daily bars, split-adjusted. Total return (dividends reinvested) where dividends are on file; other assets are price-only (flagged).
- **Idle cash** earns 0%. Strategies that go to "cash" buy BIL, a T-bill ETF.
- **Sharpe and Sortino** are computed on returns in excess of BIL.
- **Periods** (fixed in code before any result): train 2008-10-01..2016-12-30, validation 2017-01-03..2021-12-31, test 2022-01-03..end.
  - Selection uses train and validation only.
  - The test period is evaluated once, only for the benchmarks, the incumbent (GTAA = live Strategy C) and accepted candidates.
- **Robustness:**
  - every parameter in a pre-registered grid;
  - 1×/2×/3× costs;
  - yearly walk-forward parameter selection (2011–2021);
  - a block-bootstrap Sharpe interval;
  - a deflated Sharpe ratio over all 30 trials;
  - a paired bootstrap of the Sharpe difference vs SPY.
- **Account-constrained** runs apply the real account's hard limits: max 10%/position, 80% gross, 20%/day buys, 3 entries/day.
- **Acceptance rules (all must hold):** `min_excess_cagr_vs_cash` = 0.01; `min_sharpe_each` = 0.3; `max_drawdown_floor` = -0.25; `min_bootstrap_sharpe_lo` = 0.0; `min_deflated_sharpe_prob` = 0.9; `max_grid_sharpe_range` = 0.5; `min_cost_retention_3x` = 0.7; `max_sharpe_shortfall_vs_bench` = 0.1.

**Data checks:**

- BIL: 2 bars with missing or non-positive prices dropped
- VNQ: 1 daily moves above 25% (largest 30% on 2008-10-13); check for an unadjusted split

## Train + validation (selection data)

| Strategy | CAGR | Sharpe | Sortino | Max DD | Vol | Trades | Turnover/yr | Exposure |
|---|---|---|---|---|---|---|---|---|
| BENCH_SPY | +13.5% | 0.71 | 1.01 | -40.8% | +20.3% | 0 | 0.0 | +100% |
| BENCH_CASH | +0.3% | 0.00 | n/a | -0.6% | +0.4% | 0 | 0.0 | +100% |
| BENCH_6040 | +10.1% | 0.90 | 1.28 | -24.1% | +11.1% | 0 | 0.2 | +100% |
| BENCH_EW7 | +6.8% | 0.61 | 0.87 | -26.9% | +11.3% | 0 | 0.4 | +100% |
| GTAA | +4.4% | 0.65 | 0.91 | -8.4% | +6.6% | 199 | 3.5 | +100% |
| SPY_TREND | +9.3% | 0.73 | 1.00 | -23.2% | +13.1% | 38 | 2.9 | +100% |
| DUAL_MOM | +7.1% | 0.48 | 0.66 | -33.7% | +16.3% | 45 | 3.4 | +100% |
| RS_TOP3 | +9.4% | 0.69 | 0.96 | -21.8% | +14.1% | 272 | 7.1 | +100% |
| SECTOR_RS | +6.5% | 0.46 | 0.64 | -24.1% | +15.5% | 296 | 8.1 | +100% |
| VOL_TREND | +6.1% | 0.62 | 0.84 | -16.7% | +9.7% | 107 | 6.6 | +100% |
| RSI2_MR | +0.2% | 0.02 | 0.03 | -20.1% | +7.0% | 415 | 31.3 | +95% |
| COMBO_GTAA_TREND | +7.0% | 0.76 | 1.04 | -13.7% | +9.0% | 199 | 3.2 | +100% |

### By period

| Strategy | Train CAGR | Train Sharpe | Train MDD | Val CAGR | Val Sharpe | Val MDD | Sharpe − SPY (95% CI) |
|---|---|---|---|---|---|---|---|
| BENCH_SPY | +10.6% | 0.58 | -40.8% | +18.4% | 0.94 | -33.7% | — |
| BENCH_CASH | -0.1% | 0.00 | -0.6% | +0.9% | 0.00 | -0.2% | -0.71 (-1.23 to -0.25) |
| BENCH_6040 | +8.6% | 0.78 | -24.1% | +12.7% | 1.12 | -18.9% | +0.19 (+0.07 to +0.30) |
| BENCH_EW7 | +5.0% | 0.45 | -26.9% | +10.0% | 1.00 | -19.5% | -0.09 (-0.38 to +0.17) |
| GTAA | +3.2% | 0.48 | -8.4% | +6.6% | 1.01 | -6.1% | -0.06 (-0.59 to +0.40) |
| SPY_TREND | +7.8% | 0.64 | -19.9% | +12.0% | 0.86 | -23.2% | +0.02 (-0.39 to +0.44) |
| DUAL_MOM | +5.8% | 0.45 | -20.3% | +9.3% | 0.54 | -33.7% | -0.22 (-0.60 to +0.16) |
| RS_TOP3 | +7.6% | 0.59 | -21.8% | +12.2% | 0.86 | -19.5% | -0.02 (-0.57 to +0.45) |
| SECTOR_RS | +4.7% | 0.39 | -24.1% | +9.6% | 0.58 | -23.7% | -0.24 (-0.64 to +0.13) |
| VOL_TREND | +4.6% | 0.52 | -16.7% | +8.5% | 0.79 | -16.3% | -0.08 (-0.51 to +0.34) |
| RSI2_MR | +0.2% | 0.08 | -17.3% | +0.1% | -0.07 | -16.0% | -0.69 (-1.21 to -0.17) |
| COMBO_GTAA_TREND | +5.6% | 0.63 | -13.0% | +9.4% | 0.98 | -13.7% | +0.05 (-0.39 to +0.45) |

### Robustness (train + validation)

| Candidate | Grid Sharpe (default **bold**) | Sharpe 1×/2×/3× costs | Walk-forward Sharpe vs fixed default (2011–21) | Bootstrap Sharpe 95% CI | Deflated Sharpe P | Decision |
|---|---|---|---|---|---|---|
| GTAA | 6: 0.66, 8: 0.68, **10: 0.65**, 12: 0.63 | 0.65 / 0.58 / 0.52 | 0.58 vs 0.65 | 0.19 to 1.14 | 0.59 | REJECTED |
| SPY_TREND | 6: 0.91, 8: 0.99, **10: 0.73**, 12: 0.69 | 0.73 / 0.70 / 0.67 | 0.93 vs 0.74 | 0.22 to 1.29 | 0.70 | REJECTED |
| DUAL_MOM | 6: 0.43, 9: 0.37, **12: 0.48** | 0.48 / 0.46 / 0.43 | 0.44 vs 0.48 | 0.03 to 0.98 | 0.36 | REJECTED |
| RS_TOP3 | 3: 0.80, **6: 0.69**, 9: 0.61, 12: 0.40 | 0.69 / 0.62 / 0.56 | 0.76 vs 0.70 | 0.25 to 1.17 | 0.65 | REJECTED |
| SECTOR_RS | 3: 0.62, **6: 0.46**, 9: 0.60, 12: 0.59 | 0.46 / 0.40 / 0.33 | 0.42 vs 0.49 | 0.01 to 0.97 | 0.34 | REJECTED |
| VOL_TREND | 0.08: 0.58, **0.1: 0.62**, 0.12: 0.66, 0.15: 0.70 | 0.62 / 0.54 / 0.45 | 0.63 vs 0.58 | 0.13 to 1.16 | 0.56 | REJECTED |
| RSI2_MR | 5.0: -0.00, **10.0: 0.02**, 15.0: -0.02, 20.0: -0.16 | 0.02 / -0.53 / -1.03 | -0.21 vs -0.05 | -0.33 to 0.46 | 0.02 | REJECTED |
| COMBO_GTAA_TREND | 8: 0.95, **10: 0.76**, 12: 0.72 | 0.76 / 0.71 / 0.67 | 0.97 vs 0.77 | 0.29 to 1.27 | 0.74 | REJECTED |

**Failed acceptance checks:**

- GTAA: deflated_sharpe, not_worse_than_simple_benchmarks
- SPY_TREND: deflated_sharpe, not_worse_than_simple_benchmarks
- DUAL_MOM: drawdown_train_and_validation, deflated_sharpe, not_worse_than_simple_benchmarks
- RS_TOP3: deflated_sharpe, not_worse_than_simple_benchmarks
- SECTOR_RS: deflated_sharpe, not_worse_than_simple_benchmarks
- VOL_TREND: deflated_sharpe, not_worse_than_simple_benchmarks
- RSI2_MR: beats_cash_train_and_validation, sharpe_train_and_validation, bootstrap_sharpe_ci_above_zero, deflated_sharpe, parameter_robust, cost_robust, not_worse_than_simple_benchmarks
- COMBO_GTAA_TREND: deflated_sharpe, not_worse_than_simple_benchmarks

### Stress windows (return / max drawdown inside the window)

| Strategy | GFC tail 2008-10..2009-03 | Euro crisis 2011 | 2015-16 sell-off | Q4 2018 | COVID crash 2020 |
|---|---|---|---|---|---|
| BENCH_SPY | -41% / -41% | -18% / -18% | -13% / -13% | -19% / -19% | -33% / -34% |
| BENCH_CASH | -0% / -1% | +0% / -0% | -0% / -0% | +1% / -0% | +0% / -0% |
| BENCH_6040 | -24% / -24% | -7% / -8% | -5% / -6% | -10% / -10% | -19% / -19% |
| BENCH_EW7 | -27% / -27% | -6% / -7% | -6% / -8% | -7% / -7% | -18% / -20% |
| GTAA | -1% / -6% | -1% / -7% | -5% / -6% | -4% / -5% | -2% / -6% |
| SPY_TREND | -0% / -1% | -9% / -17% | -16% / -19% | -21% / -22% | -11% / -12% |
| DUAL_MOM | +8% / -6% | -17% / -17% | -15% / -20% | -19% / -19% | -33% / -34% |
| RS_TOP3 | +5% / -8% | +5% / -5% | -8% / -15% | -14% / -15% | -5% / -11% |
| SECTOR_RS | -1% / -1% | -10% / -15% | -12% / -16% | -16% / -17% | -24% / -24% |
| VOL_TREND | -0% / -1% | -9% / -10% | -13% / -15% | -13% / -14% | -8% / -9% |
| RSI2_MR | +0% / +0% | -10% / -14% | -2% / -4% | -3% / -6% | -5% / -9% |
| COMBO_GTAA_TREND | -1% / -3% | -5% / -12% | -11% / -13% | -13% / -14% | -7% / -9% |

### Under the real account's limits ($1,000; train + validation)

Constraints: max 10%/position, 80% gross, 20%/day buys, 3 entries/day. The $100-per-position cap means single-ETF strategies can invest only 10% of the account. Dollar figures are per year on $1,000.

| Strategy | Train CAGR | Val CAGR | ≈ $/yr on $1,000 (val) | Val max DD | Avg exposure (val) |
|---|---|---|---|---|---|
| BENCH_SPY | +1.2% | +4.1% | $41 | -8.3% | +23% |
| BENCH_CASH | -0.0% | +0.1% | $1 | -0.0% | +10% |
| BENCH_6040 | +1.6% | +2.2% | $22 | -3.1% | +20% |
| BENCH_EW7 | +3.6% | +7.0% | $70 | -13.8% | +70% |
| GTAA | +2.4% | +4.5% | $45 | -4.5% | +56% |
| SPY_TREND | +0.8% | +1.2% | $12 | -2.5% | +10% |
| DUAL_MOM | +0.6% | +1.0% | $10 | -3.7% | +10% |
| RS_TOP3 | +2.4% | +3.7% | $37 | -6.0% | +30% |
| SECTOR_RS | +1.6% | +3.0% | $30 | -7.5% | +30% |
| VOL_TREND | +0.7% | +1.2% | $12 | -2.3% | +14% |
| RSI2_MR | +0.0% | +0.0% | $0 | -1.7% | +10% |
| COMBO_GTAA_TREND | +1.9% | +3.6% | $36 | -3.8% | +44% |

## Final test (out of sample, evaluated once)

Evaluated for: BENCH_SPY, BENCH_CASH, BENCH_6040, BENCH_EW7, GTAA. Not evaluated (remains untouched): SPY_TREND, DUAL_MOM, RS_TOP3, SECTOR_RS, VOL_TREND, RSI2_MR, COMBO_GTAA_TREND.

> ⚠ The earlier research study (2026-10-12, outside this pipeline) viewed 2008–2026 for GTAA and SPY trend, so for those two families the test period was not untouched by the researcher.

| Strategy | CAGR | Sharpe | Sortino | Max DD | Vol | Trades | Turnover/yr | Exposure |
|---|---|---|---|---|---|---|---|---|
| BENCH_SPY | +12.5% | 0.54 | 0.78 | -24.5% | +17.3% | 0 | 0.0 | +100% |
| BENCH_CASH | +3.9% | 0.00 | n/a | -0.0% | +0.3% | 0 | 0.0 | +100% |
| BENCH_6040 | +6.6% | 0.29 | 0.41 | -20.9% | +11.1% | 0 | 0.2 | +100% |
| BENCH_EW7 | +6.1% | 0.26 | 0.36 | -18.8% | +10.1% | 0 | 0.3 | +100% |
| GTAA | +5.4% | 0.25 | 0.33 | -6.6% | +6.6% | 84 | 4.3 | +99% |

| Strategy | Sharpe − SPY, test (95% CI) | Account-limited CAGR | Account-limited max DD | 2022 bear (test) | 2025 sell-off (test) | Decision |
|---|---|---|---|---|---|---|
| BENCH_SPY | — | +4.6% | -7.9% | -24% / -24% | -19% / -19% | benchmark |
| BENCH_CASH | -0.54 (-1.33 to +0.23) | +0.4% | -0.0% | +1% / -0% | +1% / +0% | benchmark |
| BENCH_6040 | -0.25 (-0.48 to -0.03) | +1.1% | -4.3% | -21% / -21% | -10% / -11% | benchmark |
| BENCH_EW7 | -0.29 (-0.86 to +0.34) | +4.3% | -13.5% | -18% / -19% | -7% / -8% | benchmark |
| GTAA | -0.30 (-1.11 to +0.55) | +3.3% | -5.5% | -4% / -6% | -4% / -4% | REJECTED |

Test pass rules for accepted candidates: {'min_sharpe': 0.0, 'max_drawdown_floor': -0.25}.

## Candidates (pre-registered)

- **BENCH_SPY** (benchmark). *Hypothesis:* Broad US equity buy-and-hold. *Rules:* Buy SPY once; hold.
- **BENCH_CASH** (benchmark). *Hypothesis:* T-bill ETF buy-and-hold (investable cash). *Rules:* Buy BIL once; hold.
- **BENCH_6040** (benchmark). *Hypothesis:* Classic balanced portfolio. *Rules:* 60% SPY / 40% IEF, rebalanced monthly.
- **BENCH_EW7** (benchmark). *Hypothesis:* The GTAA assets without timing (isolates the value of the trend rule). *Rules:* 1/7 each of the 7 GTAA ETFs, rebalanced monthly.
- **GTAA** (trend (multi-asset)). *Hypothesis:* Asset-class trend timing cuts drawdowns with a modest return cost (Faber 2007). *Rules:* Month-end: hold each of SPY, EFA, IEF, DBC, VNQ, TLT, GLD at 1/7 while above its N-month SMA; rest in BIL. Default 10; grid [6, 8, 10, 12].
- **SPY_TREND** (trend (single index)). *Hypothesis:* A 10-month SMA filter on US equities avoids the worst of bear markets. *Rules:* Month-end: SPY if above its N-month SMA, else BIL. Default 10; grid [6, 8, 10, 12].
- **DUAL_MOM** (momentum (absolute + relative)). *Hypothesis:* Global equity momentum: own the stronger of US/international equities only when it beats T-bills (Antonacci). *Rules:* Month-end: best of SPY/EFA by N-month return if it beats BIL, else IEF. Default 12; grid [6, 9, 12].
- **RS_TOP3** (momentum (cross-asset relative strength)). *Hypothesis:* Assets with the strongest recent returns keep outperforming over the next month (time-series + cross-sectional momentum). *Rules:* Month-end: top 3 of 10 ETFs by N-month return, each 1/3 if it beats BIL; empty slots in BIL. Default 6; grid [3, 6, 9, 12]. *Note:* QQQ, IWM, EEM, VNQ, DBC, GLD, IEF, TLT, SPY, EFA. EEM, DBC and GLD price-only where no dividends are on file.
- **SECTOR_RS** (momentum (sector rotation)). *Hypothesis:* Sector momentum: the strongest sectors keep leading for a month. *Rules:* Month-end: top 3 of 9 sector SPDRs by N-month return, each 1/3 if it beats BIL; empty slots in BIL. Default 6; grid [3, 6, 9, 12]. *Note:* PRICE-ONLY sector data (no dividends on file): understates returns by roughly 1.5-2.5%/yr.
- **VOL_TREND** (trend + volatility targeting). *Hypothesis:* Scaling equity exposure to a volatility target improves risk-adjusted returns (Moreira-Muir; disputed by Cederburg et al.). *Rules:* Weekly: SPY weight = min(1, target / 20-day realised vol) while SPY is above its 10-month SMA, else 0; rest in BIL. Default 0.1; grid [0.08, 0.1, 0.12, 0.15].
- **RSI2_MR** (mean reversion). *Hypothesis:* Short-term oversold pullbacks in an uptrend revert within days (Connors RSI-2). *Rules:* Daily: buy SPY when RSI(2) < threshold and close > 200-day SMA; sell when close > 5-day SMA; otherwise BIL. Default 10.0; grid [5.0, 10.0, 15.0, 20.0].
- **COMBO_GTAA_TREND** (combination). *Hypothesis:* Two independently tested trend signals combined diversify each other's whipsaws. *Rules:* 50% GTAA(N) + 50% SPY_TREND(N), rebalanced at month-end. Default 10; grid [8, 10, 12].

## Not tested, and why

- **Fundamental quality and earnings revisions:** no point-in-time fundamentals or estimate history are available. Robinhood `preview_scan` is current-only. Testing on today's fundamentals would be look-ahead.
- **News and earnings catalysts:** no point-in-time news archive with reliable timestamps. Earnings drift for large caps is weak since 2006 (Martineau 2022).
- **Single-stock momentum on the S&P 500:** tested by `evaluate-scanner` on point-in-time constituents (2019–2025). It did not beat SPY, and its rank IC was ≈ 0. It is not repeated here, because today's survivors would add survivorship bias.
- **Leveraged / inverse ETFs (Strategy B's TQQQ/SQQQ):** prohibited for the account. `evaluate-desk` showed a trading edge near zero per instrument, with Sharpe 95% intervals that include zero.
