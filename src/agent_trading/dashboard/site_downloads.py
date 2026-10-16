"""CSV exports of stored band and option research; no calculations or ranking changes."""

from __future__ import annotations

import csv
import io

from .fmt import (
    csv_value,
)
from .fmt import (
    sval as sval,
)
from .site_company import profile_of


def band_csv(band: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    comps = profile_of(band)
    keys = [m for c in comps for m in c.metrics]
    w.writerow(
        [
            "rank",
            "ticker",
            "name",
            "sector",
            "composite",
            *[f"component_{c.key}" for c in comps],
            "confidence",
            "price",
            "market_cap",
            *keys,
            "missing",
            "flags",
            "counterargument",
        ]
    )
    for c in band["candidates"]:
        w.writerow(
            [
                csv_value(x)
                for x in [
                    c["rank"],
                    c["ticker"],
                    c["name"],
                    c["sector"],
                    c["composite"],
                    *[c["components"].get(k.key) for k in comps],
                    c["confidence"],
                    c["price"],
                    c["market_cap"],
                    *[c["metrics"].get(k) for k in keys],
                    ";".join(c["missing"]),
                    ";".join(c["flags"]),
                    c["counterargument"],
                ]
            ]
        )
    return buf.getvalue()


def options_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = [
        "rank",
        "type",
        "underlying",
        "option",
        "strike",
        "expiration",
        "dte",
        "spot",
        "bid",
        "ask",
        "spread_pct",
        "volume",
        "open_interest",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "multiplier",
        "adjusted",
        "premium_basis",
        "premium_per_contract_ask",
        "breakeven",
        "breakeven_move",
        "required_move",
        "max_loss_per_contract",
    ]
    extra = [
        "horizon",
        "mid",
        "premium_per_contract_mid",
        "implied_move_1sd",
        "theta_available",
        "theta_share_per_day",
        "quote_time_utc",
        "quote_date_ny",
        "quote_status",
        "quote_source",
        "underlying_last_trade",
        "contract_last_trade",
        "events_status",
    ]
    w.writerow(
        cols
        + ["rank_score", "earnings_before_expiry", "flags"]
        + extra
        + [
            "score_liquidity",
            "score_breakeven",
            "score_time_decay",
            "probability_status",
            "probability_of_profit",
            "fees",
        ]
    )
    for x in rows:
        rc = x.get("rank_components") or {}
        p = x.get("probability") or {}
        w.writerow(
            [
                csv_value(v)
                for v in [x.get(c, "call" if c == "type" else None) for c in cols]
                + [
                    rc.get("total"),
                    ";".join(str(e["date"]) for e in x.get("events_before_expiry", [])),
                    ";".join(x.get("flags", [])),
                ]
                + [x.get(c) for c in extra]
                + [
                    rc.get("liquidity"),
                    rc.get("breakeven"),
                    rc.get("time_decay"),
                    p.get("status") or "not_established",
                    p.get("probability_of_profit"),
                    "before fees (none deducted)",
                ]
            ]
        )
    return buf.getvalue()
