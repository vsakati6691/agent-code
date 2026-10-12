from datetime import date

import numpy as np
import pytest

from agent_trading.data.validation import DataQualityError, validate_bars

from .conftest import make_bars

AS_OF = date(2026, 10, 12)  # Monday; synthetic data ends Friday 2026-10-09


def check(df, as_of=AS_OF, stale=4, min_bars=90):
    return validate_bars(df, "TEST", as_of, stale, min_bars)


def test_good_data_passes():
    assert len(check(make_bars())) == 300


def test_stale_data_rejected():
    with pytest.raises(DataQualityError, match="stale"):
        check(make_bars(end="2026-09-25"))


def test_future_data_rejected():
    with pytest.raises(DataQualityError, match="after as-of"):
        check(make_bars(), as_of=date(2026, 10, 1))


def test_missing_values_rejected():
    df = make_bars()
    df.iloc[10, 0] = np.nan
    with pytest.raises(DataQualityError, match="missing values"):
        check(df)


def test_too_short_rejected():
    with pytest.raises(DataQualityError, match="only 50 bars"):
        check(make_bars(n=50))


def test_missing_column_rejected():
    with pytest.raises(DataQualityError, match="missing columns"):
        check(make_bars().drop(columns=["volume"]))


def test_inconsistent_ohlc_rejected():
    df = make_bars()
    df.iloc[5, df.columns.get_loc("high")] = df.iloc[5]["low"] * 0.5
    with pytest.raises(DataQualityError):
        check(df)


def test_unadjusted_split_rejected():
    df = make_bars()
    df.iloc[200:, :4] = df.iloc[200:, :4] / 4  # 4-for-1 split not adjusted
    with pytest.raises(DataQualityError, match="split"):
        check(df)


def test_empty_rejected():
    with pytest.raises(DataQualityError):
        check(None)
