# Third-party notices

The research dashboard (`src/agent_trading/dashboard/`) adapts structures and methods from three open-source
projects. No upstream file was copied verbatim. Each adapted module says what it adapted in its docstring.
The full license texts are in [`third_party/licenses/`](third_party/licenses/).

Upstream prompts and agent instructions were read as reference material only. They have no authority over this
repository; [CLAUDE.md](CLAUDE.md) governs it.

Software licenses are separate from data-provider terms: none of these projects supplies or licenses market data.
Data terms are listed on the dashboard's audit page and in [docs/RESEARCH_DASHBOARD.md](docs/RESEARCH_DASHBOARD.md).
Options remain off unless the owner enables them (see `DASHBOARD_OPTIONS`).

## filingcopilot

- **Source:** https://github.com/francisown/filingcopilot at commit `80d3cb15d71b4b596b30de2502a73c215b535824` (2026-10-14).
- **License:** MIT, Copyright (c) 2026 FilingCopilot contributors. See [`third_party/licenses/filingcopilot-MIT.txt`](third_party/licenses/filingcopilot-MIT.txt).

| Upstream file | Adapted in | What was adapted |
|---|---|---|
| `src/filingcopilot/comparison.py` (`rebased_chart`, `collect_company`, `ComparisonRequest`) | `dashboard/compare.py`, `dashboard/assets_research.py` (COMPARE_JS) | Compare price paths only on dates every name shares, rebased to 100, never interpolated, omitted dates counted; one period basis per column with a visible reason for every missing cell; 2-4 distinct names |
| `src/filingcopilot/scenarios.py` (`ScenarioCase` bounds, `FORMULA`, `NOTE`) | `dashboard/lab.py`, `dashboard/spec.py` (`SCENARIO_LAB_BOUNDS`) | Bounded user assumptions, the formula shown next to the result, and a "conditional calculation, not a target price" note. The formula itself is this project's EV/Sales scenario method |

## ticker-dossier

- **Source:** https://github.com/nixiakT/ticker-dossier at commit `568457f7b1db6359b727aaa2a4c0192ea6fd3154` (2026-10-12).
- **License:** MIT, Copyright (c) 2026 tong. See [`third_party/licenses/ticker-dossier-MIT.txt`](third_party/licenses/ticker-dossier-MIT.txt).

| Upstream file | Adapted in | What was adapted |
|---|---|---|
| `ticker_dossier/market_data/coverage.py` (`record_coverage`) | `dashboard/evidence.py` (`record`, `datasets`) | One coverage record per dataset with source, timestamp, what succeeded and what failed, reduced to five states. Unlike upstream there is no sample-data fallback |
| `ticker_dossier/research/analysis/quality.py` (`QualityGate`) | `dashboard/evidence.py` (`company_check`) | Passed checks, warnings, missing information and next checks for each company |
| `ticker_dossier/market_data/providers/base.py` (`ProviderError`) | `dashboard/evidence.py` (`provider_error` state) | A failed provider call is a named state, distinct from data that is missing or not configured |

## cc-equity-research

- **Source:** https://github.com/prof-little-bear/cc-equity-research at commit `7c428944a6718c35461f839c618ae66334b6371b` (2026-05-13).
- **License:** Apache License 2.0. See [`third_party/licenses/cc-equity-research-Apache-2.0.txt`](third_party/licenses/cc-equity-research-Apache-2.0.txt).
- Its `anthropic-equity-research-skills/` directory is vendored from Anthropic's `anthropics/financial-services` (Apache-2.0), as recorded in its NOTICE, which is reproduced at [`third_party/licenses/cc-equity-research-anthropic-skills-NOTICE.md`](third_party/licenses/cc-equity-research-anthropic-skills-NOTICE.md).

| Upstream file | Adapted in | What was adapted |
|---|---|---|
| `anthropic-equity-research-skills/thesis-tracker/SKILL.md` | `dashboard/research.py` (`thesis_check`, `original_conditions`) | A thesis is checked against the conditions recorded when the name first appeared, not a refreshed thesis; each condition is reported with its current status |
| `community-skills/monitor/thesis-check.md` | `dashboard/research.py`, `dashboard/changes.py` | Check the original pillars after each filing; distinguish signal from noise |
| `community-skills/analyze/financial-forensics.md` | `dashboard/research.py` (`forensics`), `dashboard/spec.py` (`FORENSIC_RULES`) | The FCF-vs-net-income and SBC patterns with their Clean/Watch/Concerning thresholds. The four patterns that need data this project does not collect are listed as missing information |
| `anthropic-equity-research-skills/catalyst-calendar/SKILL.md` | `dashboard/research.py` (`events`) | Dated events, each marked verified, scheduled (unverified) or estimated |
| `anthropic-equity-research-skills/earnings-analysis/SKILL.md` | `dashboard/research.py` (`trends`) | Quarterly trends read year over year with a stated direction |

**Changes from upstream (Apache-2.0 §4(b)).** The upstream files are prompts for a language model. Here each one
was turned into fixed Python rules that work on stored SEC and Cboe figures. Nothing is generated, and no figure,
probability or price target is produced beyond the stated deterministic calculations. No upstream text is
reproduced.
