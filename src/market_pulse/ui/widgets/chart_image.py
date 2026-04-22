"""Vraie image PNG du chart générée par matplotlib, pour affichage via
le protocole iTerm2 Inline Images / Kitty Graphics (ou fallback halfblocks).

C'est la seule façon d'avoir un rendu NON pixelisé en terminal : afficher
une vraie image. textual-image détecte le protocole supporté par le terminal.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from market_pulse.data.models import Bar

BG = "#0A0A0B"
SAUGE = "#7FB069"
TERRA = "#C97064"
OFF_WHITE = "#E8E6E3"
MUTED = "#8A8680"
GRID = "#2A2A2E"


def render_candles_png(
    bars: list[Bar],
    trade_plan=None,
    width_px: int = 1800,
    height_px: int = 600,
    show_volume: bool = True,
) -> BytesIO:
    """Génère le chart candlestick en PNG via matplotlib."""
    if not bars:
        fig = Figure(figsize=(width_px / 100, height_px / 100), dpi=100, facecolor=BG)
        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor=BG)
        buf.seek(0)
        return buf

    closes = [b.close for b in bars]
    opens = [b.open for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    vols = [b.volume for b in bars]

    fig = Figure(figsize=(width_px / 100, height_px / 100), dpi=100, facecolor=BG)
    if show_volume:
        ax = fig.add_axes([0.05, 0.30, 0.93, 0.68])   # zone chart principal
        ax_v = fig.add_axes([0.05, 0.08, 0.93, 0.20])  # zone volume
    else:
        ax = fig.add_axes([0.05, 0.10, 0.93, 0.85])
        ax_v = None

    for a in (ax, ax_v):
        if a is None:
            continue
        a.set_facecolor(BG)
        for spine in a.spines.values():
            spine.set_color(GRID)
        a.tick_params(colors=MUTED, labelsize=9)
        a.grid(False)

    # ---- Candles ----
    body_width = 0.7
    for i, b in enumerate(bars):
        is_up = b.close >= b.open
        color = SAUGE if is_up else TERRA
        body_top = max(b.open, b.close)
        body_bot = min(b.open, b.close)
        # Wick (mèche)
        ax.plot([i, i], [b.low, b.high], color=color, linewidth=0.9,
                solid_capstyle="butt", zorder=2)
        # Body
        h = body_top - body_bot
        if h < 1e-9:
            # Doji : ligne horizontale
            ax.plot([i - body_width / 2, i + body_width / 2], [b.close, b.close],
                    color=color, linewidth=1.4, zorder=3)
        else:
            ax.add_patch(Rectangle(
                (i - body_width / 2, body_bot), body_width, h,
                facecolor=color, edgecolor=color, zorder=3,
            ))

    # Lignes de référence du trade plan
    if trade_plan is not None:
        ax.axhline(trade_plan.entry, color=OFF_WHITE, linewidth=1.1,
                   linestyle="--", alpha=0.9, zorder=1)
        ax.axhline(trade_plan.target, color=SAUGE, linewidth=1.1,
                   linestyle="--", alpha=0.9, zorder=1)
        ax.axhline(trade_plan.stop, color=TERRA, linewidth=1.1,
                   linestyle="--", alpha=0.9, zorder=1)

    ax.set_xlim(-0.5, len(bars) - 0.5)
    # Marge verticale : inclure les 3 niveaux du trade plan si présents
    y_vals = highs + lows
    if trade_plan is not None:
        y_vals.extend([trade_plan.entry, trade_plan.target, trade_plan.stop])
    y_min = min(y_vals)
    y_max = max(y_vals)
    pad = (y_max - y_min) * 0.03
    ax.set_ylim(y_min - pad, y_max + pad)

    # Ticks X : 5 dates espacées
    n = len(bars)
    tick_idxs = [int(i) for i in [0, n / 4, n / 2, 3 * n / 4, n - 1]]
    ax.set_xticks(tick_idxs)
    ax.set_xticklabels([bars[i].date.isoformat() for i in tick_idxs],
                        color=MUTED, fontsize=9)

    # ---- Volume ----
    if ax_v is not None:
        colors = [SAUGE if b.close >= b.open else TERRA for b in bars]
        ax_v.bar(range(len(bars)), vols, color=colors, width=body_width,
                 linewidth=0, alpha=0.85)
        ax_v.set_xlim(-0.5, len(bars) - 0.5)
        ax_v.set_xticks([])

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, edgecolor="none")
    buf.seek(0)

    # Cleanup matplotlib state
    from matplotlib import pyplot as plt
    plt.close(fig)
    return buf


def save_chart_to_temp(bars: list[Bar], trade_plan=None,
                       width_px: int = 1800, height_px: int = 600) -> Path:
    """Génère le chart et le sauvegarde dans un fichier temporaire, retourne le path.

    textual-image préfère un path sur disque plutôt qu'un BytesIO dans certains cas.
    """
    import tempfile
    buf = render_candles_png(bars, trade_plan, width_px, height_px)
    # Fichier temporaire qui persiste le temps du détail
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="mp_chart_")
    tmp.write(buf.getvalue())
    tmp.close()
    return Path(tmp.name)
