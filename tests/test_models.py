from datetime import date

import pytest

from market_pulse.data.models import Bar


def test_bar_is_frozen_dataclass():
    bar = Bar(date=date(2026, 1, 2), open=100.0, high=105.0,
              low=99.0, close=104.0, volume=1_000_000)
    with pytest.raises(Exception):
        bar.close = 200.0  # type: ignore[misc]


def test_bar_rejects_invalid_prices():
    with pytest.raises(ValueError, match="high must be >= low"):
        Bar(date=date(2026, 1, 2), open=100.0, high=95.0,
            low=99.0, close=104.0, volume=1_000_000)


def test_bar_rejects_negative_volume():
    with pytest.raises(ValueError, match="volume must be >= 0"):
        Bar(date=date(2026, 1, 2), open=100.0, high=105.0,
            low=99.0, close=104.0, volume=-1)
