"""Optional local notification outbox for downstream integrations. No outbound network."""

import json
from pathlib import Path

from .store import Store

ALERT_KINDS = {
    "qualified_signal",
    "paper_order_submitted",
    "paper_fill",
    "paper_exit_submitted",
    "position_exit",
    "risk_limit",
    "provider_failure",
    "reconciliation_failed",
    "unresolved_overnight_positions",
}


def export_alerts(store: Store, path: str | Path) -> int:
    """Append an at-least-once JSONL outbox; downstream readers deduplicate by event id.

    A crash after append but before cursor commit can repeat an event, never lose it.
    External consumers are configured by the owner, separately from this simulator.
    """
    dest = Path(path).resolve()
    key = f"alert_cursor:{dest}"
    with store.transaction():
        cursor = int(store.get(key, "0"))
        rows = [e for e in store.rows("events") if e["id"] > cursor]
        alerts = [{**e, "payload": json.loads(e["payload"])} for e in rows if e["kind"] in ALERT_KINDS]
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as out:
            for event in alerts:
                out.write(json.dumps(event, allow_nan=False) + "\n")
            out.flush()
        if rows:
            store.set(key, str(rows[-1]["id"]))
    return len(alerts)
