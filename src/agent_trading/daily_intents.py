"""Translate strategy output to paper/manual-ticket intents; never execute brokerage orders."""

from __future__ import annotations

import pandas as pd

from .config import Settings
from .paper import Intent
from .strategies.desk import DeskDecision


def _desk_intents(decisions: list[DeskDecision]) -> list[Intent]:
    out = []
    for d in decisions:
        if d.action == "BUY" and d.stop is not None and d.price is not None:
            out.append(Intent(d.symbol, "buy", d.price, d.stop, "B-desk", f"desk BUY ({d.confidence})", 1.0))
        elif d.action == "SELL/REDUCE":
            out.append(Intent(d.symbol, "sell", d.price or 0.0, None, "B-desk", "; ".join(d.reasons)))
    return out


def _gtaa_intents(settings: Settings, signals: dict, bars: dict[str, pd.DataFrame], held: set[str]) -> list[Intent]:
    from .indicators import atr as atr_fn

    out = []
    for a, sig in signals.items():
        df = bars.get(a)
        if sig["above"] is None or df is None:
            continue
        close = float(df["close"].iloc[-1])
        if sig["above"] and a not in held:
            stop = close - settings.risk.atr_stop_multiple * float(atr_fn(df, 14).iloc[-1])
            out.append(Intent(a, "buy", close, stop, "C-gtaa", "GTAA: above 10-month average", 0.5))
        elif not sig["above"] and a in held:
            out.append(Intent(a, "sell", close, None, "C-gtaa", "GTAA: closed below 10-month average"))
    return out
