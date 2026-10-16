"""Reconcile dated earnings inputs for the daily research run."""

from __future__ import annotations

from datetime import date

import pandas as pd


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
