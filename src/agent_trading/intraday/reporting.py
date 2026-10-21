"""Net fill accounting and disclosed daily-return statistics, never assumed profitability."""

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

from . import STRATEGY_VERSION
from .calendar import NY
from .config import Settings
from .store import Store


def performance(store: Store, cfg: Settings, day: date | None = None) -> dict:
    orders = {o["id"]: o for o in store.rows("orders")}
    fills = store.rows("fills")
    positions = [p for p in store.rows("positions") if p["quantity"]]
    selected = [f for f in fills if day is None or datetime.fromisoformat(f["time"]).astimezone(NY).date() == day]
    trades = {}
    for f in fills:
        order = orders[f["order_id"]]
        key = (order["contract"], order["day"])
        t = trades.setdefault(
            key,
            {
                "contract": key[0],
                "day": key[1],
                "bought": 0,
                "sold": 0,
                "pnl": 0,
                "right": json.loads(order["spec"])["right"],
                "hour": order["created"][11:13],
            },
        )
        t["bought" if f["side"] == "BUY" else "sold"] += f["quantity"]
        t["pnl"] += f["pnl"]
    closed = [
        t
        for t in trades.values()
        if t["bought"] > 0 and t["bought"] == t["sold"] and (day is None or t["day"] == day.isoformat())
    ]
    pnls = [t["pnl"] / 100 for t in closed]
    wins, losses = [x for x in pnls if x > 0], [x for x in pnls if x < 0]
    eq = sorted(store.rows("equity"), key=lambda e: e["time"])
    eq_selected = [e for e in eq if day is None or e["time"][:10] == day.isoformat()]
    complete = bool(eq_selected) and all(e["complete"] for e in eq_selected)
    prior = [e for e in eq if day and e["time"][:10] < day.isoformat() and e["complete"]]
    initial = prior[-1]["cents"] / 100 if prior else cfg.initial_capital
    values = [initial] + [e["cents"] / 100 for e in eq_selected if e["complete"]]
    peak, drawdown = initial, 0.0
    for v in values:
        peak = max(peak, v)
        drawdown = max(drawdown, peak - v)
    eod = {}
    for e in eq:
        eod[e["time"][:10]] = e["cents"] / 100 if e["complete"] else None
    daily, prev = [], cfg.initial_capital
    for value in eod.values():
        if value is None:
            daily = []
            break
        daily.append(value / prev - 1)
        prev = value
    sharpe = (
        float(np.mean(daily) / np.std(daily, ddof=1) * np.sqrt(252))
        if len(daily) >= 2 and np.std(daily, ddof=1) > 0
        else None
    )
    groups = {}
    for key in ["right", "hour"]:
        groups[key] = {
            value: {
                "trades": sum(t[key] == value for t in closed),
                "net_pnl": sum(t["pnl"] for t in closed if t[key] == value) / 100,
            }
            for value in sorted({t[key] for t in closed})
        }
    skips = {}
    for event in store.rows("events"):
        if day and event["time"][:10] != day.isoformat():
            continue
        if event["kind"] in {"skipped", "provider_failure", "risk_limit", "unresolved_overnight_positions"}:
            payload = json.loads(event["payload"])
            reason = str(payload.get("reason", payload.get("reasons", event["kind"])))
            skips[reason] = skips.get(reason, 0) + 1
    return {
        "strategy_version": STRATEGY_VERSION,
        "mode": "LOCAL SIMULATION ONLY",
        "data_mode": store.get("data_mode", "no fills"),
        "as_of_day": day.isoformat() if day else None,
        "orders_submitted": sum(
            o["side"] == "BUY" and (day is None or o["day"] == day.isoformat()) for o in orders.values()
        ),
        "filled_entries": sum(
            t["bought"] > 0 and (day is None or t["day"] == day.isoformat()) for t in trades.values()
        ),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(pnls) - len(wins) - len(losses),
        "realized_net_pnl": sum(f["pnl"] for f in selected if f["side"] == "SELL") / 100,
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "average_win": float(np.mean(wins)) if wins else None,
        "average_loss": float(np.mean(losses)) if losses else None,
        "expectancy_per_closed_trade": float(np.mean(pnls)) if pnls else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "profit_factor_note": "undefined when there are no losing trades; never reported as proof of an edge",
        "equity": values[-1] if complete else None,
        "net_total_return": values[-1] / initial - 1 if complete else None,
        "maximum_drawdown_dollars": drawdown if complete else None,
        "daily_sharpe": sharpe if day is None else None,
        "sharpe_method": "sample standard deviation of observed session-close equity returns, sqrt(252), zero risk-free rate; null with <2 sessions or zero variance",
        "average_observed_daily_return": float(np.mean(daily)) if daily and day is None else None,
        "observed_sessions": len(eod),
        "valuation_complete": complete,
        "open_positions": positions,
        "groups": groups,
        "skips": skips,
        "edge_status": "NOT ESTABLISHED; fixtures and mocked tests are not market evidence",
        "objective": "$50 net/day is an experimental target, not a forecast",
        "closed_trade_details": closed,
    }


def write_report(store: Store, cfg: Settings, directory: str | Path, day: date) -> Path:
    dest = Path(directory)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"intraday-{day}.json"
    path.write_text(json.dumps(performance(store, cfg, day), indent=2, allow_nan=False), encoding="utf-8")
    return path
