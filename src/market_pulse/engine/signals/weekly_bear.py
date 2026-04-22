"""Signaux techniques baissiers pour l'horizon 1 semaine.

Miroirs des signaux de weekly.py : même indicateurs mais interprétés
dans le sens SHORT (score élevé = opportunité de vente à découvert).
"""
import pandas as pd

from market_pulse.engine.indicators import (
    bollinger_bands, macd, moving_average, rsi,
)
from market_pulse.engine.signals.base import Signal, SignalResult


def _clip(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


class RSIOverboughtBear(Signal):
    """Score élevé si RSI > 70 avec rejet. Signale une vente sur survente haussière."""
    name = "RSIOverboughtBear"
    weight = 0.25

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        r = rsi(df["Close"], period=14)
        last = float(r.iloc[-1]) if not r.empty else 50.0
        # Score max à RSI=80, nul à RSI=50
        score = _clip((last - 50) * (100 / 30)) if last >= 50 else 0
        return SignalResult(score=score, metadata={"rsi": last})


class MACDBearCrossover(Signal):
    """Score élevé si MACD vient de croiser son signal vers le bas (hist devient négatif)."""
    name = "MACDBearCrossover"
    weight = 0.20

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        line, sig, hist = macd(df["Close"])
        h = hist.dropna()
        if len(h) < 2:
            return SignalResult(50.0, {"skipped": True})
        last_hist = float(h.iloc[-1])
        prev_hist = float(h.iloc[-2])
        if prev_hist > 0 and last_hist < 0:
            score = 90.0
        elif last_hist < 0 and last_hist < prev_hist:
            score = 70.0
        elif last_hist < 0:
            score = 55.0
        else:
            score = max(0, 50 - last_hist * 1000)
        return SignalResult(
            score=_clip(score),
            metadata={"hist": last_hist, "prev_hist": prev_hist},
        )


class BollingerSqueezeBreakdownBear(Signal):
    """Score élevé si Bollinger squeeze + cassure sous la bande inférieure."""
    name = "BollingerSqueezeBreakdown"
    weight = 0.15

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        upper, middle, lower = bollinger_bands(df["Close"], period=20, std_dev=2.0)
        width = ((upper - lower) / middle).dropna()
        if len(width) < 30:
            return SignalResult(50.0, {"skipped": True})
        recent_width = float(width.iloc[-1])
        close_last = float(df["Close"].iloc[-1])
        lower_last = float(lower.iloc[-1])
        percentile = (width.iloc[-30:].le(recent_width).sum() / 30) * 100
        breakdown = close_last < lower_last
        if percentile <= 30 and breakdown:
            score = 90.0
        elif percentile <= 40:
            score = 60.0
        else:
            score = 30.0
        return SignalResult(
            score=_clip(score),
            metadata={"width_percentile": float(percentile), "breakdown": bool(breakdown)},
        )


class MA5BelowMA20Bear(Signal):
    """Score élevé si MA5 croise MA20 vers le bas (death cross court)."""
    name = "MA5BelowMA20"
    weight = 0.15

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        ma5 = moving_average(df["Close"], period=5)
        ma20 = moving_average(df["Close"], period=20)
        diff = (ma5 - ma20).dropna()
        if len(diff) < 2:
            return SignalResult(50.0, {"skipped": True})
        last = float(diff.iloc[-1])
        prev = float(diff.iloc[-2])
        if prev > 0 and last < 0:
            score = 90.0
        elif last < 0 and last < prev:
            score = 70.0
        elif last < 0:
            score = 55.0
        else:
            score = 30.0
        return SignalResult(score=_clip(score), metadata={"ma5_minus_ma20": last})


class VolumeConfirmationBear(Signal):
    """Volume élevé sur une bougie baissière : capitulation possible."""
    name = "VolumeConfirmationBear"
    weight = 0.15

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        vol = df["Volume"]
        avg5 = float(vol.iloc[-5:].mean())
        avg20 = float(vol.iloc[-20:].mean()) if len(vol) >= 20 else avg5
        ratio = avg5 / avg20 if avg20 > 0 else 1.0
        # Volume élevé + prix qui baisse sur 5j → baissier
        ret_5d = (df["Close"].iloc[-1] - df["Close"].iloc[-5]) / df["Close"].iloc[-5] \
                 if len(df) >= 5 else 0
        bear_factor = 1.0 if ret_5d < 0 else 0.3
        score = _clip((ratio - 1.0) * 100 * bear_factor, 0, 100)
        return SignalResult(
            score=score,
            metadata={"volume_ratio": ratio, "ret_5d": float(ret_5d)},
        )


class RelativeWeaknessBear(Signal):
    """Score élevé si sous-performance 5j vs benchmark."""
    name = "RelativeWeakness"
    weight = 0.10

    def __init__(self, benchmark_df: pd.DataFrame | None = None) -> None:
        self.benchmark_df = benchmark_df

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        if self.benchmark_df is None or self.benchmark_df.empty:
            return SignalResult(50.0, {"skipped": True})
        ticker_ret = df["Close"].pct_change(5).iloc[-1]
        bench_ret = self.benchmark_df["Close"].pct_change(5).iloc[-1]
        deficit = float(bench_ret - ticker_ret)  # sous-performance positive
        score = _clip(50 + deficit * 1000)
        return SignalResult(
            score=score,
            metadata={"underperf_5d": deficit},
        )
