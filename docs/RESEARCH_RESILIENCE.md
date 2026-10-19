# Provider recovery, sector balance and earnings validation

Registered as methodology **2026-10-19.1**, with verification fixes in **2026-10-19.2** and live-build fixes in **2026-10-19.3**,
these changes apply to new collections.
Existing snapshots and tracked results retain their original rules. No improved
investment performance is claimed.

## Provider recovery

`Providers` keeps Cboe quotes and dated SEC XBRL scoring fundamentals. On a Cboe
quote error it tries an Alpha Vantage daily quote, then optional FMP.
`Providers.overview()` tries Alpha Vantage, then FMP's basic company profile.
All dashboard requests still pass through `HttpClient`.

Set `FMP_API_KEY` in the ignored local `.env` to enable FMP; the GitHub workflows
also accept the optional repository secret with that name. This change creates
no credentials or paid plan. Without a key, collection continues with explicit
missing data. Endpoint access depends on the key's entitlement. The adapter uses
FMP's documented [stock quote](https://site.financialmodelingprep.com/developer/docs/stable/quote)
and [company profile](https://site.financialmodelingprep.com/developer/docs/stable/profile-symbol) endpoints.

```python
from agent_trading.dashboard.providers import Providers

# Reuse the run's HttpClient to share pacing and request budgets.
providers = Providers(http, av_key=av_key, fmp_key=fmp_key)
quote = providers.daily_quote("AAPL", as_of=completed_session)
profile = providers.overview("AAPL")
```

`daily_quote()` rejects wrong symbols, stale sessions, invalid prices and intraday
FMP timestamps. Fallback quotes retain source and retrieval timestamps; they are
close-only and cannot fill missing Cboe daily OHLCV bars. A profile is a current
observation, not a substitute for SEC history. Its fields are retained in
`basic_fundamentals`. Missing forward P/E, PEG and analyst targets remain missing.

Transient timeouts, connection failures and HTTP 500/502/503/504 receive at most
three attempts, with 2- and 4-second exponential delays plus provider pacing.
Both Alpha Vantage clients charge every attempt to the persisted daily budget.
Quota notices, HTTP 429, billing and authorization failures stop immediately;
retries cannot recover an exhausted daily allowance. FMP has an independent
80-attempt run limit, tightened to 20 in a light refresh. The refresh requests
the earnings calendar before quote fallbacks to preserve its single AV allowance.

`pipeline_external.institutional_record()` isolates per-company 13F errors, in
addition to the bulk-fetch boundary. It preserves unavailable states and adds
`score_adjustment: 0.0`. Missing ownership is never fabricated as zero. This
isolates failures; it does not repair an unavailable upstream SEC archive.
From 2026-10-19.3, current collections also execute `Providers.institutional_holders()`
when the SEC record is unavailable, partial or stale and `FMP_API_KEY` is configured.
This uses FMP's documented [positions summary](https://site.financialmodelingprep.com/developer/docs/stable/positions-summary)
for the latest completed quarter at least 45 calendar days old. Symbol, exact quarter,
holder count and share count are validated before use. The aggregate is labeled FMP;
it is not an individual holder list or point-in-time SEC filing history. Historical
backfills never query this current source. Each record and the dataset summary report
fallback status: `available`, `provider_error`, `unconfigured`, `historical_disabled`
or `not_needed`. Both providers failing leaves explicit missing data and a neutral
score adjustment. An entitled FMP repository secret is required for live recovery.

## Sector penalty

```python
from agent_trading.dashboard.sector_balance import sector_penalty

adjusted = sector_penalty(eligible_tradable_scores, sectors_by_ticker, size=10)
```

Measure sector shares in the raw top N, apply the same deduction to every
candidate in each overrepresented sector, and rerank once. On the 0–100 scale:

```text
deduction = 10 × max(0, sector_share − 0.50) / 0.50
```

50% receives no deduction, 80% receives six points, and 100% receives ten. Scores
are floored at zero. `raw_composite`, `sector_penalty`, adjusted `composite` and
a readable flag explain the result. Existing gates, tradability and tie breaks
still apply. Unknown sectors remain explicit. SEC SIC mappings are sector
proxies; S&P labels come from the GICS column. This is a soft penalty, not a hard
cap: it cannot diversify a pool without eligible alternatives.

`score_bands()` runs this after tradability and before the candidate cutoff, for both
growth and AI lists. New snapshots record `sector_adjustment.applied`, the number of
eligible candidates penalized, and individual raw scores/deductions. The site explains
when an older snapshot predates these fields. Publishing code alone does not rescore
an immutable historical snapshot; the next completed-session collection supplies
the new ranking.

## Short-term options desk

The Options page links to `options-short-term.html`, a separate delayed research
desk for NVDA, PLTR, MU and AVGO. It displays 0DTE, 1 calendar DTE and the next actual
listed expiry within seven days. Empty windows remain empty. A tomorrow contract
can appear in both the 1DTE and next-listed views. This is liquidity research, not
an earnings-event trigger, probability estimate, or brokerage order interface.

Run **research-dashboard-short-term** from GitHub Actions on `main` during the
regular session (`DASHBOARD_OPTIONS=true`; publication also needs
`DASHBOARD_PUBLISH=true`). The manual workflow tests, collects, verifies, appends
research data, builds and publishes. It makes no Alpha Vantage requests and needs
no FMP key. There is no new recurring schedule. Locally:

```powershell
.\.venv\Scripts\python.exe -m agent_trading.dashboard short-term --data data/research-preview --cache .cache/short-term
.\.venv\Scripts\python.exe -m agent_trading.dashboard build --data data/research-preview --out data/research-preview-site
```

The desk is included only in the full site edition. Customer builds omit its page,
script and stored chain observations; the new workflow honors `DASHBOARD_EDITION`.

Only `HttpClient` fetches data: four chains, a 12-attempt Cboe cap, ten-second
request timeouts and a two-minute collection deadline. Cached responses cannot
masquerade as an intraday refresh. Both the chain timestamp (UTC when naive) and
underlying trade timestamp (New York when naive) must fall within the regular
session and 25 minutes of collection. Cutoffs follow the regular session and
[NYSE early-close calendar](https://www.nyse.com/trade/hours-calendars); they are
research cutoffs, not broker exercise deadlines or extended trading hours.

The fixed filters and sort order live in `spec.LIVE_GAP_RULES`. Standard roots,
positive bid, noncrossed quotes, integer volume/OI and finite numbers are required.
Duplicate OCC symbols are rejected. Premium/max premium loss use ask × 100, without
fees or a pricing model. Immutable `short-term/<UTC timestamp>/scan.json` observations
have integrity manifests and a 100 KB cap. A completely failed collection appends
an audit event without replacing the latest good observation. Partial coverage and
closed sessions are explicit. Stored rows turn stale/expired in the browser based
on their original timestamps; the page does not fetch new prices automatically.

`tests/test_dashboard_live_gaps.py` covers the executing fallback adapter, candidate
ranking integration, actual expiry selection, malformed/stale quotes, duplicate
contracts, early closes and failed-run preservation. A live smoke test must report
actual provider availability separately from these mocked regression checks.

## Earnings quarantine

```python
from datetime import date
from agent_trading.dashboard.earnings_cadence import validate

check = validate("2026-11-25", "2026-10-29", as_of=date(2026, 10, 9))
assert check["validation_status"] == "Review Required: Outlier"
assert check["deviation_days"] == 27
assert check["event_eligible"] is False
```

The ±21-day boundary is inclusive. Outliers retain their scheduled and estimated
dates for review, but cannot create upcoming events, option catalyst research or
desk earnings triggers. Light refreshes revalidate new dates against stored
cadence. A previous quarantine for the same date persists when SEC is unavailable.

Use the existing `earnings-calendar import` workflow for manual verification.
A matching, confirmed calendar entry checked on or before the as-of date and
within 14 days releases the record on a new collection. Tentative, stale,
future-dated and different-date checks cannot release it. Display-only labels do
not mutate snapshots. Missing cadence remains explicitly unverified.

Regression tests: `tests/test_dashboard_resilience.py` (external services mocked).
Run `./.venv/Scripts/python.exe -m pytest` before committing.

## Verification and failure behavior

- Both quote/profile providers failing, including empty, malformed and scalar JSON,
  returns explicit unavailable data and a warning. Responses and endpoint schemas
  are validated before replacing cache files. Prior cache bytes remain intact;
  stale values are not relabeled current. A cache write failure is nonfatal.
- A refresh with no usable quotes or chains is not saved, so a later retry can
  recover. Partial refreshes retain explicit missing values. Full collection still
  requires every benchmark and at least 90% S&P price coverage; failure leaves the
  prior immutable snapshot intact.
- Missing/unrecognized sector tags count in the denominator and retain their scores.
  Only the eleven GICS names and registered aliases are penalized. The concentration
  warning reports missing coverage, including when every label is missing.
- Aware ISO timestamps convert to New York dates before the inclusive 21-day check.
  Date-only and naive timestamps already denote New York dates. Invalid historical
  rows are skipped individually and future filings excluded. Missing cadence stays
  unverified, rather than inventing an estimate.
- A future quarantine survives a failed calendar or an omitted ticker. Refreshes
  carry forward the latest stored daily validation. Only relevant tickers enter the
  daily validation payload; a 5,001-symbol calendar is covered by a storage-limit test.
- Malformed FRED metadata and option-chain layouts produce provider errors. Invalid
  OCC calendar dates are rejected as contracts. 13F remains a neutral unavailable
  metric on bulk/per-company errors; it cannot fabricate ownership or change scores.

Additional fault-injection tests are in `tests/test_dashboard_resilience_audit.py`.
Services are mocked: passing tests establish local failure behavior, not live API
availability or plan entitlements. Watch the published dataset states, request counts,
freshness and coverage after the next authorized collection. The full run still
caches histories and SEC submissions in memory and can reach its configured request
caps on a broad universe; no production memory benchmark was performed in this audit.
