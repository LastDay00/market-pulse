"""Rendu chart style Bloomberg : area chart + volume + stats overlay.

Utilise plotext pour la base (line+fill avec marker braille) avec conversion
ANSI→Rich Text pour intégration Textual propre.
"""
from __future__ import annotations

from statistics import mean

import plotext as plt
from rich.text import Text

from market_pulse.data.models import Bar

SAUGE_RGB = (127, 176, 105)
TERRA_RGB = (201, 112, 100)
AMBRE_RGB = (232, 180, 93)
SMOKE_RGB = (107, 140, 174)       # bleu fumée Nothing (couleur principale du chart)
OFF_WHITE_RGB = (232, 230, 227)
GRID_RGB = (60, 60, 66)
MUTED_RGB = (138, 134, 128)


def _rgb(c: tuple[int, int, int]) -> str:
    return f"rgb({c[0]},{c[1]},{c[2]})"


def render_candlestick_chart(
    bars: list[Bar],
    trade_plan=None,
    width: int = 70,
    chart_height: int = 14,
    volume_height: int = 0,  # volume intégré ci-dessous, cet arg est ignoré
) -> Text:
    """Rend un chart style Bloomberg : stats + area chart + volume bars.

    - Stats en en-tête : Dernier, Haut, Bas, Moyenne
    - Area chart (ligne + remplissage) en bleu fumée
    - Lignes horizontales entry (blanc), TP (sauge), SL (terre cuite)
    - Volume bars en-dessous, colorisées vert/rouge selon direction de la bougie
    """
    text = Text()
    if not bars:
        text.append("no data", style=_rgb(MUTED_RGB))
        return text

    # -------- Stats en-tête --------
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    last = closes[-1]
    hi_val = max(highs)
    hi_date = bars[highs.index(hi_val)].date.isoformat()
    lo_val = min(lows)
    lo_date = bars[lows.index(lo_val)].date.isoformat()
    avg_val = mean(closes)

    muted = _rgb(MUTED_RGB)
    text.append(f" Dernier ", style=muted)
    text.append(f"{last:>8.2f}", style=_rgb(OFF_WHITE_RGB))
    text.append(f"     ▲ Haut ", style=muted)
    text.append(f"{hi_val:>8.2f}", style=_rgb(SAUGE_RGB))
    text.append(f" ({hi_date})", style=muted)
    text.append(f"     ▼ Bas ", style=muted)
    text.append(f"{lo_val:>8.2f}", style=_rgb(TERRA_RGB))
    text.append(f" ({lo_date})", style=muted)
    text.append(f"     Moyenne ", style=muted)
    text.append(f"{avg_val:>8.2f}", style=_rgb(AMBRE_RGB))
    text.append("\n\n")

    # -------- Area chart principal --------
    plt.clf()
    plt.theme("pro")
    plt.plotsize(width, chart_height)
    plt.date_form("Y-m-d")

    dates = [b.date.strftime("%Y-%m-%d") for b in bars]

    # Ligne de prix avec fill sous la courbe, en bleu fumée (couleur Bloomberg-like)
    plt.plot(dates, closes, color=SMOKE_RGB, fillx=True, marker="braille")

    # Lignes de référence DEVANT (appel après plot)
    if trade_plan is not None:
        plt.hline(trade_plan.entry, color=OFF_WHITE_RGB)
        plt.hline(trade_plan.target, color=SAUGE_RGB)
        plt.hline(trade_plan.stop, color=TERRA_RGB)

    # Pas de grille (fond uni, plus propre en terminal)
    plt.grid(False, False)

    text.append(Text.from_ansi(plt.build()))
    text.append("\n")

    # -------- Volume bars --------
    vol_height = 5
    plt.clf()
    plt.theme("pro")
    plt.plotsize(width, vol_height)
    plt.date_form("Y-m-d")

    # Deux passes pour colorer vert/rouge selon direction, mais plotext bar ne
    # supporte pas 1 couleur par barre → on remplace par 1 seule couleur neutre
    # (Bloomberg utilise gris monocolore, lisible sans distraction)
    vols = [b.volume for b in bars]
    plt.bar(dates, vols, color=MUTED_RGB, marker="sd", width=0.9)
    plt.xticks([], [])  # pas de ticks x (les dates sont déjà dans le chart principal)

    text.append(Text.from_ansi(plt.build()))
    text.append(" VOL  max ", style=muted)
    max_vol = max(vols)
    if max_vol >= 1e9:
        text.append(f"{max_vol/1e9:.2f}Md\n", style=muted)
    elif max_vol >= 1e6:
        text.append(f"{max_vol/1e6:.2f}M\n", style=muted)
    else:
        text.append(f"{max_vol:,.0f}\n".replace(",", " "), style=muted)

    return text
