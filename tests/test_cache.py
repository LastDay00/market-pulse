from datetime import date

import pytest

from market_pulse.data.cache import BarCache
from market_pulse.data.models import Bar


@pytest.fixture
def cache(tmp_path):
    db_path = tmp_path / "test.db"
    return BarCache(db_path)


def test_cache_insert_and_get(cache):
    bars = [
        Bar(date(2026, 1, 2), 100.0, 105.0, 99.0, 104.0, 1_000_000),
        Bar(date(2026, 1, 3), 104.0, 108.0, 103.0, 107.5, 1_200_000),
    ]
    cache.upsert_bars("ASML", bars)
    retrieved = cache.get_bars("ASML")
    assert len(retrieved) == 2
    assert retrieved[0].close == 104.0
    assert retrieved[1].close == 107.5


def test_cache_returns_empty_for_unknown_ticker(cache):
    assert cache.get_bars("UNKNOWN") == []


def test_cache_upsert_overwrites_same_date(cache):
    cache.upsert_bars("ASML", [Bar(date(2026, 1, 2), 100, 105, 99, 104, 1_000_000)])
    cache.upsert_bars("ASML", [Bar(date(2026, 1, 2), 100, 105, 99, 999, 1_000_000)])
    bars = cache.get_bars("ASML")
    assert len(bars) == 1
    assert bars[0].close == 999


def test_cache_latest_date_returns_none_if_empty(cache):
    assert cache.latest_date("ASML") is None


def test_cache_latest_date_returns_max(cache):
    cache.upsert_bars("ASML", [
        Bar(date(2026, 1, 2), 100, 105, 99, 104, 1_000_000),
        Bar(date(2026, 1, 5), 104, 108, 103, 107, 1_200_000),
        Bar(date(2026, 1, 3), 104, 106, 103, 105, 900_000),
    ])
    assert cache.latest_date("ASML") == date(2026, 1, 5)
