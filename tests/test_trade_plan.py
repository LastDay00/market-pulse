import pandas as pd
import pytest

from market_pulse.engine.trade_plan import TradePlan, compute_trade_plan


@pytest.fixture
def rising_df():
    """Série linéaire croissante de 60 jours, ATR ~= 2."""
    dates = pd.date_range("2026-01-01", periods=60, freq="D")
    close = pd.Series(range(100, 160), index=dates, dtype=float)
    high = close + 1
    low = close - 1
    return pd.DataFrame({
        "Open": close, "High": high, "Low": low, "Close": close,
        "Volume": [1_000_000] * 60,
    }, index=dates)


def test_trade_plan_returns_tradeplan_instance(rising_df):
    plan = compute_trade_plan(rising_df, horizon="1w")
    assert isinstance(plan, TradePlan)


def test_trade_plan_entry_equals_last_close(rising_df):
    plan = compute_trade_plan(rising_df, horizon="1w")
    assert plan.entry == float(rising_df["Close"].iloc[-1])


def test_trade_plan_tp_above_entry(rising_df):
    plan = compute_trade_plan(rising_df, horizon="1w")
    assert plan.target > plan.entry


def test_trade_plan_sl_below_entry(rising_df):
    plan = compute_trade_plan(rising_df, horizon="1w")
    assert plan.stop < plan.entry


def test_risk_reward_is_positive(rising_df):
    plan = compute_trade_plan(rising_df, horizon="1w")
    assert plan.risk_reward > 0


def test_unknown_horizon_raises(rising_df):
    with pytest.raises(ValueError, match="unknown horizon"):
        compute_trade_plan(rising_df, horizon="42h")
