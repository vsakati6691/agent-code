"""Read-only brokerage account snapshot.

A Claude session reads the account through the Robinhood MCP (get_accounts,
get_portfolio, get_equity_positions, get_equity_orders) and saves the JSON;
`account import` validates it and stores a masked copy. Nothing here can talk
to a broker or place orders. Only the last four digits of the account number
are ever stored.

Input JSON shape:
{
  "fetched_at": "2026-10-12T14:00:00+00:00",
  "account_number": "...",            # full or last-4; masked on import
  "nickname": "Agent-trading",
  "unsettled_funds": "0",             # from get_accounts; required for live buy tickets
  "account_type": "limited_margin",   # from get_accounts (informational)
  "portfolio": {"total_value": "1000", "cash": "1000", "buying_power": {"buying_power": "1000"}},
  "positions": [{"symbol": "SPY", "quantity": "1", "average_buy_price": "500"}],
  "orders": [{"symbol": "SPY", "side": "sell", "state": "confirmed", "quantity": "1",
              "type": "market", "trigger": "stop", "stop_price": "480"}]   # as get_equity_orders returns them
}
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings

SNAPSHOT_FILE = "account_snapshot.json"
OPEN_ORDER_STATES = {"new", "queued", "confirmed", "unconfirmed", "partially_filled"}


class SnapshotError(ValueError):
    """The snapshot is malformed and must not be used."""


@dataclass(frozen=True)
class AccountSnapshot:
    fetched_at: str
    account_last4: str
    nickname: str
    total_value: float
    cash: float
    buying_power: float
    positions: list[dict] = field(default_factory=list)
    open_orders: list[dict] = field(default_factory=list)
    unsettled_funds: float | None = None  # None = not captured (live buys are then blocked)
    account_type: str = ""

    @property
    def settled_cash(self) -> float | None:
        """Cash that is settled and spendable without margin, or None when unknown."""
        if self.unsettled_funds is None:
            return None
        return max(0.0, min(self.cash, self.buying_power) - self.unsettled_funds)

    @property
    def fetched(self) -> datetime:
        return datetime.fromisoformat(self.fetched_at)


def _num(value, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise SnapshotError(f"{name} is missing or not a number") from None
    if not math.isfinite(out) or out < 0:
        raise SnapshotError(f"{name} must be a finite, non-negative number")
    return out


def _price(value, name: str) -> float | None:
    """Optional price: None when absent or zero (unknown), an error when not finite or negative."""
    if value in (None, ""):
        return None
    out = _num(value, name)
    return out if out > 0 else None


def parse_snapshot(raw: dict) -> AccountSnapshot:
    try:
        fetched = datetime.fromisoformat(str(raw["fetched_at"]))
    except (KeyError, ValueError):
        raise SnapshotError("fetched_at is missing or not an ISO timestamp") from None
    if fetched.tzinfo is None:
        raise SnapshotError("fetched_at must include a timezone")
    acct = str(raw.get("account_number", "")).strip()
    if len(acct) < 4:
        raise SnapshotError("account_number is missing")
    portfolio = raw.get("portfolio") or {}
    bp = portfolio.get("buying_power")
    bp_value = bp.get("buying_power") if isinstance(bp, dict) else bp
    positions = [
        {
            "symbol": str(p["symbol"]).upper(),
            "quantity": _num(p.get("quantity"), "position quantity"),
            "average_buy_price": _price(p.get("average_buy_price"), "average_buy_price"),
        }
        for p in raw.get("positions") or []
    ]
    # type/trigger/stop_price decide whether an open sell protects a position (live.stop_coverage)
    orders = [
        {
            "symbol": str(o.get("symbol", "")).upper(),
            "side": o.get("side"),
            "state": o.get("state"),
            "quantity": o.get("quantity"),
            "type": str(o.get("type") or "").lower(),
            "trigger": str(o.get("trigger") or "").lower(),
            "stop_price": _price(o.get("stop_price"), "stop_price"),
        }
        for o in raw.get("orders") or []
        if str(o.get("state", "")).lower() in OPEN_ORDER_STATES
    ]
    return AccountSnapshot(
        fetched_at=fetched.astimezone(UTC).isoformat(timespec="seconds"),
        account_last4=acct[-4:],
        nickname=str(raw.get("nickname", "")),
        total_value=_num(portfolio.get("total_value"), "total_value"),
        cash=_num(portfolio.get("cash"), "cash"),
        buying_power=_num(bp_value, "buying_power"),
        positions=positions,
        open_orders=orders,
        unsettled_funds=None
        if raw.get("unsettled_funds") in (None, "")
        else _num(raw["unsettled_funds"], "unsettled_funds"),
        account_type=str(raw.get("account_type", "")),
    )


def verify_snapshot(snap: AccountSnapshot, settings: Settings, now: datetime | None = None) -> list[str]:
    """Problems that make the snapshot unusable. Empty list = verified."""
    now = now or datetime.now(UTC)
    cfg = settings.broker
    problems = []
    if cfg.account_last4 and snap.account_last4 != cfg.account_last4:
        problems.append(f"account ••{snap.account_last4} is not the configured agent account ••{cfg.account_last4}")
    age_h = (now - snap.fetched).total_seconds() / 3600
    if age_h > cfg.snapshot_max_age_hours:
        problems.append(f"snapshot is {age_h:.0f} hours old (max {cfg.snapshot_max_age_hours:g})")
    if age_h < -0.1:
        problems.append("snapshot timestamp is in the future")
    return problems


def save_snapshot(settings: Settings, snap: AccountSnapshot) -> Path:
    path = settings.resolve(settings.data.cache_dir).parent / SNAPSHOT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snap), indent=2), encoding="utf-8")
    return path


def load_saved_snapshot(settings: Settings) -> AccountSnapshot | None:
    path = settings.resolve(settings.data.cache_dir).parent / SNAPSHOT_FILE
    if not path.exists():
        return None
    return AccountSnapshot(**json.loads(path.read_text(encoding="utf-8")))


def import_snapshot(settings: Settings, source: Path) -> tuple[AccountSnapshot, list[str]]:
    snap = parse_snapshot(json.loads(Path(source).read_text(encoding="utf-8")))
    save_snapshot(settings, snap)
    return snap, verify_snapshot(snap, settings)
