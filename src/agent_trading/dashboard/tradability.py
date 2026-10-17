"""Robinhood tradability verdicts for the research universe (owner rule, spec 2026-10-14.1).

GitHub Actions cannot reach the Robinhood MCP, so a Claude session checks symbols
with the READ-ONLY `get_equity_tradability` tool (at most 10 per call), saves the
JSON results, and imports them here. The weekly run reads the stored verdicts:

* a stock may be published only with a verdict of "tradable" that is at most
  spec.TRADABILITY_MAX_AGE_DAYS old;
* "not tradable" (or not found on Robinhood) excludes it with that reason;
* no verdict, or a stale one, excludes it as "not yet verified" and puts it on
  the to-check list (`robinhood_tradability_todo.json`) for the next session.

Only symbols, verdicts, reasons and check dates are stored, never an account
number or any other account data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from . import spec
from .providers import canonical

FILE = "robinhood_tradability.json"
TODO_FILE = "robinhood_tradability_todo.json"
ACCOUNT_KEYS = {"account_number", "rhs_account_number", "rhc_account_number", "account"}


class TradabilityError(ValueError):
    pass


def verdict_from_result(r: dict) -> tuple[bool, str]:
    """spec.TRADABILITY_RULE applied to one get_equity_tradability result row."""
    if r.get("tradeable") is not True:
        return False, "Robinhood: not tradeable"
    if str(r.get("state", "")).lower() != "active":
        return False, f"Robinhood: instrument state {r.get('state')!r}"
    by_type = {
        str(x.get("account_type")): str(x.get("account_type_tradability"))
        for x in r.get("account_type_tradabilities") or []
    }
    if by_type.get("individual") != "tradable":
        return False, "Robinhood: not tradable in an individual account during regular hours"
    return True, ""


def parse_results(raw: dict, checked_at: str) -> dict[str, dict]:
    """Verdicts from one saved get_equity_tradability response (results + not_found)."""
    if has_account_keys(raw):
        raise TradabilityError("payload contains account fields; save only the tool's `data` results")
    data = raw.get("data", raw)
    if not isinstance(data, dict) or "results" not in data:
        raise TradabilityError("not a get_equity_tradability response (no results)")
    out = {}
    for r in data.get("results") or []:
        ok, why = verdict_from_result(r)
        out[canonical(r["symbol"])] = {"tradable": ok, "reason": why, "checked_at": checked_at}
    for s in data.get("not_found") or []:
        out[canonical(s)] = {"tradable": False, "reason": "Robinhood: symbol not found", "checked_at": checked_at}
    return out


def has_account_keys(obj) -> bool:
    if isinstance(obj, dict):
        return any(str(k).lower() in ACCOUNT_KEYS for k in obj) or any(has_account_keys(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_account_keys(v) for v in obj)
    return False


@dataclass
class Tradability:
    symbols: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path) -> Tradability:
        p = Path(data_dir) / FILE
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(dict(raw.get("symbols", {})))

    def save(self, data_dir: Path) -> Path:
        p = Path(data_dir) / FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "source": "Robinhood MCP get_equity_tradability (read-only), checked from a Claude session",
                    "rule": spec.TRADABILITY_RULE,
                    "max_age_days": spec.TRADABILITY_MAX_AGE_DAYS,
                    "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "symbols": dict(sorted(self.symbols.items())),
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        return p

    def merge(self, verdicts: dict[str, dict]) -> int:
        """Newer checks replace older ones; returns how many symbols changed."""
        n = 0
        for s, v in verdicts.items():
            old = self.symbols.get(s)
            if old is None or v["checked_at"] >= old.get("checked_at", ""):
                self.symbols[s] = v
                n += 1
        return n

    def check(self, symbol: str, as_of: date) -> tuple[bool | None, str]:
        """(True, '') tradable; (False, reason) not tradable; (None, reason) not yet verified."""
        v = self.symbols.get(canonical(symbol))
        if v is None:
            return None, "Robinhood tradability not yet verified"
        age = (as_of - datetime.fromisoformat(v["checked_at"]).date()).days
        if age > spec.TRADABILITY_MAX_AGE_DAYS:
            return None, f"Robinhood tradability check is {age} days old (max {spec.TRADABILITY_MAX_AGE_DAYS})"
        if age < -1:
            return None, "Robinhood tradability check is dated after the as-of date"
        return (True, "") if v["tradable"] else (False, v.get("reason") or "Robinhood: not tradable")

    @classmethod
    def all_tradable(cls, symbols, checked_at: str) -> Tradability:
        """For tests and fixtures."""
        return cls({canonical(s): {"tradable": True, "reason": "", "checked_at": checked_at} for s in symbols})


def write_todo(data_dir: Path, todo: list[dict], as_of: date) -> Path:
    p = Path(data_dir) / TODO_FILE
    p.write_text(
        json.dumps(
            {
                "as_of": as_of.isoformat(),
                "count": len(todo),
                "instructions": "Check with the read-only Robinhood get_equity_tradability tool "
                "(Agent-trading account, at most 10 symbols per call), save each "
                "response, then run: python -m agent_trading.dashboard tradability "
                "import --data <dir> <files>",
                "symbols": todo,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return p


def read_todo(data_dir: Path) -> list[str]:
    p = Path(data_dir) / TODO_FILE
    if not p.exists():
        return []
    return [t["ticker"] for t in json.loads(p.read_text(encoding="utf-8")).get("symbols", [])]
