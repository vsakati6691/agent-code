# agent-code

An AI-assisted trading **research** system for liquid US stocks and ETFs, built
to be driven from Claude Code with the Robinhood MCP connected.

> **Status: research and paper trading only.** This code cannot place, modify,
> or cancel brokerage orders, move money, use margin, sell short, or trade
> options or crypto. The config loader refuses to start if any of that is enabled.
> Nothing here is investment advice.

## How it works

```
Alpha Vantage (daily, free tier) ─┐
Robinhood MCP history (seed) ─────┼─► local cache ─► validation ─► indicators ─► screen / signals
                                  │                  (stale,        │
Earnings calendar ────────────────┘                   gaps, splits) ├─► daily report (Markdown)
                                                                    ├─► backtest + walk-forward
                                                                    └─► risk sizing ─► paper journal ─► dashboard
```

| Capability | Module |
|---|---|
| Price + earnings data, local cache, Robinhood history import | `src/agent_trading/data/` |
| Rejects stale, incomplete, inconsistent or unadjusted-split data | `data/validation.py` |
| SMA/EMA, RSI, MACD, ATR, momentum, volume ratio | `indicators.py` |
| Liquidity + trend/momentum screener | `screen.py` |
| Baseline strategy rules | `strategy.py` |
| Backtest with slippage and commissions; out-of-sample and walk-forward | `backtest/` |
| Central RiskEngine: per-trade, aggregate and correlated risk, gap buffer, cash-only | `risk.py` |
| Simulated paper broker (next-open fills, stops, same costs as backtest) | `paper.py` |
| Train/validation/holdout evaluation, benchmarks, bootstrap, deflated Sharpe, sensitivity, cost and stress tables | `backtest/evaluation.py`, `benchmarks.py`, `stats.py` |
| Target-weight allocation engine (month-end rebalance, same RiskEngine caps) | `backtest/portfolio.py` |
| 3-month T-bill interest on idle cash (no look-ahead) | `data/rates.py` |
| Market regime (trend, volatility) | `regime.py` |
| Read-only broker account snapshot (masked, staleness-checked) | `account.py` |
| Paper-trade journal (SQLite) | `journal.py` |
| Daily report + HTML dashboard | `report.py` |
| Command line | `cli.py` |

## Strategies (paper only)

| Strategy | What it does | Evidence so far |
|---|---|---|
| **A: S&P 500 scanner** (`strategies/scanner.py`) | Ranks every current constituent (price strength, volume, quality, valuation, low volatility); top 3 that pass all filters become paper entries | `evaluate-scanner`: point-in-time S&P 500 lists 2019–2023; see `reports/scanner_backtest_*.md` |
| **B: focused desk** (`strategies/desk.py`) | TQQQ/SQQQ (QQQ regime, 5-day limit, never both, event blackout), NVDA (trend + RS vs SMH, earnings blackout), IBIT | `evaluate-desk`: trading-only edge near zero per instrument; weak combined evidence |
| **C: GTAA** (`strategies/gtaa.py`) | 7 ETFs, hold each while above its 10-month average, month-end rebalance | `evaluate-gtaa`: modest returns, small drawdowns (validation +5.7%/yr, max DD −6.9%) |
| Legacy trend (`strategy.py`) | The original 22-symbol trend rules | Kept as a baseline (`evaluate`) |

Daily cycle: `daily` (see [docs/DAILY_ROUTINE.md](docs/DAILY_ROUTINE.md)).

## Legacy strategy (a hypothesis, not a proven edge)

Buy liquid names that are already trending up, cut losers quickly, and risk very
little per trade.

| Rule | Default |
|---|---|
| Entry | close > 20-day SMA > 50-day SMA, 63-day momentum > 0, RSI(14) < 75, liquidity filter passed |
| Exit | close < 50-day SMA, or the stop is hit |
| Initial stop | entry − 2.5 × ATR(14) |
| Timing | signal at day *t* close, fill at day *t+1* open (no look-ahead) |
| Risk per trade | 0.5% of equity |
| Aggregate open risk | 1.5% of equity |
| Max position | 25% of equity, never more than available cash |
| Minimum order | $1 |
| Earnings | flagged when a report is within 7 days |

**Universe** (`config/settings.yaml`): SPY, QQQ, SMH, XLK, IGV, XLU, XLE, XLI,
NVDA, AMD, AVGO, TSM, MU, ANET, VRT, MSFT, AMZN, GOOGL, ORCL, ETN, CEG, VST.
These are themes to study (AI infrastructure, semiconductors, cloud,
power/energy), not predictions.

### Backtest snapshot (Oct 2023 to Oct 2026, 22 symbols, 10 bps slippage per side)

| Test | Return | Max drawdown | SPY buy-and-hold, same period |
|---|---|---|---|
| Out-of-sample (Dec 2025 to Oct 2026) | +3.2% | −3.7% | +13.2% |
| Walk-forward, stitched (Jan 2025 to Oct 2026) | +13.8% | −5.3% | +31.5% |
| Full period | +16.5% | −4.4% | +82.2% (−19% max drawdown) |

Small, controlled drawdowns, but far below buy-and-hold: at 0.5% risk per trade
most capital sits in cash. Three years of mostly rising markets on today's large
caps (survivorship bias) is not evidence of an edge.

## Quick start (Windows)

Full guide: [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env                     # add your Alpha Vantage key
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m agent_trading report
```

## Commands

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m agent_trading fetch                  # update prices + earnings (uses API quota)
& $py -m agent_trading report [--no-fetch]    # reports\daily_YYYY-MM-DD.md
& $py -m agent_trading screen
& $py -m agent_trading backtest               # full + in-sample / out-of-sample
& $py -m agent_trading walkforward
& $py -m agent_trading evaluate               # train/validation + benchmarks, regimes, bootstrap, sensitivity
& $py -m agent_trading evaluate --holdout     # also the untouched holdout (logged; use rarely)
& $py -m agent_trading daily [--no-paper] [--label premarket|intraday|postclose]   # two-strategy cycle + report
& $py -m agent_trading evaluate-scanner       # Strategy A on point-in-time S&P 500 lists
& $py -m agent_trading evaluate-desk          # Strategy B rules on history
& $py -m agent_trading evaluate-gtaa          # Strategy C (GTAA)
& $py -m agent_trading universe import|import-history|show|symbols
& $py -m agent_trading snapshot fundamentals|quotes|news|filings|econ <files>
& $py -m agent_trading paper run              # fill paper orders at next open, check stops, queue new orders
& $py -m agent_trading paper status
& $py -m agent_trading account import <snapshot.json>   # read-only broker snapshot (masked)
& $py -m agent_trading account show
& $py -m agent_trading journal open NVDA 0.3 229 215 --thesis "trend + momentum"
& $py -m agent_trading journal close 1 240 --reason "exit signal"
& $py -m agent_trading journal list
& $py -m agent_trading dashboard              # reports\dashboard.html
& $py -m agent_trading import-robinhood <saved get_equity_historicals JSON>
& $py -m agent_trading import-csv SPY <file.csv>
```

`journal open` rejects any paper trade that breaks the risk limits.

## Safety controls

- `mode` must be `paper`; `allow_short`, `allow_margin`, `allow_options`, `allow_crypto` must be `false`.
- Sizing is long-only and capped by available cash (no margin).
- The journal schema itself rejects shorts, non-paper trades, and stops at or above entry.
- Rejected data is listed in the report and never used.
- Earnings dates show their source and fetch time, or are marked **UNVERIFIED**.
- Secrets come only from `.env` (git-ignored) or environment variables and are redacted from logs.
- Runtime data (`data/`, `logs/`, `reports/`) is git-ignored.

## Known limitations

- Free Alpha Vantage tier: ~100 bars per fetch and 25 requests/day. Long history (2007 onward, about 19 years) is seeded from Robinhood via `import-robinhood`. Never use Robinhood's `adjustment_type: all` daily bars; they are wrong.
- Robinhood daily volume sometimes drops out for a few days (e.g. Aug 2010, Oct 2025) while prices stay correct; this is tolerated. Runs of flat price bars (dead feeds, pre-merger SPAC shells) are rejected, or trimmed from old history in backtests.
- Dividends are not modelled (price return only), for both strategies and benchmarks.
- Alpha Vantage daily bars are not split-adjusted; a split inside the cached history causes that symbol to be rejected.
- Daily bars only: intraday stop fills, partial fills, halts and taxes are not modelled.
- The Robinhood MCP is only available inside a Claude session; the Python code never talks to the broker.

## Roadmap

1. Paper trade for several weeks using the daily report and journal.
2. Review journal statistics against the out-of-sample backtest.
3. Only if results justify it, design a separate live phase with brokerage approvals on, small limits, and a kill switch.

## For AI assistants

See [CLAUDE.md](CLAUDE.md) for the rules any AI agent working in this repository must follow.
