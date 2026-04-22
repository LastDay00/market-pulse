"""Chart inline simple et propre pour Terminal.app.

Terminal.app (macOS de base) ne supporte aucun protocole image inline
(iTerm2/Kitty/Sixel). La meilleure qualité atteignable dans ces limites :
- Ligne pure en braille (4x plus de résolution verticale qu'un bloc)
- Pas de remplissage (le fill en terminal donne toujours un aspect mosaïque)
- Lignes horizontales de référence visibles
- Pour un vrai chart pixel-perfect, la touche G ouvre le PNG dans Preview.app
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
    """Header compact 2-lignes pour éviter le wrap dans un panneau étroit."""
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
    # Ligne 1 : Dernier et Moyenne
    text.append(" Dernier ", style=MUTED)
    text.append(f"{last:.2f}", style=OFF_WHITE)
    text.append("   ·   Moyenne ", style=MUTED)
    text.append(f"{avg_val:.2f}", style=AMBRE)
    text.append("\n")
    # Ligne 2 : Haut / Bas
    text.append(" ▲ Haut ", style=MUTED)
    text.append(f"{hi_val:.2f}", style=SAUGE)
    text.append(f" ({hi_date})", style=MUTED)
    text.append("   ·   ▼ Bas ", style=MUTED)
    text.append(f"{lo_val:.2f}", style=TERRA)
    text.append(f" ({lo_date})", style=MUTED)
    return text


def render_candlestick_chart(
    bars: list[Bar],
    trade_plan=None,
    width: int = 170,
    chart_height: int = 22,
    volume_height: int = 0,
) -> Group:
    """Rend un line chart braille avec lignes de référence colorées.

    Accept en terminal : pas d'image pixel-perfect possible, mais la ligne
    braille est ce qu'il y a de plus smooth en cell-based rendering.
    Le user peut appuyer G pour voir le vrai chart dans Preview.app.
    """
    if not bars:
        return Group(Text("no data", style=MUTED))

    closes = [b.close for b in bars]

    # --- Main chart : line braille smooth ---
    plt.clf()
    plt.theme("pro")
    plt.plotsize(width, chart_height)
    plt.date_form("Y-m-d")

    dates = [b.date.strftime("%Y-%m-%d") for b in bars]

    trend_up = closes[-1] >= closes[0]
    line_color = "green" if trend_up else "red"

    plt.plot(dates, closes, color=line_color, marker="braille")

    # Lignes de référence par-dessus
    if trade_plan is not None:
        plt.hline(trade_plan.entry, color="white")
        plt.hline(trade_plan.target, color="green")
        plt.hline(trade_plan.stop, color="red")

    chart_text = Text.from_ansi(plt.build())

    # --- Astuce pour voir un vrai chart ---
    tip = Text()
    tip.append(" 💡  Pour un vrai chart pixel-perfect, appuie sur ", style=MUTED)
    tip.append("G", style=f"bold {AMBRE}")
    tip.append("  (ouvre Preview.app avec un rendu haute résolution)", style=MUTED)

    # --- Légende lignes avec valeurs exactes pour vérif visuelle ---
    legend = Text()
    legend.append(" Lignes : ", style=MUTED)
    if trade_plan is not None:
        legend.append(f"entry {trade_plan.entry:.2f}", style=OFF_WHITE)
        legend.append("   ·   ", style=MUTED)
        legend.append(f"TP {trade_plan.target:.2f}", style=SAUGE)
        legend.append("   ·   ", style=MUTED)
        legend.append(f"SL {trade_plan.stop:.2f}", style=TERRA)
    else:
        legend.append("entry ", style=OFF_WHITE)
        legend.append("·  ", style=MUTED)
        legend.append("TP ", style=SAUGE)
        legend.append("·  ", style=MUTED)
        legend.append("SL", style=TERRA)

    return Group(
        _stats_header(bars),
        chart_text,
        legend,
        tip,
    )
