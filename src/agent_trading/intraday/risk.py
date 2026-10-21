"""Central entry gate, called inside the same transaction as order reservation."""

from dataclasses import dataclass
from datetime import datetime

from .calendar import NY, entry_window
from .config import Settings
from .models import Contract, Signal
from .options import cents, contract_problems
from .store import Store


@dataclass(frozen=True)
class Decision:
    quantity: int
    reasons: tuple[str, ...]


class RiskEngine:
    def __init__(self, store: Store, cfg: Settings):
        self.store, self.cfg = store, cfg

    def assess(
        self, signal: Signal, contract: Contract, limit_cents: int, now: datetime, fixture: bool, cash: int
    ) -> Decision:
        cfg, db = self.cfg, self.store.db
        day = now.astimezone(NY).date().isoformat()
        reasons = contract_problems(contract, signal.symbol, signal.right, now, cfg, fixture)
        if not entry_window(now):
            reasons.append("outside trading window")
        if self.store.get("enabled") != "true" or self.store.get("running") != "true":
            reasons.append("new entries disabled")
        if self.store.get("killed") == "true" or self.store.get("kill_day") == day:
            reasons.append("kill switch engaged")
        if (
            not signal.qualified
            or signal.score < cfg.minimum_score
            or not 0 <= (now - signal.timestamp).total_seconds() <= cfg.max_bar_age_seconds
        ):
            reasons.append("signal invalid or stale")
        if db.execute(
            "SELECT 1 FROM orders WHERE day=? AND underlying=? AND side='BUY'", (day, signal.symbol)
        ).fetchone():
            reasons.append("duplicate symbol for session")
        count = db.execute("SELECT COUNT(*) FROM orders WHERE day=? AND side='BUY'", (day,)).fetchone()[0]
        if count >= cfg.max_trades:
            reasons.append("daily entry count limit")
        active = db.execute("SELECT COUNT(*) FROM positions WHERE quantity>0").fetchone()[0]
        pending = db.execute(
            "SELECT COUNT(*) FROM orders WHERE side='BUY' AND status IN ('pending','partial') AND filled=0"
        ).fetchone()[0]
        if active + pending >= cfg.max_positions:
            reasons.append("maximum position count")
        if db.execute("SELECT 1 FROM positions WHERE underlying=? AND quantity>0", (signal.symbol,)).fetchone():
            reasons.append("no averaging down or second position in underlying")
        fee = cents(cfg.fee_per_contract)
        realized_loss = -db.execute(
            "SELECT COALESCE(SUM(MIN(pnl,0)),0) FROM fills WHERE side='SELL' AND substr(time,1,10)=?", (day,)
        ).fetchone()[0]
        exposure = db.execute(
            "SELECT COALESCE(SUM(cost+quantity*?),0) FROM positions WHERE quantity>0", (fee,)
        ).fetchone()[0]
        reserved = db.execute(
            "SELECT COALESCE(SUM((quantity-filled)*(limit_cents*100+2*?)),0) FROM orders WHERE side='BUY' AND status IN ('pending','partial')",
            (fee,),
        ).fetchone()[0]
        per_contract = limit_cents * contract.multiplier + 2 * fee
        remaining = min(
            cents(cfg.max_trade_loss),
            cents(cfg.daily_loss_budget) - realized_loss - exposure - reserved,
            cash - reserved,
        )
        quantity = max(0, remaining // per_contract)
        if quantity < 1:
            reasons.append("insufficient full-premium risk budget or settled cash")
        return Decision(0 if reasons else quantity, tuple(reasons))
