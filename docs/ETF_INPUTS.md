# Dated ETF inputs

`config/etf_exposure.json` contains public fund metadata for the nine ETFs in
the current watchlist. Every entry has an observation date, issuer, index (or
active management), expense ratio, inception, exposure class and issuer link.
The page labels this curated file **owner-supplied, unverified**. The classification
is a recorded judgment about exposure, not a fitted return estimate.

The new methodology version `2026-10-15.1` registers the canonical JSON hash.
Changing the file requires a new registration; whitespace-only edits do not.
The loader rejects metadata observed after the snapshot date. Earlier immutable
snapshots keep their original inputs and show unavailable metadata when absent.
No snapshot on `research-data` has been rewritten to add these fields.

Classification uses the ticker mapping first, then the previous name fallback.
The existing exposure-class bear/base/bull returns, scales, weights, gates and
lists are unchanged. The sourced expense replaces only the fee input in the
existing price-return equation. TQQQ uses its reported gross fee for the long
horizon; its current net fee is also recorded, without assuming a waiver lasts
until 2030. Distribution yields remain explicitly assumed; a 30-day SEC yield
is not substituted for a distribution yield.

Where a verified fund CIK is mapped, the existing GET-only SEC client checks
up to three recent eligible N-PORT/N-CEN filings. Filing and reporting dates
must be on or before the snapshot date. Structured XML must match the series
ID, or the exact normalized fund name. N-PORT holdings are displayed with their
reporting and filing dates; no classification is inferred from a different
series. No new network hosts are used. Missing mappings, unsupported HTML
documents, mismatches and request limits remain visible as unavailable.

N-PORT provides holdings, and N-CEN is an annual census; this parser does not
infer an annual operating expense ratio from other amounts in these forms.
The dated issuer/prospectus expense input remains in use. For example, the
EUV and AIPO entries also cite their SEC summary prospectuses. Fund filing
structure references: [SEC N-PORT XML specification](https://www.sec.gov/info/edgar/specifications/form-n-port-xml-tech-specs-1.4.htm)
and [Form N-CEN](https://www.sec.gov/files/formn-cen.pdf).

The nine ETF scenarios are covered by synthetic fixture tests with valid prices
and index history. This is not a promise that all thirteen live watchlist rows
will have scenarios: RVI is a [closed-end venture fund](https://robinhood.com/us/en/ventures/rvi/),
which the registered methods do not cover. Operating companies can also lack
the positive revenue, filing history or valuation inputs required by the
unchanged company method. Those cases stay unavailable with their reasons;
meeting the zero-unavailable target would require additional evidence or a
separately approved methodology, not relabelling the securities or inventing data.
