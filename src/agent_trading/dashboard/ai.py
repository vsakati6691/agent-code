"""AI page logic (spec 2026-10-14.7): the curated universe, the top-20 market-cap scenario test and the private-company
context. Pure functions over data the run already holds; nothing here fetches anything.

* The universe is `spec.AI_UNIVERSE`, a fixed list recorded in the methodology. A name that cannot be scored keeps
  its reason on the excluded page.
* The top-20 test compares conditional scenario market caps with TODAY's 20th-largest S&P 500 market cap. It is a
  scenario comparison, never a probability (spec.AI_PROBABILITY_NOTE).
* Private companies come from `config/ai_private_companies.json`. A valuation is accepted only with a source link
  and a date, and is always shown as reported and unverified; nothing is invented.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from . import spec
from .providers import common_stock_reason
from .store import find_private_keys

PRIVATE_FILE = Path(__file__).resolve().parents[3] / "config" / "ai_private_companies.json"
TEST_YEARS = (5, 10)
LADDER_SIZE = 30
CURRENCIES = ("USD", "EUR", "GBP")


class PrivateConfigError(ValueError):
    """The private-company file breaks a rule (a valuation without a source, an account-like field...)."""


def roles() -> dict[str, str]:
    return dict(spec.AI_UNIVERSE)


def resolve_universe(
    sec: pd.DataFrame, dirs: pd.DataFrame, sp: pd.DataFrame
) -> tuple[list[tuple[str, int, str, str | None]], dict[str, str]]:
    """([(ticker, cik, name, sector)], {ticker: why it cannot be evaluated}) for spec.AI_UNIVERSE.

    Uses the same listing, common-stock and SEC-registrant checks as the broad universe. The sector comes from the
    S&P 500 list when the company is a member (else it is filled from the SEC SIC code for the names that are shown)."""
    rows: list[tuple[str, int, str, str | None]] = []
    rejects: dict[str, str] = {}
    for t, _role in spec.AI_UNIVERSE:
        if t not in dirs.index:
            rejects[t] = "not in the current exchange listings (not listed yet, renamed or delisted)"
            continue
        d = dirs.loc[t]
        why = common_stock_reason(
            str(d["name"]), bool(d["etf"]), bool(d["test_issue"]), str(d.get("financial_status", ""))
        )
        if why is None and d["exchange"] not in spec.LISTED_EXCHANGES:
            why = f"listed on {d['exchange']} (not an eligible exchange)"
        if why is None and t not in sec.index:
            why = "not in the SEC ticker file (no SEC registrant match)"
        if why is not None:
            rejects[t] = why
            continue
        sector = str(sp.loc[t, "sector"]) if t in sp.index else None
        rows.append((t, int(sec.loc[t, "cik"]), str(d["name"]), sector))
    return rows, rejects


def size_ladder(caps: dict[str, float], n: int = LADDER_SIZE) -> dict:
    """The largest market caps among the S&P 500 members that had valid data, and the 20th-largest as the bar."""
    ranked = sorted(
        ((float(c), t) for t, c in caps.items() if isinstance(c, (int, float)) and math.isfinite(c) and c > 0),
        reverse=True,
    )
    ok = len(ranked) >= 20
    return {
        "basis": "S&P 500 members with valid data in this run (as-of close x SEC cover-page shares)",
        "n_with_cap": len(ranked),
        "available": ok,
        "threshold": ranked[19][0] if ok else None,
        "threshold_ticker": ranked[19][1] if ok else None,
        "reason": None if ok else "fewer than 20 S&P 500 members had a valid market cap in this run",
        "members": [{"rank": i, "ticker": t, "market_cap": c} for i, (c, t) in enumerate(ranked[:n], 1)],
    }


def top20_test(c: dict, ladder: dict) -> dict:
    """Bear, base and bull scenario market caps at 5 and 10 years against today's 20th-largest cap (held flat).

    `c` is a stored candidate record (scenario years are string keys). Nothing here is a forecast or a probability."""
    thr = ladder.get("threshold")
    out = {
        "status": "ok",
        "threshold": thr,
        "threshold_ticker": ladder.get("threshold_ticker"),
        "market_cap_now": c.get("market_cap"),
        "rows": [],
        "current_vs_threshold": None,
        "reason": None,
    }
    if thr is None:
        return {**out, "status": "unavailable", "reason": ladder.get("reason") or "no threshold this week"}
    sc = c.get("scenarios")
    if not sc:
        return {
            **out,
            "status": "unavailable",
            "reason": c.get("scenario_note") or "scenarios were not computed for this stock",
        }
    now = c.get("market_cap")
    out["current_vs_threshold"] = now / thr if isinstance(now, (int, float)) and math.isfinite(now) else None
    for case in ("bear", "base", "bull"):
        for y in TEST_YEARS:
            v = ((sc.get(case) or {}).get("years") or {}).get(str(y))
            if not v:
                continue
            cap = v["value_per_share"] * v["shares"]
            out["rows"].append(
                {
                    "case": case,
                    "year": y,
                    "market_cap": cap,
                    "multiple_of_threshold": cap / thr,
                    "above_today_bar": cap >= thr,
                }
            )
    if not out["rows"]:
        return {**out, "status": "unavailable", "reason": "the scenario table has no 5- or 10-year values"}
    return out


# --- private companies ------------------------------------------------------------------------------------------


def _https(url) -> bool:
    return isinstance(url, str) and url.startswith("https://") and len(url) > 12


def load_private(path: Path = PRIVATE_FILE) -> dict:
    """Validated private-company records. A valuation needs a source link, a label, a date, a currency and its basis;
    a record without a valuation needs the reason. Account-like fields are refused."""
    p = Path(path)
    if not p.exists():
        return {"reviewed_on": None, "note": "No private-company file is configured.", "companies": []}
    raw = json.loads(p.read_text(encoding="utf-8"))
    hits = find_private_keys(raw)
    if hits:
        raise PrivateConfigError(f"private-company file contains private-looking fields: {hits[:3]}")
    out = []
    for c in raw.get("companies") or []:
        name = str(c.get("name") or "").strip()
        if not name or not str(c.get("what") or "").strip():
            raise PrivateConfigError("every private company needs a name and a one-line description")
        v = c.get("valuation")
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise PrivateConfigError(f"{name}: the valuation must be a positive number (billions)")
            missing = [k for k in ("currency", "basis", "valuation_date", "source_label", "source_url") if not c.get(k)]
            if missing:
                raise PrivateConfigError(f"{name}: a valuation needs {', '.join(missing)}")
            if c["currency"] not in CURRENCIES:
                raise PrivateConfigError(f"{name}: currency must be one of {', '.join(CURRENCIES)}")
            if not _https(c["source_url"]):
                raise PrivateConfigError(f"{name}: the valuation source must be an https link")
        elif not str(c.get("no_valuation_reason") or "").strip():
            raise PrivateConfigError(f"{name}: a record without a valuation needs no_valuation_reason")
        if (c.get("status_note") or c.get("status_source_url")) and not _https(c.get("status_source_url")):
            raise PrivateConfigError(f"{name}: a status note needs an https source link")
        out.append(
            {
                k: c.get(k)
                for k in (
                    "name",
                    "what",
                    "valuation",
                    "currency",
                    "basis",
                    "valuation_date",
                    "source_label",
                    "source_url",
                    "no_valuation_reason",
                    "status_note",
                    "status_source_label",
                    "status_source_url",
                )
            }
        )
    return {"reviewed_on": raw.get("reviewed_on"), "note": raw.get("note"), "companies": out}


def place_in_ladder(company: dict, ladder: dict) -> str | None:
    """Where a USD private valuation would sit among today's largest S&P 500 members, in words (None when it cannot
    be compared). A valuation is not a market cap, and the sentence says so."""
    v = company.get("valuation")
    if v is None or company.get("currency") != "USD" or not ladder.get("members"):
        return None
    value = float(v) * 1e9
    members = ladder["members"]
    above = sum(1 for m in members if m["market_cap"] > value)
    if above >= len(members):
        return f"below the {len(members)}th-largest S&P 500 member by market cap"
    if above == 0:
        return f"above the largest S&P 500 member today ({members[0]['ticker']})"
    return (
        f"between #{above} ({members[above - 1]['ticker']}) and #{above + 1} ({members[above]['ticker']}) "
        "among today's largest S&P 500 members"
    )
