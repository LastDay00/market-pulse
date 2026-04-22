"""Chart lisse style Bloomberg : area chart avec fill Unicode blocks + volume.

Plutôt que plotext (qui utilise du braille et donne un aspect "pointillé"),
on rend nous-mêmes le chart avec des Unicode blocks ▁▂▃▄▅▆▇█ pour un
remplissage lisse. 8 niveaux de précision sub-cellulaire = courbe smooth.
"""
from __future__ import annotations

from statistics import mean

from rich.text import Text

from market_pulse.data.models import Bar

SAUGE_RGB = (127, 176, 105)
TERRA_RGB = (201, 112, 100)
AMBRE_RGB = (232, 180, 93)
SMOKE_RGB = (107, 140, 174)
OFF_WHITE_RGB = (232, 230, 227)
GRID_RGB = (60, 60, 66)
MUTED_RGB = (138, 134, 128)


def _rgb(c: tuple[int, int, int]) -> str:
    return f"rgb({c[0]},{c[1]},{c[2]})"


_BLOCKS_UP = [" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]


def render_candlestick_chart(
    bars: list[Bar],
    trade_plan=None,
    width: int = 70,
    chart_height: int = 16,
    volume_height: int = 0,
) -> Text:
    """Rend un area chart lisse + volume + stats header.

    Layout vertical :
      1. Ligne de stats (Dernier / Haut / Bas / Moyenne)
      2. Area chart (fill Unicode blocks, axe Y à gauche)
      3. Axe X avec dates
      4. Volume bars (Unicode blocks)
    """
    text = Text()
    if not bars:
        text.append("no data", style=_rgb(MUTED_RGB))
        return text

    y_label_w = 7
    separator = 1
    chart_w = max(10, width - y_label_w - separator)
    n = min(len(bars), chart_w)
    visible = bars[-n:]

    closes = [b.close for b in visible]
    highs = [b.high for b in visible]
    lows = [b.low for b in visible]
    vols = [b.volume for b in visible]

    last = closes[-1]
    hi_val = max(highs)
    hi_idx = highs.index(hi_val)
    hi_date = visible[hi_idx].date.isoformat()
    lo_val = min(lows)
    lo_idx = lows.index(lo_val)
    lo_date = visible[lo_idx].date.isoformat()
    avg_val = mean(closes)

    muted = _rgb(MUTED_RGB)
    grid_style = _rgb(GRID_RGB)

    # -------- 1) Stats header --------
    text.append(" Dernier ", style=muted)
    text.append(f"{last:>8.2f}", style=_rgb(OFF_WHITE_RGB))
    text.append("     ▲ Haut ", style=muted)
    text.append(f"{hi_val:>8.2f}", style=_rgb(SAUGE_RGB))
    text.append(f" ({hi_date})", style=muted)
    text.append("     ▼ Bas ", style=muted)
    text.append(f"{lo_val:>8.2f}", style=_rgb(TERRA_RGB))
    text.append(f" ({lo_date})", style=muted)
    text.append("     Moyenne ", style=muted)
    text.append(f"{avg_val:>8.2f}", style=_rgb(AMBRE_RGB))
    text.append("\n\n")

    # -------- 2) Area chart --------
    # Plage de prix (inclut les lignes du trade plan pour qu'elles soient visibles)
    prices = list(closes)
    if trade_plan is not None:
        prices.extend([trade_plan.entry, trade_plan.target, trade_plan.stop])
    chart_hi = max(prices)
    chart_lo = min(prices)
    rng = chart_hi - chart_lo if chart_hi > chart_lo else 1.0

    # 8 niveaux de précision sub-cellulaire par rangée
    total_levels = chart_height * 8
    col_levels = [
        int((c - chart_lo) / rng * total_levels + 0.5) for c in closes
    ]

    # Positions des lignes de référence (row index dans le chart)
    ref_rows: dict[int, tuple[int, int, int]] = {}
    if trade_plan is not None:
        for price, rgb_color in (
            (trade_plan.entry, OFF_WHITE_RGB),
            (trade_plan.target, SAUGE_RGB),
            (trade_plan.stop, TERRA_RGB),
        ):
            row = int((chart_hi - price) / rng * (chart_height - 1) + 0.5)
            if 0 <= row < chart_height:
                ref_rows[row] = rgb_color

    trend_up = closes[-1] >= closes[0]
    line_style = _rgb(SAUGE_RGB if trend_up else TERRA_RGB)

    tick_rows = {0, chart_height // 4, chart_height // 2,
                 3 * chart_height // 4, chart_height - 1}
    tick_prices: dict[int, float] = {}
    for r in tick_rows:
        ratio = r / (chart_height - 1) if chart_height > 1 else 0
        tick_prices[r] = chart_hi - ratio * rng

    for r in range(chart_height):
        # Axe Y
        if r in tick_rows:
            text.append(f"{tick_prices[r]:>{y_label_w}.2f}", style=muted)
            text.append("┤", style=grid_style)
        else:
            text.append(" " * y_label_w, style=muted)
            text.append("│", style=grid_style)

        # Cette rangée couvre les niveaux [row_bottom, row_top)
        row_top_level = (chart_height - r) * 8
        row_bot_level = (chart_height - r - 1) * 8
        ref_color = ref_rows.get(r)

        for i in range(n):
            col_level = col_levels[i]
            if col_level >= row_top_level:
                # Entièrement sous la courbe : bloc plein coloré
                text.append("█", style=line_style)
            elif col_level <= row_bot_level:
                # Entièrement au-dessus de la courbe : espace vide (ou ref line)
                if ref_color:
                    text.append("─", style=_rgb(ref_color))
                else:
                    text.append(" ")
            else:
                # Partiel dans cette rangée : block fractionnel
                frac = col_level - row_bot_level  # 1..7
                text.append(_BLOCKS_UP[frac], style=line_style)
        text.append("\n")

    # -------- 3) Axe X + dates --------
    text.append(" " * y_label_w, style=muted)
    text.append("└" + "─" * n + "\n", style=grid_style)

    start_lbl = visible[0].date.isoformat()
    end_lbl = visible[-1].date.isoformat()
    pad = max(1, n - len(start_lbl) - len(end_lbl))
    text.append(" " * (y_label_w + 1))
    text.append(start_lbl, style=muted)
    text.append(" " * pad)
    text.append(end_lbl, style=muted)
    text.append("\n\n")

    # -------- 4) Volume bars --------
    vol_height = 3
    max_vol = max(vols) if vols else 1
    vol_levels_total = vol_height * 8
    vol_levels = [
        int(v / max_vol * vol_levels_total + 0.5) if max_vol > 0 else 0
        for v in vols
    ]

    vol_style = muted
    for r in range(vol_height):
        text.append(" " * y_label_w, style=muted)
        text.append("│", style=grid_style)
        row_top = (vol_height - r) * 8
        row_bot = (vol_height - r - 1) * 8
        for i in range(n):
            lvl = vol_levels[i]
            if lvl >= row_top:
                text.append("█", style=vol_style)
            elif lvl <= row_bot:
                text.append(" ")
            else:
                text.append(_BLOCKS_UP[lvl - row_bot], style=vol_style)
        text.append("\n")

    # Légende volume
    text.append(" " * y_label_w, style=muted)
    text.append("└" + "─" * n + "\n", style=grid_style)
    text.append(" VOL  max ", style=muted)
    if max_vol >= 1e9:
        text.append(f"{max_vol/1e9:.2f} Md", style=muted)
    elif max_vol >= 1e6:
        text.append(f"{max_vol/1e6:.2f} M", style=muted)
    else:
        text.append(f"{max_vol:,.0f}".replace(",", " "), style=muted)

    return text
