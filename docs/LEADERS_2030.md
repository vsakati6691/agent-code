# Leaders 2030

Registered as additive methodology `2026-10-16.1`; freeze date `2026-10-16`.
Zero weekly snapshots existed under `2026-10-15.1` at registration. Evidence
counts still group by exact version. Existing lists, scoring, gates, scenario
math and tracking rules are unchanged.

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

The existing exact-date company formula now resides in `scenarios.py`, with the
original public functions re-exported from `watchlist.py`. For each case, cap is
the conditional 2030 price times that case's projected shares:

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
assumptions. Display the union of current top 50, conditional top 50 and all
curated challengers. Rank change is current rank minus conditional rank.
Unavailable scenarios retain their current rank and visible reason.

Partial coverage is prominent: these are ranks among available stored records,
and missing members could change every rank or movement. The page does not claim
full-index top-50 membership when coverage is partial. Missing members are grouped
by specific reason in an expandable, server-rendered coverage section and recorded
in the derived JSON. If no company scenario is computable, one sentence at the top
explains that future weekly collection must retain the missing inputs. No fictitious
50-row list is generated. The core table and linked evidence pages work without JS;
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
