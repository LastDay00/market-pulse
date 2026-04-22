"""Orchestration du scan : univers → signals → score → trade plan."""
import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from market_pulse.data.cache import BarCache
from market_pulse.data.models import Bar
from market_pulse.data.providers.base import (
    Fundamentals, NewsItem, Provider, TickerMeta,
)
from market_pulse.engine.scoring import aggregate_score
from market_pulse.engine.signals.weekly import (
    BollingerSqueezeBreakout, MA5AboveMA20, MACDCrossover,
    RelativeStrength, RSIDivergence, VolumeConfirmation,
)
from market_pulse.engine.signals.weekly_bear import (
    BollingerSqueezeBreakdownBear, MA5BelowMA20Bear, MACDBearCrossover,
    RelativeWeaknessBear, RSIOverboughtBear, VolumeConfirmationBear,
)
from market_pulse.engine.trade_plan import (
    ATR_MULTIPLIERS, TradePlan, compute_trade_plan,
)

HORIZON_SIGNALS_1W_LONG = [
    RSIDivergence(),
    MACDCrossover(),
    BollingerSqueezeBreakout(),
    MA5AboveMA20(),
    VolumeConfirmation(),
    RelativeStrength(benchmark_df=None),
]

HORIZON_SIGNALS_1W_SHORT = [
    RSIOverboughtBear(),
    MACDBearCrossover(),
    BollingerSqueezeBreakdownBear(),
    MA5BelowMA20Bear(),
    VolumeConfirmationBear(),
    RelativeWeaknessBear(benchmark_df=None),
]


async def _translate_news_titles(titles: list[str]) -> list[str]:
    """Traduit une liste de titres EN → FR via deep_translator.

    Silencieux en cas d'erreur (pas de réseau, rate-limit) : retourne les
    titres originaux. On fait tout en une seule requête asynchrone via executor.
    """
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return titles

    loop = asyncio.get_running_loop()

    def _do_translate() -> list[str]:
        try:
            translator = GoogleTranslator(source="auto", target="fr")
            # translate_batch si dispo, sinon boucle
            try:
                return translator.translate_batch(titles)
            except Exception:
                return [translator.translate(t) or t for t in titles]
        except Exception:
            return titles

    try:
        return await loop.run_in_executor(None, _do_translate)
    except Exception:
        return titles


@dataclass(frozen=False)
class Opportunity:
    ticker: str
    horizon: str
    score: float                  # Score affiché (technique initial, puis blended après F)
    trade_plan: TradePlan
    signal_details: list[tuple[str, float, dict]]
    recent_bars: list[Bar]
    name: str = ""
    meta: TickerMeta | None = None
    news: list[NewsItem] = field(default_factory=list)
    fundamentals: Fundamentals | None = None
    # Scores détaillés, renseignés après enrichment avec fondamentaux
    technical_score: float | None = None   # Score d'origine (pur technique)
    fundamental_score: float | None = None # Score fondamental 0-100
    blended: bool = False                  # True si .score est un mix tech+fonda


def _score_low_is_good(v: float | None, good_max: float, bad_min: float) -> float | None:
    """Ratio où la valeur basse est favorable (ex. PER, dette).
    100 pts si ≤ good_max, 0 pts si ≥ bad_min, interpolé au milieu.
    """
    if v is None:
        return None
    if v <= good_max:
        return 100.0
    if v >= bad_min:
        return 0.0
    return 100.0 - (v - good_max) / (bad_min - good_max) * 100


def _score_high_is_good(v: float | None, good_min: float, bad_max: float) -> float | None:
    """Ratio où la valeur haute est favorable (ex. marges, ROE, croissance)."""
    if v is None:
        return None
    if v >= good_min:
        return 100.0
    if v <= bad_max:
        return 0.0
    return (v - bad_max) / (good_min - bad_max) * 100


def compute_fundamental_score(meta: TickerMeta | None) -> float | None:
    """Score fondamental 0-100 agrégé à partir des ratios clés.
    Retourne None si meta absent ou si aucun sous-score calculable.
    """
    if meta is None:
        return None
    sub_scores = [
        # Valorisation (bas = bon)
        _score_low_is_good(meta.trailing_pe, 15, 35),
        _score_low_is_good(meta.peg_ratio, 1.0, 2.5),
        _score_low_is_good(meta.debt_to_equity, 100, 300),
        _score_low_is_good(meta.price_to_book, 2.0, 5.0),
        # Rentabilité (haut = bon)
        _score_high_is_good(meta.profit_margin, 0.15, 0.03),
        _score_high_is_good(meta.return_on_equity, 0.15, 0.05),
        _score_high_is_good(meta.gross_margin, 0.40, 0.15),
        _score_high_is_good(meta.operating_margin, 0.20, 0.05),
        # Croissance (haut = bon)
        _score_high_is_good(meta.revenue_growth, 0.10, 0.00),
        _score_high_is_good(meta.earnings_growth, 0.10, 0.00),
        # Solvabilité (haut = bon)
        _score_high_is_good(meta.current_ratio, 1.5, 1.0),
    ]
    valid = [s for s in sub_scores if s is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


async def enrich_opportunity(opp: Opportunity, provider: Provider,
                              blend_fundamentals: bool = True) -> None:
    """Fetch meta + news + fundamentals, traduit les news, puis blend
    optionnellement le score technique avec un score fondamental (80/20).
    """
    meta, news, fundamentals = await asyncio.gather(
        provider.fetch_meta(opp.ticker),
        provider.fetch_news(opp.ticker, max_items=5),
        provider.fetch_fundamentals(opp.ticker),
    )
    opp.meta = meta
    opp.fundamentals = fundamentals
    if news:
        translated_titles = await _translate_news_titles([n.title for n in news])
        news = [
            NewsItem(title=t, publisher=n.publisher,
                     published=n.published, link=n.link)
            for n, t in zip(news, translated_titles)
        ]
    opp.news = news

    if not blend_fundamentals:
        return

    # Score fondamental + blend avec le score technique
    fund_score = compute_fundamental_score(meta)
    if fund_score is not None:
        effective_fund = fund_score
        if opp.trade_plan.direction == "short":
            effective_fund = 100.0 - fund_score
        if opp.technical_score is None:
            opp.technical_score = opp.score
        opp.fundamental_score = fund_score
        opp.score = 0.8 * opp.technical_score + 0.2 * effective_fund
        opp.blended = True


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
    ticker: str, provider: Provider, cache: BarCache, lookback_days: int,
    force_refresh: bool = False,
) -> list[Bar]:
    """Charge les bars depuis le cache ou fetch frais.

    Cache hit si (et seulement si) :
      - on est weekend/jour férié et la dernière bar est du dernier jour ouvré, OU
      - la dernière bar date est aujourd'hui ET le fetch date de moins de 15 min

    Sinon on refetch. force_refresh=True bypasse totalement le cache.
    """
    from datetime import datetime
    today = date.today()
    start = today - timedelta(days=lookback_days)
    cached = cache.get_bars(ticker)

    if not force_refresh and cached:
        last_bar_date = cached[-1].date
        fetched_at = cache.latest_fetched_at(ticker)
        # Si la dernière bar est d'aujourd'hui, cache valide si fetch < 15 min
        if last_bar_date == today:
            if fetched_at and (datetime.now() - fetched_at).total_seconds() < 900:
                return cached
        # Si la dernière bar est d'hier ou avant, cache valide si weekend/jour férié
        elif last_bar_date >= today - timedelta(days=1):
            # On est potentiellement un dimanche/lundi matin : tolérance 12h
            if fetched_at and (datetime.now() - fetched_at).total_seconds() < 12 * 3600:
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
    names: dict[str, str] | None = None,
    force_refresh: bool = False,
    progress_callback=None,
) -> list[Opportunity]:
    if horizon not in ATR_MULTIPLIERS:
        raise ValueError(f"Horizon non supporté : {horizon}")

    cache = BarCache(cache_path)
    counter = {"done": 0, "total": len(tickers)}

    async def _process(ticker: str) -> Opportunity | None:
        bars = await _load_bars(ticker, provider, cache, lookback_days,
                                force_refresh=force_refresh)
        counter["done"] += 1
        if progress_callback:
            progress_callback(counter["done"], counter["total"], ticker)
        if len(bars) < 30:
            return None
        df = _bars_to_df(bars)

        # Évaluer les 2 directions en parallèle, garder la meilleure
        long_score, long_details = _score_ticker(df, HORIZON_SIGNALS_1W_LONG)
        short_score, short_details = _score_ticker(df, HORIZON_SIGNALS_1W_SHORT)

        if long_score >= short_score:
            direction, score, details = "long", long_score, long_details
        else:
            direction, score, details = "short", short_score, short_details

        plan = compute_trade_plan(df, horizon=horizon, direction=direction)
        if plan.risk_reward < min_rr:
            return None
        recent_bars = bars[-252:]
        return Opportunity(
            ticker=ticker, horizon=horizon, score=score,
            trade_plan=plan, signal_details=details,
            recent_bars=recent_bars,
            name=(names or {}).get(ticker, ""),
        )

    results = await asyncio.gather(*(_process(t) for t in tickers))
    opps = [o for o in results if o is not None]
    opps.sort(key=lambda o: o.score, reverse=True)

    # Enrichissement meta + news pour les top N seulement (coût réseau contenu)
    top = opps[:enrich_top_n]

    # Blend fundamentals selon settings user
    try:
        from market_pulse.config import UserSettings
        _settings = UserSettings.load()
        _blend = _settings.blend_fundamentals
    except Exception:
        _blend = True
    await asyncio.gather(
        *(enrich_opportunity(o, provider, blend_fundamentals=_blend) for o in top)
    )

    cache.close()
    return opps
