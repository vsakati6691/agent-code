# agent-code

**📊 Live research dashboard:** https://vsakati6691.github.io/agent-code/

AI-assisted **research, paper-trading and live-ticket** system for US stocks and ETFs.
Scheduled AI sessions collect data through read-only market connectors; the Python
engine does the analysis.

> **The system never places orders.** Strategies B and C write **order tickets** for the
> real Robinhood "Agent-trading" account ($1,000 cap) and the owner places each one by
> hand. The code cannot place, modify or cancel orders, move money, use margin, short,
> or trade options or crypto. The config loader refuses to start if any of that is
> enabled, and a test fails if a broker order call appears in the source.
> Nothing here is investment advice.

## Strategies

| Strategy | What it does | Evidence (backtests, costs included) |
|---|---|---|
| **A: S&P 500 scanner** · paper only | Ranks current constituents on strength, volume, quality, valuation and low volatility; up to 3 paper entries | ❌ No edge: did not beat SPY 2019–2025, rank IC ≈ 0, no better than plain 12-1 momentum |
| **B: Desk** · paper + live tickets | Daily signals for TQQQ, SQQQ (paper only), IBIT and NVDA with pre-registered trend rules | ⚠️ Weak: edge near zero per instrument |
| **C: GTAA** · paper + live tickets | Faber trend: hold each of SPY, EFA, IEF, DBC, VNQ, TLT, GLD while above its 10-month average; monthly rebalance | ✅ Modest: validation +6.8%/yr, Sharpe 0.96, −6.9% max drawdown (SPY +11.1%, −34%) |

The 2026-10-12 tournament ran 12 pre-registered candidates through one engine: **none passed
the acceptance rules**. See [research/TOURNAMENT_2026-10-12.md](research/TOURNAMENT_2026-10-12.md).
Backtests are evidence with limits, not proof.

## Risk limits (enforced in code)

| Limit | Value on $1,000 |
|---|---|
| Per position / aggregate / correlated | $5 (TQQQ/SQQQ $2.50) / $15 / $10 shared |
| Max position | $250, cash only; stops at 2.5 × ATR(14) |
| Daily loss / drawdown | $10 stops new entries; 5% engages the kill switch until the owner releases it |
| Real account order gate | $100/order; $200 and 3 entries/day; $800 exposure; $200 cash reserve; settled cash; no leveraged or inverse ETFs; fresh reconciled snapshot |
| Costs | 10 bps slippage + 5 bps half-spread per side |

Stops never guarantee the loss limit: gaps can fill worse. At most about three positions are
open at once, so most of the $1,000 stays in cash by design.

## How it runs

The Python code cannot call MCP tools, so each run is an AI session that collects data,
saves JSON, imports it and runs the analysis ([docs/DAILY_ROUTINE.md](docs/DAILY_ROUTINE.md)).

| Weekdays (ET) | Run | Output |
|---|---|---|
| 08:30 | Pre-market | Account, calendar, quotes; repeats open tickets |
| 12:30 | Midday | Stop breaches and changed decisions, no trades |
| 16:30 | Post-close | Paper fills, loss checks, **live tickets**, full report |
| Fri 17:30 | Weekly review | Paper P&L vs SPY, missed runs |

Runs happen only while the laptop and the app are open. A missed run means no tickets, which
is safe. Reports go to `reports/` (git-ignored). Dashboards:
[Agent-trading desk](https://claude.ai/artifact/A3dcSc1pWfKjykdjFxHnNo) (owner's snapshot of the
last run) and the weekly public-data [research dashboard](https://vsakati6691.github.io/agent-code/)
(live on GitHub Pages, [how it is built](docs/RESEARCH_DASHBOARD.md)) built by GitHub Actions.

Data comes from Robinhood (account, prices, quotes, fundamentals), Financial Datasets
(S&P 500 list, news, filings), Bigdata.com (economic calendar) and Alpha Vantage (rates,
backup prices). All read-only.

## Quick start (Windows, Python 3.12)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env                     # add your Alpha Vantage key; never commit .env
.\.venv\Scripts\python.exe -m pytest       # all tests must pass
```

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m agent_trading daily [--no-paper] [--label premarket|intraday|postclose]
& $py -m agent_trading paper status | account show | kill-switch status
& $py -m agent_trading import-robinhood <files> | snapshot <kind> <files> | universe import <file> | account import <file>
& $py -m agent_trading evaluate-scanner | evaluate-desk | evaluate-gtaa | tournament --no-test
```

## Layout

```
config/settings.yaml          limits, costs, strategy and data settings
src/agent_trading/
  strategies/                 scanner.py (A), desk.py (B), gtaa.py (C)
  risk.py, paper.py, live.py  risk engine, paper broker, live tickets (never sends orders)
  daily.py, cli.py            daily cycle, report, commands
  data/, backtest/            imports and validation; backtest engines and stats
  dashboard/                  weekly research dashboard (public data only)
docs/                         DAILY_ROUTINE, ARCHITECTURE (diagrams, full rule tables), audits
tests/                        unit, integration (mocked) and safety tests
```

## More

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): diagrams, Strategy B rules, live-ticket settings, data sources, known limitations.
- [docs/FINAL_REPORT_2026-10-12.md](docs/FINAL_REPORT_2026-10-12.md): research findings.
- **AI assistants:** rules live in [CLAUDE.md](CLAUDE.md); [AGENTS.md](AGENTS.md) points Codex and other tools there.


Growth decision research (methodology 2026-10-14.9) adds dated valuation,
fiscal-year growth, margin/balance-sheet, ownership and timing fields to the
Growth Stocks scanner and company pages. Fundamental quality and momentum are
separate. `options.html` includes speculative 30–90 DTE comparisons and a local
hypothetical risk-budget calculator when `DASHBOARD_OPTIONS` is enabled.
Missing data stays n/a with its reason, including unclassified insider trades
and IV rank until 252 comparable sessions exist. See
[the research dashboard methodology](docs/RESEARCH_DASHBOARD.md) for formulas,
source coverage, request budgets and the unchanged full-loss disclaimer.
