# Dashboard browser validation — Task 4

All 14 tabs and a company page pass on the synthetic interaction fixture and
the latest retained public snapshot, at 1440 × 900 and 390 × 844 in light and
dark themes. Each dataset has 60 JavaScript views and 60 no-JavaScript views.
The standalone AI browser script also passes on each dataset.

The only production change in this task opens the Treasury-rate disclosure
on Audit by default. Following the Options collection-details link now exposes
that explanation in one click. No information was removed, and no calculation,
ranking, collection, CSV schema or registered rule changed. SPEC_VERSION remains
2026-10-17.2, hash `48a72cddda547a92`.

## Validation

- Full local CI: 996 Python tests; Ruff lint and formatting; the configured
  12-module Mypy check; 299 deterministic fixture files with zero differences;
  snapshot integrity; all 142 fixture and 159 public HTML pages have zero broken
  links and satisfy the 150,000-byte budget. See command list below.
- Browser checks: every nav destination returns 200, all 14 tabs are followed
  across the matrix, and the active tab has its underline and `aria-current`.
  Every page's ticker palette opens a company page. Every CSV is non-empty.
- Every table search, filter option, visible sortable column, pin and reset is
  exercised. Sorting checks actual values, missing values last and reset order.
  Pinned-row filters are also checked after pinning a row. Every native
  disclosure and loaded row-evidence disclosure opens; expanded disclosures
  retain internal scrolling without horizontal page overflow.
- Initial-screen checks find no text overlap, page overflow or AA text-contrast
  failures in either theme. The test inspects actual visible text rectangles;
  descendants of closed disclosures are excluded. These automated text checks
  do not constitute a complete accessibility certification.
- Keyboard palette navigation, focus restoration, nested-page paths, saved
  theme, reduced motion, print, sticky table axes, empty searches, and retry
  after deliberately injected HTTP 503/invalid JSON are retained regressions.
  Injected errors are separate from the zero-error normal-navigation matrix.
- The populated fixture covers Small Bets filters/sizing/local-only slip,
  speculative budgets, daily options, partial-refresh reasons and 20 Leaders
  rows. The public build honestly shows its 10 available Leaders rows.
- All 31 plain-fixture CSV downloads are byte-identical to Task 3.
- Fixed Plan inputs: $10,000 initial, $20,000 goal, $100 monthly over four
  years require 9.28%/yr; without contributions, 18.92%/yr. A 100% Cash weight
  gives $14,800 for all three cases, persists on reload and resets correctly.
  A separate Python test locks literal 50/50 equity/Cash and stressed results.

## Page matrix

Each Pass below covers both datasets. Desktop/mobile each include both themes;
light/dark each include both sizes. Console errors exclude deliberate fault
injection in the separate retry regression. Broken links include every local
HTML link from the full site checker, plus browser nav/CSV requests.

| Page | Desktop | Mobile | Light | Dark | Console errors | Broken links | Issues found | Fixed? |
|---|---|---|---|---|---:|---:|---|---|
| index | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| growth | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| multibaggers | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| ai | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| options | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| bets | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| watchlist | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| leaders | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| goal | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| evidence | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| compare | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| history | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| methodology | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |
| audit | Pass | Pass | Pass | Pass | 0 | 0 | Treasury-rate detail needed a second click | Yes; expanded on Audit |
| company | Pass | Pass | Pass | Pass | 0 | 0 | None in final pass | — |

Raw browser results: [fixture](browser/fixture/browser-results.json), [public](browser/public/browser-results.json).

Fixture matrix totals (includes all four size/theme combinations): 840 navLinks, 68 csv, 424 details, 112 tables, 32 searches, 196 filterOptions, 1,500 sorts, 200 pins, 666 resets.

Public matrix totals (includes all four size/theme combinations): 840 navLinks, 68 csv, 520 details, 112 tables, 32 searches, 264 filterOptions, 1,500 sorts, 268 pins, 734 resets.

## Before and after measurements

These use the same plain CI fixture as Task 0, independently of the populated
browser fixture above. Both baseline and final counts use the corrected
closed-disclosure visibility method documented in [Task 3](DATA_FIRST.md).
Compare has no default selection and the plain CI fixture has no daily Small
Bets explorer, so those first-data metrics are N/A. Points count visible numeric
text in the documented selectors, not unique economic observations.

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
| audit | 19,271 → 22,693 | 72 → 23 | 72 → 23 | 15 → 20 | 3 → 4 |
| company | 67,858 → 69,240 | 68 → 45 | 68 → 45 | 3 → 3 | 2 → 2 |

## Screenshots

Before/after links use matching plain-fixture data. The interaction-fixture and
public links additionally cover light/dark screens with populated daily data.

| Page | Before desktop / mobile | After desktop / mobile | Interaction fixture | Latest public |
|---|---|---|---|---|
| index | [desktop](before/index-desktop.png) / [mobile](before/index-mobile.png) | [desktop](browser/metrics/index-desktop.png) / [mobile](browser/metrics/index-mobile.png) | [1440 light](browser/fixture/index-1440-light.png) · [1440 dark](browser/fixture/index-1440-dark.png) · [390 light](browser/fixture/index-390-light.png) · [390 dark](browser/fixture/index-390-dark.png) | [1440 light](browser/public/index-1440-light.png) · [1440 dark](browser/public/index-1440-dark.png) · [390 light](browser/public/index-390-light.png) · [390 dark](browser/public/index-390-dark.png) |
| growth | [desktop](before/growth-desktop.png) / [mobile](before/growth-mobile.png) | [desktop](browser/metrics/growth-desktop.png) / [mobile](browser/metrics/growth-mobile.png) | [1440 light](browser/fixture/growth-1440-light.png) · [1440 dark](browser/fixture/growth-1440-dark.png) · [390 light](browser/fixture/growth-390-light.png) · [390 dark](browser/fixture/growth-390-dark.png) | [1440 light](browser/public/growth-1440-light.png) · [1440 dark](browser/public/growth-1440-dark.png) · [390 light](browser/public/growth-390-light.png) · [390 dark](browser/public/growth-390-dark.png) |
| multibaggers | [desktop](before/multibaggers-desktop.png) / [mobile](before/multibaggers-mobile.png) | [desktop](browser/metrics/multibaggers-desktop.png) / [mobile](browser/metrics/multibaggers-mobile.png) | [1440 light](browser/fixture/multibaggers-1440-light.png) · [1440 dark](browser/fixture/multibaggers-1440-dark.png) · [390 light](browser/fixture/multibaggers-390-light.png) · [390 dark](browser/fixture/multibaggers-390-dark.png) | [1440 light](browser/public/multibaggers-1440-light.png) · [1440 dark](browser/public/multibaggers-1440-dark.png) · [390 light](browser/public/multibaggers-390-light.png) · [390 dark](browser/public/multibaggers-390-dark.png) |
| ai | [desktop](before/ai-desktop.png) / [mobile](before/ai-mobile.png) | [desktop](browser/metrics/ai-desktop.png) / [mobile](browser/metrics/ai-mobile.png) | [1440 light](browser/fixture/ai-1440-light.png) · [1440 dark](browser/fixture/ai-1440-dark.png) · [390 light](browser/fixture/ai-390-light.png) · [390 dark](browser/fixture/ai-390-dark.png) | [1440 light](browser/public/ai-1440-light.png) · [1440 dark](browser/public/ai-1440-dark.png) · [390 light](browser/public/ai-390-light.png) · [390 dark](browser/public/ai-390-dark.png) |
| options | [desktop](before/options-desktop.png) / [mobile](before/options-mobile.png) | [desktop](browser/metrics/options-desktop.png) / [mobile](browser/metrics/options-mobile.png) | [1440 light](browser/fixture/options-1440-light.png) · [1440 dark](browser/fixture/options-1440-dark.png) · [390 light](browser/fixture/options-390-light.png) · [390 dark](browser/fixture/options-390-dark.png) | [1440 light](browser/public/options-1440-light.png) · [1440 dark](browser/public/options-1440-dark.png) · [390 light](browser/public/options-390-light.png) · [390 dark](browser/public/options-390-dark.png) |
| bets | [desktop](before/bets-desktop.png) / [mobile](before/bets-mobile.png) | [desktop](browser/metrics/bets-desktop.png) / [mobile](browser/metrics/bets-mobile.png) | [1440 light](browser/fixture/bets-1440-light.png) · [1440 dark](browser/fixture/bets-1440-dark.png) · [390 light](browser/fixture/bets-390-light.png) · [390 dark](browser/fixture/bets-390-dark.png) | [1440 light](browser/public/bets-1440-light.png) · [1440 dark](browser/public/bets-1440-dark.png) · [390 light](browser/public/bets-390-light.png) · [390 dark](browser/public/bets-390-dark.png) |
| watchlist | [desktop](before/watchlist-desktop.png) / [mobile](before/watchlist-mobile.png) | [desktop](browser/metrics/watchlist-desktop.png) / [mobile](browser/metrics/watchlist-mobile.png) | [1440 light](browser/fixture/watchlist-1440-light.png) · [1440 dark](browser/fixture/watchlist-1440-dark.png) · [390 light](browser/fixture/watchlist-390-light.png) · [390 dark](browser/fixture/watchlist-390-dark.png) | [1440 light](browser/public/watchlist-1440-light.png) · [1440 dark](browser/public/watchlist-1440-dark.png) · [390 light](browser/public/watchlist-390-light.png) · [390 dark](browser/public/watchlist-390-dark.png) |
| leaders | [desktop](before/leaders-desktop.png) / [mobile](before/leaders-mobile.png) | [desktop](browser/metrics/leaders-desktop.png) / [mobile](browser/metrics/leaders-mobile.png) | [1440 light](browser/fixture/leaders-1440-light.png) · [1440 dark](browser/fixture/leaders-1440-dark.png) · [390 light](browser/fixture/leaders-390-light.png) · [390 dark](browser/fixture/leaders-390-dark.png) | [1440 light](browser/public/leaders-1440-light.png) · [1440 dark](browser/public/leaders-1440-dark.png) · [390 light](browser/public/leaders-390-light.png) · [390 dark](browser/public/leaders-390-dark.png) |
| goal | [desktop](before/goal-desktop.png) / [mobile](before/goal-mobile.png) | [desktop](browser/metrics/goal-desktop.png) / [mobile](browser/metrics/goal-mobile.png) | [1440 light](browser/fixture/goal-1440-light.png) · [1440 dark](browser/fixture/goal-1440-dark.png) · [390 light](browser/fixture/goal-390-light.png) · [390 dark](browser/fixture/goal-390-dark.png) | [1440 light](browser/public/goal-1440-light.png) · [1440 dark](browser/public/goal-1440-dark.png) · [390 light](browser/public/goal-390-light.png) · [390 dark](browser/public/goal-390-dark.png) |
| evidence | [desktop](before/evidence-desktop.png) / [mobile](before/evidence-mobile.png) | [desktop](browser/metrics/evidence-desktop.png) / [mobile](browser/metrics/evidence-mobile.png) | [1440 light](browser/fixture/evidence-1440-light.png) · [1440 dark](browser/fixture/evidence-1440-dark.png) · [390 light](browser/fixture/evidence-390-light.png) · [390 dark](browser/fixture/evidence-390-dark.png) | [1440 light](browser/public/evidence-1440-light.png) · [1440 dark](browser/public/evidence-1440-dark.png) · [390 light](browser/public/evidence-390-light.png) · [390 dark](browser/public/evidence-390-dark.png) |
| compare | [desktop](before/compare-desktop.png) / [mobile](before/compare-mobile.png) | [desktop](browser/metrics/compare-desktop.png) / [mobile](browser/metrics/compare-mobile.png) | [1440 light](browser/fixture/compare-1440-light.png) · [1440 dark](browser/fixture/compare-1440-dark.png) · [390 light](browser/fixture/compare-390-light.png) · [390 dark](browser/fixture/compare-390-dark.png) | [1440 light](browser/public/compare-1440-light.png) · [1440 dark](browser/public/compare-1440-dark.png) · [390 light](browser/public/compare-390-light.png) · [390 dark](browser/public/compare-390-dark.png) |
| history | [desktop](before/history-desktop.png) / [mobile](before/history-mobile.png) | [desktop](browser/metrics/history-desktop.png) / [mobile](browser/metrics/history-mobile.png) | [1440 light](browser/fixture/history-1440-light.png) · [1440 dark](browser/fixture/history-1440-dark.png) · [390 light](browser/fixture/history-390-light.png) · [390 dark](browser/fixture/history-390-dark.png) | [1440 light](browser/public/history-1440-light.png) · [1440 dark](browser/public/history-1440-dark.png) · [390 light](browser/public/history-390-light.png) · [390 dark](browser/public/history-390-dark.png) |
| methodology | [desktop](before/methodology-desktop.png) / [mobile](before/methodology-mobile.png) | [desktop](browser/metrics/methodology-desktop.png) / [mobile](browser/metrics/methodology-mobile.png) | [1440 light](browser/fixture/methodology-1440-light.png) · [1440 dark](browser/fixture/methodology-1440-dark.png) · [390 light](browser/fixture/methodology-390-light.png) · [390 dark](browser/fixture/methodology-390-dark.png) | [1440 light](browser/public/methodology-1440-light.png) · [1440 dark](browser/public/methodology-1440-dark.png) · [390 light](browser/public/methodology-390-light.png) · [390 dark](browser/public/methodology-390-dark.png) |
| audit | [desktop](before/audit-desktop.png) / [mobile](before/audit-mobile.png) | [desktop](browser/metrics/audit-desktop.png) / [mobile](browser/metrics/audit-mobile.png) | [1440 light](browser/fixture/audit-1440-light.png) · [1440 dark](browser/fixture/audit-1440-dark.png) · [390 light](browser/fixture/audit-390-light.png) · [390 dark](browser/fixture/audit-390-dark.png) | [1440 light](browser/public/audit-1440-light.png) · [1440 dark](browser/public/audit-1440-dark.png) · [390 light](browser/public/audit-390-light.png) · [390 dark](browser/public/audit-390-dark.png) |
| company | [desktop](before/company-desktop.png) / [mobile](before/company-mobile.png) | [desktop](browser/metrics/company-desktop.png) / [mobile](browser/metrics/company-mobile.png) | [1440 light](browser/fixture/company-1440-light.png) · [1440 dark](browser/fixture/company-1440-dark.png) · [390 light](browser/fixture/company-390-light.png) · [390 dark](browser/fixture/company-390-dark.png) | [1440 light](browser/public/company-1440-light.png) · [1440 dark](browser/public/company-1440-dark.png) · [390 light](browser/public/company-390-light.png) · [390 dark](browser/public/company-390-dark.png) |

## Data refresh and deployment

Task 3 is deployed from merge `8710c56b91a92d6983324ab1badbcd91476ff1a7`.
The owner-authorized weekly import [run 39041263843](https://github.com/vsakati6691/agent-code/actions/runs/39041263843)
failed because the public IJH provider history contains opens outside its
high/low range. A read-only diagnostic also found its latest history ended
October 15. Validation was preserved; no prices, snapshots or historical audit
records were rewritten. The workflow published the failure status while keeping
the latest valid weekly snapshot dated October 15 and daily refresh dated
October 16. Public data commit: `90e1db59de2d40fa01b0239fd881f5165f252aa8`.

The new full-index collection cannot populate the live top 20 until a weekly
run succeeds with valid inputs. After the provider data is corrected, run
`research-dashboard.yml` manually on main with `dry_run=false` and `options=true`.
The owner has already authorized merging and deployment; no additional owner
approval or brokerage action is needed for this task.

## Reproduce

Use Python 3.12 with the development dependencies. The browser scripts need
Playwright and Chromium (this run used headless Microsoft Edge Chromium).
Set `PLAYWRIGHT_MODULE` and `DASHBOARD_BROWSER` only when they are outside their
normal install paths. All browser requests are served from the local build.

```text
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m tests.dashboard_ci determinism --root <new-temp>/repeat
python -m tests.dashboard_ci build --root <new-temp>/plain
python -m agent_trading.dashboard verify --data <new-temp>/plain/data
python -m tests.dashboard_ci check --site <new-temp>/plain/site
python -m tests.dashboard_browser_fixture <new-temp>/browser
node tests/dashboard_ui_browser.cjs <new-temp>/browser/site <report>/fixture
node tests/dashboard_ai_browser.cjs <new-temp>/browser/site <report>/fixture-ai
python -m agent_trading.dashboard verify --data <research-data-clone>
python -m agent_trading.dashboard build --data <research-data-clone> --out <new-temp>/public
python -m tests.dashboard_ci check --site <new-temp>/public
node tests/dashboard_ui_browser.cjs <new-temp>/public <report>/public
node tests/dashboard_ai_browser.cjs <new-temp>/public <report>/public-ai
node tests/dashboard_ux_capture.cjs <new-temp>/plain/site <report>/metrics
```

The public browser profile defaults to the retained October 15 snapshot. For
other snapshots, supply `browser-fixture.json` in the local site build with
the relevant ticker, query, unavailable AI entry/reason and company-page path;
this is test metadata, never a modification to the stored snapshot.
