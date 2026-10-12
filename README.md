# agent-code

An AI-assisted trading **research and paper-trading** system for US stocks and
ETFs, run from Claude Code with the Robinhood MCP (read-only) and other market
data connectors.

> **Paper trading only.** This code cannot place, modify, or cancel brokerage
> orders, move money, use margin, sell short, or trade options or crypto. The
> config loader refuses to start if any of that is enabled, and a test fails if
> any broker order call appears in the source. Nothing here is investment advice.

## What it does

Three independent strategies share one risk engine, one simulated paper broker,
and one daily report:

| Strategy | What it does | Evidence so far (backtests, costs included) |
|---|---|---|
| **A: S&P 500 scanner** (`strategies/scanner.py`) | Scans every current S&P 500 constituent (list refreshed from SPY's holdings filing). Ranks them by price strength, volume, quality, valuation and low volatility. Up to 3 that pass every filter become paper entries | ❌ On point-in-time S&P 500 lists (2019–2025, price factors only) it did **not** beat SPY. The score had no significant predictive power (rank IC ≈ 0). A factor ablation shows the full composite adds nothing over plain 12-1 momentum, at twice the turnover (no variant has \|t\| > 2). Research only |
| **B: focused desk** (`strategies/desk.py`) | Daily BUY / SELL / HOLD / WAIT / NO TRADE for **TQQQ, SQQQ, IBIT** (Bitcoin ETF) and **NVDA**, each with its own rules | ⚠️ Trading-only edge near zero per instrument; weak combined evidence (validation Sharpe 95% CI 0.11–2.17) |
| **C: GTAA** (`strategies/gtaa.py`) | Faber multi-asset trend: hold SPY, EFA, IEF, DBC, VNQ, TLT and GLD each while it trades above its 10-month average; rebalance at month-end | ✅ Validation (2019–2023, total return incl. dividends) +6.8%/yr, Sharpe 0.96, −6.9% max drawdown, vs SPY +11.1% with −34%. Train (2008–2019) only +3.6%/yr (Sharpe 0.53) vs SPY +10.5%. Modest returns, small losses; survives 3× costs |

Backtests are evidence with limits, not proof. Past performance does not
guarantee future results.

### Strategy B rules (pre-registered)

| Instrument | Entry | Exit / limits |
|---|---|---|
| TQQQ | QQQ close > 50-day SMA > 200-day SMA, QQQ above its 20-day SMA, QQQ 20-day volatility ≤ 25% | QQQ closes below its 20-day SMA, stop, or **5-day maximum hold**; **$2.50 max risk** |
| SQQQ | QQQ close < 50-day SMA < 200-day SMA, QQQ below its 20-day SMA, volatility ≤ 30% | Mirror image; same 5-day and $2.50 limits; **never held together with TQQQ** |
| Both leveraged ETFs | No entry within 1 day of a high-impact US release (CPI, FOMC, jobs…) or a Nasdaq-leader earnings date, measured from the fill day. A missing calendar also blocks entries | |
| NVDA | Close > 20-day SMA > 50-day SMA, 63-day momentum > 0, RSI < 75, relative strength vs SMH ≥ 0, no earnings within 5 days (an unknown date blocks entries) | Close below the 50-day SMA, or the stop |
| IBIT | Same trend rules (tracks spot bitcoin; trades only in US hours; spot BTC itself is not used) | Close below the 50-day SMA, or the stop |

## Risk limits (enforced in code, all strategies)

| Limit | Value on $1,000 paper equity |
|---|---|
| Max planned loss per position | 0.5% ($5); TQQQ/SQQQ 0.25% ($2.50) |
| Max aggregate planned open risk | 1.5% ($15) |
| Correlated positions (≥ 0.8 correlation) | Share one 1% ($10) budget |
| Max position size | 25% ($250), never more than cash (no margin) |
| Stops | 2.5 × ATR(14); sizing assumes the stop fills 20% worse (gaps) |
| Daily loss limit | 1% ($10): no new entries for the rest of the day |
| Drawdown shutdown | 8% ($80) from peak: no new entries until reviewed |
| Costs | 10 bps slippage + 5 bps half-spread per side |

A stop price never guarantees the loss limit: gaps can fill worse.

## How it runs

The Python code cannot call MCP tools, so each run is a **Claude Code session**
that collects data with read-only MCP tools, saves it as JSON, imports it, and
runs the analysis ([docs/DAILY_ROUTINE.md](docs/DAILY_ROUTINE.md)):

| When (weekdays, US Eastern) | Run | What it does |
|---|---|---|
| 08:30 | Pre-market | Account snapshot, economic calendar, news, quotes → pre-market report |
| 12:30 | Midday check | Quotes and news; flags stop breaches and changed decisions (no paper trades) |
| 16:30 | Post-close | Prices, constituents, fundamentals, calendar → paper fills, stops, loss limits, new paper orders, full report |
| Fri 17:30 | Weekly review | Local files only: paper P&L per strategy vs SPY, loss-limit headroom, missed runs |

These are Claude Code scheduled tasks. They run only while the Claude app is
open; if it's closed, a run happens the next time it opens.

The daily report (`reports\daily_two_strategy_<date>_<label>.md`) has these sections:
- **A: Scanner.** Market regime, coverage (scanned vs expected constituents), top 10, actionable setups with entry, stop, target and evidence, and rejections.
- **B: Desk.** One section per instrument: signal, reasons, live quote, sizing, catalysts.
- **C: GTAA.** The current signals.
- **C (account):** Broker snapshot, paper positions, risk and loss-limit status.
- **D: Actions.** Research findings, paper actions, and orders awaiting authorization (always none).

## Data sources

| Data | Source | Notes |
|---|---|---|
| Account, positions, orders | Robinhood MCP (read-only, Agent-trading account) | Stored masked (last 4 digits only), rejected if over 24 hours old |
| Daily price history | Robinhood MCP `get_equity_historicals` | Split-adjusted. Never use `adjustment_type: all` for daily bars |
| Fundamentals, earnings dates | Robinhood MCP `preview_scan` (bulk, by market-cap band) | Current only, not point-in-time |
| Live quotes, spreads | Robinhood MCP `get_equity_quotes` | |
| S&P 500 constituents | Financial Datasets `get_index_fund` (SPY holdings) | Point-in-time lists from 2019. **Prepaid; balance currently exhausted** |
| News, SEC filings | Financial Datasets (headlines are unverified); Bigdata.com fallback | |
| Economic calendar | Bigdata.com | Drives the leveraged-ETF event blackout |
| T-bill rate, daily backup prices | Alpha Vantage (free key in `.env`) | 25 requests/day |

## Quick start (Windows)

Needs Python 3.12 (`winget install Python.Python.3.12`).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env                     # add your free Alpha Vantage key (never commit .env)
.\.venv\Scripts\python.exe -m pytest       # all tests must pass
```

## Commands

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m agent_trading daily [--no-paper] [--label premarket|intraday|postclose]   # full cycle + report
& $py -m agent_trading paper status                 # paper positions, P&L, pending orders
& $py -m agent_trading account show                 # last read-only broker snapshot

# Data imports (files saved from MCP tools by a Claude session)
& $py -m agent_trading universe import|import-history|show|symbols
& $py -m agent_trading snapshot fundamentals|quotes|news|filings|econ <files>
& $py -m agent_trading import-robinhood <get_equity_historicals JSON files>
& $py -m agent_trading account import <snapshot.json>
& $py -m agent_trading dividends <SYMBOL> <file>    # for GTAA total-return backtests
& $py -m agent_trading fetch [--symbols ...]        # Alpha Vantage fallback: prices, earnings calendar, T-bills

# Evidence
& $py -m agent_trading evaluate-scanner             # Strategy A: point-in-time lists + factor ablation
& $py -m agent_trading evaluate-desk                # Strategy B: 1x/2x/3x costs + baselines
& $py -m agent_trading evaluate-gtaa                # Strategy C: C0/C1/C2, total return
```

Every evaluation reports train and validation periods only. The most recent 20%
of history is an untouched holdout that no command evaluates.

## Project layout

```
config/settings.yaml          all limits, costs, strategy and data settings
src/agent_trading/
  strategies/                 scanner.py (A), desk.py (B), gtaa.py (C)
  risk.py                     RiskEngine, loss limits, order checks
  paper.py                    simulated broker (next-open fills, stops, time exits)
  daily.py                    daily cycle + report
  data/                       validation, cache, universe, snapshots, rates, imports
  backtest/                   desk engine, allocation engine (GTAA), scanner backtest, splits, stats
  account.py, journal.py, regime.py, cli.py
docs/DAILY_ROUTINE.md         the runbook the scheduled Claude sessions follow
tests/                        unit, integration (mocked services) and safety tests
```

## Known limitations

- **Survivorship bias:** about 10% of historical S&P 500 members are missing from the scanner backtest, either because the filing omits the ticker or because the stock is delisted on Robinhood. No point-in-time lists are available after Sept 2023.
- **Fundamentals:** current values only, so they can't be backtested.
- **Dividends:** the GTAA backtest uses total return (dividend-adjusted), but the daily GTAA signals and the other backtests use price-only bars.
- **Daily bars only:** intraday stop fills, partial fills, halts and taxes are not modelled, and exchange holidays aren't in code (the runbook checks them).
- **News:** headlines are unverified until the article is read.

## Roadmap

1. Paper trade all three strategies for 3–6 months, giving the most weight to GTAA.
2. Compare paper results with the backtests.
3. Only if the evidence justifies it, design a separate live phase: small limits, a kill switch, and authorization for every order (Robinhood trade approvals are already on for the agent account).

## For AI assistants

See [CLAUDE.md](CLAUDE.md) for the rules any AI agent working in this repository must follow.
