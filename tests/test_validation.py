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


def test_frozen_feed_rejected():
    df = make_bars()
    for i in (250, 251, 252):  # HON-style: flat $200 bars with almost no volume
        df.iloc[i, :4] = 200.0
        df.iloc[i, df.columns.get_loc("volume")] = 401
    df.iloc[253:, :4] = df.iloc[253:, :4] * (200 / df.iloc[253]["open"])  # avoid a split-like jump
    with pytest.raises(DataQualityError, match="frozen"):
        check(df)


def test_volume_dropout_with_normal_prices_is_kept():
    # Vendor glitch seen on NVDA (Aug 2010) and XLE (Oct 2025): prices fine, volume missing
    df = make_bars()
    df.iloc[100:104, df.columns.get_loc("volume")] = 0
    assert len(check(df)) == 300


def test_trim_frozen_history_keeps_data_after_old_shell_period():
    from agent_trading.data.validation import trim_frozen_history

    df = make_bars()
    df.iloc[20:24, :4] = 10.0  # SPAC-shell style flat bars early on
    df.iloc[24:, :4] = df.iloc[24:, :4] * (10 / df.iloc[24]["open"])
    trimmed, note = trim_frozen_history(df, "VRT")
    assert trimmed.index[0] == df.index[24] and "dropped" in note
    assert len(check(trimmed, min_bars=200)) == 276


def test_trim_frozen_history_rejects_recent_freeze():
    from agent_trading.data.validation import trim_frozen_history

    df = make_bars()
    df.iloc[-10:-6, :4] = df.iloc[-11]["close"]
    with pytest.raises(DataQualityError, match="recently"):
        trim_frozen_history(df, "HON")


def test_empty_rejected():
    with pytest.raises(DataQualityError):
        check(None)
