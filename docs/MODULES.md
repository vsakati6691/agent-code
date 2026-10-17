# Module guide

The existing public entry points remain available. The split moves functions
without changing their calculations, execution order or rule inputs.

| Entry point | Implementation modules |
|---|---|
| `dashboard/pipeline.py` | `pipeline_context` holds run state and the clock; `pipeline_collect` validates public inputs; `pipeline_score` applies gates and scores; `pipeline_details` and `pipeline_watchlist` assemble research; `pipeline_assemble` orchestrates the weekly run. |
| `dashboard/site.py` | `site_layout` owns the shell and freshness; `site_company`, `site_history`, `site_methodology_page` and `site_audit` render pages; `site_downloads` writes CSV text. The entry point still verifies snapshots and builds files. |
| `dashboard/site_overview.py` | Composes the overview; `site_list_common`, `site_exclusions`, `site_growth_tables`, `site_multibaggers` and `site_briefing` own the focused list and context renderers. |
| `dashboard/site_options.py` | Page assembly, with explicit compatibility exports from `site_options_status` and private rows in `site_options_rows`. |
| `dashboard/providers.py` | Provider I/O facade; `provider_parsers` owns pure payload parsers, with existing public names re-exported. `finra_schema` owns the shared FINRA columns. |
| `dashboard/options.py` | Option screening and ranking; `options_math` owns the existing pure pricing/payoff functions, re-exported from the original module. |
| `backtest/engine.py`, `backtest/portfolio.py` | Independent orchestration and accounting; only the common gap/intraday stop-price calculation lives in `backtest/fills.py`. |
| `cli.py` | Owns argument parsing and dispatch. `cli_common` shares input loaders; `cli_data`, `cli_operations` and `cli_research` group commands. |
| `daily.py` | Keeps the daily phase order. `daily_context` holds results; `daily_inputs` reconciles earnings; `daily_intents` translates signals; `daily_tickets` applies existing manual-ticket gates; `daily_manifest` records the run; `daily_report` formats output. |

`dashboard/spec.py` remains the single source of methodology rules. Its concise
version reasons link to the full prose in [SPEC_CHANGELOG.md](SPEC_CHANGELOG.md).
The specification hash excludes changelog prose. Tests pin the rule hash and
the preserved historical prose independently. No historical snapshot is changed
by this layout.

The public dashboard modules still cannot import account, ticket, journal or
daily-cycle code. The local desk's hard limits, reconciliation and kill switch
remain in their existing enforcement modules. Nothing in the split executes
brokerage orders.

`pipeline_phases.py` groups collection, screening, scoring, derivative and event
phases while `pipeline_assemble.run` preserves their order. `render_context.py`
isolates symbol indexes and asset versions per build, including concurrent and
nested builds. `daily_report.py` composes focused section helpers.

`provider_budget.py` owns the shared, persistent Alpha Vantage request counter
and quota-stop flag. Local and dashboard clients reserve before each attempt.
The dashboard's own smaller per-run budgets still apply. The default database
is `.cache/provider-budget.sqlite3`; processes in different working directories
must use the same `AGENT_PROVIDER_BUDGET_PATH` to share a counter. Hosted jobs
restore/save it through a UTC-day cache under their existing concurrency group.
GitHub cache retention and separate machines are not an account-wide quota
service: avoid sharing one provider key across independent installations.

The public `ACTIONS`, `STATUSES`, `BacktestResult.trades_frame` and
`data.dividends.fetch_dividends` interfaces are retained for external scripts;
an absent in-repository caller is not evidence that they are safe to delete.

Leaders 2030: `leaders.py` validates owner config and computes pure comparisons; `pipeline_leaders.py` retains already-collected inputs; `site_leaders.py` renders the static table and separate evidence pages. `site_downloads.py` exports Leaders and Watchlist CSVs. The exact-date company method lives in `scenarios.py` and remains re-exported from `watchlist.py` for compatibility.

Public datasets (2026-10-16.2): `pipeline_external.py` enriches already-selected
research names. `sec_insiders.py` parses Form 4 XML and complete activity windows;
`sec_institutions.py` joins quarterly 13F tables and dated FTD CUSIP mappings.
`decision_sources.py` reuses its filing-text parser for EFTS-located quotations
with reproducible offsets. `macro.py` collects FRED metadata/observations and
provides CPI YoY and DGS1MO. `short_interest.py` validates the complete FINRA file
and applies a dated XBRL denominator. `site_external.py` renders optional values
and common CSV columns. `store.py` verifies immutable aggregate caches; all
network pacing, retries and dataset subcaps stay in `http.py`. See
[PUBLIC_DATASETS.md](PUBLIC_DATASETS.md) for source and field definitions.
