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
check. Follow-up calls for an actually listed October 23 contract returned
**301604: no quote access** for both option quotes and depth. No prices were obtained.

- [Longbridge SDK](https://open.longbridge.com/docs/getting-started): the local
  adapter pins Python `longbridge==4.5.0`, constructs only quote/content contexts,
  and uses the SDK HTTP client for one fixed GET-only calendar route. Version 4.5's
  calendar method lacks count/offset paging; the reader follows the official
  [calendar implementation](https://github.com/longbridge/openapi/blob/main/rust/src/calendar/context.rs).
  The chat plugin's authorization is separate from this process.
- [Option quotes](https://open.longbridge.com/docs/quote/pull/option-quote) require
  OPRA US Options Quotes **OpenAPI** permission; app/web permissions are separate.
- [Historical candles](https://open.longbridge.com/docs/quote/pull/history-candlestick)
  have a 1,000-row cap and monthly symbol quotas. Two-session requests avoid truncating
  the RVOL baseline. Reads are paced at least 0.55 seconds apart, below the documented
  60 historical calls per 30 seconds. A full universe needs over 500 symbol slots.
- [Depth](https://open.longbridge.com/docs/quote/push/depth) supplies prices and sizes
  without an exchange timestamp. Conservative receipt-time handling is described below.
- [News](https://open.longbridge.com/docs/content/news) publication times are preserved;
  retrieved headlines remain explicitly unverified research material.

## Preregistered starting methodology

Version `intraday-options-2026-10-21.2` is exploratory and has no demonstrated edge.
Version .2 adds explicit depth receipt-time provenance and automatic sourced event
screening. Risk ceilings are unchanged. Old .1 ledgers retain their original
methodology; the new default is `data/intraday/longbridge-paper.sqlite3`.
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
Unknown news, earnings or economic-event coverage blocks entry. Longbridge reads
US earnings, dividend, split and macro calendars and recent stock/SPY news. It blocks
a stock for a scheduled event that day, blocks the market for macro importance >=2
or unknown importance,
and flags headline keywords for earnings, guidance, bankruptcy, corporate actions,
investigations, offerings, halts, recalls, fraud, lawsuits, inflation, payrolls,
Fed/FOMC, war and tariffs. Clearances expire within 15 minutes. Refreshing the
calendar invalidates earlier clearances. Failed or truncated responses are not
treated as an empty, safe calendar. This English-keyword screen can miss unreported
or differently worded events; "clear" means no risk found in available coverage,
not that no news exists. File/Massive providers still accept sourced event JSON.

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
session was on Windows. No OS service, startup item, automation or cloud deployment
is installed automatically.

Configure `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET` and
`LONGBRIDGE_ACCESS_TOKEN` in the ignored `.env`. Never paste them into chat or commit
them. Legacy `LONGPORT_*` names also work. Endpoint redirects and SDK log-path
overrides are rejected. Authentication is for read-only market data; all fills are
still local simulations. No account/trading context is constructed.

Run `doctor` to probe stock quotes, a real listed option, depth, calendar and news.
It does not spend the quota for the entire index. A passing probe is not validation
of full-universe throughput, quote freshness outside market hours or profitability.
The service also probes once on startup and stops safely on a permission failure.

Start before 08:30 ET. Cold history warm-up can take tens of minutes. A background
collector subscribes to confirmed one-minute regular-session bars, loads ten prior
sessions, and persists complete sessions under `data/intraday/longbridge-bars`.
The foreground position monitor does not wait for that warm-up. Each stock scan
ranks the full universe, then refreshes bars and revalidates shortlisted stocks
against current breadth and market/sector data before considering entries.
The position monitor checks technical invalidation between scheduled scans.
The 08:30 preparation is completed again when the collector finishes warming.

The scheduler remains active across sessions. End-of-day entry suspension can
resume on the next session if previously enabled. Manual disable/stop, provider
failures and emergency stop cancel automatic resumption. No kill switch is released.
Failures latch by SDK context until the cause is fixed and the process restarted;
there is no automatic entitlement-error retry loop. Stream outages or missing bars
block entries. Keep just one scheduler running; the dashboard can monitor its ledger.

Massive remains an optional fallback via `--provider massive`; its original pacing
and event-file requirements still apply. It is not called by the Longbridge path.

```powershell
# Check local credentials and read-only data access first.
.\.venv\Scripts\python.exe -m agent_trading.intraday doctor
# Foreground automatic local-paper service (Longbridge is the default).
.\.venv\Scripts\python.exe -m agent_trading.intraday run --enable-entries
# Or use one validated normalized JSON snapshot, atomically refreshed by your collector.
.\.venv\Scripts\python.exe -m agent_trading.intraday --provider file --snapshot data/intraday/latest.json scan
# Foreground local scheduler. This flag authorizes LOCAL SIMULATED entries only.
.\.venv\Scripts\python.exe -m agent_trading.intraday --provider file --snapshot data/intraday/latest.json run --enable-entries
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

The dashboard can run the scheduler while open and retains its collector across
refreshes. The foreground CLI is preferable for continuous operation. A one-shot
Longbridge `scan` can report warming/incomplete inputs; use the running dashboard's
manual scan after warm-up, or the file provider for a ready normalized snapshot.
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
Longbridge depth has no exchange timestamp. Its `quote_time_basis` explicitly says
`changed_depth_receipt`. Identical bid/ask/size books retain their original observation
time on repeated reads and restarts; only a changed book advances that time. A recent
option trade and underlying quote are also required. This is a conservative freshness
proxy, not proof of the exchange age of a depth level; executions remain simulated.
Raw Longbridge Greeks are retained with `greek_units=longbridge_raw`: vendor docs
give inconsistent theta/vega scaling guidance, so no unverified normalization is
applied. Only delta is used as a selection threshold; theta/vega are displayed as raw.
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

The running scheduler delivers console notifications and a durable JSONL outbox
automatically (`--alert-outbox` selects its path). The `alerts` command also exports
an outbox on demand for an owner-configured notification integration;
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
| Scanner and CALL/PUT scoring | Implemented; deterministic tests | Full live S&P 500 cadence still requires entitled feed verification |
| Next-session contract selector | Implemented; filter tests | Longbridge listings accessible, quotes/depth denied by current entitlement |
| Central risk gate | Implemented; limit/restart tests | Full premium and fees, no guaranteed stop fill |
| Local simulator and SQLite ledger | Implemented; lifecycle/partial-fill tests | Displayed-size/queue assumptions remain simulations |
| External Alpaca paper execution | Not implemented | Excluded by repository no-broker-order rule |
| Massive GET-only adapter | Implemented; mocked parser/pagination tests | Real-time stock and options entitlements/credentials required |
| Longbridge SDK collector | Implemented; mocked SDK and failure tests | Local credentials missing; OPRA OpenAPI permission denied; full-universe quota unverified |
| Exchange calendar/local scheduler | Implemented; holiday/DST/early-close/job tests | Runs only while process/UI operates |
| Streamlit dashboard | Implemented; UI tests | Local app, not GitHub Pages |
| Reports/CSV/local alerts | Implemented; accounting/outbox tests | External messaging integration is an owner-side outbox consumer |
| Event-driven replay/walk-forward framework | Implemented; causal/boundary tests | Real historical options study blocked by missing dataset |
| News and economic/earnings risk | Automatic calendar/headline screening implemented and tested | Requires local Longbridge access; finite vendor coverage and keyword heuristic |
| AI research | Partially implemented | Deterministic explanations; external model integration not implemented |
| 0DTE vs 1DTE, trending vs sideways studies | Not performed | Suitable historical contract dataset not supplied |
| Profitability / $50 per day | Not validated | No market-data evidence supports a claim |

## Validation executed on 2026-10-21

- Full repository suite after the Longbridge integration: **1,391 passed in 383.39 seconds**,
  Python 3.12 on Windows. Includes 21 Longbridge/automation tests, the prior 63
  intraday tests and the Streamlit interaction test. Provider fixtures do not prove
  live SDK entitlements or complete real-data coverage.
- `ruff check .`, `ruff format --check .`, and the repository's configured `mypy`
  checks passed. The existing broker/network safety tests remain green.
- Executed the offline demo, chronological replay, no-data coverage report, CSV
  export, alert outbox export and schedule listing. Demo orders stayed pending
  until later quotes, filled with fees/slippage, and closed with no remaining positions.
- Re-ran the synthetic entry/exit scenario after the Longbridge changes: two closed
  local trades and no open positions. `doctor` correctly reported missing local
  credentials; it did not enable entries. A 500-symbol synthetic timing check for
  the two-position monitor took approximately 0.8 seconds, excluding network time.
- Inspected the running Streamlit UI in a browser: disabled entries, explicit
  fixture labels, stale-scan warnings, orders, fills and historical equity rendered.
- Massive denied the options snapshot probe with NOT_ENTITLED. Longbridge returned
  actual listings but denied option quotes and depth with 301604. Neither probe validated full-universe real-time
  operation, historical options performance, broker paper fills or profitability.
