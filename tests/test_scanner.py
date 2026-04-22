from datetime import date, timedelta

import pytest

from market_pulse.data.models import Bar
from market_pulse.data.providers.base import Provider
from market_pulse.engine.scanner import Opportunity, scan


class _StubProvider(Provider):
    def __init__(self, bars_by_ticker: dict[str, list[Bar]]):
        self.bars_by_ticker = bars_by_ticker

    async def fetch_bars(self, ticker, start, end):
        return self.bars_by_ticker.get(ticker, [])


def _synthetic_bars(trend_up: bool = True, n: int = 200) -> list[Bar]:
    """Génère n bars consécutives, tendance up ou down, ancrée près d'aujourd'hui."""
    end = date.today()
    start = end - timedelta(days=n - 1)
    out = []
    price = 100.0
    for i in range(n):
        d = start + timedelta(days=i)
        price = price * (1.002 if trend_up else 0.998)
        out.append(Bar(d, price, price * 1.01, price * 0.99, price, 1_000_000))
    return out


@pytest.fixture
def stub_provider():
    return _StubProvider({
        "AAAA": _synthetic_bars(trend_up=True),
        "BBBB": _synthetic_bars(trend_up=False),
    })


async def test_scan_returns_opportunities(stub_provider, tmp_path):
    opps = await scan(
        tickers=["AAAA", "BBBB"],
        horizon="1w",
        provider=stub_provider,
        cache_path=tmp_path / "c.db",
        min_rr=0.0,  # no filter for test
    )
    assert isinstance(opps, list)
    assert all(isinstance(o, Opportunity) for o in opps)
    assert {o.ticker for o in opps} <= {"AAAA", "BBBB"}
    # Chaque opportunity a un historique de prix non-vide
    assert all(len(o.price_history) > 0 for o in opps)
    assert all(isinstance(p[1], float) for o in opps for p in o.price_history)


async def test_scan_filters_by_risk_reward(stub_provider, tmp_path):
    opps = await scan(
        tickers=["AAAA", "BBBB"],
        horizon="1w",
        provider=stub_provider,
        cache_path=tmp_path / "c.db",
        min_rr=10.0,  # filtre agressif
    )
    assert all(o.trade_plan.risk_reward >= 10.0 for o in opps)


async def test_scan_sorts_by_score_descending(stub_provider, tmp_path):
    opps = await scan(
        tickers=["AAAA", "BBBB"],
        horizon="1w",
        provider=stub_provider,
        cache_path=tmp_path / "c.db",
        min_rr=0.0,
    )
    scores = [o.score for o in opps]
    assert scores == sorted(scores, reverse=True)
