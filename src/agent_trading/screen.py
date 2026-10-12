"""Stock/ETF screener: liquidity filter plus trend and momentum metrics."""
from __future__ import annotations

import pandas as pd

from .config import Settings
from .indicators import add_indicators
from .strategy import generate_signals


def latest_snapshot(df: pd.DataFrame, settings: Settings) -> dict:
    ind = add_indicators(df, settings.strategy)
    sig = generate_signals(ind, settings.strategy)
    last, prev = ind.iloc[-1], ind.iloc[-2]
    sc = settings.screen
    liquid = bool(last["close"] >= sc.min_price and last["avg_dollar_volume"] >= sc.min_avg_dollar_volume)
    return {
        "date": ind.index[-1].date(),
        "close": last["close"],
        "change_pct": last["close"] / prev["close"] - 1,
        "sma_fast": last["sma_fast"],
        "sma_slow": last["sma_slow"],
        "uptrend": bool(sig["uptrend"].iloc[-1]),
        "momentum": last["momentum"],
        "rsi": last["rsi"],
        "atr": last["atr"],
        "atr_pct": last["atr"] / last["close"],
        "vol_ratio": last["vol_ratio"],
        "macd_hist": last["macd_hist"],
        "avg_dollar_volume": last["avg_dollar_volume"],
        "liquid": liquid,
        "entry_signal": bool(sig["entry"].iloc[-1]) and liquid,
        "exit_signal": bool(sig["exit"].iloc[-1]),
    }


def run_screen(bars: dict[str, pd.DataFrame], settings: Settings) -> pd.DataFrame:
    rows = [{"symbol": sym, **latest_snapshot(df, settings)} for sym, df in bars.items()]
    if not rows:
        return pd.DataFrame()
    table = pd.DataFrame(rows).set_index("symbol")
    return table.sort_values(["entry_signal", "momentum"], ascending=[False, False])
