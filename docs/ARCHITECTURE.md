# Architecture and detailed rules

Detail moved out of [README.md](../README.md) on 2026-10-13. The README keeps the summary; this page keeps the diagrams and full tables.

## Diagrams

### System overview

```mermaid
flowchart LR
    subgraph Sources["Data sources (read-only)"]
        RH["Robinhood MCP<br/>account, prices, quotes,<br/>fundamentals"]
        FD["Financial Datasets<br/>S&P 500 list, news"]
        BD["Bigdata.com<br/>economic calendar, news"]
    end

    subgraph Session["Scheduled Claude Code session"]
        COLLECT["Collect data<br/>save JSON to scratchpad"]
        IMPORT["Import and validate<br/>reject stale or bad data"]
    end

    subgraph Engine["agent_trading (Python)"]
        A["A: S&P 500 scanner"]
        B["B: Desk<br/>TQQQ, SQQQ, IBIT, NVDA"]
        C["C: GTAA<br/>7 ETFs, monthly"]
        RISK["RiskEngine<br/>sizing and loss limits"]
        PAPER["Paper broker<br/>simulated fills"]
        LIVE["Live tickets<br/>real account, $1,000 cap"]
        REPORT["Daily report<br/>and run log"]
    end

    OWNER(["Owner places tickets<br/>in the Robinhood app"])
    PHONE(["Phone alert"])

    RH --> COLLECT
    FD --> COLLECT
    BD --> COLLECT
    COLLECT --> IMPORT --> A & B & C
    A -- paper only --> RISK
    B --> RISK
    C --> RISK
    RISK --> PAPER --> REPORT
    RISK --> LIVE --> REPORT
    REPORT --> PHONE --> OWNER
```

### From signal to ticket (post-close run)

```mermaid
flowchart TD
    START["Post-close run<br/>(about 4:40 PM ET)"] --> SNAP{"Account snapshot<br/>fresh and from the configured account?"}
    SNAP -- no --> FAIL["No tickets<br/>alert: run FAILED"]
    SNAP -- yes --> RECON["Check previous tickets:<br/>filled, open or not placed"]
    RECON --> STOPS{"Every position has<br/>a stop-loss order?"}
    STOPS -- no --> WARN["Warn: Add stop"]
    STOPS -- yes --> LIMITS
    WARN --> LIMITS{"Daily loss under $10 and<br/>drawdown under $50?"}
    LIMITS -- no --> HALT["No new buys<br/>alert: HALTED"]
    LIMITS -- yes --> SIGNALS["Run B (desk) and C (GTAA)<br/>on the REAL positions"]
    HALT -- sells only --> SELLS
    SIGNALS --> SELLS["SELL tickets for held<br/>positions the rules exit"]
    SELLS -- if not halted --> BUYS["BUY candidates"]
    BUYS --> SIZE{"RiskEngine:<br/>$5 risk, $15 total, $250 max,<br/>correlation, cash"}
    SIZE -- rejected --> SKIP["Listed as not ticketed"]
    SIZE -- approved --> GATE{"Order gate (fail closed):<br/>$100/order, $200 + 3 entries/day,<br/>$800 exposure, $200 cash reserve,<br/>no leveraged ETFs, kill switch off"}
    GATE -- rejected --> SKIP
    GATE -- approved --> TICKET["BUY ticket:<br/>qty, limit, stop-loss"]
    TICKET --> OUT["Report + phone alert<br/>Trades to place"]
```

### A day in the system

```mermaid
sequenceDiagram
    autonumber
    participant S as Scheduled session
    participant R as Robinhood (read-only)
    participant P as Python engine
    participant O as Owner
    Note over S,O: ~8:40 AM ET, pre-market
    S->>R: account, quotes
    S->>P: daily --no-paper
    P-->>S: repeats last tickets, flags stops
    S-->>O: alert only if something needs action
    Note over O,R: 9:30 AM ET onward
    O->>R: places tickets by hand (limit buy, then GTC stop-loss)
    Note over S,O: ~4:40 PM ET, post-close
    S->>R: account, positions, orders, prices
    S->>P: daily (paper broker + live tickets)
    P-->>S: report with tickets
    S-->>O: alert: trades to place, add stop, failed or halted
```

### Strategy B rules (pre-registered)

| Instrument | Entry | Exit / limits |
|---|---|---|
| TQQQ | QQQ close > 50-day SMA > 200-day SMA, QQQ above its 20-day SMA, QQQ 20-day volatility ≤ 25% | QQQ closes below its 20-day SMA, stop, or **5-day maximum hold**; **$2.50 max risk** |
| SQQQ | QQQ close < 50-day SMA < 200-day SMA, QQQ below its 20-day SMA, volatility ≤ 30% | Mirror image; same 5-day and $2.50 limits; **never held together with TQQQ** |
| Both leveraged ETFs | No entry within 1 day of a high-impact US release (CPI, FOMC, jobs…) or a Nasdaq-leader earnings date, measured from the fill day. A missing calendar also blocks entries | |
| NVDA | Close > 20-day SMA > 50-day SMA, 63-day momentum > 0, RSI < 75, relative strength vs SMH ≥ 0, no earnings within 5 days (an unknown date blocks entries) | Close below the 50-day SMA, or the stop |
| IBIT | Same trend rules (tracks spot bitcoin; trades only in US hours; spot BTC itself is not used) | Close below the 50-day SMA, or the stop |

## Live tickets (real account)

| Setting (`live:` in `config/settings.yaml`) | Value |
|---|---|
| Account | Robinhood "Agent-trading" (the configured account) only; snapshot must be under 24 hours old |
| Capital used for sizing | At most $1,000, whatever the account holds |
| Strategies | B (desk) and C (GTAA). A stays paper-only |
| Order type | Day limit order at the last close ± 0.5%; after a buy fills, a GTC stop-loss sell at the ticket's stop |
| Blocks | No new buys while any buy order is open, after a loss limit, or with an unverified snapshot |
| Positions opened by hand | Stop unknown, so their whole value counts as risk (blocks new buys) |
| Checks each run | Previous tickets (filled / still open / not placed); positions not fully covered by open stop sell orders (limit sells don't count) |
| Same-day reruns | Earlier tickets for the day are kept and count against the daily limits; a symbol is never ticketed twice in a day |
| Alerts | One phone alert only for: trades to place, a missing stop, a failed run, or a halt |

GTAA tickets appear only on the last trading day of a month. Desk tickets
appear only when its rules fire, so most days have no tickets.

## Daily report sections

The daily report (`reports\daily_two_strategy_<date>_<label>.md`) has these sections:
- **A: Scanner.** Market regime, coverage (scanned vs expected constituents), top 10, actionable setups with entry, stop, target and evidence, and rejections.
- **B: Desk.** One section per instrument: signal, reasons, live quote, sizing, catalysts.
- **C: GTAA.** The current signals.
- **C (account):** Broker snapshot, live sizing, live loss limits and positions, paper positions, risk status.
- **D: Actions.** Research findings, paper actions, the status of the previous live tickets, and the **live order tickets** to place by hand.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Account, positions, orders | Robinhood MCP (read-only, Agent-trading account) | Stored masked (last 4 digits only), rejected if over 24 hours old |
| Daily price history | Robinhood MCP `get_equity_historicals` | Split-adjusted. Never use `adjustment_type: all` for daily bars |
| Fundamentals, earnings dates | Robinhood MCP `preview_scan` (bulk, by market-cap band) | Current only, not point-in-time |
| Live quotes, spreads | Robinhood MCP `get_equity_quotes` | |
| S&P 500 constituents | Financial Datasets `get_index_fund` (SPY holdings) | Point-in-time lists from 2019. **Prepaid; balance currently exhausted** |
| News, SEC filings | Financial Datasets (headlines are unverified); Bigdata.com fallback | |
| Economic calendar | Bigdata.com | Drives the leveraged-ETF event blackout |
| T-bill rate, daily backup prices | Alpha Vantage (free key in `.env`) | 25 requests/day |

## Known limitations

- **Survivorship bias:** about 10% of historical S&P 500 members are missing from the scanner backtest, either because the filing omits the ticker or because the stock is delisted on Robinhood. No point-in-time lists are available after Sept 2023.
- **Fundamentals:** current values only, so they can't be backtested.
- **Dividends:** the GTAA backtest uses total return (dividend-adjusted), but the daily GTAA signals and the other backtests use price-only bars.
- **Daily bars only:** intraday stop fills, partial fills, halts and taxes are not modelled. `market_calendar.py` models regular NYSE holidays and recorded exceptional closures; it is not a live exchange-status feed. Price-cache staleness remains conservatively measured in weekdays.
- **News:** headlines are unverified until the article is read.

