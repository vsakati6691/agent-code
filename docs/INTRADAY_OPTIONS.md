# Local intraday options research

## Repository audit and architecture

The existing strategies A/B/C use daily stock/ETF bars, `indicators.py`, causal
next-bar simulation, `paper.py`, `risk.py`, and a SQLite journal. They are not
intraday option strategies. `data/universe.py` imports dated SPY holdings;
`dashboard/providers.py` also parses a current S&P 500 constituent table with
sector names. `dashboard/http.py` supplies bounded, rate-limited, allow-listed
GET requests and `logging_setup.py` redacts secrets. The existing options desk
uses delayed Cboe chains; those are unsuitable for this intraday execution model.
The daily `market_calendar.py` does not model early closes.

The new `agent_trading.intraday` package reuses the indicators, constituent parser,
HTTP gate and redaction. Separate models, configuration, XNYS calendar, scanner,
option selector, centralized risk engine, SQLite ledger, simulator, replay engine,
scheduler and Streamlit UI prevent coupling to live tickets or public Pages data.
It never imports the account or live-ticket modules. Existing risk ceilings,
dashboard methodology, published snapshots and research registry are untouched.

Implementation order: scanner and causal data validation; listed option selection;
transactional risk reservation and simulator; event replay and metrics; local
automation/UI and failure-path tests. All fills are local simulations. The repo's
no-broker-order rule precludes an Alpaca submission adapter in this implementation.

## Official API references checked on 2026-10-21

- [Massive stock minute aggregates](https://massive.com/docs/rest/stocks/aggregates/custom-bars):
  bar timestamps mark the start; the adapter converts them to one-minute ends.
  Missing intervals are not fabricated. Pagination is bounded and host-checked.
- [Massive option snapshots](https://massive.com/docs/rest/options/snapshots/option-chain-snapshot):
  Greeks/quotes depend on entitlement. The connected plan returned NOT_ENTITLED
  for AAPL next-session snapshots in this session; no option price was obtained.
- [Alpaca options](https://docs.alpaca.markets/docs/options-trading) and
  [paper environment](https://docs.alpaca.markets/docs/paper-trading): paper options
  are supported, but brokerage calls remain excluded by repository policy.
- [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars) supplies
  XNYS holidays, exceptional closures, DST and early closes.
- [Streamlit fragments](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)
  support local UI refresh; a separate polling process supports unattended operation.

A read-only Longbridge probe returned AAPL expirations 2026-10-21, 2026-10-23,
2026-10-26, 2026-10-28 and 2026-10-30. October 22 was absent. This was an expiration
check, not validation of real-time quotes, Greeks, liquidity or an executable feed.

## Preregistered starting methodology

Version `intraday-options-2026-10-21.1` is exploratory and has no demonstrated edge.
Weights: trend 30 (VWAP/ORB/structure share one budget), participation 20
(time-of-day cumulative RVOL/volume acceleration), relative strength 25 (vs SPY
and sector), momentum 15 (momentum/RSI/ADX share one budget), context 10 (breadth,
support/resistance clearance). These are initial hypotheses, not fitted weights.
Mandatory gates independently require market and sector agreement, RVOL >=1.5,
breakout confirmation, breadth, acceptable ATR/price, current event clearance and
score >=70. A 15-minute opening range cannot break out on its own final bar.
The first possible confirmation uses a subsequent completed minute.

RVOL compares cumulative volume to the same regular-session minute across at least
10 prior complete comparable sessions. The universe must be observed at or before
the decision and at most one day old. Observed-market scans require 480–520 members
and at least 95% minute coverage. Every member is considered; unavailable inputs and
rejections remain visible. Fixture universes are explicitly exempt from member count.
Unknown news, earnings or economic-event coverage blocks entry. Event clearance is
an imported, sourced, timestamped assessment, not an AI assertion of safety.

Contracts must actually be listed for the next **exchange session** (Friday to
Monday is three calendar days). No fallback expiry is used. Standard 100-share
deliverables only; OCC identity, direction, finite Greeks, actual volume, quote
time, source, spread, and full-premium affordability are checked. A $150 contract
is rejected at the $50 ceiling. Entry and exit fee reserves are included.

Each ledger pins its configuration hash and strategy version. Changing configuration
requires a separate research database; it cannot reinterpret an existing ledger.
No optimizer changes production parameters automatically. The $50/day objective
is only a research question. Neither a 1.5:1 nor 2:1 target establishes expectancy.

## Install and run

Windows PowerShell, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,intraday]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m agent_trading.intraday --help
.\.venv\Scripts\python.exe -m agent_trading.intraday demo
.\.venv\Scripts\python.exe -m agent_trading.intraday --db data/intraday/demo.sqlite3 status
.\.venv\Scripts\python.exe -m agent_trading.intraday backtest data/intraday/demo.jsonl
.\.venv\Scripts\python.exe -m streamlit run src/agent_trading/intraday/dashboard.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

For a second demo, provide a new empty ledger, e.g. `--db data/intraday/demo2.sqlite3 demo`.
In Streamlit, change **Local ledger** to `data/intraday/demo.sqlite3` to inspect
the finished synthetic run. The default ledger is empty and entries are disabled.
The synthetic replay is not a real-data scan file: it is newline-delimited snapshots.

macOS equivalents:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,intraday]'
.venv/bin/python -m pytest
.venv/bin/python -m agent_trading.intraday demo
.venv/bin/python -m streamlit run src/agent_trading/intraday/dashboard.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

macOS commands are provided for portability; execution in this implementation
session was on Windows. No service, startup item, automation or cloud deployment
is installed automatically.

Use real data only after configuring `MASSIVE_API_KEY` in `.env`, verifying
entitlement to fresh stock minutes and option bid/ask/size/Greeks, and supplying
current sourced event coverage. The default 13-second provider request spacing
cannot refresh 500 symbols in five minutes. Set pacing to your **verified plan's**
allowance, or use a separate collector to provide a normalized file. Bounded
collection fails closed if the full scan cannot finish. Increasing the deadline
does not turn stale data into valid data. The current adapter is sequential; a
high-throughput feed collector is required before claiming production scan cadence.

```powershell
# Read-only manual scan; does not enable new paper entries.
.\.venv\Scripts\python.exe -m agent_trading.intraday --provider massive --events data/intraday/events.json scan
# Or use one validated normalized JSON snapshot, atomically refreshed by your collector.
.\.venv\Scripts\python.exe -m agent_trading.intraday --snapshot data/intraday/latest.json scan
# Foreground local scheduler. This flag authorizes LOCAL SIMULATED entries only.
.\.venv\Scripts\python.exe -m agent_trading.intraday --snapshot data/intraday/latest.json run --enable-entries
.\.venv\Scripts\python.exe -m agent_trading.intraday control disable
.\.venv\Scripts\python.exe -m agent_trading.intraday control emergency
.\.venv\Scripts\python.exe -m agent_trading.intraday control stop
.\.venv\Scripts\python.exe -m agent_trading.intraday report
.\.venv\Scripts\python.exe -m agent_trading.intraday export reports/intraday/fills.csv
.\.venv\Scripts\python.exe -m agent_trading.intraday alerts reports/intraday/alerts.jsonl
.\.venv\Scripts\python.exe -m agent_trading.intraday explain
```

New entries require both running and enabled controls. Stop/disable cancels pending
entry remainders; existing positions continue to be monitored while the CLI loop
or dashboard scheduler is operating. Emergency stop is latched with no release
command. It requests exits on fresh executable quotes. If every process is closed,
no monitoring runs. Restart opens the same ledger and reconciles fill quantities.
Do not create a replacement ledger to hide unresolved positions.

All times are America/New_York. Jobs: 08:30 preparation; 09:45–10:30 scans every
five minutes; 13:30 scan; close minus 30 minutes flatten; close plus 10 minutes
report. Short sessions disable entry jobs. Missed scans older than 60 seconds
are recorded and never caught up as entry trades. Durable job claims and unique
entry identifiers prevent replay after restart or double-clicks. A claimed job
interrupted by a crash is not retried as an entry job.

The dashboard can run the scheduler while open. The foreground CLI is preferable
for continuous operation because its provider/history cache survives UI refreshes.
Run `control start` and `control enable` only when the data/monitor process is ready.
Neither command starts a background process by itself.

## Input format and provenance

`models.py` defines the complete validated schema. `Snapshot.model_json_schema()`
can be used by a collector to generate a schema. A snapshot includes:

- `observed_at`, `membership_at`, `membership_source`, `source`, `feed`;
- `universe`: all current constituents mapped to sector ETFs;
- `bars`: symbol -> completed one-minute OHLCV and actual per-bar VWAP history;
- `contracts`: actual OCC identifiers, listed expiry, Greeks, quote and underlying
  timestamps, daily volume timestamp, displayed sizes, multiplier and source;
- `events`: per-symbol and `MARKET` coverage with observed time, expiry, status,
  source and summary; missing/unknown coverage prohibits entries;
- `problems`: collection failures that prohibit entry while preserving visibility.

All datetimes must have UTC offsets. Raw Massive quotes retain their own timestamps,
not collection time. File imports are never restamped. `feed` is `realtime`,
`delayed` or `fixture`; one ledger cannot mix them. The fixture generator uses
synthetic ALFA/BETA symbols and never disguises them as S&P 500 data.

An event input maps tickers and `MARKET` to `EventRisk` objects. A safe example:

```json
{
  "MARKET": {
    "observed_at": "2026-10-21T08:30:00-04:00",
    "valid_until": "2026-10-21T09:00:00-04:00",
    "status": "unknown",
    "source": "example only; replace with a dated, verified event source",
    "summary": "Economic releases, earnings and news not yet checked. Blocks entry."
  }
}
```

## Execution and reporting assumptions

Entry limits use ask plus configured slippage; exit limits use bid minus slippage.
A fill requires a **later** fresh quote, an executable limit, an open session and
displayed size. Identical quote timestamps cannot replenish size on repeated ticks
or restart. Partial fills keep the unfilled remainder pending until filled or
expired. Default order timeout is 60 seconds. Exits may be re-quoted on a later
tick after an old exit expires. Fees apply per contract per side. Fill labels always
say local simulated fill; no external broker paper fills are claimed.

Risk reservations include full premium plus entry/exit fees for open and pending
entries. Realized losses consume the remaining daily budget. One entry per
underlying per session, at most two daily, no averaging down, no short options,
no margin, and no reuse of same-day sale proceeds. Maximum hold is 60 minutes;
risk, profit and invalidation exits can occur sooner than 15 minutes.

Closing is an intent, not a guarantee. Missing or crossed quotes cannot produce
a fill. Unresolved positions at market close remain in the ledger and latch the
stop; reports never fabricate a zero position or a successful overnight prohibition.
Unknown marks are zero only in conservative risk calculations; displayed P&L/equity
is unavailable. Recorded marks are historical and the UI flags stale current quotes.

Reports include net realized P&L, completed-trade win rate, mean win/loss,
expectancy, profit factor, drawdown, observed daily returns and Sharpe methodology.
Partial fills are not counted as separate trades. Profit factor is undefined with
no losses. Daily Sharpe uses sample standard deviation, zero risk-free rate and
sqrt(252), and is unavailable with fewer than two complete session observations.
Reports separate CALL/PUT and entry hour; skip reasons remain in the ledger.

Local structured console logs and SQLite events are always available. `alerts`
exports an optional JSONL outbox for an owner-configured notification integration;
it has at-least-once semantics and event IDs for deduplication. No emails, messages,
webhooks or notifications to third parties are sent by this implementation.

## Replay and walk-forward research

Replay consumes chronological JSONL snapshots through the same risk/fill engine.
Historical option bids/asks/sizes, actual expiry calendars, point-in-time membership
and contemporaneous event coverage must be supplied. It never manufactures option
premiums from stock history. Missing contract data, session gaps, absent closing
observations and unresolved positions are reported. Fixtures cannot satisfy the
`performance_evidence_complete` flag even when their input coverage is complete.

```powershell
# Explicit missing-data report when no historical dataset is supplied.
.\.venv\Scripts\python.exe -m agent_trading.intraday backtest
# Compare entry windows separately, chosen before evaluating results.
.\.venv\Scripts\python.exe -m agent_trading.intraday backtest data/intraday/history.jsonl --entry-time 09:50
.\.venv\Scripts\python.exe -m agent_trading.intraday backtest data/intraday/history.jsonl --entry-time 13:30
# Prespecified 1.5 and 2.0 exit-ratio variants; train selection only, one-session embargo.
.\.venv\Scripts\python.exe -m agent_trading.intraday backtest data/intraday/history.jsonl --walk-forward --train-sessions 20 --test-sessions 5
```

The walk-forward runner requires at least 20 completed training trades and complete
observed-data coverage before selecting a variant. It freezes the selected variant
for the unseen test block. It does not write production configuration, touch the
existing tournament's holdout, or rewrite `research/registry.jsonl`. Explain output
is deterministic evidence and research hypotheses; no paid AI model is required.

## Delivery status and limitations

| Component | Status | Practical limit |
|---|---|---|
| Scanner and CALL/PUT scoring | Implemented; deterministic tests | Full live S&P 500 cadence not established; sequential collection and plan limits |
| Next-session contract selector | Implemented; filter tests | Actual-chain Massive access blocked by current entitlement |
| Central risk gate | Implemented; limit/restart tests | Full premium and fees, no guaranteed stop fill |
| Local simulator and SQLite ledger | Implemented; lifecycle/partial-fill tests | Displayed-size/queue assumptions remain simulations |
| External Alpaca paper execution | Not implemented | Excluded by repository no-broker-order rule |
| Massive GET-only adapter | Implemented; mocked parser/pagination tests | Real-time stock and options entitlements/credentials required |
| Longbridge | Read-only expiry probe only | No autonomous SDK collector implemented |
| Exchange calendar/local scheduler | Implemented; holiday/DST/early-close/job tests | Runs only while process/UI operates |
| Streamlit dashboard | Implemented; UI tests | Local app, not GitHub Pages |
| Reports/CSV/local alerts | Implemented; accounting/outbox tests | External messaging integration is an owner-side outbox consumer |
| Event-driven replay/walk-forward framework | Implemented; causal/boundary tests | Real historical options study blocked by missing dataset |
| News and economic/earnings risk | Partially implemented | Validated sourced event import; no automatic event/news collector |
| AI research | Partially implemented | Deterministic explanations; external model integration not implemented |
| 0DTE vs 1DTE, trending vs sideways studies | Not performed | Suitable historical contract dataset not supplied |
| Profitability / $50 per day | Not validated | No market-data evidence supports a claim |

## Validation executed on 2026-10-21

- Full repository suite: **1,370 passed in 414.23 seconds**, Python 3.12 on Windows.
  Includes 63 new intraday tests and one Streamlit interaction test.
- `ruff check .`, `ruff format --check .`, and the repository's configured `mypy`
  checks passed. The existing broker/network safety tests remain green.
- Executed the offline demo, chronological replay, no-data coverage report, CSV
  export, alert outbox export and schedule listing. Demo orders stayed pending
  until later quotes, filled with fees/slippage, and closed with no remaining positions.
- Inspected the running Streamlit UI in a browser: disabled entries, explicit
  fixture labels, stale-scan warnings, orders, fills and historical equity rendered.
- Massive denied the options snapshot probe with NOT_ENTITLED. Longbridge returned
  actual listed expirations only. Neither probe validated full-universe real-time
  operation, historical options performance, broker paper fills or profitability.
