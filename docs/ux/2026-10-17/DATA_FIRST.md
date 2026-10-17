# Data-first dashboard — Task 3

All 14 tabs and company pages now use a compact freshness line and native
disclosures. Tables, recorded values and charts lead the research pages.
Warnings about failed updates and stale sessions remain server-rendered.
Audit holds full collection errors, budgets and methodology version details.

The new Leaders range marks reuse the existing Watchlist colors and show
bear/base/bull market caps against the current cap, with a separate scale per
row. No scores, valuation inputs, ranks or calculator arithmetic changed.

## Before and after

Same CI fixture, viewport sizes and data selectors as Task 0: 1440 × 900 desktop and
390 × 844 mobile. The browser can return cached text rectangles inside closed
native disclosures. The visibility check now explicitly excludes those descendants,
and both the unchanged baseline build and new build were remeasured. These corrected
counts supersede the original Task 0 counts; HTML bytes are unaffected.
Words exclude navigation and collapsed disclosures; points
count visible numeric text in the baseline's data selectors. They are useful
layout comparisons, not counts of unique economic observations. Compare has
no default selection; this CI fixture has no daily Small Bets explorer, so
their first-data metrics are N/A. Task 4 exercises populated states too.

| Page | Bytes before → after | Words D before → after | Words M before → after | Points D before → after | Points M before → after |
|---|---:|---:|---:|---:|---:|
| index | 29,123 → 28,978 | 82 → 23 | 82 → 23 | 4 → 4 | 2 → 4 |
| growth | 88,809 → 91,312 | 204 → 61 | 204 → 61 | 0 → 50 | 0 → 9 |
| multibaggers | 33,448 → 35,159 | 194 → 23 | 194 → 23 | 1 → 34 | 0 → 25 |
| ai | 56,980 → 59,304 | 119 → 55 | 119 → 55 | 28 → 56 | 0 → 6 |
| options | 128,858 → 130,004 | 335 → 61 | 335 → 71 | 0 → 72 | 0 → 21 |
| bets | 8,164 → 10,575 | N/A → N/A | N/A → N/A | 0 → 0 | 0 → 0 |
| watchlist | 40,032 → 42,279 | 55 → 23 | 55 → 23 | 28 → 43 | 4 → 9 |
| leaders | 37,278 → 52,717 | 66 → 33 | 66 → 33 | 37 → 78 | 5 → 15 |
| goal | 21,492 → 31,440 | 118 → 32 | 118 → 32 | 2 → 37 | 0 → 22 |
| evidence | 11,608 → 13,763 | 119 → 47 | 119 → 47 | 20 → 23 | 3 → 20 |
| compare | 10,402 → 12,610 | N/A → N/A | N/A → N/A | 0 → 0 | 0 → 0 |
| history | 16,033 → 18,136 | 118 → 37 | 118 → 37 | 6 → 7 | 6 → 6 |
| methodology | 57,313 → 60,711 | 272 → 9 | 272 → 9 | 25 → 33 | 0 → 19 |
| audit | 19,271 → 22,688 | 72 → 23 | 72 → 23 | 15 → 20 | 3 → 4 |
| company | 67,858 → 69,240 | 68 → 45 | 68 → 45 | 3 → 3 | 2 → 2 |

The fixture and public build stay below 150,000 bytes per HTML page. Both
themes have zero browser errors, failed requests and horizontal page overflow
in the 60-view capture pass. [Raw metrics](data-first/metrics.json).

## Text inventory

Every shortened explanation retains its underlying information in the
destinations below. Native disclosures work without JavaScript; Audit links
open expanded run details. Duplicated headings and marketing copy carry no
unique methodology information.

| Location / original block | New location or treatment |
|---|---|
| Every page: full freshness paragraph, completed-session convention, build time, October 16 correction | Freshness **Details**; one-line date/age/delayed label stays visible |
| Every page: full failed-run message, partial snapshot problem list | **Audit → Latest run**; failed/partial warning and direct link stay visible |
| Every page: long footer research/probability/source disclosure and renderer version | One short footer summary with full disclosure; versions in Audit and Methodology |
| Daily refresh: collected timestamp, weekly-vs-daily explanation, split/dividend limitations | Timestamp tooltip and **Audit → Daily refresh details** |
| Daily refresh: dataset errors and provider request/budget/cache counts | Expanded **Audit → Daily refresh details**, linked from each daily status line |
| Overview: market-scanning tagline, repeated hero links and snapshot aside | Short Overview heading/sentence; navigation and research-path links retained |
| Overview: six empty macro cards plus repeated six reasons | One **Macro data not collected this week** disclosure with every reason and CSV |
| Overview: all-missing benchmark-price cards | **Benchmark prices unavailable** disclosure; dated values remain cards when available |
| Overview: verbose options status/setup paragraphs | **Audit → Options collection**; compact status/link or one unavailable disclosure |
| Growth: duplicate hero/eyebrow and scanner explanation | Short heading/sentence; **How to read scores and returns** below table |
| Growth: always-visible list/sector/evidence/input/pin and research-field controls | **Filters and research fields**; search/reset remain visible |
| Growth: repeated missing daily-price and research-field reasons | Cell tooltips; dates/values preserved; company evidence links retained |
| Multibaggers: long introductory caveats and selection paragraph | **Selection rules and 5–10 year scenario limits**, with original criteria/CSV/count/shortfall |
| Multibaggers: thesis, growth evidence, debt/dilution, flags, invalidation | Per-card **Growth evidence, assumptions and risks**, after the scenario table |
| AI: repeated snapshot/score/scenario text | **Scoring and scenario limits** below the ranked tables |
| AI: eligibility, list composition and shortfall | Per-list **Eligibility and list composition** below its table |
| Options: universe, selection, eligibility, theta, quote, event, fee, delta and probability paragraphs | **Eligibility, pricing and probability limits** after the weekly tables |
| Options: version strings, rate assumption, chain errors and owner setup | **Audit → Options collection**, linked from compact status |
| Options: long horizon tab labels and repeated panel title | Short 3M/6M/1Y controls; complete windows in tooltips, list counts and accessible headings |
| Options: underlying list, calendar note, shortfall and exclusions | **Underlying coverage and controls**, **Why fewer qualified**, and existing exclusion disclosures |
| Daily options: repeated basis and risk paragraphs; unavailable chains | **Daily list basis**; errors in Audit; wholly absent sections collapse |
| Speculative contracts: introductory risk/selection/date/IV/exit paragraphs and calculator | **Speculative contract assumptions and limits** and **Hypothetical risk budget**, after values; wholly missing section collapses |
| Small bets: full premium warning, selection/cost/probability paragraphs | One short premium warning; **Premium, selection and probability limits** contains full text |
| Small bets: always-visible filters, budget and saved slip | **Filter contracts** and **Budget, sizing and local slip**; table leads; Use in calculator opens the disclosure |
| Small bets: missing explorer explanation | **Explorer data unavailable**; populated state also has a bounded 25-row no-JS preview and full public JSON link |
| Watchlist: scenario warning, concentration and methods prose | **Scenario limits**, **About this watchlist and its concentration**, **Valuation methods and assumptions** |
| Watchlist: per-cell missing reasons and ETF metadata | Tooltips and existing ticker row details; table cells use dashes |
| Watchlist / Leaders: always-visible selects | **Filter watchlist / Filter leaders**; search/reset stay visible |
| Leaders: date/dilution/evidence explanations | Existing per-row **Details** and coverage/rules disclosures retained from Tasks 2/2b |
| Plan: controls preceding price table | Price table first; target/contributions follow; allocation/stress controls in named native disclosures |
| Plan: inline missing reason and repeated long disclosure | Reason in cell tooltip and ticker assumptions; full research limitations in a disclosure |
| Plan: company/ETF scenario differences and all calculation assumptions | Existing named disclosures retained, including SMH and QQQ assumptions |
| Evidence: history/holdout caveat and acceptance text | **Evidence limits: the final test was not untouched** and **Pre-registered acceptance rules**; verdict remains visible |
| Compare: full currency/filing/price basis paragraph | **Comparison basis and limits** |
| History: version-count and estimated-date explanation | **Version counts and estimated collection dates** after the table |
| Methodology: version/hash/universe/market-cap preamble | **Registration and universe definitions** after the universe table |
| Audit: long pre-table integrity/coverage introduction | Dataset table first; full integrity/coverage/run information follows |
| Company: price chart and return table below narrative/missing cards | Immediately after price/cap/date cards |
| Company: empty decision groups, business excerpts, insider/institutional/short-interest/risk sections | Named empty-data disclosures; if all four external datasets are missing, one disclosure contains them all |
| Company: field definitions, dates, source conventions and long rationale | **Field definitions, dates and sources**; individual field notes/reasons in tooltips |
| Shared tables: repeated plain unavailable/n/a labels | Dash with original reason as title; numeric data attributes unchanged |
| Shared navigation / evidence without JavaScript | Added native **Browse tickers** links and direct company evidence links; static tabs and row evidence remain readable |

## Validation and scope

Full local CI: **995 tests passed**; Ruff lint/format and configured Mypy (12
modules) passed; determinism compared 299 files with zero differences; snapshot
verification and all 142 fixture pages passed links and budgets. All 159 public
pages also pass. The 31 CSV downloads are byte-identical to the Task 2b build
of the same immutable fixture snapshot.
Spec remains `2026-10-17.2` / `48a72cddda547a92`; no registered rule or safety
control is changed. Plan arithmetic, saved allocation mapping and sort/reset
checks pass. The latest stored public snapshot builds without integrity or
link errors. Task 4 adds the full interaction matrix and final test report.

The user authorized deployment. A code-only publish uses stored data and does
not rewrite snapshots. The October 16 weekly import was attempted separately
and failed on provider IJH OHLC validation; weekly data still ends October 15.
The dated daily refresh remains a separate context dataset.

## Screenshots

[All before screenshots and measurement notes](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/BASELINE.md).
Each row below links directly to both before and after images.

| Page | Before desktop | After desktop | Before mobile | After mobile |
|---|---|---|---|---|
| index | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/index-desktop.png) | [After](data-first/index-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/index-mobile.png) | [After](data-first/index-mobile.png) |
| growth | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/growth-desktop.png) | [After](data-first/growth-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/growth-mobile.png) | [After](data-first/growth-mobile.png) |
| multibaggers | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/multibaggers-desktop.png) | [After](data-first/multibaggers-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/multibaggers-mobile.png) | [After](data-first/multibaggers-mobile.png) |
| ai | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/ai-desktop.png) | [After](data-first/ai-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/ai-mobile.png) | [After](data-first/ai-mobile.png) |
| options | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/options-desktop.png) | [After](data-first/options-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/options-mobile.png) | [After](data-first/options-mobile.png) |
| bets | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/bets-desktop.png) | [After](data-first/bets-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/bets-mobile.png) | [After](data-first/bets-mobile.png) |
| watchlist | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/watchlist-desktop.png) | [After](data-first/watchlist-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/watchlist-mobile.png) | [After](data-first/watchlist-mobile.png) |
| leaders | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/leaders-desktop.png) | [After](data-first/leaders-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/leaders-mobile.png) | [After](data-first/leaders-mobile.png) |
| goal | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/goal-desktop.png) | [After](data-first/goal-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/goal-mobile.png) | [After](data-first/goal-mobile.png) |
| evidence | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/evidence-desktop.png) | [After](data-first/evidence-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/evidence-mobile.png) | [After](data-first/evidence-mobile.png) |
| compare | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/compare-desktop.png) | [After](data-first/compare-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/compare-mobile.png) | [After](data-first/compare-mobile.png) |
| history | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/history-desktop.png) | [After](data-first/history-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/history-mobile.png) | [After](data-first/history-mobile.png) |
| methodology | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/methodology-desktop.png) | [After](data-first/methodology-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/methodology-mobile.png) | [After](data-first/methodology-mobile.png) |
| audit | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/audit-desktop.png) | [After](data-first/audit-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/audit-mobile.png) | [After](data-first/audit-mobile.png) |
| company | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/company-desktop.png) | [After](data-first/company-desktop.png) | [Before](https://github.com/vsakati6691/agent-code/blob/ae39a92/docs/ux/2026-10-17/before/company-mobile.png) | [After](data-first/company-mobile.png) |
