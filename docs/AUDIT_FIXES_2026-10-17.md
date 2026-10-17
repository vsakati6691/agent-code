# Audit implementation — 2026-10-17

The owner authorized implementation and a pull request after the
[read-only baseline audit](AUDIT_2026-10-17.md). This follow-up distinguishes
confirmed defects from optional structural work and operational questions.
The base is `ee5f803b11389d849656a0c43f54fd74a7a9436c` on `main`;
changes are on `feature/research-system`.

## Correctness and security changes

| Audit finding | Implemented behavior | Regression evidence |
|---|---|---|
| BUG-1 | Account imports require explicit complete position/order arrays, known states/sides and valid records. Saved snapshots are revalidated and need a completeness marker. | Missing/null/wrong-type arrays, invalid records, duplicate positions, saved-file tampering and valid empty lists in `test_audit_safety.py`. |
| BUG-2 | Config numeric boundaries reject booleans, NaN, infinity and invalid signs/types before hard-limit comparisons. Existing hard limits are unchanged. | Parametrized config/risk/gate boundary cases. |
| BUG-3 | Tournament defaults to selection-only. Prices and dividends are cut at 2021-12-31 before adjustment/simulation. The already-consumed 2022+ holdout is sealed; the legacy test entry point rejects calls before evaluation. Malformed registry entries fail closed. | Mocked tournament, API, date-boundary and registry probes; no actual holdout evaluation. |
| BUG-4 | Final gate validates finite positive quantities, prices and notionals for sells and buys; malformed issued tickets reject the batch. | Invalid quantity/price/side tables and existing daily-limit tests. |
| DATA-1 | A quote can no longer manufacture a history row or missing volume. Stale history and invalid OHLC remain unavailable; independently observed quotes retain their provenance. | Missing-volume/range and stale-history regressions in `test_audit_boundaries.py`. |
| DATA-2 | OHLCV validation rejects infinite, boolean and nonnumeric observations. | Finite-value boundary table plus existing price tests. |
| SEC-1 | Shared CSV serialization neutralizes formula-leading text, including whitespace prefixes. Numeric negatives remain numeric. | All six prefixes and ordinary-value checks. |
| SEC-2 | Symbol-derived cache paths validate tickers, reject reserved/traversal names and enforce resolved containment. Explicit user-selected import paths remain supported. | Traversal, drive paths, Windows reserved names and legitimate dotted/dashed tickers. |
| SEC-3 | Audit/status persistence recursively redacts diagnostics; dashboard logging installs redaction filters. Verification scans named environment secrets before publishing data. | Synthetic secret markers, persistence, logging and workflow-boundary checks. |
| DATE-1 | CLI dates use New York time; inferred entry dates use the next exchange session and disclose the unknown actual fill date. Price-cache weekday staleness stays conservative. | UTC/New York date boundary and July holiday regression. |
| PERF-1 | Local and dashboard clients share an atomic persistent daily Alpha Vantage counter, reserve before each attempt, and stop after quota/entitlement errors. The existing 24-attempt ceiling and smaller dashboard run cap are unchanged. | Concurrent reservations, client restarts, next-day rollover, cross-client exhaustion, quota responses and corrupt-state rejection. |

Legacy saved account snapshots must be **re-imported from fresh, complete
read-only responses**. Do not insert the marker manually or substitute empty
lists for failed responses. See [DAILY_ROUTINE.md](DAILY_ROUTINE.md).

The consumed holdout cannot be re-enabled with a CLI flag. A genuinely new
holdout would require separately preregistered research, not reuse of the
already-observed 2022+ period. Existing registry records and acceptance criteria
have not been changed.

## Engineering changes

- REF-1/TEST-1: test-only frozen clocks and complete-file manifests support a
  repeatable two-build determinism check in CI. The browser suite now has a
  synthetic fixture with a partial refresh; production snapshot data is optional.
- REF-2: per-build render context prevents symbols and asset versions leaking
  between concurrent or nested builds, including exception paths.
- REF-3: 12 validated safety/orchestration modules pass Mypy with a pinned
  development version, enforced in CI. Full-tree debt is reduced, not hidden.
- REF-4: weekly collection, screening, scoring, derivatives and event phases
  are extracted in their original order. Daily reporting has focused section
  helpers. Typed quota exceptions complement existing error handling.
- REF-5: options status and row renderers are separated from page assembly.
  Provider parsers and pure option math also have dedicated modules; original
  public import paths remain available.
- REF-6: the two backtest engines share only the pure stop-fill calculation.
  Sequencing, risk enforcement, costs and accounting stay in each engine.
- REF-7: FINRA columns have one dependency-free definition.
- REF-8: all four workflows share pinned Python setup/install steps. Existing
  permissions, credential policies, opt-in switches, main guards and immutable
  data checks remain. Collection jobs restore/save the provider budget cache
  under their existing shared concurrency group, including after failed runs.
- REF-9: comparison ownership indexes are built once; each symbol's cached
  history is read once per refresh.
- REF-10: dangerous CSV text handling is centralized. Specialized table
  renderers retain their existing escaping and structure.
- DEAD-3/4/5/6/8: removed unused bindings, a private argument, an unreachable
  test arm, an unused fixture argument and two obsolete CSS selectors.
- DOC-1: corrected current holiday and rerun documentation; the automation
  proposal is prominently marked historical. Protected evidence reports stay
  at their original paths with their historical claims intact.

Browser testing also exposed a pre-existing 5-pixel mobile overflow on the
multibaggers page. Its grid now allows cards to shrink to the viewport.
This is an intentional CSS change, separately identified in output comparisons.

## Verification

The checkout has no `.venv`; local runs use the existing Python 3.12.10 environment
at `C:/Users/vsaka/Documents/Claude/agent-code/.venv/Scripts/python.exe`, with
`PYTHONPATH` set to this checkout's `src`. Test data and reports are synthetic
and isolated in fresh temporary directories. Provider calls are mocked.

| Check | Result |
|---|---|
| First corrective commit `b150aba` | 919 pytest tests passed. |
| Second corrective commit `7374c85` | 962 pytest tests passed. |
| Final pytest run | **971 passed**, 0 failed, 238.18 seconds (baseline: 831). |
| Ruff 0.17.1 | Lint clean; 245 Python files formatted. |
| Mypy 2.4.0, selected boundaries | 0 errors in 12 modules; `python -m mypy` is the CI contract. |
| Mypy full `src`, normal imports | 299 errors in 58 modules, down from 356 in 64. |
| Frozen fixture build | Two final builds: all 301 files identical. Before the intentional CSS change, all 301 also matched the audit baseline exactly. |
| Final fixture vs audit baseline | Only `style.css` and its fingerprint in 144 HTML files differ. No HTML difference remains after normalizing that fingerprint; all data files are identical. |
| Daily report parity | Three synthetic empty/blocked/verified-ticket and strategy contexts match the previous implementation byte-for-byte. |
| Backtest mechanics | Both engines produce equal trades/equity for gap, intraday and entry-day stops, including costs and same-day close signals. |
| Complexity | Weekly orchestration decreases from 116 to 31; daily report assembly from 87 to 8 (Radon). |
| Snapshot/link/page budgets | Integrity verification passes; 144 HTML pages checked, 0 broken links, budgets pass. |
| Playwright / local Edge | 84 page/viewport/theme combinations; search, navigation, focus, sorting, failed-fetch recovery, partial refresh, themes, print, no-JavaScript and AI interactions pass; no JavaScript errors. |
| Methodology | Rule hash `ed13539391c855db`; raw `spec.py` SHA-256 `e9f2bc010fbefbfb8dc1d7fa1dd1b6ae6d6e39bb1bfb88056d24630cbefb4569`, both unchanged. |

Repeat the offline checks from the repository root:

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m pytest
& $py -m ruff check .
& $py -m ruff format --check .
& $py -m mypy
& $py -m tests.dashboard_ci determinism --root <new-temporary-directory>
& $py -m agent_trading.dashboard verify --data <new-temporary-directory>/first/data
& $py -m tests.dashboard_ci check --site <new-temporary-directory>/first/site
& $py -m tests.dashboard_browser_fixture <another-new-temporary-directory>
node tests/dashboard_ui_browser.cjs <another-new-temporary-directory>/site <browser-report-directory>
```

The optional browser command requires Playwright. `PLAYWRIGHT_MODULE` can name
an installed module path and `DASHBOARD_BROWSER` an installed Chromium/Edge
executable. External browser requests are blocked in the interaction context.

## Deliberately retained work and operational limits

1. The remaining 299 full-tree type diagnostics are gradual-typing work.
   This PR establishes and checks the first boundary group; it does not claim
   the entire application is typed.
2. DEAD-1/2/7 public helpers (`ACTIONS`, `STATUSES`, `trades_frame`,
   `data.dividends.fetch_dividends`) remain for external notebooks/scripts.
   No known caller is broken to satisfy an unused-code tool. Large declarative
   schema/asset string splits remain optional; `spec.py` is deliberately intact.
3. BRANCH-1 remains informational. No remote branch is deleted; the required
   `feature/research-system` branch remains in use.
4. This is offline software verification, not evidence of an unattended full
   trading day or reboot recovery. No schedule, production refresh, brokerage
   action, kill-switch release or deployment was triggered for the refactor.
5. The provider counter coordinates processes sharing one database. GitHub
   cache persistence is best-effort and scoped by GitHub; cache eviction and
   independent machines cannot provide a global account-wide quota guarantee.
   Use the same configured path for local clients and avoid sharing one key
   across independent installations. Quota responses always stop further
   attempts in the persisted scope for that UTC day.
6. Runtime dependency ranges remain unchanged. Mypy joins the pinned Ruff dev
   check; a full runtime lockfile is a separate reproducibility decision.

No risk limit or hard account limit was loosened. `config/settings.yaml`,
`HARD_LIMITS`, registered methodology, real registry and historical snapshots
are preserved. Live output remains manual tickets only.
