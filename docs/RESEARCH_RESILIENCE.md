# Provider recovery, sector balance and earnings validation

Registered as methodology **2026-10-19.1**, these changes apply to new collections.
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
