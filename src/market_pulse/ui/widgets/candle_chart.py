"""Candlestick chart via plotext (theme 'dark') + stats header + volume bars.

Re-bascule sur plotext après le détour matplotlib/rich-pixels : avec le thème
'dark' et un plotsize correct, plotext produit des vraies bougies vertes/rouges
bien propres sur fond noir.
"""
from __future__ import annotations

from statistics import mean

import plotext as plt
from rich.console import Group
from rich.text import Text

from market_pulse.data.models import Bar

SAUGE = "#7FB069"
TERRA = "#C97064"
AMBRE = "#E8B45D"
SMOKE_BLUE = "#6B8CAE"
OFF_WHITE = "#E8E6E3"
MUTED = "#8A8680"


def _stats_header(bars: list[Bar]) -> Text:
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    last = closes[-1]
    hi_val = max(highs)
    hi_date = bars[highs.index(hi_val)].date.isoformat()
    lo_val = min(lows)
    lo_date = bars[lows.index(lo_val)].date.isoformat()
    avg_val = mean(closes)

    text = Text()
    text.append(" Dernier ", style=MUTED)
    text.append(f"{last:>8.2f}", style=OFF_WHITE)
    text.append("     ▲ Haut ", style=MUTED)
    text.append(f"{hi_val:>8.2f}", style=SAUGE)
    text.append(f" ({hi_date})", style=MUTED)
    text.append("     ▼ Bas ", style=MUTED)
    text.append(f"{lo_val:>8.2f}", style=TERRA)
    text.append(f" ({lo_date})", style=MUTED)
    text.append("     Moyenne ", style=MUTED)
    text.append(f"{avg_val:>8.2f}", style=AMBRE)
    return text


def render_candlestick_chart(
    bars: list[Bar],
    trade_plan=None,
    width: int = 70,
    chart_height: int = 18,
    volume_height: int = 0,
) -> Group:
    """Rend un vrai candlestick plotext + volume bars + stats."""
    if not bars:
        return Group(Text("no data", style=MUTED))

    # Nombre de bougies en fonction de la largeur : ~3 chars par bougie pour que
    # les bodies aient de la place (comme dans l'article plotext)
    target_candles = max(30, min(120, width // 3))
    visible = bars[-target_candles:]

    # ---- Chart candlestick ----
    plt.clf()
    plt.theme("dark")
    plt.plotsize(width, chart_height)
    plt.date_form("Y-m-d")

    dates = [b.date.strftime("%Y-%m-%d") for b in visible]
    data = {
        "Open":  [b.open for b in visible],
        "High":  [b.high for b in visible],
        "Low":   [b.low for b in visible],
        "Close": [b.close for b in visible],
    }
    plt.candlestick(dates, data)

    # Lignes de référence entry/TP/SL
    if trade_plan is not None:
        plt.hline(trade_plan.entry, color="white")
        plt.hline(trade_plan.target, color="green")
        plt.hline(trade_plan.stop, color="red")

    chart_text = Text.from_ansi(plt.build())

    # ---- Volume bars ----
    plt.clf()
    plt.theme("dark")
    plt.plotsize(width, 5)
    vols = [b.volume for b in visible]
    up_x = [i for i, b in enumerate(visible) if b.close >= b.open]
    up_v = [visible[i].volume for i in up_x]
    dn_x = [i for i, b in enumerate(visible) if b.close < b.open]
    dn_v = [visible[i].volume for i in dn_x]
    if up_x:
        plt.bar(up_x, up_v, color="green", marker="sd", width=0.8)
    if dn_x:
        plt.bar(dn_x, dn_v, color="red", marker="sd", width=0.8)
    plt.xticks([], [])
    vol_text = Text.from_ansi(plt.build())

    # ---- Légende volume ----
    legend = Text()
    max_vol = max(vols)
    legend.append(" VOL  max ", style=MUTED)
    if max_vol >= 1e9:
        legend.append(f"{max_vol/1e9:.2f} Md", style=MUTED)
    elif max_vol >= 1e6:
        legend.append(f"{max_vol/1e6:.2f} M", style=MUTED)
    else:
        legend.append(f"{max_vol:,.0f}".replace(",", " "), style=MUTED)
    legend.append("     · Lignes : ", style=MUTED)
    legend.append("entry ", style=OFF_WHITE)
    legend.append("·  ", style=MUTED)
    legend.append("TP ", style=SAUGE)
    legend.append("·  ", style=MUTED)
    legend.append("SL", style=TERRA)

    return Group(
        _stats_header(bars),
        chart_text,
        vol_text,
        legend,
    )
