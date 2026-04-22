"""Indicateurs techniques (wrapper pandas-ta)."""
import pandas as pd
import pandas_ta as ta


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    return ta.rsi(close, length=period)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    df = ta.macd(close, fast=fast, slow=slow, signal=signal)
    return (
        df[f"MACD_{fast}_{slow}_{signal}"],
        df[f"MACDs_{fast}_{slow}_{signal}"],
        df[f"MACDh_{fast}_{slow}_{signal}"],
    )


def bollinger_bands(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    df = ta.bbands(close, length=period, std=std_dev)
    upper_col = next(c for c in df.columns if c.startswith(f"BBU_{period}_"))
    middle_col = next(c for c in df.columns if c.startswith(f"BBM_{period}_"))
    lower_col = next(c for c in df.columns if c.startswith(f"BBL_{period}_"))
    return df[upper_col], df[middle_col], df[lower_col]


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    return ta.atr(high, low, close, length=period)


def moving_average(close: pd.Series, period: int = 20) -> pd.Series:
    return close.rolling(window=period, min_periods=period).mean()
