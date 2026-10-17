"""Buy/Sell desk (spec 2026-10-17.5): TradingAgents' five stages as fixed rules over stored snapshot fields.

TradingAgents (Apache-2.0, https://github.com/TauricResearch/TradingAgents; Xiao et al., arXiv 2412.20138) runs
language-model agents: four analysts, bull and bear researchers, a trader, three risk reviewers and a portfolio
manager. Only that structure is adapted here; no code or prompt was copied. Each stage below is a pure function of
figures the weekly snapshot already stores (spec.DESK_RULE), so a rating can be recomputed exactly from the
published JSON. Nothing is fetched, generated or estimated, and a missing input abstains instead of counting as zero.
"""

from __future__ import annotations

import math
from datetime import date

from . import spec

R = spec.DESK_RULES
RATINGS = spec.DESK_RATINGS
HOLD = RATINGS.index("Hold")
STANCES = {1: "bullish", 0: "neutral", -1: "bearish", None: "abstains"}
# the components behind the stored fundamental quality score (spec.DECISION_RULES growth_weights)
QUALITY_PARTS = tuple(spec.DECISION_RULES["growth_weights"])


def finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def stored(c: dict, group: str, key: str) -> dict:
    """One decision-research field ({value, reason, ...}); {} when the snapshot predates it."""
    groups = (c.get("decision_research") or {}).get("groups") or {}
    return ((groups.get(group) or {}).get("fields") or {}).get(key) or {}


def _point(text: str, vote: int, side: str | None = None) -> dict:
    return {"text": text, "vote": vote, "side": side or ("bull" if vote > 0 else "bear" if vote < 0 else "neutral")}


def _analyst(key: str, title: str, points: list[dict], inputs: dict, bull: float, bear: float, missing: list[str]):
    if not points:
        return {
            "key": key,
            "title": title,
            "vote": None,
            "stance": STANCES[None],
            "score": None,
            "points": [],
            "inputs": inputs,
            "reason": "; ".join(missing) or "No inputs stored",
        }
    score = sum(p["vote"] for p in points)
    vote = 1 if score >= bull else -1 if score <= bear else 0
    return {
        "key": key,
        "title": title,
        "vote": vote,
        "stance": STANCES[vote],
        "score": score,
        "points": points,
        "inputs": inputs,
        "reason": "; ".join(missing) or None,
    }


# --- indicators (causal: only the stored closes up to the as-of session) ----------------------------------------


def sma(values: list[float], n: int) -> float:
    return sum(values[-n:]) / n


def ema(values: list[float], n: int) -> list[float]:
    """Exponential average seeded with the first value (pandas ewm(span=n, adjust=False))."""
    alpha, out = 2 / (n + 1), [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def macd(values: list[float], fast: int, slow: int, signal: int) -> tuple[float, float]:
    line = [a - b for a, b in zip(ema(values, fast), ema(values, slow), strict=True)]
    return line[-1], ema(line, signal)[-1]


def rsi(values: list[float], n: int) -> float:
    """Wilder's RSI: simple averages over the first n changes, then Wilder smoothing."""
    changes = [b - a for a, b in zip(values, values[1:], strict=False)]
    gain = sum(max(c, 0.0) for c in changes[:n]) / n
    loss = sum(max(-c, 0.0) for c in changes[:n]) / n
    for c in changes[n:]:
        gain = (gain * (n - 1) + max(c, 0.0)) / n
        loss = (loss * (n - 1) + max(-c, 0.0)) / n
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def volatility(values: list[float], sessions: int) -> float | None:
    """Annualised sample standard deviation of the last `sessions` daily log returns."""
    tail = values[-(sessions + 1) :]
    rets = [math.log(b / a) for a, b in zip(tail, tail[1:], strict=False)]
    if len(rets) < sessions:
        return None
    mean = sum(rets) / len(rets)
    return math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) * 252)


def closes(c: dict) -> list[float]:
    spark = (c.get("decision_research") or {}).get("spark") or []
    return [float(v) for v in spark] if all(finite(v) and v > 0 for v in spark) else []


# --- stage 1: four analysts ---------------------------------------------------------------------------------------


def fundamentals_analyst(c: dict) -> dict:
    rule = R["fundamentals"]
    field = stored(c, "quality", "quality")
    q = field.get("value")
    if not finite(q):
        missing = [f"Fundamental quality score unavailable: {field.get('reason') or 'not stored in this snapshot'}"]
        return _analyst("fundamentals", "Fundamentals analyst", [], {}, 1, -1, missing)
    vote = 1 if q >= rule["bullish_at_least"] else -1 if q < rule["bearish_below"] else 0
    points = [
        _point(
            f"Fundamental quality {q:.0f}/100 (bullish at {rule['bullish_at_least']:.0f} or more, "
            f"bearish below {rule['bearish_below']:.0f})",
            vote,
        )
    ]
    comps = {k: v for k, v in (c.get("components") or {}).items() if k in QUALITY_PARTS and finite(v)}
    titles = {comp.key: comp.title for comp in spec.COMPONENTS}
    if len(comps) >= 2:
        best, worst = max(comps, key=comps.get), min(comps, key=comps.get)
        points.append(_point(f"Strongest part: {titles[best].lower()} ({comps[best]:.2f} of 1)", 0))
        points.append(_point(f"Weakest part: {titles[worst].lower()} ({comps[worst]:.2f} of 1)", 0))
    return _analyst("fundamentals", "Fundamentals analyst", points, {"quality": q, **comps}, 1, -1, [])


def technical_analyst(c: dict) -> dict:
    rule = R["technical"]
    px = closes(c)
    if len(px) < rule["min_closes"]:
        missing = [f"Needs {rule['min_closes']} stored daily closes; {len(px)} available"]
        return _analyst("technical", "Technical analyst", [], {}, 1, -1, missing)
    last, fast, slow = px[-1], sma(px, rule["sma_fast"]), sma(px, rule["sma_slow"])
    line, signal = macd(px, *rule["macd"])
    strength = rsi(px, rule["rsi_period"])
    up = last > slow
    points = [
        _point(
            f"Close ${last:,.2f} {'above' if up else 'at or below'} its 200-day average ${slow:,.2f}", 1 if up else -1
        ),
        _point(
            f"50-day average ${fast:,.2f} {'above' if fast > slow else 'at or below'} the 200-day "
            f"({'uptrend' if fast > slow else 'downtrend'})",
            1 if fast > slow else -1,
        ),
        _point(
            f"MACD {line:,.2f} {'above' if line > signal else 'at or below'} its signal line {signal:,.2f} "
            f"({'momentum improving' if line > signal else 'momentum fading'})",
            1 if line > signal else -1,
        ),
    ]
    if strength > rule["rsi_overbought"]:
        points.append(_point(f"RSI(14) {strength:.0f}: overbought (above {rule['rsi_overbought']:.0f})", -1))
    elif strength < rule["rsi_oversold"]:
        points.append(_point(f"RSI(14) {strength:.0f}: oversold (below {rule['rsi_oversold']:.0f})", 1))
    else:
        points.append(_point(f"RSI(14) {strength:.0f}: neither overbought nor oversold", 0))
    inputs = {"close": last, "sma_50": fast, "sma_200": slow, "macd": line, "macd_signal": signal, "rsi_14": strength}
    return _analyst(
        "technical", "Technical analyst", points, inputs, rule["bullish_at_least"], rule["bearish_at_most"], []
    )


def positioning_analyst(c: dict) -> dict:
    rule = R["positioning"]
    ext = c.get("external") or {}
    points, inputs, missing = [], {}, []
    window = ((ext.get("insiders") or {}).get("windows") or {}).get(rule["insider_window"]) or {}
    net, source = window.get("net_shares"), "SEC Form 4, 90 days"
    if not finite(net):
        av = stored(c, "ownership", "insider_net")
        net, source = av.get("value"), "Alpha Vantage, six months"
        if not finite(net):
            missing.append(f"Insider trades unavailable: {window.get('reason') or av.get('reason') or 'not stored'}")
    if finite(net):
        inputs["insider_net_shares"] = net
        if net > 0:
            points.append(
                _point(f"Insiders bought more than they sold on the open market ({source}, net {net:,.0f} shares)", 1)
            )
        elif net < 0:
            points.append(
                _point(
                    f"Insiders sold more than they bought ({source}, net {net:,.0f} shares); "
                    "not counted against, since sales are often for pay or tax",
                    0,
                    "bear",
                )
            )
        else:
            points.append(_point(f"No net open-market insider buying or selling ({source})", 0))
    short = ext.get("short_interest") or {}
    share = short.get("percent_of_diluted_shares")
    if finite(share):
        inputs["short_interest"] = share
        heavy = share >= rule["short_heavy_at_least"]
        points.append(
            _point(
                f"Short interest {share:.1%} of diluted shares (FINRA)"
                + (f": heavily shorted (at least {rule['short_heavy_at_least']:.0%})" if heavy else ""),
                -1 if heavy else 0,
            )
        )
    else:
        missing.append(
            f"Short interest unavailable: {short.get('percent_reason') or short.get('reason') or 'not stored'}"
        )
    target_field, price = stored(c, "ownership", "analyst_target"), c.get("price")
    target = target_field.get("value")
    if finite(target) and finite(price) and price > 0:
        upside = target / price - 1
        inputs["analyst_target"], inputs["target_upside"] = target, upside
        vote = 1 if upside >= rule["target_upside_at_least"] else -1 if upside <= rule["target_downside_at_most"] else 0
        where = f"{upside:.0%} above" if upside > 0 else "at or below"
        points.append(
            _point(f"Analyst target ${target:,.2f} is {where} the price (provider estimate, unverified)", vote)
        )
    else:
        missing.append(f"Analyst target unavailable: {target_field.get('reason') or 'not stored'}")
    return _analyst(
        "positioning",
        "Sentiment & positioning analyst",
        points,
        inputs,
        rule["bullish_at_least"],
        rule["bearish_at_most"],
        missing,
    )


def events_analyst(c: dict) -> dict:
    rule = R["events"]
    points, inputs, missing = [], {}, []
    trend = stored(c, "growth", "growth_trend")
    if trend.get("value") in ("accelerating", "stable", "decelerating"):
        inputs["revenue_trend"] = trend["value"]
        vote = {"accelerating": 1, "stable": 0, "decelerating": -1}[trend["value"]]
        points.append(
            _point(f"Revenue growth {trend['value']} in the latest quarter (year-on-year, vs the quarter before)", vote)
        )
    else:
        missing.append(f"Revenue trend unavailable: {trend.get('reason') or 'not stored'}")
    for key, label in (("operating_margin_change", "Operating margin"), ("fcf_margin_change", "Free-cash-flow margin")):
        field = stored(c, "growth", key)
        if field.get("trend") in ("improving", "stable", "deteriorating") and finite(field.get("value")):
            inputs[key] = field["value"]
            vote = {"improving": 1, "stable": 0, "deteriorating": -1}[field["trend"]]
            points.append(_point(f"{label} {field['trend']} ({field['value'] * 100:+.1f} pts vs a year earlier)", vote))
        else:
            missing.append(f"{label} trend unavailable: {field.get('reason') or 'not stored'}")
    filed = (c.get("decision_research") or {}).get("filing_as_of")
    if points and filed:
        points.append(_point(f"Read from the latest 10-Q/10-K, filed {filed}; no news headlines are collected", 0))
    return _analyst(
        "events", "News & events analyst", points, inputs, rule["bullish_at_least"], rule["bearish_at_most"], missing
    )


# --- stages 2-5 -------------------------------------------------------------------------------------------------


def trader(net: int) -> str:
    t = R["trader"]
    if net >= t["buy_at_least"]:
        return "Buy"
    if net >= t["overweight_at_least"]:
        return "Overweight"
    if net <= t["sell_at_most"]:
        return "Sell"
    if net <= t["underweight_at_most"]:
        return "Underweight"
    return "Hold"


def risk_flags(c: dict, as_of: date) -> tuple[list[dict], list[str]]:
    """(flags raised, checks that could not run)."""
    rule = R["risk"]
    flags, unchecked = [], []
    nxt = c.get("next_earnings")
    try:
        days = (date.fromisoformat(str(nxt)[:10]) - as_of).days if nxt else None
    except ValueError:
        days = None
    if days is None:
        unchecked.append("Next earnings date unknown")
    elif 0 <= days <= rule["earnings_within_days"]:
        flags.append(
            {
                "key": "earnings",
                "text": f"Earnings scheduled {str(nxt)[:10]}, {days} days after the as-of date (unverified date)",
            }
        )
    extended = stored(c, "timing", "extended").get("value")
    if extended == "extended":
        flags.append(
            {
                "key": "extended",
                "text": f"1-year gain above {spec.DECISION_RULES['extended_return']:.0%} (stored 'extended' flag)",
            }
        )
    elif extended is None:
        unchecked.append("1-year return unavailable for the 'extended' check")
    px = closes(c)
    vol = volatility(px, rule["volatility_sessions"]) if px else None
    if vol is None:
        unchecked.append(f"Volatility needs {rule['volatility_sessions'] + 1} stored closes")
    elif vol > rule["volatility_above"]:
        flags.append(
            {
                "key": "volatility",
                "text": f"Annualised volatility {vol:.0%} over the last "
                f"{rule['volatility_sessions']} sessions (above "
                f"{rule['volatility_above']:.0%})",
            }
        )
    balance = (c.get("components") or {}).get("balance")
    if not finite(balance):
        unchecked.append("Balance-sheet score unavailable")
    elif balance < rule["balance_below"]:
        flags.append(
            {"key": "balance", "text": f"Balance-sheet score {balance:.2f} of 1 (below {rule['balance_below']:.2f})"}
        )
    return flags, unchecked


def review(proposal: str, flags: int, steps: tuple) -> str:
    down = max((s for at_least, s in steps if flags >= at_least), default=0)
    i = RATINGS.index(proposal)
    return RATINGS[max(i - down, HOLD)] if i > HOLD else proposal


def assess(c: dict, as_of: date) -> dict:
    analysts = [fundamentals_analyst(c), technical_analyst(c), positioning_analyst(c), events_analyst(c)]
    voting = [a for a in analysts if a["vote"] is not None]
    out = {
        "ticker": c["ticker"],
        "name": c.get("name"),
        "sector": c.get("sector"),
        "price": c.get("price"),
        "confidence": c.get("confidence_label"),
        "analysts": analysts,
    }
    if len(voting) < R["min_analysts"]:
        return {
            **out,
            "rating": None,
            "summary": f"Not rated: only {len(voting)} of 4 analysts had their inputs (needs {R['min_analysts']}).",
        }
    net = sum(a["vote"] for a in voting)
    d = R["debate"]
    verdict = (
        "Bull case stronger"
        if net >= d["bull_at_least"]
        else "Bear case stronger"
        if net <= d["bear_at_most"]
        else "Balanced"
    )
    bull = [f"{a['title']}: {p['text']}" for a in analysts for p in a["points"] if p["side"] == "bull"]
    bear = [f"{a['title']}: {p['text']}" for a in analysts for p in a["points"] if p["side"] == "bear"]
    if c.get("counterargument"):
        bear.append(f"Stored research: {c['counterargument']}")
    proposal = trader(net)
    flags, unchecked = risk_flags(c, as_of)
    reviews = {name: review(proposal, len(flags), steps) for name, steps in R["reviewers"].items()}
    median = sorted(reviews.values(), key=RATINGS.index)[1]
    capped = c.get("confidence_label") == "low" and RATINGS.index(median) > RATINGS.index(R["low_confidence_cap"])
    rating = R["low_confidence_cap"] if capped else median
    bulls, bears = sum(a["vote"] == 1 for a in voting), sum(a["vote"] == -1 for a in voting)
    summary = (
        f"{rating}: {bulls} of {len(voting)} voting analysts bullish and {bears} bearish (net {net:+d}), so the "
        f"trader proposed {proposal}. "
        + (f"{len(flags)} risk flag{'s' if len(flags) != 1 else ''}; " if flags else "No risk flags; ")
        + f"the portfolio manager took the middle review ({median})"
        + (", then capped it at Hold because evidence confidence is low." if capped else ".")
    )
    return {
        **out,
        "debate": {"net": net, "verdict": verdict, "bull": bull, "bear": bear},
        "trader": proposal,
        "risk": {"flags": flags, "unchecked": unchecked, "reviews": reviews},
        "manager": {"median": median, "capped": capped},
        "rating": rating,
        "summary": summary,
    }


def build(bands: dict, as_of) -> dict:
    """Rate every listed stock once, in registered list order; the first list supplies its benchmark."""
    as_of = date.fromisoformat(str(as_of)[:10])
    order = [b.key for b in spec.BANDS] + sorted(set(bands) - {b.key for b in spec.BANDS})
    configs = {b.key: b for b in spec.BANDS}
    entries: dict[str, dict] = {}
    for key in order:
        for c in (bands.get(key) or {}).get("candidates", []):
            if c["ticker"] in entries:
                entries[c["ticker"]]["lists"].append(key)
                continue
            bench = configs[key].benchmark if key in configs else c.get("benchmark")
            entries[c["ticker"]] = {**assess(c, as_of), "lists": [key], "benchmark": bench}
    rows = sorted(
        entries.values(),
        key=lambda e: (
            -(RATINGS.index(e["rating"]) if e["rating"] else -1),
            -(e.get("debate") or {}).get("net", -99),
            e["ticker"],
        ),
    )
    counts = {r: sum(e["rating"] == r for e in rows) for r in reversed(RATINGS)}
    counts["Not rated"] = sum(e["rating"] is None for e in rows)
    return {"as_of": as_of.isoformat(), "spec_version": spec.SPEC_VERSION, "entries": rows, "counts": counts}
