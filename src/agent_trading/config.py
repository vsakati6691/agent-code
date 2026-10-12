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
    # Sizing assumes the stop may fill this fraction of the stop distance worse
    # (gaps, fast markets). 0.2 => a $5 risk budget plans for a 1.2x stop loss.
    stop_risk_buffer: float = 0.0
    # Positions whose daily returns correlate at or above max_correlation share
    # one risk budget of max_correlated_risk_pct.
    max_correlation: float = 0.8
    max_correlated_risk_pct: float = 0.01
    correlation_lookback: int = 60
    # Account-level circuit breakers (paper equity): no new entries after the
    # day's loss reaches daily_loss_limit_pct; shut down after a drawdown of
    # max_drawdown_pct from peak equity (exits still run).
    daily_loss_limit_pct: float = 0.01
    max_drawdown_pct: float = 0.08
    # Instrument-specific controls (e.g. leveraged ETFs)
    symbol_risk_pct: dict[str, float] = field(default_factory=dict)
    max_holding_days: dict[str, int] = field(default_factory=dict)
    exclusive_groups: list[list[str]] = field(default_factory=list)
    allow_short: bool = False
    allow_margin: bool = False
    allow_options: bool = False
    allow_crypto: bool = False


@dataclass(frozen=True)
class CostConfig:
    commission_per_order: float = 0.0
    slippage_bps: float = 10.0
    spread_bps: float = 0.0  # full quoted spread; half is paid on each side

    @property
    def per_side(self) -> float:
        """Fractional price penalty applied to every fill."""
        return (self.slippage_bps + self.spread_bps / 2) / 10_000


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
class EvaluationConfig:
    train_fraction: float = 0.6
    validation_fraction: float = 0.2  # the remainder is the untouched holdout
    min_trades: int = 30


@dataclass(frozen=True)
class RegimeConfig:
    benchmark: str = "SPY"
    fast_ma: int = 50
    slow_ma: int = 200
    vol_lookback: int = 20
    high_vol_threshold: float = 0.25  # annualised realised volatility


@dataclass(frozen=True)
class BrokerConfig:
    """Read-only account snapshot settings. Never used to place orders."""
    account_last4: str = ""
    account_nickname: str = ""
    snapshot_max_age_hours: float = 24.0


@dataclass(frozen=True)
class PaperConfig:
    order_expiry_days: int = 3


@dataclass(frozen=True)
class ScannerConfig:
    """Strategy A: S&P 500 scanner."""
    index_fund: str = "SPY"
    min_constituents: int = 495
    max_constituents: int = 510
    universe_max_age_days: int = 10
    min_coverage: float = 0.95
    benchmark: str = "SPY"
    min_price: float = 10.0
    min_avg_dollar_volume: float = 50_000_000.0
    max_spread_pct: float = 0.0025
    earnings_blackout_days: int = 5
    top_research: int = 10
    top_actionable: int = 3
    target_r_multiple: float = 2.0
    # Actionable candidates may have at most this many missing factors (0 = all
    # factors required). Research ranking requires the price factors.
    max_missing_factors_actionable: int = 0
    weights: dict[str, float] = field(default_factory=lambda: {
        "price_strength": 0.35, "volume": 0.10, "quality": 0.20, "valuation": 0.10, "risk": 0.25})


@dataclass(frozen=True)
class DeskConfig:
    """Strategy B: focused daily desk."""
    symbols: list[str] = field(default_factory=lambda: ["TQQQ", "SQQQ", "IBIT", "NVDA"])
    underlying: str = "QQQ"
    leveraged_long: str = "TQQQ"
    leveraged_inverse: str = "SQQQ"
    bitcoin_instrument: str = "IBIT"
    nvda_benchmark: str = "SMH"
    max_vol_long: float = 0.25
    max_vol_inverse: float = 0.30
    event_blackout_days: int = 1
    earnings_blackout_days: int = 5
    nasdaq_leaders: list[str] = field(default_factory=lambda: [
        "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA"])


@dataclass(frozen=True)
class GTAAConfig:
    """Strategy C: Faber multi-asset trend, rebalanced at month-end."""
    enabled: bool = True
    assets: list[str] = field(default_factory=lambda: ["SPY", "EFA", "IEF", "DBC", "VNQ", "TLT", "GLD"])
    sma_months: int = 10


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
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    desk: DeskConfig = field(default_factory=DeskConfig)
    gtaa: GTAAConfig = field(default_factory=GTAAConfig)
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
    if not 0 <= r.stop_risk_buffer <= 2:
        raise ConfigError("risk.stop_risk_buffer must be in [0, 2]")
    if not 0 < r.max_correlation <= 1:
        raise ConfigError("risk.max_correlation must be in (0, 1]")
    if not r.risk_per_trade_pct <= r.max_correlated_risk_pct <= r.max_open_risk_pct:
        raise ConfigError("risk.max_correlated_risk_pct must be between risk_per_trade_pct and max_open_risk_pct")
    if r.correlation_lookback < 10:
        raise ConfigError("risk.correlation_lookback must be at least 10")
    if not 0 < r.daily_loss_limit_pct <= 0.05:
        raise ConfigError("risk.daily_loss_limit_pct must be in (0, 0.05]")
    if not 0 < r.max_drawdown_pct <= 0.25:
        raise ConfigError("risk.max_drawdown_pct must be in (0, 0.25]")
    for sym, pct in r.symbol_risk_pct.items():
        if not 0 < pct <= r.risk_per_trade_pct:
            raise ConfigError(f"risk.symbol_risk_pct[{sym}] may only tighten the per-trade limit")
    if any(d < 1 for d in r.max_holding_days.values()):
        raise ConfigError("risk.max_holding_days values must be at least 1")
    sc = settings.scanner
    if abs(sum(sc.weights.values()) - 1.0) > 1e-6 or any(w < 0 for w in sc.weights.values()):
        raise ConfigError("scanner.weights must be non-negative and sum to 1")
    if settings.paper_starting_equity <= 0:
        raise ConfigError("paper_starting_equity must be positive")
    c = settings.costs
    if c.slippage_bps < 0 or c.commission_per_order < 0 or c.spread_bps < 0:
        raise ConfigError("costs must be non-negative")
    e = settings.evaluation
    if not (0 < e.train_fraction and 0 < e.validation_fraction and e.train_fraction + e.validation_fraction < 1):
        raise ConfigError("evaluation fractions must be positive and leave room for a holdout")
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
        "evaluation": EvaluationConfig,
        "regime": RegimeConfig,
        "broker": BrokerConfig,
        "paper": PaperConfig,
        "scanner": ScannerConfig,
        "desk": DeskConfig,
        "gtaa": GTAAConfig,
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
