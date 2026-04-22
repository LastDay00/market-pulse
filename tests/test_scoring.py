import pytest

from market_pulse.engine.scoring import aggregate_score
from market_pulse.engine.signals.base import SignalResult


def test_aggregate_weighted_average():
    results = [
        (SignalResult(80.0, {}), 0.5),
        (SignalResult(40.0, {}), 0.5),
    ]
    assert aggregate_score(results) == 60.0


def test_aggregate_handles_zero_weights():
    with pytest.raises(ValueError, match="sum of weights"):
        aggregate_score([(SignalResult(80.0, {}), 0.0)])


def test_aggregate_returns_score_0_to_100():
    results = [
        (SignalResult(100.0, {}), 0.3),
        (SignalResult(50.0, {}), 0.3),
        (SignalResult(0.0, {}), 0.4),
    ]
    score = aggregate_score(results)
    assert 0 <= score <= 100


def test_aggregate_ignores_skipped_signals():
    results = [
        (SignalResult(90.0, {}), 0.5),
        (SignalResult(50.0, {"skipped": True}), 0.5),  # doit être ignoré
    ]
    assert aggregate_score(results) == 90.0


def test_aggregate_all_skipped_returns_50():
    results = [
        (SignalResult(50.0, {"skipped": True}), 0.5),
        (SignalResult(50.0, {"skipped": True}), 0.5),
    ]
    assert aggregate_score(results) == 50.0
