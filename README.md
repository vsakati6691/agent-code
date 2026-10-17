# agent-code · Tikasa Stock Research

[Open the research dashboard](https://vsakati6691.github.io/agent-code/index.html) ·
[GitHub repository](https://github.com/vsakati6691/agent-code) ·
[Dashboard methodology](docs/RESEARCH_DASHBOARD.md) ·
[Daily runbook](docs/DAILY_ROUTINE.md)

A public stock and options research dashboard, plus a local Python system for
stock/ETF research, paper trading and manual live-order tickets. The dashboard
compares companies using dated evidence and rules fixed in advance. The local
desk analyzes data imported through read-only market and account connectors.

> **The system never places orders.** Strategies B and C can write manual tickets
> for the owner's Robinhood Agent-trading account, sized on at most $1,000. The
> owner reviews and places each order by hand. Brokerage tools are read-only;
> the code cannot place, modify or cancel orders, move money, use margin, short,
> or trade options or crypto. Dashboard options are research comparisons only
> and do not change those restrictions. Nothing here is investment advice.

## Research dashboard

The [GitHub Pages site](https://vsakati6691.github.io/agent-code/index.html) uses
public market data only. Account snapshots, positions, orders, manual tickets
and journals stay out of the dashboard. Sources include SEC EDGAR, Nasdaq
Trader, Cboe delayed quotes, Alpha Vantage, FRED and FINRA; coverage and timestamps appear
on the site.

| Page | What you can explore |
|---|---|
| [Overview](https://vsakati6691.github.io/agent-code/index.html) | SPY/IJH/IWM market context, snapshot changes, scheduled earnings, concentration and downside flags, benchmark tracking and data coverage. |
| [Growth Stocks](https://vsakati6691.github.io/agent-code/growth.html) | Large-, mid- and small-cap research lists with search, field filters, sorting, CSV downloads and device-local pins. Large-cap candidates come from the S&P 500. |
| [Multibaggers](https://vsakati6691.github.io/agent-code/multibaggers.html) | Up to five speculative companies with a 5–10 year research horizon, conditional scenarios, failure risks and thesis invalidation conditions. |
| [AI stocks](https://vsakati6691.github.io/agent-code/ai.html) | Up to five large-cap and five mid-cap AI candidates, their roles in the AI supply chain, conditional market-cap comparisons and sourced private-company context. |
| [Compare](https://vsakati6691.github.io/agent-code/compare.html) | Two to four companies side by side: financial trends, valuation, returns, drawdowns, evidence quality and SEC sources, with warnings for incompatible periods or scoring profiles. |
| [Options](https://vsakati6691.github.io/agent-code/options.html) | Separate weekly and daily call/put comparisons across 3M/6M/1Y expiry windows, plus speculative 30–90 days-to-expiry research and a hypothetical risk-budget calculator when options are enabled. |
| [Small bets](https://vsakati6691.github.io/agent-code/bets.html) | A separate options explorer with Core/Long-shot tiers, premium filters, whole-contract budget arithmetic and a device-local research slip. |
| [Watchlist 2030](https://vsakati6691.github.io/agent-code/watchlist.html) | A saved ticker list with verified symbol information, dated prices and conditional year-end-2030 bear/base/bull price scenarios. |
| [Leaders 2030](https://vsakati6691.github.io/agent-code/leaders.html) | Current size versus conditional 2030 size, dated share assumptions, coverage gaps, curated challengers and CSV. |
| [Plan 2030](https://vsakati6691.github.io/agent-code/goal.html) | Browser-only target and contribution arithmetic, stored scenario comparisons, optional weighted ending values and a year-one drawdown stress test. Missing weighted scenarios stay unavailable. |
| [Evidence](https://vsakati6691.github.io/agent-code/evidence.html) | Benchmark and GTAA results, acceptance rules and the no-candidate-passed verdict, read from the repository's tournament and final report at build time. |
| [History & tracking](https://vsakati6691.github.io/agent-code/history.html) | Stored research reports and forward list returns versus benchmarks at 1, 3, 6 and 12 months, when enough observations exist. |
| [Methodology](https://vsakati6691.github.io/agent-code/methodology.html) / [Audit trail](https://vsakati6691.github.io/agent-code/audit.html) | Versioned rules, exclusions, source coverage, timestamps, snapshot hashes, downloadable data and the append-only event log. |

Company detail pages bring together financial trends, thesis and bear case,
valuation, filing links, changes since the previous snapshot, and scenario
calculators. A ticker lookup connects each symbol to its research and history.

### Data sources

| Source | Weekly inputs |
|---|---|
| SEC EDGAR | XBRL fundamentals, Form 4 P/S activity, quarterly 13F aggregates, dated FTD CUSIP mappings and EFTS-located risk quotations. |
| FRED | Seven dated macro series; DGS1MO supplies the existing Black-Scholes rate parameter for new weekly estimates. Requires `FRED_API_KEY`. |
| FINRA | Settlement short shares and changes, divided by dated XBRL diluted shares; never float. |
| Nasdaq Trader / Wikipedia | Listed symbols and S&P 500 membership. |
| Cboe / Alpha Vantage | Delayed prices and optional option chains; earnings and current company estimates. |

### Latest research features

Methodology **2026-10-16.2** adds [dated public datasets](docs/PUBLIC_DATASETS.md).
The prior version had zero weekly snapshots at registration; exact-version
continuity counts remain separate. Scores, weights, gates, lists and equity
scenario formulas remain unchanged.


Methodology **2026-10-16.1** adds [Leaders 2030 and explicit watchlist upside](docs/LEADERS_2030.md). Version **2026-10-15.1** added [dated ETF exposure and expense inputs](docs/ETF_INPUTS.md),
with issuer sources, inception dates and explicit unverified labels. Existing
scales, weights, gates and lists are unchanged. Scenarios remain unavailable
where the registered models or required financial evidence do not support them.
The [full methodology changelog](docs/SPEC_CHANGELOG.md) preserves every registration reason.

The preceding **2026-10-14.9** version adds dated growth-decision fields: fiscal-year revenue
and EPS growth, margins, debt and cash, valuation, ownership-data coverage and
issuer business/risk excerpts. Growth lists separate **fundamental quality from
momentum**; scores should be compared within their original list and profile.
Older snapshots retain their original methodology and missing fields.

Plan 2030 shows dated starting prices, conditional 2030 prices and the return
required for the goal beside the stored scenarios and research evidence. Inputs
stay in the browser's local storage. The overview
reports missing refresh datasets and progress toward 52 weekly snapshots under
the current methodology, frozen as of **2026-10-16**. The administrative freeze
date is recorded separately from methodology version **2026-10-17.4** and its pinned hash. Versions retain separate evidence counts.

Version **2026-10-17.1** registers full S&P 500 collection for the current top-20
Leaders view. Version **2026-10-17.2** anchors Leaders base growth in three-year
revenue CAGR, accelerates the fade above $500B, permits revenue declines in bear
cases and shows implied cap growth next to every scenario. A base above 25%/yr
is labelled an aggressive assumption. See [Leaders rules](docs/LEADERS_2030.md).
These rows still depend on a successful weekly import; code deployment does not
fill missing data in older snapshots.

Version **2026-10-17.4** adds the **Buy/Sell desk** tab: the five stages of
[TradingAgents](https://github.com/TauricResearch/TradingAgents) (analysts, bull vs bear
debate, trader, risk team, portfolio manager), each a fixed rule over stored fields
instead of a language model, ending in Buy, Overweight, Hold, Underweight or Sell.
Ratings are rule-based research labels, not advice; they are stored with each new
weekly snapshot and tracked by rating. See the [desk rules](docs/SPEC_CHANGELOG.md).

All tabs now put data before longer explanations, with full operating details
on Audit. [UI documentation](docs/DASHBOARD_UI.md) and the
[browser test report](docs/ux/2026-10-17/BROWSER_TESTS.md) cover both viewport
sizes/themes, no-JavaScript behavior, screenshots and before/after measurements.

Every built HTML page has a 150 KB budget. Detail panels, scanner/comparison data
and sparklines use separate assets; older larger options lists are split by
expiry. Tables scroll within their wrappers, muted text meets AA contrast in
both themes, and the stale warning is readable without JavaScript.

The Options page also supports speculative 30–90 DTE comparisons for up to the
top three names in each large/mid/small growth list. Its browser calculator
shows hypothetical premium exposure and cap warnings. Small bets uses a
separate universe and longer expiry windows. These tools do not change the
local trading desk's risk limits or submit orders.

Quotes are **delayed, never live**. Missing, stale or unsupported fields retain
their reasons; missing earnings data means unknown. Insider net buying/selling
stays unavailable without unambiguous transaction classifications. IV rank
requires 252 comparable stored sessions. Scenarios are conditional calculations,
and **probability is not established** without out-of-sample calibration. Any
option contract can lose its entire premium.

### Refreshes and publication

| Workflow | Schedule | What changes |
|---|---|---|
| [Publish code changes](.github/workflows/research-dashboard-publish.yml) | Every push to `main`, or manual run on `main` | Tests the code, verifies stored data and rebuilds Pages without collecting data or changing snapshots. |
| [Weekly research](.github/workflows/research-dashboard.yml) | Saturday 14:17 UTC (10:17 EDT / 09:17 EST); Sunday retry at the same time | Collects fundamentals and prices, ranks candidates, stores an immutable snapshot, updates tracking and builds the site. |
| [Daily light refresh](.github/workflows/research-dashboard-daily.yml) | Weekdays 22:17 UTC (18:17 EDT / 17:17 EST), when enabled | Adds delayed closing prices and optional options research. Weekly stock scores, ranks, trailing returns and tracking remain unchanged. |

GitHub Actions runs independently of the owner's laptop. Scheduled jobs can be
late or skipped; holidays, provider failures and incomplete coverage are
reported. Weekly snapshots and daily records live on the `research-data` branch
with integrity manifests; existing records are never backfilled or overwritten.

The [deployment runbook](docs/DEPLOYMENT.md) explains how to confirm the live
site matches `main`. Every build writes `build.json` with the site-code commit,
stored-data commit and separate registered/snapshot methodology versions.
The audit page exposes the same provenance. A code-only rebuild preserves the
stored scenarios; new methodology inputs appear after a future collection.

Repository variables control `DASHBOARD_DAILY` (weekday collection),
`DASHBOARD_OPTIONS` (option collection/display) and `DASHBOARD_PUBLISH` (Pages
deployment). These are opt-in gates. SEC access requires `SEC_USER_AGENT`;
`ALPHAVANTAGE_API_KEY` supports earnings and optional enrichment; `FRED_API_KEY` supports macro observations. Local secrets
belong in the ignored `.env`; workflow credentials belong in GitHub Actions
secrets. Review the [data-source terms and setup](docs/RESEARCH_DASHBOARD.md#owner-actions-required-before-the-first-deployment)
before enabling collection or publication. Cboe redistribution requires consent.

## Local research and manual-ticket desk

The desk is separate from the public dashboard. An AI session collects data
through read-only connectors, saves payloads in its scratchpad, imports them
and runs the Python engine. Follow [the daily runbook](docs/DAILY_ROUTINE.md).

| Strategy | What it does | Backtest evidence, including costs |
|---|---|---|
| **A: S&P 500 scanner** · paper only | Ranks constituents on strength, volume, quality, valuation and low volatility; up to three paper entries. | No demonstrated edge: did not beat SPY in 2019–2025, rank IC approximately zero, no better than plain 12-1 momentum. |
| **B: Desk** · paper + manual tickets | Trend rules for TQQQ, SQQQ, IBIT and NVDA. Only IBIT and NVDA are eligible for real-account tickets. | Weak: edge near zero per instrument. |
| **C: GTAA** · paper + manual tickets | Monthly rebalance across SPY, EFA, IEF, DBC, VNQ, TLT and GLD; hold an asset while above its 10-month average. | Modest returns and lower drawdowns, but rejected by the tournament: train + validation (2008–2021) CAGR +4.4%, Sharpe 0.65, maximum drawdown −8.4%. |

The [2026-10-12 tournament](research/TOURNAMENT_2026-10-12.md) compared eight
pre-registered candidates and four benchmarks: **no candidate passed the
acceptance rules**. These desk
backtests do not establish an edge for the newer dashboard lists. Use
`tournament --no-test` for further research; the tournament test period has
already been evaluated. Signals at day *t* close fill at day *t+1* open in the
simulator, and the research registry is append-only.

### Enforced risk limits

| Control | Current configuration on $1,000 |
|---|---|
| Planned risk per position / aggregate / correlated | $5 ($2.50 for paper TQQQ/SQQQ) / $15 / $10 shared. |
| Position size and stops | 25% maximum position; cash only; initial stop at 2.5 × ATR(14), with a 20% stop-distance risk buffer. Real buy tickets also face the stricter $100/order gate. |
| Leveraged ETFs | TQQQ/SQQQ are paper only, have a five-day maximum hold and cannot be held together. |
| Daily loss / drawdown | 1% stops new entries; 5% drawdown engages the kill switch. Only the owner may release it. |
| Real-account order gate | $100 per buy; $200 and three new entries/day; $800 exposure; $200 cash reserve; settled cash; one position per ticker; an allowed-symbol list and a fresh, reconciled same-day snapshot. |
| Simulator cost settings | 10 bps slippage plus half the configured 5 bps spread per side; zero commission. |

Stops cannot guarantee a loss ceiling because gaps can fill worse. The
configuration rejects shorting, margin, options and crypto trading, and safety
tests guard against broker order calls. See [architecture and full rules](docs/ARCHITECTURE.md)
and [current settings](config/settings.yaml).

### Local operating routine

| Time (New York) | Run | Output |
|---|---|---|
| Weekdays 08:30 | Pre-market | Account, calendar and quote checks; repeats open tickets. |
| Weekdays 12:30 | Midday | Stop breaches and changed decisions. |
| Weekdays 16:30 | Post-close | Paper fills, loss checks, manual live tickets and the full report. |
| Friday 17:30 | Weekly review | Paper P&L versus SPY and missed runs. |

These local sessions require the laptop and app to be open and the automation
to be configured. Reports go to ignored `reports/`. The public dashboard's
GitHub Actions schedule above is independent.

## Quick start

Use **Windows, PowerShell and Python 3.12**, the version used in CI. Run commands
from the repository root. `pyproject.toml` declares Python 3.11 or newer.

```powershell
git clone https://github.com/vsakati6691/agent-code.git
cd agent-code
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env   # first setup only; add local keys, never commit this file
.\.venv\Scripts\python.exe -m pytest
```

After importing the required data using the [runbook](docs/DAILY_ROUTINE.md):

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m agent_trading daily --no-paper --label premarket
& $py -m agent_trading paper status
& $py -m agent_trading account show
& $py -m agent_trading kill-switch status
```

The post-close cycle advances the paper simulator and writes eligible manual
tickets. Research evaluations use the available local history:

```powershell
& $py -m agent_trading daily --label postclose
& $py -m agent_trading evaluate-scanner
& $py -m agent_trading evaluate-desk
& $py -m agent_trading evaluate-gtaa
& $py -m agent_trading tournament --no-test
```

To build a local dashboard from the existing public data branch without
collecting new data, first check out that branch into the ignored folder:

```powershell
git fetch origin research-data
git -c core.autocrlf=false worktree add --detach research-data origin/research-data
& $py -m agent_trading.dashboard verify --data research-data
& $py -m agent_trading.dashboard build --data research-data --out site
& $py -m http.server 8000 --directory site
```

Open [localhost:8000](http://localhost:8000). The build reads stored snapshots
without network requests. If `research-data/` already exists, reuse its checkout
instead of adding it again. See [dashboard commands](docs/RESEARCH_DASHBOARD.md#commands)
for collection, refresh and tradability-import options.
Keep the data checkout's original line endings: Windows CRLF conversion changes
the snapshot bytes and correctly fails integrity verification.

## Repository layout

```text
config/                       strategy/risk settings, watchlist and research inputs
src/agent_trading/
  dashboard/                  collectors, scoring, daily refresh, static site and browser tools
  strategies/                 scanner.py (A), desk.py (B), gtaa.py (C)
  risk.py, paper.py, live.py   risk engine, paper broker and manual live tickets
  order_gate.py, killswitch.py real-account ticket limits and persistent shutdown
  daily.py, cli.py            local daily cycle, reports and commands
  data/, backtest/            imports, validation, backtest engines and statistics
.github/workflows/            weekly research and optional weekday refresh
docs/                         methodology, architecture, daily runbook and audits
research/                     pre-registered experiments, results and append-only registry
tests/                        unit, integration, dashboard and safety tests
```

Runtime `data/`, `logs/`, `reports/`, generated `site/` and the local
`research-data/` checkout are git-ignored.

See the [module guide](docs/MODULES.md) for the pipeline stages, page renderers,
CLI command groups and daily run phases.

For historical findings, see the [research report](docs/FINAL_REPORT_2026-10-12.md).
**AI assistants and contributors:** read [CLAUDE.md](CLAUDE.md) in full;
[AGENTS.md](AGENTS.md) points to the same rules. Work on `feature/research-system`,
run the full test suite and scan the staged diff for secrets before committing.
Changes reach `main` through a PR on the owner's instruction.

The [CI workflow](.github/workflows/ci.yml) runs on every push and pull request:
the full test suite, Ruff lint/format checks, and an offline fixture-site build
with snapshot integrity, internal-link checks and the 150 KB HTML budget. **Tests, lint and fixture
site** is required for merge; the owner must select that check in the `main`
branch protection rules or ruleset. Adding this workflow does not configure
GitHub branch protection automatically. Run the same checks locally with
`python -m ruff check .` and `python -m ruff format --check .` after installing
the development dependencies.

Local manual tickets require `BROKER_ACCOUNT_LAST4` in the ignored `.env` or
process environment. The shipped configuration leaves the account suffix
empty and fails closed while `live.enabled` is true until it is supplied.
Process environment values take precedence over `.env`; leading zeros are
preserved. Never commit an account identifier to configuration or documentation.

## License

Original project code is available under the [MIT License](LICENSE).
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and its linked license texts
govern the adapted third-party pieces. Software licensing does not grant
market-data redistribution rights.
