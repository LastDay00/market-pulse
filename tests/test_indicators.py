from pathlib import Path

import pandas as pd
import pytest

from market_pulse.engine.indicators import (
    atr, bollinger_bands, macd, moving_average, rsi,
)


@pytest.fixture
def asml_df(fixtures_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(fixtures_dir / "asml_bars_1y.csv", parse_dates=["date"])
    return df.set_index("date")


def test_rsi_14_stays_between_0_and_100(asml_df):
    values = rsi(asml_df["Close"], period=14)
    valid = values.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()
    assert len(valid) > 200  # au moins 200 valeurs non-NaN sur 1 an


def test_macd_returns_three_series(asml_df):
    line, signal_, hist = macd(asml_df["Close"])
    assert len(line) == len(asml_df)
    assert len(signal_) == len(asml_df)
    assert len(hist) == len(asml_df)


def test_bollinger_upper_always_above_lower(asml_df):
    upper, middle, lower = bollinger_bands(asml_df["Close"], period=20, std_dev=2.0)
    valid = upper.dropna().index.intersection(lower.dropna().index)
    assert (upper.loc[valid] >= lower.loc[valid]).all()


def test_atr_is_positive(asml_df):
    values = atr(asml_df["High"], asml_df["Low"], asml_df["Close"], period=14)
    valid = values.dropna()
    assert (valid >= 0).all()


def test_moving_average_length_and_nan_behavior(asml_df):
    ma20 = moving_average(asml_df["Close"], period=20)
    assert len(ma20) == len(asml_df)
    assert ma20.iloc[:19].isna().all()
    assert ma20.iloc[19:].notna().all()
