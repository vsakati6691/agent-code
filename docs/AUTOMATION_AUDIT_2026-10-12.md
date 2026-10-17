# Automated execution: audit, gaps and plan (2026-10-12)

> Historical proposal, not current authorization. The automated-execution and
> credential-storage proposals below are superseded by [CLAUDE.md](../CLAUDE.md):
> brokerage access is read-only, all live tickets are placed manually by the
> owner, and secrets stay in `.env`. Retained for the audit trail; do not
> implement those proposals. See [the 2026-10-17 fixes](AUDIT_FIXES_2026-10-17.md).

Scope: can `agent-code` become an unattended trading system on the existing
Robinhood Agent-trading account (the configured account)? No order was placed, reviewed,
modified or cancelled during this audit. Every Robinhood call was read-only:
`get_accounts` and `get_trade_approval_setting`.

## 1. Current architecture (baseline: `3940ccc`, 223/223 tests passing)

- **Scheduled Claude Code sessions** (desktop app tasks) call the Robinhood, Financial Datasets and Bigdata.com MCP servers. They save JSON files, and Python imports them.
- **Python package `agent_trading`:**
  - strategies A (S&P 500 scanner), B (desk) and C (GTAA);
  - `RiskEngine`, a simulated `PaperBroker` and a SQLite journal;
  - `live.py` writes **order tickets**, which `order_gate.py` checks (hard limits);
  - a persistent kill switch, an NYSE calendar, a tournament with an append-only registry, and reports.
- **Execution:** none. The owner places tickets by hand in the Robinhood app. A static test fails if any source file references a broker order tool. This is a deliberate rule in `CLAUDE.md`.

## 2. Why unattended trading did not happen

1. **By design.** On 2026-10-12 the owner chose manual tickets. The repo forbids order code, and `tests/test_safety_guards.py` enforces that.
2. **Broker approvals are on.** This was verified today: `human_must_approve_trades: true`, set 2026-10-12 15:27 UTC. Any agent order waits for a tap in the app. Only the owner can change this, in the app.
3. **Python cannot reach the broker.** The only supported equity trading interface is Robinhood's agent MCP server, an OAuth-authenticated MCP connection. Today only the AI client (Claude) holds that connection, so every data pull depends on a live AI session.
4. **The scheduler is not reliable.** Desktop-app scheduled tasks need the app open and the PC awake. On 2026-10-12 the 12:37 ET run stayed active for about 54 minutes, most likely stalled on a permission prompt.
5. **Claude does not place orders.** This holds under both the repo rules and Claude's own operating rules. Switching AI models does not fix items 3 and 4. Codex would also be an agent session holding the MCP connection.

## 3. Robinhood capabilities actually available

Sources: tool schemas in this environment, read-only calls, and Robinhood's own pages ([agentic trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/), [newsroom](https://robinhood.com/newsroom/robinhood-is-now-open-to-agents/)).

| Capability | Status | Evidence |
|---|---|---|
| Accounts, cash, buying power, positions, orders (read) | VERIFIED WORKING (via the Claude MCP session) | `get_accounts` today; portfolio, positions and orders in earlier audits |
| Quotes, daily historicals since 2005, fundamentals, scanner, earnings | VERIFIED WORKING (via the MCP session) | Earlier audits; daily `adjustment_type: all` data is wrong |
| Place equity order | EXISTS, NOT VERIFIED | `place_equity_order` supports market, limit, stop_market and stop_limit orders; gfd or gtc; regular, extended and 24-hour sessions; and a `ref_id` idempotency key. Fractional shares only on market orders in regular hours |
| Cancel order | EXISTS, NOT VERIFIED | `cancel_equity_order` |
| Order status lookup | EXISTS | `get_equity_orders` by `order_id`, or a list filtered by state, symbol or time. There is **no lookup by `ref_id`**. To resolve a timeout, the adapter must either re-send the same `ref_id` (Robinhood says it de-duplicates) or match recent orders by symbol and time |
| Unattended (no per-trade approval) | SUPPORTED BY ROBINHOOD, BLOCKED HERE | Robinhood's disclosures allow trades without per-trade input when approvals are off. Today approvals are ON |
| Clients | Robinhood lists Claude, ChatGPT, Codex, Codex CLI, Cursor, Grok and "any localhost platform" | No public REST API for equities; endpoint `https://agent.robinhood.com/mcp/trading` |
| Token lifetime and re-authentication | UNKNOWN | Not documented. Robinhood's only fix offered is "disconnect and reconnect". This must be measured |
| Account type | `limited_margin`, options level 2 | **Not a cash account.** The code enforces settled cash only. Ask Robinhood whether the agentic account can be cash-only |
| Options, crypto, margin | Present at the broker; banned by owner rules and by config validation | — |

## 4. Gaps: connectors, packages, credentials, infrastructure

| Need | Gap | Best supported option |
|---|---|---|
| Broker access outside an AI chat | No Python MCP client | Official `mcp` Python SDK as an OAuth client of the Robinhood MCP (read-only first; prove the token survives for days). Fallback: Codex CLI or Claude headless as the scheduled MCP client |
| Market data for about 500 symbols daily without an AI session | Alpha Vantage is the free key: 25 calls/day | The same Robinhood MCP client (historicals and quotes), or Alpha Vantage premium (about $50/mo, verify) |
| S&P 500 constituents | Financial Datasets prepaid balance exhausted | Pay-as-you-go top-up, or the issuer's published SPY holdings file (free; check its terms) |
| Fundamentals and filings | Works | SEC EDGAR XBRL (free) |
| News, LLM summaries | No OpenAI key or package | Optional. `openai` package plus `OPENAI_API_KEY`. Summaries only; never prices or order status |
| Scheduler and supervisor | Desktop-app tasks only | Windows Task Scheduler (`At startup` + `Restart on failure`) running a Python daemon, or a $5–12/mo VPS |
| Alerts | Phone alert only from Claude sessions | ntfy.sh (free) or SMTP email from Python |
| Secrets | `.env` only | Windows Credential Manager via `keyring` for the OAuth refresh token |

## 5. Implementation plan (smallest viable changes, in order)

1. **Execution core.** Done in this change: `src/agent_trading/execution/`, described in §8.
2. **Paper daemon.** A `run-service --mode paper|dry_run` loop:
   - market-session scheduling, start-up health check and reconciliation;
   - a heartbeat file, JSON logs and a missed-run alarm;
   - the GTAA and desk intents converted to whole-share limit orders.
   - Install it under Task Scheduler and verify it survives a reboot.
3. **Read-only Robinhood MCP client in Python.** Authenticate once (the owner does the login). Then measure token lifetime and refresh over at least 5 trading days. This decides whether unattended access is feasible.
4. **Promotion gate.** The live service may only run strategies whose tournament registry entry passed `ACCEPTANCE` on untouched data, recorded with a config hash. **Today no strategy passes (0/8).** GTAA is the closest, but it is still a modest edge.
5. **Paper period.** At least 20 trading days on live data, with forced drills: kill the process mid-order, network loss, a stale quote, a broker outage, and a reboot.
6. **Live adapter (owner decision).** A `RobinhoodMcpBroker` with `is_live = True`. It is used only when all of these hold:
   - live mode is selected explicitly;
   - a signed readiness file exists;
   - the promotion gate passes;
   - the kill switch is off;
   - the hard limits are unchanged.
   Building it requires the owner to retire `CLAUDE.md` hard rule 1 for this one module. Claude will not place the first live order or any later one. The owner verifies the first live orders.

## 6. Estimated monthly cost (USD, verify current prices)

| Item | Cost |
|---|---|
| Robinhood commissions | $0. Regulatory fees on sells are cents |
| Robinhood MCP | No fee stated. Robinhood links a separate token-usage billing article that was not reviewed |
| Market data | $0 via the Robinhood MCP client; Alpha Vantage premium about $50 if needed |
| Constituents | $0–10 |
| OpenAI API (optional summaries with a small model, about 50/day) | Low single-digit dollars. ChatGPT Plus and Codex plans do not include API credits |
| Hosting | $0 on the home PC (must stay on); $5–12 for a small VPS |
| Alerts | $0 (ntfy.sh) |
| **Total** | **About $0–15/mo** without premium data; **about $55–75/mo** with it |

Context: with $1,000 and the hard limits, the backtests support cents per day (see `docs/FINAL_REPORT_2026-10-12.md`). Paying for data can cost more than the strategy is expected to earn.

## 7. Tests required before any live order

- Unit and failure drills for the execution service (done, §8).
- The live adapter against a recorded or mocked MCP: payload mapping, `ref_id` reuse, timeout resolution without a duplicate, partial fill, reject, cancel, and rate-limit or 5xx responses.
- Token-expiry handling: an expired token must block orders, raise an alert and never retry in a loop.
- A daemon reboot test: Task Scheduler restart, start-up reconciliation, and no duplicate orders after a restart.
- At least 20 paper days with daily reconciliation, with zero unexplained mismatches.
- The promotion gate passes on untouched data.
- The owner verifies the first small live orders in the app; approvals stay ON for that phase.

## 8. What this change adds (`src/agent_trading/execution/`, 26 tests)

- **`ledger.py`:**
  - each attempt is saved to SQLite with a fresh `ref_id` **before** submission;
  - `decision_id` is unique, so the same decision is never sent twice, even after a restart;
  - there is an append-only event log.
- **`validator.py`:** a fail-closed check before every order:
  - kill switch; the regular-session window, with buffers and early closes;
  - whole shares, limit orders and day orders only;
  - quote age, spread, and how far the limit sits from the quote;
  - the allowlist, with no leveraged or inverse ETFs;
  - nothing unresolved for the symbol, no open broker order, and no shorting;
  - one position per ticker;
  - $100 per order; $200 and 3 entries per day;
  - $800 exposure, the capital cap, and a $200 reserve from **settled** cash.
- **`service.py`:**
  - validate, persist, submit once, then read back the real state;
  - timeouts become `UNKNOWN` and are **never resubmitted**: they are looked up on every run and block their symbol;
  - only the owner can clear an `UNKNOWN` order, with an exact phrase;
  - daily loss halts buys, and a 5% drawdown engages the kill switch;
  - start-up reconciliation of broker positions against baseline plus fills: a mismatch engages the kill switch;
  - `halt()` engages the kill switch and cancels open orders;
  - modes are `dry_run` (never calls submit) and `paper`; `live` is refused, and so is any broker reporting `is_live`.
- **`sim.py`:** a simulated broker:
  - `ref_id` de-duplication, marketable-limit fills and T+1 settlement of sale proceeds;
  - injected faults: timeout after accept, timeout before accept, not sent, reject, partial fill, and outage.
