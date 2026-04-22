"""Vrai chart pixel-based rendu via matplotlib + rich-pixels.

matplotlib génère une vraie image PNG (anti-aliasing, courbes smooth, lignes
fines nettes). rich-pixels la convertit en Unicode halfblocks colorisés pour
un affichage dans Textual. Résultat : qualité bien supérieure aux chars
ASCII/braille.
"""
from __future__ import annotations

from io import BytesIO
from statistics import mean

import matplotlib
matplotlib.use("Agg")  # backend sans écran, indispensable en terminal
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from PIL import Image
from rich.console import Group
from rich.text import Text
from rich_pixels import Pixels

from market_pulse.data.models import Bar

SAUGE = "#7FB069"       # vert sauge Nothing
TERRA = "#C97064"       # terre cuite
AMBRE = "#E8B45D"
SMOKE_BLUE = "#6B8CAE"
OFF_WHITE = "#E8E6E3"
BG = "#0A0A0B"
MUTED = "#8A8680"


def _stats_header(bars: list[Bar]) -> Text:
    """Ligne de stats en en-tête (Dernier / Haut / Bas / Moyenne)."""
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
    text.append("\n")
    return text


def _render_matplotlib_png(
    bars: list[Bar], trade_plan, width_px: int, height_px: int
) -> Image.Image:
    """Trace le chart avec matplotlib et retourne une PIL Image."""
    closes = [b.close for b in bars]
    xs = list(range(len(bars)))

    fig = Figure(figsize=(width_px / 100, height_px / 100), dpi=100,
                 facecolor=BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG)

    # Couleur selon tendance
    trend_up = closes[-1] >= closes[0]
    line_color = SAUGE if trend_up else TERRA

    # Ligne + fill sous la courbe
    ax.plot(xs, closes, color=line_color, linewidth=1.2, antialiased=True)
    ax.fill_between(xs, min(closes) - 1, closes,
                    color=line_color, alpha=0.25, linewidth=0)

    # Lignes de référence (entry/TP/SL)
    if trade_plan is not None:
        ax.axhline(trade_plan.entry, color=OFF_WHITE, linewidth=0.8,
                   linestyle="--", alpha=0.9)
        ax.axhline(trade_plan.target, color=SAUGE, linewidth=0.8,
                   linestyle="--", alpha=0.9)
        ax.axhline(trade_plan.stop, color=TERRA, linewidth=0.8,
                   linestyle="--", alpha=0.9)

    # Style : supprimer cadre, ticks, labels
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    ax.margins(x=0, y=0.05)

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, edgecolor="none",
                bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _render_volume_png(bars: list[Bar], width_px: int, height_px: int) -> Image.Image:
    """Histogramme volume via matplotlib."""
    vols = [b.volume for b in bars]
    xs = list(range(len(bars)))

    fig = Figure(figsize=(width_px / 100, height_px / 100), dpi=100,
                 facecolor=BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG)
    colors = [SAUGE if b.close >= b.open else TERRA for b in bars]
    ax.bar(xs, vols, color=colors, width=1.0, linewidth=0, alpha=0.8)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    ax.margins(x=0, y=0.02)

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, edgecolor="none",
                bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def render_candlestick_chart(
    bars: list[Bar],
    trade_plan=None,
    width: int = 70,
    chart_height: int = 14,
    volume_height: int = 0,
) -> Group:
    """Rend le chart complet (stats + graph + volume) comme un Rich renderable.

    Utilise matplotlib pour la vraie image puis rich-pixels pour la convertir
    en Unicode halfblocks colorisés pour l'affichage Textual.
    """
    if not bars:
        return Group(Text("no data", style=MUTED))

    # 1 cellule terminal ≈ 1 pixel x 2 pixels avec halfblock
    # Pour un chart de `width` x `chart_height` cellules → image de width x 2*chart_height px
    img_w = max(40, width)
    img_h = max(20, chart_height * 2)
    vol_img_h = max(6, 3 * 2)

    # Date labels début / fin
    start_lbl = bars[0].date.isoformat()
    end_lbl = bars[-1].date.isoformat()

    # Génère images et convertit en Rich Pixels
    chart_img = _render_matplotlib_png(bars, trade_plan, img_w * 10, img_h * 10)
    chart_img = chart_img.resize((img_w, img_h), Image.LANCZOS)
    chart_pixels = Pixels.from_image(chart_img)

    vol_img = _render_volume_png(bars, img_w * 10, vol_img_h * 10)
    vol_img = vol_img.resize((img_w, vol_img_h), Image.LANCZOS)
    vol_pixels = Pixels.from_image(vol_img)

    # Légendes
    dates_line = Text()
    pad = max(1, img_w - len(start_lbl) - len(end_lbl))
    dates_line.append(start_lbl, style=MUTED)
    dates_line.append(" " * pad)
    dates_line.append(end_lbl, style=MUTED)

    legend = Text()
    max_vol = max(b.volume for b in bars)
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
        chart_pixels,
        dates_line,
        Text(""),  # spacer
        vol_pixels,
        legend,
    )
