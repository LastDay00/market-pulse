"""Price chart rendering pour l'écran détail.

Area chart avec ligne et remplissage, via plotext. Plus lisible qu'un
candlestick 1-char de large en terminal (les bougies deviennent illisibles).
Le rendu ANSI de plotext est converti en Rich Text pour Textual.
"""
from __future__ import annotations

import plotext as plt
from rich.text import Text

from market_pulse.data.models import Bar

SAUGE_RGB = (127, 176, 105)
TERRA_RGB = (201, 112, 100)
AMBRE_RGB = (232, 180, 93)
SMOKE_RGB = (107, 140, 174)
OFF_WHITE_RGB = (232, 230, 227)
MUTED_RGB = (138, 134, 128)


def render_candlestick_chart(
    bars: list[Bar],
    trade_plan=None,
    width: int = 70,
    chart_height: int = 16,
    volume_height: int = 0,  # déprécié : le volume est maintenant rendu séparément
) -> Text:
    """Rend un area chart (ligne + remplissage sous la courbe) des closes.

    Couleur de la courbe :
    - sauge si tendance haussière sur la fenêtre (close[-1] ≥ close[0])
    - terre cuite sinon

    Lignes horizontales tracées pour entry (blanc), TP (sauge), SL (terre cuite).
    """
    if not bars:
        return Text("no data", style="dim")

    plt.clf()
    plt.theme("pro")
    plt.plotsize(width, chart_height)
    plt.date_form("Y-m-d")

    dates = [b.date.strftime("%Y-%m-%d") for b in bars]
    closes = [b.close for b in bars]

    trend_up = closes[-1] >= closes[0]
    line_color = SAUGE_RGB if trend_up else TERRA_RGB

    # Ligne de prix avec remplissage sous la courbe (area chart)
    plt.plot(dates, closes, color=line_color, fillx=True, marker="braille")

    # Lignes de référence du trade plan
    if trade_plan is not None:
        plt.hline(trade_plan.entry, color=OFF_WHITE_RGB)
        plt.hline(trade_plan.target, color=SAUGE_RGB)
        plt.hline(trade_plan.stop, color=TERRA_RGB)

    return Text.from_ansi(plt.build())


def render_volume_chart(
    bars: list[Bar],
    width: int = 70,
    height: int = 5,
) -> Text:
    """Rend une sparkline de volumes sous le chart principal."""
    if not bars:
        return Text("")

    plt.clf()
    plt.theme("pro")
    plt.plotsize(width, height)

    xs = list(range(len(bars)))
    vols = [b.volume for b in bars]

    # Colorer rouge/vert selon la direction de la bougie
    # plotext bar ne supporte pas une couleur par barre, donc on plot 2 fois :
    # une pour les hausses, une pour les baisses
    up_x = [i for i, b in enumerate(bars) if b.close >= b.open]
    up_v = [bars[i].volume for i in up_x]
    dn_x = [i for i, b in enumerate(bars) if b.close < b.open]
    dn_v = [bars[i].volume for i in dn_x]

    if up_x:
        plt.bar(up_x, up_v, color=SAUGE_RGB, marker="sd", width=0.9)
    if dn_x:
        plt.bar(dn_x, dn_v, color=TERRA_RGB, marker="sd", width=0.9)

    plt.xticks([])  # pas de labels x (alignement avec le chart principal pas garanti)
    return Text.from_ansi(plt.build())
