# Dated public datasets · 2026-10-16.2

Registration reason: **additive datasets; zero weekly snapshots under 2026-10-16.1 at registration**.
These optional fields enrich already-selected names. No score, weight, gate,
list, equity scenario or continuity rule changes. Old snapshots are never
backfilled; absent fields render unavailable with a reason.

| Dataset | Headless endpoint | Weekly attempt cap |
|---|---|---|
| Insiders | `https://data.sec.gov/submissions/CIK##########.json`, historical submissions pages, ownership XML under `https://www.sec.gov/Archives/edgar/data/` | 1,800 |
| Institutional holders / CUSIP mapping | [13F bulk index](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets), [FTD index](https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data) | 24 combined |
| Risk quotations | `https://efts.sec.gov/LATEST/search-index`, then the identified 10-K/10-Q | 120 total; 2 per company |
| FRED observations / metadata | `https://api.stlouisfed.org/fred/series/observations`, `https://api.stlouisfed.org/fred/series` | 42 (14 normal calls) |
| FINRA short interest | [File index](https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files), latest two eligible files | 9 (3 normal calls) |

Retries count against every cap. All SEC hosts share at least 0.15 seconds
between attempts and `SEC_USER_AGENT`; the total ceiling is 6,000, including
a separate 4,000 core allowance. FRED starts at 0.5 seconds and FINRA at 1 second.
Usage output and audit display both provider and SEC dataset counts/caps.
Current SEC bulk and FINRA indexes are used only for the latest completed
session at collection start. Historical release availability cannot be inferred
from settlement dates, so older requested sessions do not collect these files.

## Form 4

Scope: current growth, AI, multibagger and operating-company watchlist names.
Other symbols say **not in a research list**. Display label: **P/S purchases/sales
(open market or private)**. The exact `classification_basis` is **Form 4 codes
P/S (open market or private); A, M, F, G and derivative rows excluded**.

Each filing retains accession, filing date, URL, owner CIKs, the 10b5-1 checkbox
(true/false/null) and parsed transactions. Transactions retain code, derivative
status, date, shares and price; raw XML is not stored. Only P/S nonderivative
rows enter net shares/dollars and distinct buyer/seller counts. Windows are 90
calendar days including as-of and trailing 12 calendar months. Filing and
transaction dates must not exceed as-of. Quantities are as reported, not
split-adjusted trading volumes. Complete retrieved windows with no P/S rows
can report zero; incomplete retrieval cannot. Missing transaction prices leave
dollars unavailable. Unreconciled 4/A amendments make complete totals unavailable.

At the cap, remaining names say **deferred to next run** and the shortfall
count is reported. Previously deferred names run first; prior parsed filings
are reused by accession. No selling threshold is registered, so no new flag
is introduced.

## 13F and CUSIP mapping

Modern archive names refer to filing windows, not report quarters. Verified
links on 2026-10-16:

- `https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip` (June report quarter).
- `https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip` (March report quarter).
- `https://www.sec.gov/files/data/fails-deliver-data/cnsfails202609b.zip` (dated FTD CUSIP mapping).

Join SUBMISSION, COVERPAGE and INFOTABLE by accession. Count only long SH rows
without puts/calls. Deduplicate managers by CIK; restatements replace prior
reports, new-holdings amendments add to an identified base, and unresolved
amendments make coverage partial. Each CUSIP aggregate contains holder count,
total reported shares and the top ten manager names/share counts. Managers'
holdings can overlap: this is not total institutional ownership. QoQ changes
need two complete quarter aggregates. Stale means the next report quarter end
plus 45 calendar days has passed without a newer dataset.

FTD mappings carry source URL, file date and observed settlement date. A symbol
absent from the file says **no CUSIP mapping**. Conflicting mappings are
unavailable. An absent CUSIP does not establish zero institutional ownership.

`source_aggregates/13f/<quarter>/` and `source_aggregates/ftd/<file-date>/`
contain derived JSON and immutable manifests with archive and aggregate
SHA-256 hashes. Download each quarter once, then verify/reuse it. No raw bulk
tables enter the data branch or dry-run artifacts; raw responses remain in
the disposable HTTP cache. `verify` checks these hashes with snapshot hashes.

## Risk quotations

Reuse existing `decision_sources` excerpts. A missing excerpt or one older
than the latest annual filing can use EFTS plus one filing fetch. Retries use
the same two-attempt allowance. A cap preserves the prior quotation with
**excerpt refresh deferred**. Store form, date, accession, URL and exact text;
offsets are zero-based and end-exclusive in existing `FilingText` output after
whitespace collapse. Normalized-text hash and parser version make ranges
reproducible. Legacy excerpts without offsets retain an explicit reason.
Quotations are issuer statements, never paraphrases or independent analysis.

## FRED

DGS1MO, DGS3MO, DGS2, DGS10, FEDFUNDS, CPIAUCSL and UNRATE store latest value,
observation date, series `last_updated`, requested vintage date and source link.
Requests select the as-of vintage; future observations/revisions are excluded.
CPI YoY is latest monthly CPI / same month a year earlier minus one, retaining
both dates and values. Missing/nonpositive prior CPI leaves YoY unavailable.
Overview displays six macro values; audit and CSV include all seven series.

New weekly Black-Scholes sensitivities pass DGS1MO / 100 to the existing rate
argument after contract selection. Missing DGS1MO leaves the model estimate
unavailable. Formula, rank and stored legacy estimates stay unchanged. Daily
collection retains its registered budgets and does not fetch FRED. Keys stay
in ignored `.env` or Actions secrets and never appear in published URLs, logs or artifacts.

## FINRA

Verified complete file on 2026-10-16 (22,581 rows):
`https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260930.csv`.
The pipe-delimited, quoted 14-column layout is also recorded in `providers.py`:

`accountingYearMonthNumber`, `symbolCode`, `issueName`,
`issuerServicesGroupExchangeCode`, `marketClassCode`,
`currentShortPositionQuantity`, `previousShortPositionQuantity`, `stockSplitFlag`,
`averageDailyVolumeQuantity`, `daysToCoverQuantity`, `revisionFlag`,
`changePercent`, `changePreviousNumber`, `settlementDate`.

A changed header or invalid row rejects the entire dataset as **provider
error**, with the parse failure. Store short shares, published prior quantity
and their difference with settlement dates and source URLs. The published
prior quantity can reflect FINRA revisions/split adjustment. Label exactly
**Short interest as a percentage of XBRL diluted shares outstanding**: divide
short shares by the latest stored positive quarterly diluted weighted-average
share count and show its period-end date. This is not float or class-specific
shares outstanding. Days to cover uses only average daily share volume already
stored for that company; FINRA's volume/DTC columns do not substitute for it.
No short-interest flag threshold is registered, so none is added.

## Outputs and dry run

Company/band/watchlist CSVs include states/reasons, dates, values and sources.
`<as-of>_external.csv` unifies research companies; `<as-of>_macro.csv` contains
all seven series. Ratios are decimal fractions unless explicitly labelled
percentage points. `data/schema.json` describes optional `external`, `macro`,
`external_datasets` and option `rate_input` fields. Compare adds dated holder
count; growth tables add sortable short interest / diluted shares.

Manually dispatch `research-dashboard` on the feature branch with
`dry_run=true` (default false). Tests precede the separate read-only job. It
reads existing public tradability JSON through the GitHub API, collects to
scratch storage, verifies/builds/checks, and uploads data/site/runtime artifacts
for 14 days. It never checks out or pushes `research-data`. Production update,
publish and deploy steps remain but are excluded by condition. No schedule
can activate dry run. Timeout remains 240 minutes. Supply `SEC_USER_AGENT` and
`FRED_API_KEY` as repository secrets; missing optional inputs have reasons.

Baseline successful collection: Actions run 38752822925 on 2026-10-15,
2h 14m 24s collection / 2h 14m 59s update job. Report live validation counts and
runtime from the new run; fixture tests do not establish runner accessibility.
