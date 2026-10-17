# Daily routine (run by a Claude Code session)

The Python code cannot call MCP tools, so each run is a Claude session that
(1) collects data through MCP **read-only** tools, saves each payload as JSON in
the session scratchpad (never inside the repo), (2) imports it, and (3) runs
the analysis. All commands run from the repo root:

```powershell
$py = ".\.venv\Scripts\python.exe"
```

**Hard rules for every run:** the session never trades. Never call any
`place_*`, `cancel_*`, `review_*` or `exercise_*` Robinhood tool, even to
"place the tickets": live tickets are for the owner to place by hand. Robinhood
account = Agent-trading (the configured account) only. Never write the full account number,
API keys or tokens to files, logs or reports. If a tool fails or data is
stale, say so in the summary and continue with what is available; never
invent data.

## Is the market open?

`market_calendar.py` models regular NYSE holidays and recorded exceptional
closures. The CLI's default date uses America/New_York. Confirm current status
from read-only market data as well: if `get_equity_quotes` for SPY shows
`previous_close_date` unchanged from the last run and no trade today during
regular hours, treat the day as closed: skip the paper broker and write a
one-line note.

## Post-close run (weekdays 16:30 ET) — the main daily cycle

1. **Account (read-only):** `get_accounts` (for the Agent-trading row's
   `unsettled_funds` and `type`), `get_portfolio`, `get_equity_positions`,
   `get_equity_orders` for the Agent-trading account. Write
   `{"fetched_at": <UTC ISO>, "account_number": "<configured suffix>", "nickname": "Agent-trading",
   "unsettled_funds": <from get_accounts>, "account_type": <type from get_accounts>,
   "portfolio": {...}, "positions": [...], "orders": [...]}` and run
   `& $py -m agent_trading account import <file>`. Without `unsettled_funds`
   the order gate blocks every buy ticket (settled cash unknown). Keep each
   order's `type`, `trigger`, `stop_price` and `quantity` as returned: a
   position counts as protected only by open **stop** sell orders covering its
   full quantity (a limit sell does not count). Take the
   snapshot **after 16:00 ET**: tickets need a snapshot from the ticket day
   that is under 6 hours old.
   Both `positions` and `orders` must be explicitly present as complete lists;
   `[]` means a verified empty result, while missing/null fields are rejected.
   After the 2026-10-17 audit fixes, re-import a fresh read-only snapshot:
   saved files without the collection-completeness marker are rejected.
   Never add that marker by hand or convert a failed tool response to `[]`.
2. **Constituents** (Mondays, or when `universe show` warns it is old):
   Financial Datasets `get_index_fund` (ticker `SPY`, limit `1000`) →
   `& $py -m agent_trading universe import <file>`.
3. **Prices:** `& $py -m agent_trading universe symbols` lists the tickers. Add
   `TQQQ SQQQ IBIT QQQ SMH SPY` and the GTAA assets `EFA IEF DBC VNQ TLT GLD`.
   Call `get_equity_historicals` (interval `day`,
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
   When `live.enabled`, the same run re-runs the live strategies (B, C) against
   the real positions in the account snapshot and writes **live order
   tickets** (Section D, item 3), sized on at most `live.capital`. No verified
   snapshot from today means no new tickets, so step 1 must succeed.
7. Summarise: **live tickets first** (side, symbol, qty, limit, stop, why;
   "none" if empty), then live loss-limit status and warnings, then coverage,
   actionable setups, desk decisions and paper actions. Say plainly that the
   owner must place the tickets in the app; never offer to place them.

### Order gate and kill switch (every ticket run)

Before tickets are written, `order_gate.py` re-checks every hard account limit
and fails closed:
- $100 per buy, $200 and 3 new entries per day, $800 max exposure, $200 cash reserve;
- settled cash only, and no leveraged or inverse ETFs (TQQQ/SQQQ stay paper-only);
- only `account_limits.live_allowed_symbols`;
- a fresh, reconciled snapshot from the ticket day, and an NYSE trading day;
- no open buy order at the broker.

Rejected tickets are listed as "Not ticketed: … order gate: …".

Reruns preserve already-issued tickets and their daily budget reservations.
The replacement behavior described in the historical 2026-10-12 final report
is superseded; do not clear the ledger to make a rerun fit the limits.

A 5% drawdown from the account's high-water mark **engages the kill switch**.
While engaged, no tickets of any kind are written, including after a restart.
- Check it with `& $py -m agent_trading kill-switch status`.
- Only the owner releases it, after reviewing the account:
  `kill-switch release --confirm "I have reviewed the account"`.
- A scheduled session must never release it.
- Anyone may engage it: `kill-switch engage --reason "..."`.

The kill switch never sells anything. During an outage, do not liquidate:
reconcile the account first, then decide by hand.

## Pre-market run (weekdays 08:30 ET)

1. Account snapshot (as above).
2. Economic calendar (as above).
3. News: Financial Datasets `get_news` with no ticker (market) and for `NVDA`,
   `TQQQ`, `IBIT`, plus any open paper positions and today's actionable
   tickers → `snapshot news <files...>`. Headlines are UNVERIFIED; read the
   article before treating anything as material.
4. Quotes: `get_equity_quotes` for the desk symbols, QQQ, SPY, open paper
   positions and actionable tickers → `snapshot quotes <file>`.
5. `& $py -m agent_trading daily --no-paper --label premarket`. The report
   repeats the latest post-close tickets (it never issues new ones). Compare
   them with the account snapshot: flag a ticket that was already placed or
   filled, and any live position whose quote is at or below its stop.

## Midday check (weekdays, 12:30 ET, once)

Keep it light (rate limits): quotes for the desk symbols, QQQ, SPY and open
paper positions → `snapshot quotes <file>`; market news → `snapshot news
--merge <file>`; then `& $py -m agent_trading daily --no-paper --label intraday`.
Report only changes: a live price at or below a paper stop, a new
high-impact event, or a desk decision that changed since the last run. The
paper broker does NOT run intraday; signals use daily closes.

## Weekly review (Fridays 17:30 ET)

Local files only, no MCP calls: `& $py -m agent_trading paper status`, the paper
tables in `data\journal.db` and the week's post-close reports →
`reports\weekly_review_<date>.md` (paper P&L per strategy vs SPY, loss-limit
headroom, missed runs, and a reminder of what the backtests showed).

## Data source outages

- **Financial Datasets** (constituents, news, filings) is prepaid. On 2026-10-12
  its balance ran out ("prepaid balance is exhausted"). Until it is topped up:
  keep using the last stored constituent list (the report flags it once it is
  more than 10 days old), take news from Bigdata `bigdata_search` instead, and
  say that filings were not checked. Never retry a billing error in a loop.
- **FMP** economic data needs a paid plan; use Bigdata's economic calendar.

## Month-end (GTAA)

On the last trading day of a month the post-close run also rebalances
Strategy C (GTAA): assets above their 10-month average get paper buy orders,
held GTAA assets below it get paper sell orders, all sized by the RiskEngine.

## Recovery

- A same-day rerun keeps the tickets already issued that day (they may be placed), counts them against
  the $200 / 3-entry daily limits and never re-tickets a symbol, so it can only add what is left.
- A run failed midway: rerun it. Imports are idempotent and `paper run` will
  not queue duplicate orders for the same date.
- Stale or missing data: the report lists it, the scanner reports coverage,
  and leveraged entries are blocked if the economic calendar is missing.
- Loss limit hit: `paper status` shows it. The 8% drawdown shutdown blocks
  new entries until you review the strategy; exits continue.
