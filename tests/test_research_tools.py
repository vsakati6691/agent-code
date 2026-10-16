"""T-bill data parsing and the no-look-ahead cash rate."""

import pandas as pd
import pytest

from agent_trading.data.alphavantage import AlphaVantageError, parse_treasury_json
from agent_trading.data.rates import daily_cash_rate


def test_parse_treasury_and_errors():
    s = parse_treasury_json({"data": [{"date": "2026-09-01", "value": "4.00"}, {"date": "2026-08-01", "value": "."}]})
    assert list(s.index) == [pd.Timestamp("2026-09-01")] and s.iloc[0] == 4.0
    with pytest.raises(AlphaVantageError):
        parse_treasury_json({"Information": "rate limit"})


def test_daily_rate_uses_previous_month_only():
    monthly = pd.Series([1.0, 5.0], index=pd.to_datetime(["2026-01-01", "2026-02-01"]))
    days = pd.bdate_range("2026-01-15", "2026-03-10")
    r = daily_cash_rate(monthly, days)
    assert r.loc["2026-01-20"] == 0.0  # January's average isn't known in January
    assert r.loc["2026-02-10"] == pytest.approx(0.01 / 252)  # February uses January's 1%
    assert r.loc["2026-03-02"] == pytest.approx(0.05 / 252)  # March uses February's 5%
