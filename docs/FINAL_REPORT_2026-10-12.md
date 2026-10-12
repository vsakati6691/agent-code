# Audit, self-test and strategy tournament: final report (2026-10-12)

Nothing in this work submitted, modified or cancelled an order. No broker
settings were changed and no money was moved. Robinhood MCP calls were
read-only:
- `get_accounts`
- `get_trade_approval_setting`
- `get_portfolio`
- `get_equity_positions`
- `get_equity_orders`
- Alpha Vantage `DIVIDENDS`

Nothing here is investment advice, and no backtest proves future returns.

## 1. Readiness verdict

| Mode | Verdict | Why |
|---|---|---|
| A: Audit | **Ready** | Read-only checks work. The baseline is in [AUDIT_2026-10-12.md](AUDIT_2026-10-12.md) |
| B: Research | **Ready** | Data, tournament and registry are reproducible. Fundamentals and news cannot be tested point-in-time (see §4) |
| C: Backtest | **Ready** | Same engine, costs, periods and metrics for every candidate. 219 tests pass |
| D: Paper | **Conditionally ready** | The simulator works, but the scheduled runs are not reliably unattended (see §8) |
| E: Live (manual tickets) | **Conditionally ready, not recommended to expand** | The hard limits, the final order gate and the kill switch now exist in code and are tested. However: (1) no strategy passed the tournament's acceptance rules; (2) scheduled runs can stall on permission prompts; (3) the code never places orders, and the owner does |

## 2. Baseline assessment (before changes)

The baseline was commit `ecb10b5` on `feature/research-system`, with a clean tree and 171/171 tests passing.

**Architecture:**
- Scheduled Claude sessions read the broker and data through MCP and save JSON.
- Python imports it, runs strategies A (scanner), B (desk) and C (GTAA), the RiskEngine, the paper broker and the live-ticket writer.
- The owner places the tickets by hand.
- No Python path can reach a broker. A static test enforces this.

**Gaps found** (full table in the audit):
1. No persistent kill switch.
2. None of the master-prompt account limits in code.
3. TQQQ/SQQQ eligible for live tickets.
4. Unsettled cash ignored; the broker account is `limited_margin`, not cash.
5. No final check between sizing and the ticket.
6. Tickets could use bars up to 4 days old and a 24-hour-old snapshot.
7. No balance reconciliation.
8. No holiday calendar, so GTAA would **miss the May 2027 rebalance**: Memorial Day falls on the month's last weekday.
9. An 8% drawdown limit instead of 5%.
10. Run logs recorded the code commit as "unknown", because git is not on PATH.

## 3. Test report

| Area | Result |
|---|---|
| Unit, integration and safety tests | **219 passed, 0 failed, 0 skipped**. 48 tests were added: order gate, kill switch, calendar, tournament engine, a look-ahead perturbation test on all 12 candidates, and CLI parsing |
| Order gate | Each check is tested, including rejection paths: <ul><li>$100 per order; $200 and 3 entries per day; $800 exposure; $200 cash reserve</li><li>settled cash; leveraged and inverse ETFs; the allowlist</li><li>stale bars; limit sanity; one position per ticker; duplicates; an open buy at the broker</li><li>sells only up to the held quantity</li><li>no or stale snapshot; snapshot from another day; holidays; reconciliation failure</li><li>daily loss; a 5% drawdown engages the kill switch; live disabled; config may only tighten</li></ul> |
| Kill switch | Persists across restarts (re-read from disk). An unreadable file counts as engaged. Release needs the exact phrase. Every change is logged |
| End-to-end dry run | Ran the full post-close cycle on a **sandbox copy** of the data with a fresh read-only snapshot. Today's close was not yet in the data, so the gate refused an NVDA buy: "no verified 2026-10-12 close" (fail closed, as designed) |
| Order preview, rejection, timeouts | **Blocked by policy.** The code has no order path, and the AI sessions must not call `review_*`/`place_*`. Covered instead by: the gate refusing new buys while any buy is open at the broker (no duplicates after a timeout) and the reconciliation of the previous day's tickets |
| API failures, rate limits | Covered by existing tests: mocked Alpha Vantage failures, and billing errors reported rather than retried. Two Alpha Vantage `DIVIDENDS` calls made in parallel returned empty results (rate limit); calls one at a time worked |
| Scheduler | <ul><li>Intraday run at 14:36 UTC: succeeded.</li><li>Alert test: succeeded twice.</li><li>**Intraday run at 16:37 UTC: stalled.** Still "running" 40+ minutes later, stuck on its first PowerShell command, most likely a permission prompt with nobody present.</li><li>Pre-market has never run; post-close had not yet run at the time of writing</li></ul> |
| Restart recovery | Imports are idempotent, and a rerun replaces the same day's tickets. The kill switch survives restarts. A process restart was **not** tested on the live scheduler |

## 4. Strategy comparison

Full tables are in [research/TOURNAMENT_2026-10-12.md](../research/TOURNAMENT_2026-10-12.md). Every run is logged in [research/registry.jsonl](../research/registry.jsonl).

**Setup:**
- Robinhood daily bars, 2007-09 to 2026-10-09.
- Total return for the 10 ETFs with dividend files; sector ETFs are price-only (flagged).
- Costs: 12.5 bps per side.
- Signals at the close, fills at the next open.
- **30 strategy/parameter trials.**

Train + validation (2008-10 to 2021-12, the data used for selection):

| Strategy | CAGR | Sharpe | Max DD | Decision |
|---|---|---|---|---|
| SPY buy & hold | +13.5% | 0.71 | −40.8% | benchmark |
| 60/40 SPY/IEF | +10.1% | 0.90 | −24.1% | benchmark |
| GTAA (live Strategy C) | +4.4% | 0.65 | −8.4% | rejected |
| SPY 10-month trend | +9.3% | 0.73 | −23.2% | rejected |
| GTAA + trend combo | +7.0% | 0.76 | −13.7% | rejected |
| Cross-asset relative strength top 3 | +9.4% | 0.69 | −21.8% | rejected |
| Vol-targeted trend | +6.1% | 0.62 | −16.7% | rejected |
| Dual momentum | +7.1% | 0.48 | −33.7% | rejected |
| Sector rotation (price-only) | +6.5% | 0.46 | −24.1% | rejected |
| RSI-2 mean reversion | +0.2% | 0.02 | −20.1% | rejected (fails almost every check) |

**Final test, 2022-01 to 2026-10, evaluated once:**

| Strategy | CAGR | Sharpe | Max DD | Under the $1,000 account limits |
|---|---|---|---|---|
| SPY | +12.5% | 0.54 | −24.5% | |
| BIL | +3.9% | 0.00 | | |
| 60/40 | +6.6% | 0.29 | −20.9% | |
| **GTAA** | **+5.4%** | **0.25** | **−6.6%** | +3.3%/yr, about $33/yr |

GTAA's Sharpe minus SPY's: −0.30 (95% CI −1.11 to +0.55).

The other 7 candidates were **not** evaluated on the test period, so it remains untouched for them.

Strategies A and B were tested by their own pipelines:
- **A (scanner):** no edge on point-in-time S&P 500 lists.
- **B (desk):** trading edge near zero per instrument; every Sharpe interval includes zero.

## 5. Recommended strategy

**No candidate passed the pre-registered acceptance rules, so none is recommended as an improvement.**

Every candidate failed the deflated-Sharpe test (P ≥ 0.90 after 30 trials). Every candidate was also more than 0.10 Sharpe below the simple 60/40 benchmark on the selection data.

The 60/40 benchmark's edge came from the 2008–2021 bond bull market, and it did poorly in the test period (Sharpe 0.29). The rule was fixed before the results, though, and loosening it now would be data snooping.

**The most defensible option for the account** is the incumbent **GTAA (Strategy C)**:
- It is not better than SPY on return or Sharpe.
- It has by far the smallest drawdowns in every stress window: GFC −6%, COVID −6%, 2022 −6%, 2025 −4%.
- Under the hard limits it deploys about 50–56% of the account on average; single-ETF strategies can deploy only 10%.
- It is parameter-insensitive (grid Sharpe 0.63–0.68) and survives 3× costs (0.52).

Treat it as a **low-drawdown allocation, not an edge**.

**Why the alternatives were rejected:**
- **SPY trend and the combo:** looked strongest in walk-forward, but are sensitive to the SMA length (0.69–0.99) and fail the deflated Sharpe test. Under the account's $100-per-position limit, SPY trend could invest only 10% of the account.
- **RSI-2:** no edge after costs.
- **Dual momentum:** −34% drawdown.
- **Sector rotation:** weakest Sharpe, and its data is price-only.

## 6. Risk assessment

**Worst drawdowns observed:**
- SPY: −40.8% (2008–09) and −33.7% (2020).
- GTAA: −8.4% over 2008–2021 and −6.6% in the test.

**On $1,000:**
- The new 5% review limit is $50.
- Fully invested GTAA fell 5% or more from a running peak in 14 of the 19 years from 2008.
- Under the account limits (about 50–56% invested on average), it did so in 3 years: 2011, 2016 and 2023.
- **Expect the kill switch to engage occasionally even with GTAA.** That is by design: it forces a human review.

**Remaining risks:**
1. Gaps and overnight moves can exceed every stop and limit. The limits are not loss caps.
2. The owner places orders by hand. Nothing in code can stop a manual order that ignores a ticket, and broker approvals can be switched off in the app.
3. Robinhood classes the account as `limited_margin`. The code uses settled cash only, but the broker itself would allow margin.
4. Scheduled sessions can stall on permission prompts, or not run when the laptop sleeps. Missed runs mean no tickets, which is safe, but a missed protective-stop warning is not.
5. Fills are modelled at the next open plus costs. Real limit orders may not fill.
6. Total-return data for 10 ETFs only. One 30% VNQ move on 2008-10-13 is flagged and unverified.
7. Earlier research had already seen the 2022–2026 period for GTAA and SPY trend.

## 7. Change log

| Commit | What |
|---|---|
| `e28371b` | Hard account limits, final order gate, kill switch, NYSE calendar, drawdown tightened from 8% to 5%, unsettled cash in snapshots, baseline audit doc. Files: `order_gate.py`, `killswitch.py`, `market_calendar.py`, `config.py`, `account.py`, `live.py`, `daily.py`, `cli.py`, `strategies/gtaa.py`, `strategies/desk.py`, `config/settings.yaml`, `CLAUDE.md`, `README.md`, `docs/DAILY_ROUTINE.md`, `docs/AUDIT_2026-10-12.md`. Tests: `test_order_gate.py`, `test_market_calendar.py`, `test_live.py` |
| `10883c4` | Tournament pipeline (`research/` package: engine, candidates, tournament, report), `tournament` CLI, `manifest.code_version` fix. Tests: `test_tournament.py` |
| (this commit) | Tournament results and registry, final report, CLI print fix, CLI parse test |

The tournament run recorded code `10883c4` plus one uncommitted change: a print-statement fix in `cli.py` that does not affect results. The registry says so (`code_dirty: true`).

## 8. Deployment requirements

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"     # Python 3.12; pandas, numpy, PyYAML, requests, python-dotenv
.\.venv\Scripts\python.exe -m pytest                       # 219 must pass
.\.venv\Scripts\python.exe -m agent_trading kill-switch status
.\.venv\Scripts\python.exe -m agent_trading tournament --no-test   # research reruns without touching the test period
```

- **Environment:** `.env` with `ALPHAVANTAGE_API_KEY`, git-ignored.
- **Account snapshot:** must now include `unsettled_funds` and `account_type` from `get_accounts` (runbook step 1). Without them, buys are blocked.
- **Scheduler:** Claude desktop scheduled tasks (premarket, midday, postclose, weekly).
- **Not unattended today.** Missing pieces:
  1. Permission allow-rules for exactly the commands the tasks run. Today's midday run stalled.
  2. A machine that stays awake through 16:30–17:30 ET.
  3. A missed-run alarm. Nothing alerts if the post-close run never happens.
- **Smallest-cost option:** keep the laptop. Add project allow-rules for the venv Python commands, keep the machine awake in market hours, and have the pre-market run alert when the previous post-close manifest is missing.
- **Cloud alternative (not deployed, needs your decision):** Claude cloud routines, *if* the Robinhood connector works there (unverified).

## 9. Cost report

| Item | Cost | Status |
|---|---|---|
| Robinhood equity commissions | $0 | Robinhood's public pricing; not verified in this session. Small regulatory fees on sells are not modelled |
| Slippage and spread assumption | 12.5 bps per side (≈ $0.13 per $100 order) | Assumption. Stressed at 2× and 3× |
| Alpha Vantage | $0 (free key, 25 requests/day) | Verified from config and usage |
| Financial Datasets | Prepaid; balance exhausted | From an earlier session; not re-checked |
| Bigdata.com, Robinhood MCP | Included in the existing connectors | Pricing not verified |
| Claude model usage (scheduled runs) | Unknown | Not measured. Five task runs per weekday use your Claude plan's allowance |
| Hosting | $0 (laptop) | |

## 10. Next steps (smallest safe set)

1. **Owner:** decide whether to keep Strategy B in `live.strategies`.
   - After this change, it can only ticket NVDA and IBIT.
   - Its evidence is weak: trading edge ≈ 0.
   - Removing it is a tightening, and needs only your OK.
2. **Fix unattended runs:**
   - Add permission allow-rules for the scheduled tasks' commands.
   - Add a missed-run check.
   - Then watch one full day: premarket, midday, postclose.
3. **Paper-trade GTAA through at least 6 month-ends** before adding any capital or strategy. Compare its paper results with the backtest.
4. **For future research:** reuse `tournament --no-test` and add candidates to `research/candidates.py`. The test period now has one recorded evaluation for the benchmarks and GTAA; don't re-tune against it.

## Concise verdict

- **Technically functional?** Yes. 219 tests pass, the live-ticket path fails closed, and the kill switch persists.
- **Genuinely unattended?** No. It depends on the laptop and the app, and a run stalled on a permission prompt today.
- **Existing strategy better than a simple benchmark after costs?** No on return or Sharpe. GTAA trails SPY and, on the selection data, 60/40 as well. Yes on drawdown, by a wide margin.
- **Any alternative pass out-of-sample validation?** No. 0 of 8 candidates passed the pre-registered rules.
- **What changed?**
  - Hard limits, final order gate, kill switch and holiday calendar in code.
  - TQQQ/SQQQ blocked from live; 5% drawdown review.
  - Settled-cash check.
  - Tournament pipeline and registry.
- **Unverified:**
  - The broker's order tools and order types (by design, never called).
  - Behaviour of cloud scheduling.
  - The VNQ 2008 data point.
  - Pricing of model and connector usage.
  - A full unattended day.
- **Safe to proceed?** Only to continued **paper trading plus small manual GTAA tickets** under the new limits, after the scheduler fix. Not to more capital, more strategies, or automated execution.
