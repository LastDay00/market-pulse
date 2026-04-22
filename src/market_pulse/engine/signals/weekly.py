"""Signaux techniques pour l'horizon 1 semaine."""
import pandas as pd

from market_pulse.engine.indicators import (
    bollinger_bands, macd, moving_average, rsi,
)
from market_pulse.engine.signals.base import Signal, SignalResult


def _clip(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


class RSIDivergence(Signal):
    """Score élevé si RSI < 30 avec rebond. Capte l'achat sur survente."""
    name = "RSIDivergence"
    weight = 0.25

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        r = rsi(df["Close"], period=14)
        last = float(r.iloc[-1]) if not r.empty else 50.0
        # score maximal à RSI=20, nul à RSI=50+
        score = _clip(100 - (last - 20) * (100 / 30)) if last <= 50 else 0
        return SignalResult(score=score, metadata={"rsi": last})


class MACDCrossover(Signal):
    """Score élevé si MACD vient de croiser son signal vers le haut."""
    name = "MACDCrossover"
    weight = 0.20

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        line, sig, hist = macd(df["Close"])
        h = hist.dropna()
        if len(h) < 2:
            return SignalResult(50.0, {"skipped": True})
        last_hist = float(h.iloc[-1])
        prev_hist = float(h.iloc[-2])
        # score si l'histogramme devient positif
        if prev_hist < 0 and last_hist > 0:
            score = 90.0
        elif last_hist > 0 and last_hist > prev_hist:
            score = 70.0
        elif last_hist > 0:
            score = 55.0
        else:
            score = max(0, 50 + last_hist * 1000)  # léger boost si hist remonte
        return SignalResult(
            score=_clip(score),
            metadata={"hist": last_hist, "prev_hist": prev_hist},
        )


class BollingerSqueezeBreakout(Signal):
    """Score élevé si la largeur de Bollinger était basse puis breakout à la hausse."""
    name = "BollingerSqueezeBreakout"
    weight = 0.15

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        upper, middle, lower = bollinger_bands(df["Close"], period=20, std_dev=2.0)
        width = ((upper - lower) / middle).dropna()
        if len(width) < 30:
            return SignalResult(50.0, {"skipped": True})
        recent_width = float(width.iloc[-1])
        close_last = float(df["Close"].iloc[-1])
        upper_last = float(upper.iloc[-1])
        # squeeze = width actuelle dans les 30% les plus bas des 30 derniers jours
        percentile = (width.iloc[-30:].le(recent_width).sum() / 30) * 100
        breakout = close_last > upper_last
        if percentile <= 30 and breakout:
            score = 90.0
        elif percentile <= 40:
            score = 60.0
        else:
            score = 30.0
        return SignalResult(
            score=_clip(score),
            metadata={"width_percentile": float(percentile), "breakout": bool(breakout)},
        )


class MA5AboveMA20(Signal):
    """Score élevé si MA5 vient de croiser MA20 vers le haut."""
    name = "MA5AboveMA20"
    weight = 0.15

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        ma5 = moving_average(df["Close"], period=5)
        ma20 = moving_average(df["Close"], period=20)
        diff = (ma5 - ma20).dropna()
        if len(diff) < 2:
            return SignalResult(50.0, {"skipped": True})
        last = float(diff.iloc[-1])
        prev = float(diff.iloc[-2])
        if prev < 0 and last > 0:
            score = 90.0
        elif last > 0 and last > prev:
            score = 70.0
        elif last > 0:
            score = 55.0
        else:
            score = 30.0
        return SignalResult(score=_clip(score), metadata={"ma5_minus_ma20": last})


class VolumeConfirmation(Signal):
    """Score élevé si volume moyen 5j > volume moyen 20j × 1.2."""
    name = "VolumeConfirmation"
    weight = 0.15

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        vol = df["Volume"]
        avg5 = float(vol.iloc[-5:].mean())
        avg20 = float(vol.iloc[-20:].mean()) if len(vol) >= 20 else avg5
        ratio = avg5 / avg20 if avg20 > 0 else 1.0
        # score croissant avec le ratio, plafonné à 2.5
        score = _clip((ratio - 1.0) * 100, 0, 100)
        return SignalResult(score=score, metadata={"volume_ratio": ratio})


class RelativeStrength(Signal):
    """Score élevé si performance 5j > benchmark + 2%."""
    name = "RelativeStrength"
    weight = 0.10

    def __init__(self, benchmark_df: pd.DataFrame | None = None) -> None:
        self.benchmark_df = benchmark_df

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        if self.benchmark_df is None or self.benchmark_df.empty:
            return SignalResult(50.0, {"skipped": True})
        ticker_ret = df["Close"].pct_change(5).iloc[-1]
        bench_ret = self.benchmark_df["Close"].pct_change(5).iloc[-1]
        excess = float(ticker_ret - bench_ret)
        score = _clip(50 + excess * 1000)  # +2% excess → 70, -2% → 30
        return SignalResult(
            score=score,
            metadata={"excess_return_5d": excess},
        )
