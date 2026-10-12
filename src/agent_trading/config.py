"""Settings loading and safety validation.

The loader is the first line of defence: it refuses to produce a Settings
object unless the configuration is paper-only, long-only, cash-only equities.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

API_KEY_ENV = "ALPHAVANTAGE_API_KEY"


class ConfigError(ValueError):
    """Raised for invalid or unsafe configuration."""


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.005
    max_open_risk_pct: float = 0.015
    max_position_pct: float = 0.25
    atr_stop_multiple: float = 2.5
    fractional_shares: bool = True
    min_order_notional: float = 1.0
    allow_short: bool = False
    allow_margin: bool = False
    allow_options: bool = False
    allow_crypto: bool = False


@dataclass(frozen=True)
class CostConfig:
    commission_per_order: float = 0.0
    slippage_bps: float = 10.0


@dataclass(frozen=True)
class DataConfig:
    provider: str = "alphavantage"
    cache_dir: str = "data/cache"
    outputsize: str = "compact"
    max_staleness_days: int = 4
    min_history_bars: int = 90
    request_pause_seconds: float = 12.5
    daily_request_budget: int = 24


@dataclass(frozen=True)
class StrategyConfig:
    fast_ma: int = 20
    slow_ma: int = 50
    momentum_lookback: int = 63
    rsi_period: int = 14
    rsi_max_entry: float = 75.0
    atr_period: int = 14
    volume_lookback: int = 20


@dataclass(frozen=True)
class ScreenConfig:
    min_price: float = 5.0
    min_avg_dollar_volume: float = 50_000_000.0


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int = 252
    test_bars: int = 63
    oos_fraction: float = 0.3
    grid: dict[str, list[Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportConfig:
    earnings_warning_days: int = 7


@dataclass(frozen=True)
class PathConfig:
    journal_db: str = "data/journal.db"
    reports_dir: str = "reports"
    logs_dir: str = "logs"


@dataclass(frozen=True)
class Settings:
    mode: str
    paper_starting_equity: float
    universe: dict[str, list[str]]
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    data: DataConfig = field(default_factory=DataConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    walkforward: WalkForwardConfig = field(default_factory=WalkForwardConfig)
    reports: ReportConfig = field(default_factory=ReportConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    base_dir: Path = Path(".")

    @property
    def symbols(self) -> list[str]:
        seen: dict[str, None] = {}
        for group in self.universe.values():
            for sym in group:
                seen[sym.upper()] = None
        return list(seen)

    def resolve(self, relative: str) -> Path:
        path = Path(relative)
        return path if path.is_absolute() else self.base_dir / path


def _build(cls, raw: dict[str, Any] | None, section: str):
    raw = raw or {}
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"Unknown keys in '{section}': {sorted(unknown)}")
    return cls(**raw)


def validate(settings: Settings) -> Settings:
    if settings.mode != "paper":
        raise ConfigError(
            f"mode={settings.mode!r} is not allowed; only 'paper' is supported in this version"
        )
    r = settings.risk
    for flag in ("allow_short", "allow_margin", "allow_options", "allow_crypto"):
        if getattr(r, flag):
            raise ConfigError(f"risk.{flag} must be false (prohibited by policy)")
    if not 0 < r.risk_per_trade_pct <= 0.01:
        raise ConfigError("risk.risk_per_trade_pct must be in (0, 0.01]")
    if not r.risk_per_trade_pct <= r.max_open_risk_pct <= 0.05:
        raise ConfigError("risk.max_open_risk_pct must be >= risk_per_trade_pct and <= 0.05")
    if not 0 < r.max_position_pct <= 1:
        raise ConfigError("risk.max_position_pct must be in (0, 1]")
    if r.min_order_notional < 0:
        raise ConfigError("risk.min_order_notional must be non-negative")
    if r.atr_stop_multiple <= 0:
        raise ConfigError("risk.atr_stop_multiple must be positive")
    if settings.paper_starting_equity <= 0:
        raise ConfigError("paper_starting_equity must be positive")
    if settings.costs.slippage_bps < 0 or settings.costs.commission_per_order < 0:
        raise ConfigError("costs must be non-negative")
    s = settings.strategy
    if not 0 < s.fast_ma < s.slow_ma:
        raise ConfigError("strategy.fast_ma must be positive and less than slow_ma")
    if settings.data.outputsize not in ("compact", "full"):
        raise ConfigError("data.outputsize must be 'compact' or 'full'")
    if not settings.symbols:
        raise ConfigError("universe is empty")
    return settings


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    sections = {
        "risk": RiskConfig,
        "costs": CostConfig,
        "data": DataConfig,
        "strategy": StrategyConfig,
        "screen": ScreenConfig,
        "walkforward": WalkForwardConfig,
        "reports": ReportConfig,
        "paths": PathConfig,
    }
    top_level = {"mode", "paper_starting_equity", "universe", *sections}
    unknown = set(raw) - top_level
    if unknown:
        raise ConfigError(f"Unknown top-level keys: {sorted(unknown)}")

    # Config lives in <project>/config/, so paths resolve from the project root.
    base_dir = path.resolve().parent.parent
    settings = Settings(
        mode=str(raw.get("mode", "")),
        paper_starting_equity=float(raw.get("paper_starting_equity", 0)),
        universe={k: [str(s).upper() for s in v] for k, v in (raw.get("universe") or {}).items()},
        base_dir=base_dir,
        **{name: _build(cls, raw.get(name), name) for name, cls in sections.items()},
    )
    return validate(settings)


def get_api_key() -> str:
    """Read the Alpha Vantage key from the environment / .env. Never log it."""
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key or key == "replace-me":
        raise ConfigError(
            f"{API_KEY_ENV} is not set. Copy .env.example to .env and add your key."
        )
    return key
