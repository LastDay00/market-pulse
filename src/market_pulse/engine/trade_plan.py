"""Calcul du plan de trade : entrée, objectif, stop, R:R."""
from dataclasses import dataclass

import pandas as pd

from market_pulse.engine.indicators import atr

ATR_MULTIPLIERS = {"1d": 1.5, "1w": 3.0, "1m": 6.0, "1y": 12.0}
LOOKBACK_RESISTANCE_DAYS = {"1d": 30, "1w": 120, "1m": 252, "1y": 504}
LOOKBACK_SUPPORT_DAYS = {"1d": 20, "1w": 60, "1m": 120, "1y": 252}


@dataclass(frozen=True)
class TradePlan:
    entry: float
    target: float
    stop: float
    risk_reward: float
    horizon: str


def compute_trade_plan(df: pd.DataFrame, horizon: str) -> TradePlan:
    if horizon not in ATR_MULTIPLIERS:
        raise ValueError(f"unknown horizon: {horizon}")

    entry = float(df["Close"].iloc[-1])
    atr_values = atr(df["High"], df["Low"], df["Close"], period=14).dropna()
    current_atr = float(atr_values.iloc[-1]) if len(atr_values) else entry * 0.02

    k = ATR_MULTIPLIERS[horizon]
    lookback_r = min(LOOKBACK_RESISTANCE_DAYS[horizon], len(df))
    lookback_s = min(LOOKBACK_SUPPORT_DAYS[horizon], len(df))

    recent_high = float(df["High"].iloc[-lookback_r:].max())
    recent_low = float(df["Low"].iloc[-lookback_s:].min())

    atr_target = entry + k * current_atr
    target = min(atr_target, recent_high) if recent_high > entry else atr_target

    atr_stop = entry - 1.0 * current_atr
    support_stop = recent_low - 0.5 * current_atr
    stop = max(atr_stop, support_stop)

    rr = (target - entry) / (entry - stop) if entry > stop else 0.0

    return TradePlan(entry=entry, target=target, stop=stop,
                     risk_reward=rr, horizon=horizon)
