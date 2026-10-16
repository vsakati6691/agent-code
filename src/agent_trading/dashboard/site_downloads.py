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
from .site_external import csv_fields, macro_rows
from .watchlist import upside_fields


def leaders_csv(payload: dict) -> str:
    from .schema import LEADER_ENTRY

    cols = [key for key in LEADER_ENTRY["properties"] if key != "scenario_2030"]
    scenario_cols = [f"{case}_{field}" for case in ("bear", "base", "bull") for field in ("cap", "price", "shares")]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols + scenario_cols + ["rank_scope", "universe_count", "current_cap_count", "computed_count"])
    for row in payload["entries"]:
        values = ["; ".join(row[key]) if isinstance(row.get(key), list) else row.get(key) for key in cols]
        values += [row["scenario_2030"].get(key) for key in scenario_cols]
        values += [
            "available stored inputs only" if payload["partial"] else "full stored index universe",
            payload["universe_count"],
            payload["current_cap_count"],
            payload["computed_count"],
        ]
        # Prevent owner-supplied source/notes text from becoming a spreadsheet formula.
        writer.writerow(
            [
                "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else csv_value(value)
                for value in values
            ]
        )
    return buf.getvalue()


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
            *csv_fields({}),
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
                    *csv_fields(c).values(),
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
            "risk_free_rate",
            "rate_observation_date",
            "rate_source",
            "rate_reason",
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
                    *[
                        (x.get("sensitivity", {}).get("rate_input") or {}).get(k)
                        for k in ("value", "date", "source", "reason")
                    ],
                ]
            ]
        )
    return buf.getvalue()


def watchlist_csv(snap: dict) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(
        [
            "ticker",
            "name",
            "asset_type",
            "exchange",
            "status",
            "price",
            "price_date",
            "method",
            "evidence_quality",
            "bear_2030",
            "base_2030",
            "bull_2030",
            "bear_change",
            "base_change",
            "bull_change",
            "bear_annualized",
            "base_annualized",
            "bull_annualized",
            "unavailable_reason",
            "upside_bear_pct",
            "upside_base_pct",
            "upside_bull_pct",
            "cagr_base_pct",
            *csv_fields({}),
        ]
    )
    for e in (snap.get("watchlist") or {}).get("entries", []):
        sc = e.get("scenarios") or {}
        g = lambda k, f: (sc.get(k) or {}).get(f)  # noqa: E731, B023 - consumed in this iteration.
        wr.writerow(
            [
                csv_value(v)
                for v in [
                    e["ticker"],
                    e.get("name"),
                    e.get("asset_type"),
                    e.get("exchange"),
                    e.get("status"),
                    e.get("price"),
                    e.get("price_date"),
                    e.get("method"),
                    e.get("evidence_quality"),
                    *[g(k, "price") for k in ("bear", "base", "bull")],
                    *[g(k, "change") for k in ("bear", "base", "bull")],
                    *[g(k, "annualized") for k in ("bear", "base", "bull")],
                    e.get("unavailable_reason"),
                    *upside_fields(e).values(),
                    *csv_fields(e).values(),
                ]
            ]
        )
    return buf.getvalue()


def macro_csv(snap: dict) -> str:
    rows = macro_rows(snap)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(rows[0])
    for row in rows:
        writer.writerow([csv_value(v) for v in row.values()])
    return buf.getvalue()


def external_csv(snap: dict) -> str:
    from .pipeline_external import subjects

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ticker", *csv_fields({})])
    for ticker, entries in sorted(subjects(snap.get("bands", {}), snap.get("watchlist") or {}).items()):
        writer.writerow([csv_value(v) for v in [ticker, *csv_fields(entries[0]).values()]])
    return buf.getvalue()
