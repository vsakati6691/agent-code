# Leaders 2030

Initially registered as additive methodology `2026-10-16.1`; freeze date `2026-10-16`.
Zero weekly snapshots existed under `2026-10-15.1` at registration. Evidence
counts still group by exact version. Existing lists, scoring, gates, Watchlist
scenario math and tracking rules are unchanged.

The top-20 rule was registered in `2026-10-17.1` (hash `7878076b25e6eecd`): **owner requested
a top-20 view; full S&P 500 coverage**. The former top-50 registration is retained
verbatim in the changelog and `LEADERS_RULE_2026_10_16`. Freeze date is unchanged.

The current version is **2026-10-17.2**, hash `48a72cddda547a92`, for the owner's
scenario sanity request. It changes only the Leaders valuation assumptions and
retains three-year CAGR and the already collected industry label prospectively.
No extra provider calls are needed for this addition.

## Scenario sanity assumptions

Base starts with stored three-year revenue CAGR (TTM versus TTM three years
earlier), or a dated matched fiscal-year three-year CAGR when the TTM metric is
missing. One-year growth is never substituted. Missing both makes the scenario
unavailable while retaining any dated current cap. Starting CAGR is bounded to
-30% through +60%. All inputs must have been available by the snapshot date.

Each subsequent year's growth closes 20% of the gap to the terminal rate; for
current caps **strictly above $500B**, it closes 40%. Base and bull fade toward
4%. Existing case multipliers/shifts apply, except bull cannot start below base.
Bear starts at the lower of its shifted rate, base, or -5%, then fades toward 0%.
For registered cyclical memory/storage/equipment names it starts at -20% or lower.
The names and narrow sector/industry matches are explicit in
`LEADERS_SCENARIO_RULES`; they reuse the AI-role taxonomy, with PSTG as P's older
alias. A broad Technology classification alone is insufficient. The source
industry is retained without making another request.

Bear equity is the lesser of its revenue/exit-multiple valuation and **90% of
today's cap**. This explicit downside stress constraint guarantees a bear cap
below current even when net cash or a low-multiple floor would otherwise
dominate. It is not a calibrated estimate. Each linked Details page and derived
JSON retain raw equity, the stress reduction, revenue growth path, fade,
terminal rate, exit multiple, net cash, dilution and exact horizon. These new
assumptions were chosen for the owner's requested stress behavior, not fitted
to backtests or holdout results.

Every 2030 cap has an adjacent **implied %/yr** column:
`(scenario cap / current cap) ** (1 / years to 2030-12-31) - 1`.
A zero cap gives -100%. Base above 25%/yr is labelled **aggressive assumption**.
This is market-cap CAGR, not per-share return; dilution changes the latter.
Curated assumptions without current caps have no implied CAGR or invented bear
case. CSV columns remain unchanged; derived JSON holds the additional fields.

Plan 2030 keeps its stored Watchlist price scenarios. Its one-click “Why company
and ETF scenarios differ (SMH, QQQ)” disclosure explains the original one-year
company growth anchor versus the revised Leaders model and the ETF exposure
return assumptions. It displays the stored ETF total return, fee, distribution
yield and resulting price return. ETF values are not aggregated from the selected
company scenarios; no holdings-weighted reconciliation is claimed.

## Weekly collection and request budget

The public 2026-10-15 snapshot has 503 members, 10 dated caps and no retained
full-universe input array. The current collector already attempts each member's
price during S&P screening, but skips SEC facts when price/liquidity gates fail.
The old snapshot's 493 missing rendered rows therefore do **not** establish
that a current run needs 493 additional price requests.

From this version, a completion phase after list screening attempts as-of history
and company facts for every member, reusing both successful and failed lookups.
It does not require a research score or tradability verdict. Missing CIKs use the
existing SEC ticker mapping when available, otherwise remain missing. Only the
existing short-history fallback is allowed; invalid/stale OHLCV remains rejected.
The same point-in-time SEC builder supplies diluted shares and every existing
scenario input. Retention itself remains a pure operation. A development
`--limit` still limits collection and cannot imply complete coverage.

For 503 members, the normal incremental upper bound is **503 SEC company-facts
fetches**, fewer when facts were already fetched or CIKs are shared. Normal
history requests add zero because S&P screening already attempted them; the
short-history fallback reuses the HTTP response cache. Members skipped for a
missing CIK can additionally need a history fetch (and the existing quote lookup
if history is stale). Failures are memoized; there is no new retry loop.

Unchanged limits: SEC 6,000 attempts total, core 4,000; Cboe 7,000. The 503-facts
increment alone uses 12.6% of the core cap (up to 1,509 attempts at three attempts
per fetch). It shares remaining capacity with the rest of the run; it is not a
reservation or a guarantee of full data. SEC pacing stays 0.15 seconds, with the
existing `SEC_USER_AGENT` header supplied through `HttpClient`. No extra Alpha
Vantage calls or new paid data source is used. Exhausted budgets stay exhausted.

Planning runtime: zero when all inputs are cached; at 0.5–2 seconds of fetch and
parse time per missing facts file, 503 files add roughly **4–17 minutes**. Pacing
alone has a 75-second floor for uncached requests; retries, transfer sizes and
provider outages can take longer. This is an estimate, not a production timing.
The workflow's existing 240-minute timeout is unchanged. Actual additional
attempts are recorded by provider in `leaders_2030_collection.additional_requests`
and total attempts remain in `usage`; cache hits consume no request budget.

New data arrives only in the next weekly snapshot. After reviewing/merging the
new registration, the owner can open **Actions → research-dashboard → Run
workflow**, select **main**, leave the as-of date blank for the latest completed
session, and run `research-dashboard.yml` with `dry_run` false for publication.
Use a new, not-yet-recorded session; an existing snapshot is never overwritten.
The existing publication variable and SEC identification secret must already be
configured. `dry_run` true creates a scratch artifact only. No production run
was dispatched to validate this change.

## Data and shares

The build reads verified stored snapshots only. It uses prospectively retained
`leaders_2030_inputs`, or company details already present in older snapshots.
It never fetches a provider or changes stored snapshots. The separately labelled
`data/<date>_leaders_2030.json` is a derived comparison under the new methodology,
not a historical selection or a forward-tracking observation.

Current cap is the stored as-of close times the newest positive, dated quarterly
diluted weighted-average share count available by that snapshot date. The fiscal
period end is `shares_date`; `market_cap_date` and `price_date` identify the close.
Missing or stale statements, undated shares and missing dilution stay unavailable.
This differs from the existing growth lists' cover-page-share basis; those lists
are not changed. Each index ticker is a separate size proxy. Issuer shares are
not allocated across share classes, so those proxies are not additive company values.

The original Watchlist exact-date company formula resides in `scenarios.py`, with
public functions re-exported from `watchlist.py`. Leaders now uses the separate
registered model in `leaders_scenarios.py`. For each case, cap is the conditional
2030 price times that case's projected shares:

`shares_2030 = starting diluted shares × (1 + trailing dilution + scenario shift)^years`

The starting shares, their basis/date, all three projected share counts, prices
and caps are exported in CSV. Net cash, growth and EV/Sales inputs retain their
registered definitions. Missing inputs never become zero to unlock a scenario.
Observed fiscal-year revenue/EPS growth, margins and issuer excerpts supply dated
growth evidence. Absent business excerpts never trigger new SEC requests.

## Ranking and coverage

Ranks sort by cap descending, then ticker and company name ascending (null
tickers first), assigning consecutive ranks. Current ranks cover available S&P
500 records. Conditional ranks cover all computable members plus eligible curated
assumptions. Display the union of current top 20, conditional top 20 and all
curated challengers. Rank change is current rank minus conditional rank.
Unavailable scenarios retain their current rank and visible reason.

Partial coverage is prominent: these are ranks among available stored records,
and missing members could change every rank or movement. The page does not claim
full-index top-20 membership when coverage is partial. Missing members are grouped
by specific reason in an expandable, server-rendered coverage section and recorded
in the derived JSON. If no company scenario is computable, one sentence at the top
explains that future weekly collection must retain the missing inputs. No fictitious
20-row list is generated. Known current caps remain visible even when no scenarios
can be computed. The core table and linked evidence pages work without JS;
sorting, filters and device-local pins enhance them. Detailed evidence has separate
HTML pages so the main comparison remains under 150,000 UTF-8 bytes.

## Challenger configuration

`config/leaders_2030_challengers.json` starts as `{"challengers": []}`. A build
validates it even if there is no snapshot. The only top-level key is `challengers`.
Each entry requires exactly these fields; unknown fields, duplicate names/tickers,
missing sources, invalid dates, non-finite/non-positive caps and invalid listing
status fail the build. The schema is `schema.LEADERS_CHALLENGER`.

| Field | Required value |
|---|---|
| `name` | Nonempty company name |
| `ticker` | Uppercase listed ticker, or null; private companies require null |
| `listing_status` | `listed_non_index`, `private`, or `pre_ipo`; listed names require a ticker |
| `assumed_2030_market_cap_usd` | Positive finite USD cap, supplied by the owner |
| `assumption_source` | Nonempty source URL or identified document |
| `assumption_date` | ISO date (`YYYY-MM-DD`) |
| `growth_drivers` | List of strings beginning with an ISO date, no later than the assumption date |
| `notes` | Text, optionally empty |

Worked example for schema illustration only: **Example Robotics is fictional**;
the $100 billion cap below is arbitrary, not an assumption registered on the site.
The identified document in this example is this explanatory section itself.

```json
{
  "name": "Example Robotics (fictional)",
  "ticker": null,
  "listing_status": "private",
  "assumed_2030_market_cap_usd": 100000000000,
  "assumption_source": "docs/LEADERS_2030.md — fictional schema example",
  "assumption_date": "2026-10-16",
  "growth_drivers": ["2026-10-16: Illustrative owner assumption; no observed company evidence"],
  "notes": "Documentation example only; do not register as a real challenger."
}
```

A valid real entry dated no later than the snapshot participates in the combined
base-cap ranking with a **curated assumption** label and evidence grade **none**.
It never receives computed prices, bear/bull caps, or projected shares. An entry
dated after the snapshot is omitted with an explanation; an index constituent
cannot also be a curated challenger. With zero entries the page says
“No curated challengers registered”. Updating this config affects the separate
derived comparison, not past immutable snapshots or tracked selections.

2030 index membership is unknown, and probability is not established without
documented out-of-sample calibration. The standard research disclaimer remains.

## Watchlist upside

The sortable upside column exposes stored `change` and `annualized` results,
without changing scenario prices. It shows a signed base upside, annualized rate,
and bear-to-bull range with a base marker and a zero tick at the latest price.
Each bar has its own scale. Missing values sort last in both directions; missing
scenarios show a dash and their existing reason. Existing pins and filters remain.

New CSV fields `upside_bear_pct`, `upside_base_pct`, `upside_bull_pct` and
`cagr_base_pct` use **percentage points** (24 means 24%). The older `*_change`
and `*_annualized` fields keep their decimal units. Existing snapshots can supply
these display/export fields directly from their stored scenarios.
