from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from market_pulse.data.providers.yfinance_provider import YFinanceProvider


@pytest.fixture
def asml_csv(fixtures_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(fixtures_dir / "asml_bars_1y.csv", parse_dates=["date"])
    df = df.set_index("date")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


class _FakeTicker:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def history(self, period: str = None, start=None, end=None, auto_adjust=False):
        return self._df


@pytest.fixture
def provider(monkeypatch, asml_csv):
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(asml_csv))
    return YFinanceProvider(max_concurrency=2)


async def test_fetch_bars_returns_bars(provider):
    bars = await provider.fetch_bars("ASML", date(2026, 1, 1), date(2026, 12, 31))
    assert len(bars) > 0
    assert all(b.close > 0 for b in bars)
    assert all(b.high >= b.low for b in bars)


async def test_fetch_bars_returns_empty_on_exception(monkeypatch):
    import yfinance

    def _raise(*a, **kw):
        raise RuntimeError("boom")

    class _BrokenTicker:
        history = _raise

    monkeypatch.setattr(yfinance, "Ticker", lambda t: _BrokenTicker())
    prov = YFinanceProvider(max_concurrency=1)
    bars = await prov.fetch_bars("BROKEN", date(2026, 1, 1), date(2026, 12, 31))
    assert bars == []
