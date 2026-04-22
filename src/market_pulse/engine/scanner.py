"""Orchestration du scan : univers → signals → score → trade plan."""
import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from market_pulse.data.cache import BarCache
from market_pulse.data.models import Bar
from market_pulse.data.providers.base import NewsItem, Provider, TickerMeta
from market_pulse.engine.scoring import aggregate_score
from market_pulse.engine.signals.weekly import (
    BollingerSqueezeBreakout, MA5AboveMA20, MACDCrossover,
    RelativeStrength, RSIDivergence, VolumeConfirmation,
)
from market_pulse.engine.trade_plan import TradePlan, compute_trade_plan

HORIZON_SIGNALS_1W = [
    RSIDivergence(),
    MACDCrossover(),
    BollingerSqueezeBreakout(),
    MA5AboveMA20(),
    VolumeConfirmation(),
    RelativeStrength(benchmark_df=None),
]


@dataclass(frozen=False)
class Opportunity:
    ticker: str
    horizon: str
    score: float
    trade_plan: TradePlan
    signal_details: list[tuple[str, float, dict]]
    recent_bars: list[Bar]  # 252 derniers jours OHLCV (chart + stats)
    meta: TickerMeta | None = None
    news: list[NewsItem] = field(default_factory=list)


def _bars_to_df(bars: list[Bar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "Open": [b.open for b in bars],
            "High": [b.high for b in bars],
            "Low": [b.low for b in bars],
            "Close": [b.close for b in bars],
            "Volume": [b.volume for b in bars],
        },
        index=pd.DatetimeIndex([b.date for b in bars]),
    )


async def _load_bars(
    ticker: str, provider: Provider, cache: BarCache, lookback_days: int
) -> list[Bar]:
    today = date.today()
    start = today - timedelta(days=lookback_days)
    cached = cache.get_bars(ticker)
    if cached and cached[-1].date >= today - timedelta(days=3):
        return cached
    fresh = await provider.fetch_bars(ticker, start, today)
    if fresh:
        cache.upsert_bars(ticker, fresh)
    return fresh or cached


def _score_ticker(df: pd.DataFrame, signals) -> tuple[float, list[tuple[str, float, dict]]]:
    results = [(sig.evaluate(df), sig.weight) for sig in signals]
    score = aggregate_score(results)
    details = [(sig.name, r.score, r.metadata) for sig, (r, _) in zip(signals, results)]
    return score, details


async def scan(
    tickers: list[str],
    horizon: str,
    provider: Provider,
    cache_path: Path,
    min_rr: float = 2.0,
    lookback_days: int = 365,
    enrich_top_n: int = 20,
) -> list[Opportunity]:
    if horizon != "1w":
        raise NotImplementedError("Phase 1 supports only horizon='1w'")

    cache = BarCache(cache_path)
    signals = HORIZON_SIGNALS_1W

    async def _process(ticker: str) -> Opportunity | None:
        bars = await _load_bars(ticker, provider, cache, lookback_days)
        if len(bars) < 30:
            return None
        df = _bars_to_df(bars)
        score, details = _score_ticker(df, signals)
        plan = compute_trade_plan(df, horizon=horizon)
        if plan.risk_reward < min_rr:
            return None
        recent_bars = bars[-252:]
        return Opportunity(
            ticker=ticker, horizon=horizon, score=score,
            trade_plan=plan, signal_details=details,
            recent_bars=recent_bars,
        )

    results = await asyncio.gather(*(_process(t) for t in tickers))
    opps = [o for o in results if o is not None]
    opps.sort(key=lambda o: o.score, reverse=True)

    # Enrichissement meta + news pour les top N seulement (coût réseau contenu)
    top = opps[:enrich_top_n]

    async def _enrich(opp: Opportunity) -> None:
        meta, news = await asyncio.gather(
            provider.fetch_meta(opp.ticker),
            provider.fetch_news(opp.ticker, max_items=5),
        )
        opp.meta = meta
        opp.news = news

    await asyncio.gather(*(_enrich(o) for o in top))

    cache.close()
    return opps
