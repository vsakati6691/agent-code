# Dashboard deployment and synchronization

The deployable code is `main`. A PR merged into another feature branch has not
reached `main`; consolidate those changes in a PR targeting `main` before
expecting them on the public dashboard.

## Code changes

`research-dashboard-publish` runs after a push to `main`, or a manual dispatch
on `main`, when `DASHBOARD_PUBLISH=true`. It runs pytest and Ruff, checks out
`research-data` with read-only repository permission, verifies snapshot and daily
manifests, renders the site, and checks every internal link and HTML page budget.
It refuses to upload changed data. This workflow does not collect data, rescore
research or write to `research-data`.

All three publish workflows share the `research-dashboard` concurrency group.
They require `main` for deployment and reject a build whose code commit has been
superseded on `main`. Only the deployment job gets Pages and OIDC write access.
Action revisions are pinned, following [GitHub's custom Pages workflow
guidance](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Verify what is live

1. Confirm the latest `research-dashboard-publish`, weekly or daily workflow
   completed its **deploy** job successfully. A green CI run alone is not a deployment.
2. Read the live [build metadata](https://vsakati6691.github.io/agent-code/build.json).
   `code_commit` should match the deployment's commit and the intended `main` tip.
   `data_commit` identifies the exact stored-data revision used for that build.
3. Open the [audit page](https://vsakati6691.github.io/agent-code/audit.html#site-build)
   and check the build time, snapshot date and missing-data explanations.
4. Check all 14 tabs and one company page at 1440 × 900 and 390 × 844 in both
   themes, including ticker navigation from nested pages, downloads, disclosures
   and readable no-JavaScript output. Use the [UI browser commands](DASHBOARD_UI.md#verification)
   against fixture and public local builds before deployment; the [test report](ux/2026-10-17/BROWSER_TESTS.md)
   records the full interaction checks and fixed calculator regression.

The current registered methodology can be newer than the last stored snapshot.
That is expected after a code-only deployment: immutable snapshots retain their
original rules, hashes and missing data. The metadata and page labels show both
versions; a newer renderer is not evidence that fresh market data was collected.

If deployment fails, the last successful Pages deployment remains live. Fix the
failure in a PR, run all checks, and merge only on the owner's instruction. Do
not rewrite snapshots or relax the HTML budget to hide a failure.

## Windows preview

Use `git -c core.autocrlf=false worktree add --detach research-data
origin/research-data` for a new read-only preview checkout, as shown in README.
Line-ending conversion changes hashed bytes. If a local checkout fails integrity,
compare the exact Git blobs before treating it as a production-data failure; do
not edit manifests or snapshots to make a check pass.

Generated JavaScript/CSS can use CRLF on a Windows preview and LF on the Linux
deployment runner. For source-parity diagnostics, compare those text assets
after normalizing line endings. This exception applies only to generated asset
text: snapshot, daily and manifest integrity always uses the exact stored bytes.
