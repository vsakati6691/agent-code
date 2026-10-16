# Repository setup for the owner

These are review notes, not changes to GitHub settings.

## Description and topics

Suggested repository description:

> Public stock and options research dashboard with audited snapshots, paper trading and manual order tickets. No automated execution.

Suggested topics: `stock-research`, `etf`, `python`, `github-pages`,
`research-dashboard`, `backtesting`.

## Merge protection

Require the **Tests, lint and fixture site** CI check before merging to `main`.
The workflow has read-only contents permission and builds synthetic fixture
data; it does not deploy the public site or access brokerage data.

## Merged branches to review for cleanup

These four remote feature branches were merged into `main` at inspection on
2026-10-15 (main commit `74c5384`). No branch was deleted:

- `feature/ai-tab-and-dashboard-ux`
- `feature/daily-refresh`
- `feature/research-system`
- `feature/small-bet-view`

Before deleting one, verify its current tip is still fully merged and no active
chat or worktree needs it. The new review PRs use separate `codex/` branches.

## License

The project license awaits the owner's explicit choice. This change does not
grant a new license. [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and the
license texts it links govern the adapted third-party pieces regardless of the
project license. Software licensing does not grant market-data redistribution
rights.
