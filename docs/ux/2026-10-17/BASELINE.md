# Dashboard UX baseline — 17 October 2026

Task 0 contains documentation and screenshots only. Source commit:
`6ac0d8d96c446bd0f743c8af9f44b142b850bf7e`.

## Before measurements

The offline CI fixture was served locally to headless Chromium (Microsoft Edge).
Desktop is 1440 × 900; mobile is 390 × 844. Both light and dark themes were
checked. The numbers below use light mode; raw results for all 60 combinations
are in [metrics.json](before/metrics.json).

“Words” counts visible text in `main` before the first table, summary card grid,
or calculator result block, excluding navigation, footer and collapsed details.
“Points” counts numeric value-bearing text nodes in visible data cells or metric
values, including dated values but excluding input controls, prose and chart
axis labels. A cell can contain several observations. These are reproducible
layout indicators, not a count of every semantic fact. N/A means the fixture has
no visible data block (Bets is unavailable; Compare has no selected companies).
Values are measured at initial scroll position; horizontally clipped cells do
not count unless at least part of their text is visible. Screenshots provide the
visual check alongside the mechanical measurements.

| Page | HTML bytes | Words desktop | Words mobile | Points desktop | Points mobile |
|---|---:|---:|---:|---:|---:|
| index | 29,123 | 82 | 82 | 4 | 2 |
| growth | 88,809 | 204 | 204 | 0 | 0 |
| multibaggers | 33,448 | 310 | 310 | 1 | 0 |
| ai | 56,980 | 279 | 214 | 28 | 0 |
| options | 128,858 | 335 | 335 | 0 | 0 |
| bets | 8,164 | N/A | N/A | 0 | 0 |
| watchlist | 40,032 | 55 | 55 | 28 | 4 |
| leaders | 37,278 | 66 | 66 | 37 | 5 |
| goal | 21,492 | 118 | 118 | 2 | 0 |
| evidence | 11,608 | 119 | 119 | 20 | 3 |
| compare | 10,402 | N/A | N/A | 0 | 0 |
| history | 16,033 | 118 | 118 | 6 | 6 |
| methodology | 57,313 | 272 | 272 | 25 | 0 |
| audit | 19,271 | 72 | 72 | 15 | 3 |
| company | 67,858 | 68 | 68 | 3 | 2 |

All measured pages are below 150 KB. All 60 combinations have zero page errors,
failed requests and horizontal document overflow. The company example is
`stock/ai_large-AIL1.html`. Screenshots show the entire first viewport.

## Validation

- Python 3.12.10; clean workspace virtual environment; `pip install -e ".[dev]"`.
- Full pytest: **971 passed** in 259.75 seconds.
- Ruff check and format: passed (245 files).
- Configured Mypy boundaries: passed (12 modules).
- Frozen fixture determinism: **301 files, zero differences**.
- Offline fixture build, snapshot verification, links and asset budgets: passed;
  **144 HTML pages, zero broken links**.
- Read-only local build of public `research-data` commit
  `42815e8eb164cb1ab8ee6ed4811091cd5f0f859c`: verification passed;
  **159 HTML pages, zero broken links**. Latest weekly snapshot: 2026-10-15,
  original methodology 2026-10-14.9. Clone used `core.autocrlf=false` to preserve
  immutable file hashes. No production collection or snapshot writes were run.
- Public snapshot Leaders has 10 dated current caps among 503 members and no
  retained full-universe inputs. The old snapshot cannot gain missing data
  through a presentation change.

There is no after delta for Task 0: no application text or code was changed.
No text was moved or removed. Later task reports compare against these numbers.

## Before screenshots

<details><summary>index: desktop and mobile</summary>

![index desktop](before/index-desktop.png)

![index mobile](before/index-mobile.png)

</details>

<details><summary>growth: desktop and mobile</summary>

![growth desktop](before/growth-desktop.png)

![growth mobile](before/growth-mobile.png)

</details>

<details><summary>multibaggers: desktop and mobile</summary>

![multibaggers desktop](before/multibaggers-desktop.png)

![multibaggers mobile](before/multibaggers-mobile.png)

</details>

<details><summary>ai: desktop and mobile</summary>

![ai desktop](before/ai-desktop.png)

![ai mobile](before/ai-mobile.png)

</details>

<details><summary>options: desktop and mobile</summary>

![options desktop](before/options-desktop.png)

![options mobile](before/options-mobile.png)

</details>

<details><summary>bets: desktop and mobile</summary>

![bets desktop](before/bets-desktop.png)

![bets mobile](before/bets-mobile.png)

</details>

<details><summary>watchlist: desktop and mobile</summary>

![watchlist desktop](before/watchlist-desktop.png)

![watchlist mobile](before/watchlist-mobile.png)

</details>

<details><summary>leaders: desktop and mobile</summary>

![leaders desktop](before/leaders-desktop.png)

![leaders mobile](before/leaders-mobile.png)

</details>

<details><summary>goal: desktop and mobile</summary>

![goal desktop](before/goal-desktop.png)

![goal mobile](before/goal-mobile.png)

</details>

<details><summary>evidence: desktop and mobile</summary>

![evidence desktop](before/evidence-desktop.png)

![evidence mobile](before/evidence-mobile.png)

</details>

<details><summary>compare: desktop and mobile</summary>

![compare desktop](before/compare-desktop.png)

![compare mobile](before/compare-mobile.png)

</details>

<details><summary>history: desktop and mobile</summary>

![history desktop](before/history-desktop.png)

![history mobile](before/history-mobile.png)

</details>

<details><summary>methodology: desktop and mobile</summary>

![methodology desktop](before/methodology-desktop.png)

![methodology mobile](before/methodology-mobile.png)

</details>

<details><summary>audit: desktop and mobile</summary>

![audit desktop](before/audit-desktop.png)

![audit mobile](before/audit-mobile.png)

</details>

<details><summary>company: desktop and mobile</summary>

![company desktop](before/company-desktop.png)

![company mobile](before/company-mobile.png)

</details>
