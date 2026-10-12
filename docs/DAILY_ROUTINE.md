# Daily routine (run by a Claude Code session)

The Python code cannot call MCP tools, so each run is a Claude session that
(1) collects data through MCP **read-only** tools, saves each payload as JSON in
the session scratchpad (never inside the repo), (2) imports it, and (3) runs
the analysis. All commands run from the repo root:

```powershell
$py = ".\.venv\Scripts\python.exe"
```

**Hard rules for every run:** research and paper only. Never call any
`place_*`, `cancel_*`, `review_*` or `exercise_*` Robinhood tool. Robinhood
account = Agent-trading (••8204) only. Never write the full account number,
API keys or tokens to files, logs or reports. If a tool fails or data is
stale, say so in the summary and continue with what is available; never
invent data.

## Is the market open?

US exchange holidays are not modelled. If `get_equity_quotes` for SPY shows
`previous_close_date` unchanged from the last run and no trade today during
regular hours, treat the day as closed: skip the paper broker and write a
one-line note.

## Post-close run (weekdays 16:30 ET) — the main daily cycle

1. **Account (read-only):** `get_portfolio`, `get_equity_positions`,
   `get_equity_orders` for the Agent-trading account. Write
   `{"fetched_at": <UTC ISO>, "account_number": "8204", "nickname": "Agent-trading",
   "portfolio": {...}, "positions": [...], "orders": [...]}` and run
   `& $py -m agent_trading account import <file>`.
2. **Constituents** (Mondays, or when `universe show` warns it is old):
   Financial Datasets `get_index_fund` (ticker `SPY`, limit `1000`) →
   `& $py -m agent_trading universe import <file>`.
3. **Prices:** `& $py -m agent_trading universe symbols` lists the tickers. Add
   `TQQQ SQQQ IBIT QQQ SMH SPY`. Call `get_equity_historicals` (interval `day`,
   start 10 calendar days ago, default split adjustment, ≤10 symbols per call)
   for all of them, then `& $py -m agent_trading import-robinhood <files...>`.
4. **Fundamentals** (earnings dates change): Robinhood `preview_scan` with
   filters `FILTER_TYPE_INSTRUMENT_TYPE = STOCK` and market-cap bands
   `>=150e9, 60-150e9, 35-60e9, 22-35e9, 15-22e9, 11-15e9, 8-11e9, 5.5-8e9`,
   columns `Market cap, Sector, P/E, Forward P/E, PEG, Gross margin,
   Operating margin, Net profit margin, Return on equity, EPS, Earnings date`.
   If a band returns `total_items` > 200, split it. Then
   `& $py -m agent_trading snapshot fundamentals <files...>`.
5. **Economic calendar:** Bigdata `bigdata_events_calendar` with
   `{"calendar_type": "economic_calendar", "countries": ["US"], "impacts": ["HIGH"],
   "start_date": today, "end_date": today + 14 days}` → `snapshot econ <file>`.
6. **Run:** `& $py -m agent_trading daily --label postclose`. This fills
   yesterday's paper orders, checks stops, applies the loss limits, queues
   the next paper orders, and writes
   `reports\daily_two_strategy_<date>_postclose.md`.
7. Summarise: coverage, actionable setups, desk decisions, paper actions,
   warnings.

## Pre-market run (weekdays 08:30 ET)

1. Account snapshot (as above).
2. Economic calendar (as above).
3. News: Financial Datasets `get_news` with no ticker (market) and for `NVDA`,
   `TQQQ`, `IBIT`, plus any open paper positions and today's actionable
   tickers → `snapshot news <files...>`. Headlines are UNVERIFIED; read the
   article before treating anything as material.
4. Quotes: `get_equity_quotes` for the desk symbols, QQQ, SPY, open paper
   positions and actionable tickers → `snapshot quotes <file>`.
5. `& $py -m agent_trading daily --no-paper --label premarket`.

## Intraday check (weekdays, hourly 10:30–15:30 ET)

Keep it light (rate limits): quotes for the desk symbols, QQQ, SPY and open
paper positions → `snapshot quotes <file>`; market news → `snapshot news
--merge <file>`; then `& $py -m agent_trading daily --no-paper --label intraday`.
Report only changes: a live price at or below a paper stop, a new
high-impact event, or a desk decision that changed since the last run. The
paper broker does NOT run intraday; signals use daily closes.

## Recovery

- A run failed midway: rerun it. Imports are idempotent and `paper run` will
  not queue duplicate orders for the same date.
- Stale or missing data: the report lists it, the scanner reports coverage,
  and leveraged entries are blocked if the economic calendar is missing.
- Loss limit hit: `paper status` shows it. The 8% drawdown shutdown blocks
  new entries until you review the strategy; exits continue.
