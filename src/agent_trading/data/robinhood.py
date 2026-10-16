"""Parse Robinhood MCP `get_equity_historicals` output (saved JSON) into daily bars.

The MCP tool is only callable from a Claude session, so history is exported to
a JSON file there and imported here. Robinhood bars are split-adjusted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .cache import COLUMNS


def parse_historicals(payload: dict) -> dict[str, pd.DataFrame]:
    results = payload.get("data", payload).get("results")
    if not isinstance(results, list):
        raise ValueError("not a get_equity_historicals payload (no results list)")
    out: dict[str, pd.DataFrame] = {}
    for result in results:
        symbol = str(result["symbol"]).upper()
        if result.get("interval") != "day":
            raise ValueError(f"{symbol}: expected daily bars, got {result.get('interval')!r}")
        rows = [
            {
                "date": b["begins_at"],
                "open": b["open_price"],
                "high": b["high_price"],
                "low": b["low_price"],
                "close": b["close_price"],
                "volume": b["volume"],
            }
            for b in result.get("bars", [])
            if not b.get("interpolated")  # gap-fill bars carry no information
        ]
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None).dt.normalize()
        df = df.set_index("date")[COLUMNS].astype(float).sort_index()
        out[symbol] = df[~df.index.duplicated(keep="last")]
    return out


def load_historicals_file(path: Path) -> dict[str, pd.DataFrame]:
    return parse_historicals(json.loads(Path(path).read_text(encoding="utf-8")))
