"""Daily two-strategy cycle and report.

  1. load validated data (prices, constituents, snapshots) and check freshness
  2. Strategy A: scan every S&P 500 constituent with price data
  3. Strategy B: decide TQQQ / SQQQ / IBIT / NVDA
  4. turn signals into intents and run the paper broker (fills, stops, limits)
  5. write the report: A scanner, B desk, C account and risk, D actions

Nothing here can place a real order. "Orders awaiting authorization" is always
empty because live execution is disabled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import regime as regime_mod
from .account import load_saved_snapshot, verify_snapshot
from .config import Settings
from .data.service import MarketDataService
from .data.snapshots import high_impact_events, load_snapshot
from .data.universe import coverage, load_universe, universe_problems
from .journal import Journal
from .paper import Intent, PaperBroker, portfolio_state
from .strategies.desk import DeskDecision, Position, run_desk
from .strategies.scanner import ScanResult, run_scan

DISCLAIMER = ("> Research and paper-trading output only. Not investment advice. No live orders are placed. "
              "Signals are hypotheses; confidence labels are rule counts, not probabilities.")


@dataclass
class DailyContext:
    as_of: date
    data_notes: list[str] = field(default_factory=list)
    universe_note: str = ""
    coverage: dict | None = None
    scan: ScanResult | None = None
    market: dict | None = None
    desk_regime: dict | None = None
    desk: list[DeskDecision] = field(default_factory=list)
    paper_events: list[str] = field(default_factory=list)
    paper_warnings: list[str] = field(default_factory=list)
    proposals: list = field(default_factory=list)
    status: object = None
    snapshots: dict = field(default_factory=dict)


def _fmt(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{d}f}"


def _pct(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{d}%}"


def _earnings_lookup(fund: pd.DataFrame | None, cal, as_of: date):
    fmap = {}
    if fund is not None and not fund.empty:
        for r in fund.itertuples():
            if isinstance(r.earnings_date, str):
                fmap[r.ticker] = date.fromisoformat(r.earnings_date)

    def lookup(sym: str):
        dates = [d for d in [fmap.get(sym)] if d is not None and d >= as_of]
        known = sym in fmap
        if cal is not None and cal.available:
            hits = cal.table[(cal.table["symbol"] == sym) & (cal.table["reportDate"] >= as_of)]
            dates += list(hits["reportDate"])
            known = True
        return (min(dates) if dates else None), known

    return lookup


def run_daily(settings: Settings, as_of: date, run_paper: bool = True) -> tuple[str, DailyContext]:
    ctx = DailyContext(as_of)
    svc = MarketDataService(settings)
    journal = Journal(settings.resolve(settings.paths.journal_db))

    # --- inputs
    universe = load_universe(settings)
    problems = universe_problems(universe, settings, as_of)
    ctx.universe_note = "; ".join(problems) if problems else f"{len(universe.tickers)} constituents as of {universe.as_of} ({universe.source})"
    snaps = {k: load_snapshot(settings, k) for k in ("fundamentals", "quotes", "news", "filings", "econ")}
    ctx.snapshots = snaps
    for k, s in snaps.items():
        if s is None:
            ctx.data_notes.append(f"{k}: not available")
        else:
            ctx.data_notes.append(f"{k}: {len(s.table)} rows from {s.source}, fetched {s.fetched_at:%Y-%m-%d %H:%M} UTC "
                                  f"({s.age_hours():.0f}h old)")
    fund = snaps["fundamentals"].table if snaps["fundamentals"] is not None and snaps["fundamentals"].age_hours() <= 72 else None
    quotes = snaps["quotes"].table if snaps["quotes"] is not None and snaps["quotes"].age_hours() <= 24 else None
    cal = svc.earnings(as_of)
    lookup = _earnings_lookup(fund, cal, as_of)

    # --- Strategy A
    sc = settings.scanner
    desk_syms = list(dict.fromkeys([*settings.desk.symbols, settings.desk.underlying, settings.desk.nvda_benchmark, sc.benchmark]))
    loaded_desk = svc.load(desk_syms, as_of)
    bench = loaded_desk.bars.get(sc.benchmark)
    if bench is not None:
        ctx.market = regime_mod.current(bench, settings.regime)
    if universe is not None and not problems:
        loaded = svc.load(universe.tickers, as_of)
        ctx.coverage = coverage(universe, list(loaded.bars), loaded.rejected)
        ctx.scan = run_scan(loaded.bars, settings, as_of, fund, quotes,
                            cal.table if cal.available else None, bench)
    elif universe is not None:
        ctx.data_notes.append("Strategy A skipped: " + "; ".join(problems))

    # --- Strategy B
    open_df = journal.open_trades()
    positions = {t.symbol: Position(t.quantity, t.entry_price, t.stop_price, date.fromisoformat(t.entry_date))
                 for t in open_df.itertuples()} if not open_df.empty else {}
    events = high_impact_events(snaps["econ"], as_of, settings.desk.event_blackout_days)
    ctx.desk_regime, ctx.desk = run_desk(loaded_desk.bars, settings, as_of, positions, events, lookup)

    # --- paper broker
    intents: list[Intent] = []
    for d in ctx.desk:
        if d.action == "BUY" and d.stop is not None and d.price is not None:
            intents.append(Intent(d.symbol, "buy", d.price, d.stop, "B-desk", f"desk BUY ({d.confidence})", 1.0))
        elif d.action == "SELL/REDUCE":
            intents.append(Intent(d.symbol, "sell", d.price or 0.0, None, "B-desk", "; ".join(d.reasons)))
    if ctx.scan is not None:
        for s in ctx.scan.actionable:
            intents.append(Intent(s.ticker, "buy", s.entry_ref, s.stop, "A-scanner",
                                  f"scanner rank {s.rank} (score {s.composite:.2f})", s.composite))
        tbl = ctx.scan.table
        for sym in positions:
            if sym in tbl.index and sym not in settings.desk.symbols:
                row = tbl.loc[sym]
                if row["close"] < row["sma50"] or row["setup"] == "bearish":
                    intents.append(Intent(sym, "sell", float(row["close"]), None, "A-scanner",
                                          "close below the 50-day SMA" if row["close"] < row["sma50"] else "setup turned bearish"))
    all_bars = dict(loaded_desk.bars)
    if ctx.scan is not None:
        all_bars.update(loaded.bars)
    broker = PaperBroker(settings, journal)
    if run_paper and all_bars:
        res = broker.run(all_bars, None, cal, as_of, intents=intents)
        ctx.paper_events, ctx.paper_warnings, ctx.proposals = res.events, res.warnings, res.new_orders
    ctx.status = broker.status(all_bars, as_of) if all_bars else None
    text = render(settings, ctx, journal, broker, all_bars)
    return text, ctx


# ---------------------------------------------------------------- rendering

def _table(headers, rows):
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def render(settings: Settings, ctx: DailyContext, journal: Journal, broker: PaperBroker, bars) -> str:
    as_of = ctx.as_of
    out = [f"# Daily trading research: {as_of}", "",
           f"**Mode: PAPER** · generated {datetime.now():%Y-%m-%d %H:%M} local", "", DISCLAIMER, "",
           "## Data sources and freshness", ""]
    out += [f"- {n}" for n in ctx.data_notes]
    out += [f"- S&P 500 constituents: {ctx.universe_note}", ""]

    # ---------------- Section A
    out += ["## Section A: S&P 500 scanner", ""]
    if ctx.market:
        m = ctx.market
        out.append(f"**Market regime ({settings.scanner.benchmark}, {m['date']}):** trend **{m['trend']}**, volatility "
                   f"{m['volatility']} ({_pct(m['realized_vol'], 0)} annualised), {_pct(m['close_vs_slow_ma'])} vs 200-day SMA.\n")
    events = high_impact_events(ctx.snapshots.get("econ"), as_of, 7)
    if events is None:
        out.append("**Economic calendar:** unavailable or stale. Event risk is unverified.\n")
    elif not events.empty:
        out.append("**High-impact US releases (next 7 days):** " + "; ".join(
            f"{r.date} {r.name}" for r in events.drop_duplicates(["date", "name"]).itertuples()) + "\n")
    cov = ctx.coverage
    if cov is None:
        out.append("**Coverage:** scan not run (see data notes).\n")
    else:
        flag = "" if cov["ratio"] >= settings.scanner.min_coverage else " ⚠ **incomplete scan**"
        out.append(f"**Coverage:** scanned {cov['scanned']} of {cov['expected']} constituents ({cov['ratio']:.1%}){flag}.")
        if cov["missing"]:
            sample = list(cov["missing"].items())[:10]
            out.append("Missing: " + "; ".join(f"{t} ({r.split(': ', 1)[-1]})" for t, r in sample)
                       + (f"; +{len(cov['missing']) - 10} more" if len(cov["missing"]) > 10 else "") + "\n")
        else:
            out.append("")
    scan = ctx.scan
    if scan is not None and not scan.table.empty:
        out += ["### Top 10 research candidates (ranked by composite score)", "",
                "Score = 0.35 price strength (12-1 momentum, RS vs SPY, distance above 200-day, one combined factor) "
                "+ 0.10 up/down volume + 0.20 quality (operating margin, ROE) + 0.10 valuation (forward earnings yield within sector) "
                "+ 0.25 low volatility. Missing factors are reweighted and listed.", ""]
        rows = []
        for s in scan.research:
            r = scan.table.loc[s.ticker]
            rows.append([s.rank, s.ticker, _fmt(r["close"]), f"{s.composite:.2f}", s.setup, _pct(r["mom_12_1"]),
                         _pct(r["rs_63"]), _fmt(r["rsi"], 0), s.earnings_date or "unverified", r["missing_factors"] or "-"])
        out.append(_table(["#", "Ticker", "Close", "Score", "Setup", "12-1 mom", "RS vs SPY 63d", "RSI", "Earnings", "Missing"], rows))
        out += ["### Top actionable setups (passed every filter)", ""]
        if not scan.actionable:
            out.append("_None today. Cash is a valid position._\n")
        for s in scan.actionable:
            out += [f"**{s.ticker}** (rank {s.rank}, score {s.composite:.2f}, {s.setup})",
                    f"- Entry: next open, reference {_fmt(s.entry_ref)}; skip above {_fmt(s.max_entry)}",
                    f"- Invalidation / stop: {_fmt(s.stop)} ({settings.risk.atr_stop_multiple} × ATR); a stop does not guarantee the fill price",
                    f"- Target: {_fmt(s.target)} ({s.reward_risk:.0f}R methodology); holding: {s.holding_period}",
                    "- Evidence: " + "; ".join(s.evidence),
                    "- Risks: " + "; ".join(s.risks), ""]
        if scan.rejected:
            out += ["### Rejected high-ranked candidates", ""]
            out += [f"- **{t}**: " + "; ".join(r) for t, r in list(scan.rejected.items())[:10]]
            out.append("")
        if scan.bearish:
            out.append("**Bearish setups (avoid / exit if held; no short selling):** " + ", ".join(scan.bearish) + "\n")

    # ---------------- Section B
    out += ["## Section B: Focused desk (TQQQ, SQQQ, IBIT, NVDA)", ""]
    reg = ctx.desk_regime
    if reg:
        out.append(f"**QQQ regime:** {reg['trend']} trend, {'above' if reg['above_sma20'] else 'below'} 20-day SMA, "
                   f"20-day volatility {reg['vol20']:.0%} (as of {reg['date']}).\n")
    news = ctx.snapshots.get("news")
    proposals = {p.symbol: p for p in ctx.proposals}
    for d in ctx.desk:
        out.append(f"### {d.symbol}: **{d.action}** (confidence: {d.confidence})")
        out.append(f"- Price: {_fmt(d.price)} (close of {d.price_date}; latest verified daily bar)")
        out.append(f"- Trend: {d.trend}")
        out.append("- Reasons: " + "; ".join(d.reasons))
        if d.action in ("BUY", "WAIT"):
            out.append(f"- Entry conditions: {d.entry_conditions}")
        if d.stop is not None:
            out.append(f"- Invalidation / stop: {_fmt(d.stop)}")
        p = proposals.get(d.symbol)
        if p is not None:
            out.append(f"- Paper sizing: {('qty ' + format(p.quantity, 'g') + f', notional ${p.notional:,.2f}, planned risk ${p.risk:,.2f}') if p.approved else 'not sized: ' + p.reason}")
        if d.position:
            unreal = (d.price - d.position.entry_price) * d.position.quantity if d.price else None
            out.append(f"- Paper position: {d.position.quantity:g} @ {_fmt(d.position.entry_price)} since {d.position.entry_date}; unrealized ${_fmt(unreal)}")
        out.append(f"- Holding period: {d.holding_period}")
        out.append(f"- What would change the decision: {d.what_changes}")
        if d.catalysts:
            out.append("- Catalysts / notes: " + "; ".join(d.catalysts))
        if news is not None and not news.table.empty:
            heads = news.table[news.table["ticker"] == d.symbol].head(2)
            for h in heads.itertuples():
                out.append(f"- News (UNVERIFIED headline, {h.source}, {h.date}): {h.title}")
        out.append("")

    # ---------------- Section C
    out += ["## Section C: Account and portfolio risk", ""]
    snap = load_saved_snapshot(settings)
    if snap is None:
        out.append("- Broker account: **not verified** (no snapshot imported)")
    else:
        probs = verify_snapshot(snap, settings)
        out.append(f"- Broker account {snap.nickname} ••{snap.account_last4}: "
                   f"{'verified' if not probs else 'NOT VERIFIED (' + '; '.join(probs) + ')'} as of {snap.fetched_at}; "
                   f"value ${snap.total_value:,.2f}, cash ${snap.cash:,.2f}, buying power ${snap.buying_power:,.2f}, "
                   f"{len(snap.positions)} positions, {len(snap.open_orders)} open orders")
    state = portfolio_state(journal, settings, bars, pd.Timestamp(as_of))
    r = settings.risk
    out.append(f"- Paper equity ${state.equity:,.2f}, cash ${state.cash:,.2f}, planned open risk "
               f"${state.open_risk(r.stop_risk_buffer):,.2f} of ${state.equity * r.max_open_risk_pct:,.2f}")
    st = ctx.status
    if st is not None:
        out.append(f"- Loss limits: day P&L ${st.day_pnl:,.2f} (limit -${state.equity * r.daily_loss_limit_pct:,.2f}), "
                   f"drawdown ${st.drawdown:,.2f} from peak ${st.peak_equity:,.2f} (limit {r.max_drawdown_pct:.0%}): "
                   f"**{'new entries allowed' if st.new_entries_allowed else st.reason}**")
    pos = broker.positions(bars, as_of)
    out.append("")
    out.append(_table(["Symbol", "Qty", "Entry", "Stop", "Last", "Unrealized"],
                      [[p.symbol, f"{p.quantity:g}", _fmt(p.entry_price), _fmt(p.stop_price), _fmt(p.last), _fmt(p.unrealized)]
                       for p in pos.itertuples()] if not pos.empty else []))
    hist = broker.equity_history()
    bench = bars.get(settings.scanner.benchmark)
    if len(hist) >= 2 and bench is not None:
        b = bench["close"].loc[hist.index[0]:hist.index[-1]]
        if len(b) >= 2:
            out.append(f"- Paper equity since {hist.index[0].date()}: {_pct(hist.iloc[-1] / hist.iloc[0] - 1)} vs "
                       f"SPY {_pct(b.iloc[-1] / b.iloc[0] - 1)}")
    else:
        out.append("- Performance vs SPY: not enough paper history yet")
    out.append("")

    # ---------------- Section D
    out += ["## Section D: Actions", "", "**1. Research findings**", ""]
    if scan is not None:
        out.append(f"- Scanner: {len(scan.actionable)} actionable of {len(scan.table)} scanned; "
                   f"top research name {scan.research[0].ticker if scan.research else 'n/a'}")
    out += [f"- {d.symbol}: {d.action}" for d in ctx.desk]
    out += ["", "**2. Paper-trading actions** (simulated; fills at the next open)", ""]
    out += [f"- {e}" for e in ctx.paper_events] or ["- none"]
    out += [f"- ⚠ {w}" for w in ctx.paper_warnings]
    rejected = [p for p in ctx.proposals if not p.approved]
    if rejected:
        out.append("- Not sized: " + "; ".join(f"{p.symbol} ({p.reason})" for p in rejected))
    out += ["", "**3. Orders awaiting your authorization:** none. Live execution is disabled in this system.", ""]
    return "\n".join(out)


def write(settings: Settings, text: str, as_of: date) -> Path:
    d = settings.resolve(settings.paths.reports_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"daily_two_strategy_{as_of.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    return path
