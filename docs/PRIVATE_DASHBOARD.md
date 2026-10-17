# Local private dashboard

The owner chose private access on 2026-10-17 after the Cboe weekly price feed failed validation. `run --private` uses Massive's split-adjusted daily stock/ETF history and retains all existing price checks. It does not modify brokerage data, trading limits or orders. The public dashboard continues to use its existing provider and snapshots.

This mode is local personal research. Do not upload its data, HTTP cache, generated site or downloads to the public repository, `research-data`, Pages, a public artifact or another hosting service. The [standard Massive terms](https://massive.com/legal/market-data-terms-of-service) restrict public redistribution; a free or paid individual plan alone does not establish those rights. The CLI rejects private collection/rendering in GitHub Actions, and the ordinary public build and verification check every stored week for private data. A private build requires `--private` and has a visible private-use label on every page. These checks are not web authentication: keep the server bound to loopback.

## One-time setup

Use the existing environment and keep the following values only in a Git-ignored `.env` in the checkout:

```dotenv
MASSIVE_API_KEY=your-existing-key
SEC_USER_AGENT=agent-code research your-real-contact-email
```

Copy the existing key from the [Massive Keys page](https://massive.com/dashboard/keys). SEC requires a real contact address, not a GitHub noreply address. Alpha Vantage and FRED keys are optional; absent data is labelled unavailable. Do not paste credentials into commands, chat, source, reports or commits. The explicit `--env-file .env` option reads only the dashboard's credential names, does not replace existing process values, and does not print them.

Create an ignored `reports/private-dashboard/data` directory. Copy the existing verified public `research-data` files into it without `.git`, preserving file bytes. This retains immutable historical snapshots and the existing public tradability verdicts. Do not use the actual `research-data` checkout as the private destination. Do not obtain a new brokerage/account snapshot for this dashboard.

## Collect, verify and view

From this checkout in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m agent_trading.dashboard --env-file .env run --private --data reports/private-dashboard/data --cache reports/private-dashboard/http
.\.venv\Scripts\python.exe -m agent_trading.dashboard --env-file .env verify --private --data reports/private-dashboard/data
.\.venv\Scripts\python.exe -m agent_trading.dashboard --env-file .env build --private --data reports/private-dashboard/data --out reports/private-dashboard/site
.\.venv\Scripts\python.exe -m tests.dashboard_ci check --site reports/private-dashboard/site
.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory reports/private-dashboard/site
```

Open <http://127.0.0.1:8765/> on the same PC. Stop the server with Ctrl+C. Serve only the generated `site` folder, never the checkout, credential file or raw-data directory. The PC must remain awake while collecting or serving.

For a bounded initial smoke test, use `--limit 5 --no-options` and a **different** scratch data directory with a copy of the tradability verdict file. A limited run is partial, not a full weekly import; its immutable snapshot must not occupy the full-run destination for that date.

## Registered limits and evidence

Spec **2026-10-17.3** registers the source change for new private snapshots. Existing registrations, stored snapshots and freeze date remain unchanged. Every new private snapshot records its provider and collection timestamp; company, watchlist, benchmark and Leaders inputs retain source attribution.

- The [daily-aggregate endpoint](https://massive.com/docs/rest/stocks/aggregates/custom-bars) is requested with split adjustment enabled, ascending dates, at most 730 calendar days ending at the as-of session, and no dividend adjustment. The start date is no earlier than the UTC collection date minus 729 days, staying inside Basic's rolling entitlement window. Observed OHLCV is preserved. No synthetic bars, range repairs, missing-volume substitutions, source splices or automatic fallback are used.
- Basic access offers about two years of history. Missing 3-year/5-year price returns remain unavailable; this also means the leveraged-ETF model requiring three years cannot run. Fundamental history still comes from SEC filings.
- At most 600 Massive HTTP attempts per run, at least 13 seconds apart, including retries. [Basic permits five stock requests per minute](https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis). Collection can take over two hours; request exhaustion stays an explicit gap. Other provider caps and the 90% S&P 500 price-coverage requirement remain unchanged.
- Authentication, billing and quota responses stop further Massive network requests for the run. Do not loop retries or generate additional keys to evade limits. Successful responses are cached for 12 hours with an exact as-of date in the key; credentials are excluded from cache filenames.
- Current source observations are not point-in-time historical backfills. Reruns keep an existing dated snapshot unchanged. Tracking is validated and updated locally; public historical evidence is not rewritten or mixed across spec versions.

No automated public deployment is enabled for this mode. Remote private hosting would need a separate authenticated hosting design and source-use review.
