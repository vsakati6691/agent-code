"""Explicit synthetic test scenario. Never use this generator as observed market data."""

from datetime import datetime, time, timedelta

from .calendar import NY, next_session, session
from .config import Settings
from .models import Bar, Contract, EventRisk, Snapshot


def demo_snapshot(now: datetime, cfg: Settings, *, bearish: bool = False, premium: float = 0.4) -> Snapshot:
    now = now.astimezone(NY)
    direction = -1 if bearish else 1
    days, day = [], now.date() - timedelta(days=1)
    while len(days) < cfg.rvol_sessions:
        if session(day):
            days.append(day)
        day -= timedelta(days=1)
    all_bars = {}
    for symbol, slope in {"ALFA": 0.04, "BETA": 0.035, "SPY": 0.002, "XLK": 0.004}.items():
        rows = []
        for day in sorted(days) + [now.date()]:
            s = session(day)
            stop = min(now, s.close) if day == now.date() else s.close
            count = int((stop - s.open).total_seconds() // 60)
            for i in range(count):
                current = day == now.date()
                move = (slope if current else 0.0005) * direction
                opening = 100 + move * i
                closing = opening + move
                volume = (300 if i >= 15 else 200) if current else 100
                rows.append(
                    Bar(
                        end=s.open + timedelta(minutes=i + 1),
                        open=opening,
                        close=closing,
                        high=max(opening, closing) + 0.01,
                        low=min(opening, closing) - 0.01,
                        vwap=(opening + closing) / 2,
                        volume=volume,
                    )
                )
        all_bars[symbol] = rows
    expiry = next_session(now.date())
    contracts = [
        Contract(
            symbol=f"O:{symbol}{expiry:%y%m%d}{'P' if bearish else 'C'}00100000",
            underlying=symbol,
            right="PUT" if bearish else "CALL",
            expiry=expiry,
            strike=100,
            bid=round(premium - 0.02, 2),
            ask=premium,
            bid_size=1,
            ask_size=1,
            quote_at=now,
            underlying_at=now,
            underlying_price=all_bars[symbol][-1].close,
            volume_at=now,
            volume=200,
            open_interest=1000,
            delta=direction * 0.5,
            gamma=0.02,
            theta=-0.05,
            vega=0.1,
            iv=0.3,
            source="SYNTHETIC TEST FIXTURE",
            feed="fixture",
        )
        for symbol in ["ALFA", "BETA"]
    ]
    return Snapshot(
        observed_at=now,
        membership_at=datetime.combine(now.date(), time(8, 30), NY),
        membership_source="SYNTHETIC TWO-SYMBOL UNIVERSE; NOT S&P 500",
        universe={"ALFA": "XLK", "BETA": "XLK"},
        bars=all_bars,
        contracts=contracts,
        events={
            s: EventRisk(
                observed_at=now,
                valid_until=now + timedelta(minutes=5),
                status="clear",
                summary="synthetic clear-event fixture",
                source="SYNTHETIC TEST FIXTURE",
            )
            for s in ["ALFA", "BETA", "MARKET"]
        },
        feed="fixture",
        source="SYNTHETIC TEST FIXTURE — no market observations",
    )
