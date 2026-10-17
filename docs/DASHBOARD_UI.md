# Dashboard UI

The site remains Python-generated HTML with small, same-origin JavaScript files.
This presentation layer does not rescore snapshots, change research rules, or call
market-data APIs from the browser. No runtime packages, web fonts, or CDN assets
were added.

## Shared modules

| Module | Responsibility |
| --- | --- |
| `dashboard/assets_terminal.py` | Theme tokens, tabular numerals, spacing, table scrolling, focus styles, reduced motion, print rules, and command-palette styles. This is the source of the shared light/dark color tokens. |
| `dashboard/site_tables.py` | Named keyboard-focusable scroll regions and sort buttons present in the initial HTML. Existing table filters, numeric sort keys, and grouped evidence rows remain in use. |
| `dashboard/site_command.py` | Escaped inline ticker catalog, native Browse tickers links without JavaScript, and native dialog markup. |
| `dashboard/assets_command.py` | Search by ticker or company name, Ctrl+K / Cmd+K, arrow-key selection, Enter navigation, Escape, and focus restoration. Built as `assets/command.js`, independently of page-specific scripts. |
| `dashboard/site_layout.py`, `site_refresh.py`, `site_status.py`, `site_audit.py` | Compact freshness/status notices, server-rendered warnings, and full dataset-level reasons on Audit. |
| `dashboard/site_ai_context.py` | AI section links, recorded price basis, and display-only explanations of scoring and scenario limits. |
| `dashboard/assets.py` | Existing table interaction engine and evidence-fragment loader, including a 15-second timeout, response validation, retry, and full-page fallback. |

The existing public builder functions and symbol URLs are unchanged. The command
catalog covers the published symbol pages from all lists. It is local and requires
no search API. Search results use text nodes and catalog-derived links; arbitrary
input is never interpolated into a selector or destination URL.

## Layout and accessibility

- All numeric text inherits tabular figures. Positive/negative colors supplement
  signed values; they do not replace the sign or meaning of a label.
- Wide tables scroll inside bounded regions. Column headers stay visible during
  vertical scrolling, and ticker/row labels stay visible during horizontal scrolling.
  The growth scanner keeps native table semantics on narrow screens.
- Sorting controls exist before JavaScript loads, reserving the indicator width.
  The existing live sort announcements and saved-view reset controls are retained.
- The native modal supplies focus containment. Escape closes even when its search
  input contains text, and focus returns to the control that opened it.
- System theme is the default. An explicit choice is applied before stylesheet
  paint. Controls have visible focus outlines, motion respects the system preference,
  and print output removes scroll height limits and sticky positioning.
- Calculator defaults and the empty comparison prompt render on the server.
  Status regions and lazy evidence panels reserve space to reduce load-time shifts.
  Evidence panels scroll when their content is longer than the reserved area.

## Data-first pages and missing inputs

Tables, KPI cards and charts lead each page. Freshness is one date/age/delay line
with a native Details disclosure; stale and failed-update warnings still render
without JavaScript. Entirely missing sections collapse as one disclosure. Missing
table values use an em dash with a tooltip or row explanation. Full collection
errors, request budgets, methodology versions and hashes are on Audit, linked
from the relevant page. Treasury-rate assumptions are already expanded there.
No missing rate, price or financial observation is invented.

Plan 2030 shows each scenario's dated starting price and conditional 2030 prices;
a newer daily close is separate context. The target/contribution calculator and
optional weights retain their arithmetic. Leaders shows the current top 20 plus
conditional entrants when data supports them, with an implied annual rate beside
each cap. Coverage gaps remain explicit. See [the registered Leaders rules](LEADERS_2030.md)
and [the complete moved-text inventory](ux/2026-10-17/DATA_FIRST.md).

Partial-snapshot explanations preserve all supplied reasons, including XBRL
failures. Each page retains its research/scenario disclosure, and options pages
retain the full-premium-loss warning.

A failed or malformed evidence response leaves a full research-page link and an
explicit retry button. It does not change the table's stored numbers. A failed
retry remains usable from the keyboard. Malformed URL fragments fall back to the
default tab/comparison selection.

## Verification

Run the complete local CI before committing: pytest, Ruff lint/format, configured
Mypy, deterministic fixture builds, snapshot integrity and all-page link/size
checks. The [completed test report](ux/2026-10-17/BROWSER_TESTS.md) includes the
exact commands, per-page results, measurements and screenshots.

The browser scripts use Playwright from the development environment; it is not
shipped to the site. Build a fresh synthetic interaction fixture first (choose a
new output directory on each run). It includes daily options, populated Small
Bets, partial-refresh reasons and at least 20 Leaders rows; no API key is needed.

```powershell
.\.venv\Scripts\python.exe -m tests.dashboard_browser_fixture reports/dashboard-browser-fixture
# Optional: point PLAYWRIGHT_MODULE to an existing Playwright installation.
# Optional: set DASHBOARD_BROWSER to an installed Chromium/Edge executable.
node tests/dashboard_ui_browser.cjs reports/dashboard-browser-fixture/site reports/dashboard-ui
node tests/dashboard_ai_browser.cjs reports/dashboard-browser-fixture/site reports/dashboard-ai
```

Also run both scripts on a local build of the latest retained public data. The
default public profile describes the October 15 snapshot; for a different
snapshot, provide the appropriate ticker/company and unavailable-entry values
in a test-only `browser-fixture.json` alongside the generated HTML.

The UI script serves files on loopback and blocks external requests. Its matrix
covers all 14 tabs and one company page at 1440 × 900 and 390 × 844, in light and
dark themes: 60 interactive views plus 60 views without JavaScript per dataset.
It checks nav links and active state, ticker navigation, every table search,
filter option, visible sort control, pin/reset, CSV download, native disclosure
and row evidence. It also checks initial-screen text overlap/AA contrast, page
overflow, fixed Plan arithmetic, sticky axes, keyboard focus, malformed hashes,
failed/invalid evidence retries, saved theme, reduced motion and print.

Screenshots and JSON results are written to the specified report directory.
`tests/dashboard_ux_capture.cjs` independently reproduces visible-word counts,
HTML bytes and first-screen data-point metrics. Text inside closed disclosures
is excluded. Automated contrast/layout checks cover the measured states rather
than certifying every possible browser, saved view or accessibility interaction.

The AI page keeps its existing lists and models. Its section links work without
JavaScript; scoring notes and eligibility details use native disclosures. Ranked
universe names link to company research, and unavailable reasons can be opened
with touch or keyboard. The scenario table uses recorded numeric values for
sorting, including a reset control and the shared saved-view behavior. The
`dashboard_ai_browser.cjs` checks these interactions both independently and as
part of the main browser regression pass. Navigation tabs have not been removed
or regrouped.
