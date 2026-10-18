"""Customer edition of the static site: the owner-only and licence-restricted parts are left out.

Left out: Cboe option-chain research (Options, Small bets, contract pages, option downloads), the Buy/Sell desk,
and everything derived from the owner's Robinhood account (tradability verdicts, the broker earnings-calendar
check, and the Watchlist 2030 / Plan 2030 pages built on the owner's Robinhood watchlist). Stock prices still come
from Cboe delayed quotes; whether they may be shown to customers is the owner's licensing decision.

`check` fails the build if anything left out still appears in the output.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from . import spec
from .site_layout import E, brand

EDITIONS = ("full", "customer")
HIDDEN_PAGES = ("desk.html", "options.html", "bets.html", "watchlist.html", "goal.html")
DROPPED_KEYS = ("options", "speculative", "decision_desk", "watchlist", "tradability")
# Set to "reviewed" only after legal review of the terms text; until then the page says it is a draft.
TERMS_STATUS = "draft"

_NEUTRAL = (
    ("Robinhood's read-only get_equity_tradability check", "a read-only brokerage tradability check"),
    ("Robinhood tradability not yet verified", "Tradability not yet verified"),
    ("not checked for Robinhood tradability", "not checked for tradability"),
    ("Robinhood tradability", "brokerage tradability"),
    ("tradable on Robinhood", "tradable at a brokerage"),
)
# Company names (HOOD, RVI) are public facts, not account data.
_LEAK = re.compile(r"Robinhood(?! Markets| Ventures)|get_equity_tradability|get_earnings_calendar|robinhood_\w+\.json")
_HIDDEN_LINK = re.compile(
    r'href="(?:\.\./)*(?:desk(?:\.html|/)|options(?:-[\w-]+)?\.html|option/|bets\.html|watchlist\.html|goal\.html'
    r'|[^"]*_options_[^"]*\.csv|[^"]*_buy_sell_desk\.csv|[^"]*_watchlist_2030\.csv)'
)


def neutral(text: str) -> str:
    """Describe the eligibility rule without naming the owner's broker."""
    for old, new in _NEUTRAL:
        text = text.replace(old, new)
    return text


def _neutral_strings(value):
    if isinstance(value, str):
        return neutral(value)
    if isinstance(value, list):
        return [_neutral_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: _neutral_strings(v) for k, v in value.items()}
    return value


def sanitize(snap: dict | None) -> dict | None:
    """A copy of a stored snapshot without option, desk, watchlist or broker-derived data (the store is untouched)."""
    if snap is None:
        return None
    out = {k: copy.deepcopy(v) for k, v in snap.items() if k not in DROPPED_KEYS}
    out.pop("broker_calendar", None)
    return _neutral_strings(out)


def schema(full: dict) -> dict:
    """The published field guide without the left-out snapshot sections."""
    out = copy.deepcopy(full)
    for key in DROPPED_KEYS:
        out.get("properties", {}).pop(key, None)
    return _neutral_strings(out)


def neutralize_output(out: Path) -> None:
    """Apply `neutral` to rule texts rendered straight from the spec into any published text file."""
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in (".html", ".json", ".csv", ".xml"):
            text = path.read_text(encoding="utf-8")
            if (changed := neutral(text)) != text:
                path.write_text(changed, encoding="utf-8")


def strip_methodology(markup: str) -> str:
    """Drop the methodology sections for left-out pages and the broker tradability check."""
    cuts = (
        (r"<h3>Robinhood tradability</h3>", r"<h3>Not scored</h3>"),
        (r"<h2>Speculative small bets", r'<h2 id="watchlist">'),
        (r'<h2 id="watchlist">', r"<h2>Performance tracking</h2>"),
        (r'<h2 id="buy-sell-desk">', r'<h2 id="display-rules">|<h2 id="leaders|<h2>Leaders'),
    )
    for start, stop in cuts:
        m = re.search(f"({start}).*?(?={stop})", markup, re.S)
        if m:
            markup = markup[: m.start()] + markup[m.end() :]
    return markup


def terms_page() -> str:
    draft = (
        '<div class="banner warn"><strong>Draft terms</strong>Pending legal review; not yet in force.</div>'
        if TERMS_STATUS != "reviewed"
        else ""
    )
    sources = "SEC EDGAR, Nasdaq Trader, Wikipedia (CC BY-SA 4.0), Cboe delayed quotes, Alpha Vantage, FRED and FINRA"
    return f"""<h1>Terms of use</h1>{draft}
<p class="lede">{E(brand())} publishes research comparisons built from public market data with rules that are fixed
in advance and published on the <a href="methodology.html">Methodology</a> page.</p>
<h2>Not investment advice</h2><p>Nothing on this site is investment, financial, legal or tax advice, or a
recommendation or solicitation to buy, sell or hold any security. Lists, scores and scenarios do not consider your
objectives, finances or risk tolerance. Consider consulting a licensed professional before making any investment
decision. {E(spec.DISCLAIMER)}</p>
<h2>No performance claim</h2><p>No investment edge is established. Past or tracked results do not predict future
results, and tracked lists are compared with benchmarks only after enough weekly snapshots exist
({spec.MIN_SNAPSHOTS_FOR_EVIDENCE}). {E(spec.PROBABILITY_STATEMENT)}</p>
<h2>Data</h2><p>Prices are delayed, end-of-session values, never live. Data comes from {E(sources)}; each provider
owns its data. Data can be late, incomplete or wrong; missing inputs are shown as unavailable, never estimated. See
the <a href="audit.html">Audit trail</a> for each dataset's state and time.</p>
<h2>No warranty</h2><p>The site is provided "as is", without warranty of any kind, and may change, pause or stop
without notice. To the extent permitted by law, the publisher is not liable for any loss from using it.</p>
<h2>Use</h2><p>Use is for your own information. Do not republish third-party data from this site.</p>
<p class="small muted">Methodology version {E(spec.SPEC_VERSION)}.</p>"""


def check(out: Path) -> list[str]:
    """Every customer-edition file must be free of left-out pages, links and broker-derived data."""
    problems = [f"left-out page published: {name}" for name in HIDDEN_PAGES if (out / name).exists()]
    problems += [f"left-out folder published: {d}" for d in ("desk", "option") if (out / d).exists()]
    problems += [f"left-out page published: {p.name}" for p in out.glob("options-*.html")]
    problems += [
        f"left-out file published: {p.relative_to(out).as_posix()}"
        for pattern in ("downloads/*_options_*.csv", "downloads/*_buy_sell_desk.csv", "downloads/*_watchlist_2030.csv")
        for p in out.glob(pattern)
    ]
    if (out / "data" / "daily").exists():
        problems.append("left-out folder published: data/daily (daily refresh files hold option chains)")
    for path in sorted(out.rglob("*")):
        if not path.is_file() or path.suffix not in (".html", ".json", ".csv", ".xml", ".js"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(out).as_posix()
        if m := _LEAK.search(text):
            problems.append(f"{rel}: broker-derived text {text[max(0, m.start() - 40) : m.end() + 40]!r}")
        if path.suffix == ".html" and (m := _HIDDEN_LINK.search(text)):
            problems.append(f"{rel}: link to left-out content {m.group(0)!r}")
        if path.suffix == ".json" and re.search(
            r'"(?:options|decision_desk|watchlist|tradability|speculative)":', text
        ):
            problems.append(f"{rel}: left-out data key")
    return problems
