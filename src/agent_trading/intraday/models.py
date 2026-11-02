"""Timestamped input contract. All prices are observed data, never model estimates."""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .config import StrictModel


class Bar(StrictModel):
    end: AwareDatetime  # end of a completed ONE-minute bar
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    vwap: float = Field(gt=0)  # vendor's actual per-bar volume weighted price

    @model_validator(mode="after")
    def prices(self):
        if not self.low <= min(self.open, self.close, self.vwap) <= max(self.open, self.close, self.vwap) <= self.high:
            raise ValueError("inconsistent OHLC/VWAP")
        if self.end.second or self.end.microsecond:
            raise ValueError("bar end must be minute-aligned")
        return self


class Contract(StrictModel):
    symbol: str
    underlying: str
    right: Literal["CALL", "PUT"]
    expiry: date
    strike: float = Field(gt=0)
    multiplier: int = Field(default=100, gt=0, strict=True)
    bid: float = Field(ge=0)
    ask: float = Field(gt=0)
    bid_size: int = Field(ge=0, strict=True)
    ask_size: int = Field(ge=0, strict=True)
    quote_at: AwareDatetime
    quote_time_basis: Literal["exchange", "changed_depth_receipt"] = "exchange"
    underlying_at: AwareDatetime
    underlying_price: float = Field(gt=0)
    volume_at: AwareDatetime
    volume: int = Field(ge=0, strict=True)
    open_interest: int = Field(ge=0, strict=True)
    delta: float = Field(ge=-1, le=1)
    gamma: float = Field(ge=0)
    theta: float
    vega: float = Field(ge=0)
    iv: float = Field(gt=0)
    greek_units: Literal["standard", "longbridge_raw"] = "standard"
    source: str = Field(min_length=1)
    feed: Literal["realtime", "delayed", "fixture"]


class EventRisk(StrictModel):
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    status: Literal["clear", "blocked", "unknown"]
    source: str = Field(min_length=1)
    summary: str


class Snapshot(StrictModel):
    observed_at: AwareDatetime
    membership_at: AwareDatetime
    membership_source: str = Field(min_length=1)
    universe: dict[str, str]  # constituent -> sector ETF (e.g. AAPL -> XLK)
    bars: dict[str, list[Bar]]
    contracts: list[Contract] = Field(default_factory=list)
    events: dict[str, EventRisk] = Field(default_factory=dict)  # ticker and MARKET required
    feed: Literal["realtime", "delayed", "fixture"]
    source: str = Field(min_length=1)
    problems: list[str] = Field(default_factory=list)


class Signal(StrictModel):
    symbol: str
    right: Literal["CALL", "PUT"]
    timestamp: AwareDatetime
    score: float = Field(ge=0, le=100)
    qualified: bool
    reasons: list[str]
    factors: dict[str, float | bool | str]


class Scan(StrictModel):
    timestamp: AwareDatetime
    source: str
    feed: str
    expected: int
    scanned: int
    coverage: float
    signals: list[Signal]
    rejected: dict[str, str]
    problems: list[str]

    def top(self, right: str) -> list[Signal]:
        if self.problems:
            return []
        return sorted(
            (s for s in self.signals if s.qualified and s.right == right), key=lambda s: (-s.score, s.symbol)
        )[:5]
