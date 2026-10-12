# agent-code

An AI-assisted trading **research** system for liquid US stocks and ETFs.

**This version is research and paper-trading only.** It contains no code that
can place, modify, or cancel brokerage orders, move money, use margin, sell
short, or trade options or crypto. The config loader rejects any attempt to
enable those.

## What it does

| Capability | Module |
|---|---|
| Daily price + earnings-calendar data with staleness/completeness checks | `data/` |
| SMA/EMA, RSI, MACD, ATR, momentum, volume ratio | `indicators.py` |
| Liquidity + trend/momentum screener | `screen.py` |
| Baseline trend/momentum rules (a hypothesis, not a proven edge) | `strategy.py` |
| Daily-bar portfolio backtest with slippage and commissions | `backtest/engine.py` |
| In-sample / out-of-sample split and walk-forward evaluation | `backtest/walkforward.py` |
| Position sizing: 0.5% risk per trade, 1.5% aggregate open risk, cash-only | `risk.py` |
| Paper-trade journal (SQLite) | `journal.py` |
| Daily Markdown report + HTML dashboard | `report.py` |

Research themes in the default universe (`config/settings.yaml`): AI
infrastructure, semiconductors, cloud computing, and power/energy, alongside
broad-market and sector ETFs. These are areas to study, not predictions.

## Quick start (Windows)

See [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md). In short:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env      # then add your Alpha Vantage key
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m agent_trading report
```

## Safety controls

- `mode` must be `paper`; `allow_short`, `allow_margin`, `allow_options` and `allow_crypto` must be `false`.
- Sizing never exceeds available cash (no margin) and never opens short positions.
- Series that are stale, incomplete, internally inconsistent, or look like unadjusted splits are rejected and listed in the report.
- Earnings dates are shown with their source and fetch time; if unavailable they are marked **UNVERIFIED**.
- Secrets come only from `.env` / environment variables, are redacted from logs, and `.env` is git-ignored.

## Known limitations

- The free Alpha Vantage tier returns ~100 recent daily bars and allows 25 requests/day. Backtests need longer history: seed it with `import-robinhood` (saved Robinhood MCP historicals), `import-csv`, or a premium key.
- Because each trade risks only 0.5% of equity, much of the capital sits in cash. Expect low drawdowns but returns well below buy-and-hold in strong bull markets.
- Alpha Vantage `TIME_SERIES_DAILY` is not split-adjusted. Merged history across a split is rejected rather than silently used.
- Backtests use daily bars only. Intraday stop fills, partial fills, halts, and taxes are not modelled.
- Survivorship bias: the universe is today's list of large, liquid names.
