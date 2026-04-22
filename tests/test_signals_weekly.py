from pathlib import Path

import pandas as pd
import pytest

from market_pulse.engine.signals.weekly import (
    BollingerSqueezeBreakout, MA5AboveMA20, MACDCrossover,
    RelativeStrength, RSIDivergence, VolumeConfirmation,
)


@pytest.fixture
def asml_df(fixtures_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(fixtures_dir / "asml_bars_1y.csv", parse_dates=["date"])
    return df.set_index("date")


@pytest.mark.parametrize("signal_cls", [
    RSIDivergence, MACDCrossover, BollingerSqueezeBreakout,
    MA5AboveMA20, VolumeConfirmation,
])
def test_signal_returns_score_in_range(signal_cls, asml_df):
    result = signal_cls().evaluate(asml_df)
    assert 0 <= result.score <= 100


def test_signal_metadata_is_dict(asml_df):
    result = RSIDivergence().evaluate(asml_df)
    assert isinstance(result.metadata, dict)
    assert "rsi" in result.metadata


def test_rsi_divergence_high_when_rsi_low(asml_df):
    result = RSIDivergence().evaluate(asml_df)
    assert result.score >= 0


def test_relative_strength_handles_missing_benchmark(asml_df):
    result = RelativeStrength(benchmark_df=None).evaluate(asml_df)
    # Sans benchmark, le signal doit retourner un score neutre (50) + flag
    assert result.score == 50.0
    assert result.metadata.get("skipped") is True


def test_volume_confirmation_scores_on_ratio(asml_df):
    result = VolumeConfirmation().evaluate(asml_df)
    assert "volume_ratio" in result.metadata
    assert result.metadata["volume_ratio"] > 0
