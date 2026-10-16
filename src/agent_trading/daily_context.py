"""Shared daily research result and report disclaimer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .live import LiveResult
from .strategies.desk import DeskDecision
from .strategies.scanner import ScanResult

DISCLAIMER = (
    "> Research output, not investment advice. This system never places orders: live tickets are "
    "rule output for the account owner to review and place by hand. Signals are hypotheses; confidence "
    "labels are rule counts, not probabilities."
)


@dataclass
class DailyContext:
    as_of: date
    data_notes: list[str] = field(default_factory=list)
    universe_note: str = ""
    coverage: dict | None = None
    scan: ScanResult | None = None
    market: dict | None = None
    desk_regime: dict | None = None
    desk: list[DeskDecision] = field(default_factory=list)
    paper_events: list[str] = field(default_factory=list)
    paper_warnings: list[str] = field(default_factory=list)
    proposals: list = field(default_factory=list)
    status: object = None
    snapshots: dict = field(default_factory=dict)
    gtaa: dict = field(default_factory=dict)
    gtaa_rebalance: bool = False
    code: dict = field(default_factory=dict)
    config_hash: str = ""
    spec_warning: str = ""
    missed_run: str = ""
    manifest_path: str = ""
    live: LiveResult | None = None
    live_desk: list[DeskDecision] = field(default_factory=list)
