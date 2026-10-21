"""Validated, immutable configuration; paper risk ceilings can only be tightened."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Weights(StrictModel):
    trend: float = Field(default=30, ge=0)
    participation: float = Field(default=20, ge=0)
    relative_strength: float = Field(default=25, ge=0)
    momentum: float = Field(default=15, ge=0)
    context: float = Field(default=10, ge=0)

    @model_validator(mode="after")
    def total(self):
        if abs(sum(self.model_dump().values()) - 100) > 1e-8:
            raise ValueError("factor weights must sum to 100")
        return self


class Settings(StrictModel):
    mode: Literal["local_simulator"] = "local_simulator"
    initial_capital: float = Field(default=10000, gt=0, le=10000)
    max_trade_loss: float = Field(default=50, gt=0, le=50)
    daily_loss_budget: float = Field(default=100, gt=0, le=100)
    max_trades: int = Field(default=2, ge=1, le=2, strict=True)
    max_positions: int = Field(default=2, ge=1, le=2, strict=True)
    fee_per_contract: float = Field(default=0.65, ge=0)
    slippage: float = Field(default=0.01, ge=0)
    stop_fraction: float = Field(default=0.25, gt=0, lt=1)
    reward_to_risk: float = Field(default=1.5, ge=1, le=3)
    max_hold_minutes: int = Field(default=60, ge=15, le=60)
    order_timeout_seconds: int = Field(default=60, ge=1, le=120)
    max_quote_age_seconds: int = Field(default=30, ge=1, le=60)
    max_bar_age_seconds: int = Field(default=90, ge=1, le=120)
    minimum_score: float = Field(default=70, ge=0, le=100)
    minimum_rvol: float = Field(default=1.5, ge=1)
    rvol_sessions: int = Field(default=10, ge=3, le=30)
    minimum_coverage: float = Field(default=0.95, ge=0.9, le=1)
    minimum_delta: float = Field(default=0.4, gt=0, lt=1)
    maximum_delta: float = Field(default=0.6, gt=0, lt=1)
    minimum_oi: int = Field(default=500, ge=0)
    minimum_option_volume: int = Field(default=100, ge=0)
    maximum_spread: float = Field(default=0.1, gt=0, le=0.1)
    max_atr_fraction: float = Field(default=0.02, gt=0, le=0.1)
    provider_interval_seconds: float = Field(default=13, ge=0.1)
    provider_request_budget: int = Field(default=600, ge=1, le=5000)
    scan_deadline_seconds: int = Field(default=45, ge=5, le=120)
    weights: Weights = Field(default_factory=Weights)

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum_delta > self.maximum_delta:
            raise ValueError("invalid delta interval")
        if self.max_trade_loss > self.daily_loss_budget:
            raise ValueError("trade risk exceeds daily budget")
        if self.daily_loss_budget > self.initial_capital * 0.01:
            raise ValueError("daily loss budget exceeds 1% of paper capital")
        if self.max_trade_loss > self.initial_capital * 0.005:
            raise ValueError("trade risk exceeds 0.5% of paper capital")
        return self


def load_config(path: str | Path | None = None) -> Settings:
    return Settings.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}) if path else Settings()
