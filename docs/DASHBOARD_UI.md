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
| `dashboard/site_command.py` | Escaped inline ticker catalog, fallback search, and native dialog markup. |
| `dashboard/assets_command.py` | Search by ticker or company name, Ctrl+K / Cmd+K, arrow-key selection, Enter navigation, Escape, and focus restoration. Built as `assets/command.js`, independently of page-specific scripts. |
| `dashboard/site_status.py` | Compact, escaped notices with expandable dataset-level reasons. |
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

## Partial data and failures

The status and observation dates remain visible. Individual stale-chain reasons
and request usage are expandable. Missing macro observations and Treasury inputs
have a compact notice and retain their recorded reason; no fallback rate is invented.
Partial-snapshot notices preserve all supplied reasons, including XBRL failures.

A failed or malformed evidence response leaves a full research-page link and an
explicit retry button. It does not change the table's stored numbers. A failed
retry remains usable from the keyboard. Malformed URL fragments fall back to the
default tab/comparison selection.

## Verification

Run the required Python suite before committing:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=reports/pytest-ui --tb=short -q
```

The optional browser regression script uses Playwright already installed in the
development environment; it is not shipped to the site. Supply a site built from
the stored October 15 snapshot and an output directory. This suite deliberately
uses its real Nvidia row, partial daily chain states, and missing macro inputs.

```powershell
# Optional: point PLAYWRIGHT_MODULE to an existing Playwright installation.
# Optional: set DASHBOARD_BROWSER to an installed Chromium/Edge executable.
node tests/dashboard_ui_browser.cjs reports/site reports/dashboard-ui
```

The script serves the supplied files on loopback and blocks external browser
requests. It checks every navigation tab at 390, 768, and 1440 pixels in light and
dark themes, records layout shifts, checks both sticky axes, and exercises search,
keyboard focus, sorting, malformed hashes, unavailable/invalid evidence responses,
retry, theme persistence, reduced motion, print, and the JavaScript-disabled shell.
Screenshots and JSON results stay in the ignored report directory. Layout-shift
measurements describe those tested loads, not every possible saved state, browser,
connection, or user interaction.
