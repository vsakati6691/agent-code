"""Daily Markdown research report and HTML performance dashboard."""
from __future__ import annotations

import html
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .config import Settings
from .data.service import EarningsData, LoadResult
from .journal import Journal
from .risk import RiskViolation, size_position

DISCLAIMER = (
    "> Research and paper-trading output only. Not investment advice. No live orders are placed by this system. "
    "Signals are untested hypotheses until they hold up out-of-sample."
)


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{digits}%}"


def _num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{digits}f}"


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.2f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None._\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def next_earnings(earnings: EarningsData, symbol: str, as_of: date) -> date | None:
    if not earnings.available:
        return None
    t = earnings.table
    upcoming = t[(t["symbol"] == symbol) & (t["reportDate"] >= as_of)]
    return None if upcoming.empty else min(upcoming["reportDate"])


def _earnings_label(earnings: EarningsData, symbol: str, as_of: date, warn_days: int) -> str:
    if not earnings.available:
        return "UNVERIFIED"
    nxt = next_earnings(earnings, symbol, as_of)
    if nxt is None:
        return "none in 3 mo"
    flag = " ⚠" if (nxt - as_of).days <= warn_days else ""
    return f"{nxt}{flag}"


def build_daily_report(
    settings: Settings,
    loaded: LoadResult,
    screen: pd.DataFrame,
    earnings: EarningsData,
    journal: Journal,
    as_of: date,
    fetch_status: dict[str, str] | None = None,
) -> str:
    warn_days = settings.reports.earnings_warning_days
    summary = journal.summary(settings.paper_starting_equity)
    equity = summary["equity_realized"]
    cash = journal.cash(settings.paper_starting_equity)
    open_risk = summary["open_risk"]
    r = settings.risk

    out = [f"# Daily research report: {as_of}", "", "**Mode: PAPER** · generated "
           f"{datetime.now().strftime('%Y-%m-%d %H:%M')} local", "", DISCLAIMER, ""]

    # --- data quality
    out += ["## Data quality", ""]
    out.append(f"- Price series accepted: **{len(loaded.bars)}** of {len(loaded.bars) + len(loaded.rejected)}")
    if earnings.available:
        out.append(f"- Earnings calendar: {earnings.source}, fetched {earnings.fetched_at}")
    else:
        out.append(f"- Earnings calendar: **not verified** ({earnings.error}). Treat every name as possibly reporting soon.")
    if loaded.rejected:
        out += ["", "Rejected (not used anywhere in this report):", ""]
        out += [f"- {reason}" for _, reason in sorted(loaded.rejected.items())]
    if fetch_status:
        failed = {s: m for s, m in fetch_status.items() if not m.startswith(("updated", "up to date"))}
        if failed:
            out += ["", "Fetch issues:", ""] + [f"- {s}: {m}" for s, m in sorted(failed.items())]
    out.append("")

    if screen.empty:
        out += ["_No valid data; nothing to analyse._", ""]
        return "\n".join(out)

    # --- market overview
    etf_syms = [s for g, syms in settings.universe.items() if g.endswith("_etfs") for s in syms if s in screen.index]
    out += ["## Market overview (ETFs)", ""]
    out.append(_table(
        ["Symbol", "Close", "1d", f"Mom {settings.strategy.momentum_lookback}d", "RSI", "Uptrend", "Last bar"],
        [[s, _num(screen.at[s, "close"]), _pct(screen.at[s, "change_pct"]), _pct(screen.at[s, "momentum"]),
          _num(screen.at[s, "rsi"], 0), "yes" if screen.at[s, "uptrend"] else "no", str(screen.at[s, "date"])]
         for s in etf_syms],
    ))

    # --- screen
    out += ["## Screen", "",
            f"Liquidity filter: price ≥ ${settings.screen.min_price:.0f}, 20-day avg dollar volume ≥ "
            f"${settings.screen.min_avg_dollar_volume / 1e6:.0f}M. Sorted by entry signal, then momentum.", ""]
    out.append(_table(
        ["Symbol", "Close", "Mom", "RSI", "ATR %", "Vol ratio", "MACD hist", "Uptrend", "Entry", "Exit", "Earnings"],
        [[s, _num(row.close), _pct(row.momentum), _num(row.rsi, 0), _pct(row.atr_pct), _num(row.vol_ratio),
          _num(row.macd_hist), "yes" if row.uptrend else "no", "**yes**" if row.entry_signal else "no",
          "yes" if row.exit_signal else "no", _earnings_label(earnings, s, as_of, warn_days)]
         for s, row in screen.iterrows()],
    ))

    # --- candidates
    open_df = journal.open_trades()
    held = set(open_df["symbol"]) if not open_df.empty else set()
    out += ["## Paper-trade candidates (for next session)", "",
            f"Paper equity {_money(equity)}, cash {_money(cash)}, open risk {_money(open_risk)} of "
            f"{_money(equity * r.max_open_risk_pct)} allowed. Size uses last close as the reference; "
            f"the real fill will be at the next open.", ""]
    rows = []
    running_risk = open_risk
    for s, row in screen[screen["entry_signal"]].iterrows():
        if s in held:
            continue
        stop = row.close - r.atr_stop_multiple * row.atr
        note = ""
        try:
            d = size_position(equity, cash, row.close, stop, running_risk, r)
        except RiskViolation as exc:
            rows.append([s, _num(row.close), _num(stop), "0", "-", "-", str(exc)])
            continue
        nxt = next_earnings(earnings, s, as_of)
        if not earnings.available:
            note = "earnings unverified"
        elif nxt is not None and (nxt - as_of).days <= warn_days:
            note = f"earnings {nxt}: consider waiting"
        if d.quantity > 0:
            running_risk += d.risk_amount
            cash -= d.notional
        rows.append([s, _num(row.close), _num(stop), f"{d.quantity:g}", _money(d.notional), _money(d.risk_amount),
                     d.limited_by + (f"; {note}" if note else "")])
    out.append(_table(["Symbol", "Ref price", "Stop", "Qty", "Notional", "Risk", "Sizing limit / notes"], rows))

    # --- open positions
    out += ["## Open paper positions", ""]
    pos_rows = []
    for t in open_df.itertuples() if not open_df.empty else []:
        last = screen.at[t.symbol, "close"] if t.symbol in screen.index else None
        flags = []
        if last is None:
            flags.append("NO VALID PRICE")
        else:
            if last <= t.stop_price:
                flags.append("STOP BREACHED")
            if screen.at[t.symbol, "exit_signal"]:
                flags.append("exit signal")
        unreal = None if last is None else t.quantity * (last - t.entry_price)
        pos_rows.append([str(t.id), t.symbol, f"{t.quantity:g}", _num(t.entry_price), _num(t.stop_price),
                         _num(last), _money(unreal), _earnings_label(earnings, t.symbol, as_of, warn_days),
                         ", ".join(flags) or "-"])
    out.append(_table(["ID", "Symbol", "Qty", "Entry", "Stop", "Last", "Unrealized", "Earnings", "Flags"], pos_rows))

    # --- earnings
    out += ["## Upcoming earnings in universe (next 30 days)", ""]
    if earnings.available:
        t = earnings.table
        soon = t[t["symbol"].isin(settings.symbols) & (t["reportDate"] >= as_of)
                 & (t["reportDate"] <= as_of + timedelta(days=30))].sort_values("reportDate")
        out.append(_table(["Date", "Symbol", "Fiscal period", "EPS estimate"],
                          [[str(x.reportDate), x.symbol, str(x.fiscalDateEnding), str(x.estimate)] for x in soon.itertuples()]))
        out.append(f"_Source: {earnings.source}, fetched {earnings.fetched_at}. Confirm dates with the company's IR page._\n")
    else:
        out.append("_Not available: earnings dates are unverified today._\n")
    return "\n".join(out)


def write_report(settings: Settings, text: str, as_of: date) -> Path:
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"daily_{as_of.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- dashboard

_CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--pos:#15803d;--neg:#b91c1c;--accent:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;--line:#44403c;--pos:#4ade80;--neg:#f87171;--accent:#60a5fa}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}
.muted{color:var(--muted)}.pos{color:var(--pos)}.neg{color:var(--neg)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.tile b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}svg{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
"""


def _sparkline(values: list[float], width: int = 900, height: int = 220) -> str:
    if len(values) < 2:
        return '<p class="muted">Not enough data for a chart yet.</p>'
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    pad = 16
    pts = " ".join(
        f"{pad + i * (width - 2 * pad) / (len(values) - 1):.1f},{height - pad - (v - lo) * (height - 2 * pad) / span:.1f}"
        for i, v in enumerate(values)
    )
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="equity curve">'
            f'<polyline fill="none" stroke="var(--accent)" stroke-width="2" points="{pts}"/>'
            f'<text x="{pad}" y="14" font-size="11" fill="var(--muted)">{hi:,.2f}</text>'
            f'<text x="{pad}" y="{height - 4}" font-size="11" fill="var(--muted)">{lo:,.2f}</text></svg>')


def _tile(label: str, value: str, cls: str = "") -> str:
    return f'<div class="tile"><span class="muted">{html.escape(label)}</span><b class="{cls}">{html.escape(value)}</b></div>'


def build_dashboard(settings: Settings, journal: Journal, backtest: dict | None = None) -> str:
    s = journal.summary(settings.paper_starting_equity)
    closed = journal.closed_trades()
    sign = "pos" if s["realized_pnl"] > 0 else "neg" if s["realized_pnl"] < 0 else ""
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Paper Trading Dashboard</title><style>{_CSS}</style></head><body><main>",
        "<h1>Paper trading dashboard</h1>",
        f"<p class='muted'>Mode: PAPER · generated {datetime.now():%Y-%m-%d %H:%M} · not investment advice</p>",
        "<div class='tiles'>",
        _tile("Equity (realized)", _money(s["equity_realized"])),
        _tile("Realized P&L", _money(s["realized_pnl"]), sign),
        _tile("Closed / open trades", f"{s['closed_trades']} / {s['open_trades']}"),
        _tile("Win rate", f"{s['win_rate']:.0%}" if s["closed_trades"] else "n/a"),
        _tile("Avg R", f"{s['avg_r']:+.2f}" if s["closed_trades"] else "n/a"),
        _tile("Open risk", _money(s["open_risk"])),
        "</div><h2>Realized equity curve</h2>",
    ]
    curve = [settings.paper_starting_equity]
    if not closed.empty:
        curve += list(settings.paper_starting_equity + closed.sort_values("exit_date")["pnl"].cumsum())
    parts.append(_sparkline(curve))

    parts.append("<h2>Closed trades</h2><div class='wrap'><table><tr><th>Symbol</th><th>Entry</th><th>Exit</th>"
                 "<th>Qty</th><th>Entry px</th><th>Exit px</th><th>P&amp;L</th><th>R</th><th>Reason</th></tr>")
    for t in closed.itertuples() if not closed.empty else []:
        cls = "pos" if t.pnl > 0 else "neg"
        parts.append(f"<tr><td>{html.escape(t.symbol)}</td><td>{t.entry_date}</td><td>{t.exit_date}</td><td>{t.quantity:g}</td>"
                     f"<td>{t.entry_price:,.2f}</td><td>{t.exit_price:,.2f}</td><td class='{cls}'>{t.pnl:,.2f}</td>"
                     f"<td>{t.r_multiple:+.2f}</td><td>{html.escape(str(t.exit_reason or ''))}</td></tr>")
    parts.append("</table></div>")

    if backtest:
        m = backtest.get("metrics", {})
        parts.append(f"<h2>Latest backtest ({html.escape(backtest.get('kind', 'backtest'))})</h2><div class='tiles'>")
        for label, key, fmt in [("Total return", "total_return", "{:+.1%}"), ("CAGR", "cagr", "{:+.1%}"),
                                ("Sharpe", "sharpe", "{:.2f}"), ("Max drawdown", "max_drawdown", "{:.1%}"),
                                ("Trades", "trades", "{}"), ("Win rate", "win_rate", "{:.0%}")]:
            v = m.get(key)
            parts.append(_tile(label, "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else fmt.format(v)))
        parts.append(f"</div><p class='muted'>{html.escape(m.get('start', ''))} to {html.escape(m.get('end', ''))}. "
                     "In-sample results overstate real performance; weigh out-of-sample and walk-forward results.</p>")
        if backtest.get("equity"):
            parts.append(_sparkline(list(backtest["equity"].values())))
    parts.append("</main></body></html>")
    return "\n".join(parts)


def save_backtest(settings: Settings, kind: str, metrics: dict, equity: pd.Series, extra: dict | None = None) -> Path:
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": kind,
        "metrics": metrics,
        "equity": {str(k.date()): round(float(v), 2) for k, v in equity.items()},
        **(extra or {}),
    }
    path = reports / "backtest_latest.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def load_backtest(settings: Settings) -> dict | None:
    path = settings.resolve(settings.paths.reports_dir) / "backtest_latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
