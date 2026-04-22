"""Rendu custom de chart candlestick avec volume, en Rich Text colorisé.

plotext n'offre pas assez de contrôle sur la largeur des bougies, les couleurs
exactes et l'intégration Rich. Cette version rend directement en Text stylé.
"""
from __future__ import annotations

from rich.text import Text

from market_pulse.data.models import Bar

SAUGE_RGB = (127, 176, 105)
TERRA_RGB = (201, 112, 100)
AMBRE_RGB = (232, 180, 93)
SMOKE_RGB = (107, 140, 174)
OFF_WHITE_RGB = (232, 230, 227)
GRID_RGB = (60, 60, 66)
MUTED_RGB = (138, 134, 128)


def _rgb_style(rgb: tuple[int, int, int]) -> str:
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"


def render_candlestick_chart(
    bars: list[Bar],
    trade_plan=None,
    width: int = 72,
    chart_height: int = 14,
    volume_height: int = 3,
) -> Text:
    """Rend un chart candlestick + volume sparkline sous forme de Rich Text.

    Args:
        bars: liste de Bar, rendus du plus ancien au plus récent
        trade_plan: TradePlan optionnel pour tracer des lignes horizontales
        width: largeur totale en caractères
        chart_height: hauteur zone bougies
        volume_height: hauteur zone volume (0 pour désactiver)
    """
    text = Text()
    if not bars:
        text.append("no data", style=_rgb_style(MUTED_RGB))
        return text

    # Y-axis labels = 8 chars + separator '┤' = 9 chars
    y_label_w = 9
    chart_w = max(10, width - y_label_w)
    n_bars = min(len(bars), chart_w)
    visible = bars[-n_bars:]

    # Price range (inclut les lignes du trade plan pour qu'elles soient visibles)
    prices = [b.high for b in visible] + [b.low for b in visible]
    if trade_plan is not None:
        prices.extend([trade_plan.entry, trade_plan.target, trade_plan.stop])
    hi = max(prices)
    lo = min(prices)
    rng = hi - lo if hi > lo else 1.0

    def y_row(price: float) -> int:
        """Mappe prix → index de ligne (0 en haut, chart_height-1 en bas)."""
        return int((hi - price) / rng * (chart_height - 1) + 0.5)

    # Grid = lignes × colonnes, chaque cellule (char, style)
    grid: list[list[tuple[str, str | None]]] = [
        [(" ", None) for _ in range(chart_w)] for _ in range(chart_height)
    ]

    # 1) Lignes horizontales du trade plan
    if trade_plan is not None:
        for price, rgb in (
            (trade_plan.entry, OFF_WHITE_RGB),
            (trade_plan.target, SAUGE_RGB),
            (trade_plan.stop, TERRA_RGB),
        ):
            r = y_row(price)
            if 0 <= r < chart_height:
                for c in range(chart_w):
                    if grid[r][c][0] == " ":
                        grid[r][c] = ("─", _rgb_style(rgb))

    # 2) Bougies
    for i, bar in enumerate(visible):
        col = i
        if col >= chart_w:
            break
        y_high = y_row(bar.high)
        y_low = y_row(bar.low)
        y_open = y_row(bar.open)
        y_close = y_row(bar.close)

        is_up = bar.close >= bar.open
        rgb = SAUGE_RGB if is_up else TERRA_RGB
        style = _rgb_style(rgb)

        body_top = min(y_open, y_close)
        body_bot = max(y_open, y_close)

        # Mèches (wicks)
        for r in range(max(0, y_high), min(chart_height, y_low + 1)):
            if body_top <= r <= body_bot:
                continue  # body handled below
            grid[r][col] = ("│", style)
        # Corps (body)
        if body_top == body_bot:
            # Doji: pas de corps, trait horizontal
            if 0 <= body_top < chart_height:
                grid[body_top][col] = ("─", style)
        else:
            for r in range(max(0, body_top), min(chart_height, body_bot + 1)):
                grid[r][col] = ("█", style)

    # Y-axis labels aux 5 tick rows (top, 25%, 50%, 75%, bottom)
    tick_rows = {0, chart_height // 4, chart_height // 2,
                 3 * chart_height // 4, chart_height - 1}
    tick_prices: dict[int, float] = {}
    for r in tick_rows:
        ratio = r / (chart_height - 1) if chart_height > 1 else 0
        tick_prices[r] = hi - ratio * rng

    # Build text row by row
    muted_style = _rgb_style(MUTED_RGB)
    grid_style = _rgb_style(GRID_RGB)

    for r in range(chart_height):
        if r in tick_rows:
            text.append(f"{tick_prices[r]:>8.2f}", style=muted_style)
            text.append("┤", style=grid_style)
        else:
            text.append(" " * 8, style=muted_style)
            text.append("│", style=grid_style)
        for c in range(chart_w):
            ch, style = grid[r][c]
            if style:
                text.append(ch, style=style)
            else:
                text.append(ch)
        text.append("\n")

    # X-axis bottom line
    text.append(" " * 8, style=muted_style)
    text.append("└", style=grid_style)
    text.append("─" * chart_w, style=grid_style)
    text.append("\n")

    # X-axis date labels (start, end)
    start_lbl = visible[0].date.isoformat()
    end_lbl = visible[-1].date.isoformat()
    pad = max(1, chart_w - len(start_lbl) - len(end_lbl))
    text.append(" " * 9, style=muted_style)
    text.append(start_lbl, style=muted_style)
    text.append(" " * pad)
    text.append(end_lbl, style=muted_style)
    text.append("\n")

    # Volume sparkline
    if volume_height > 0:
        text.append("\n")
        vols = [b.volume for b in visible]
        vol_max = max(vols) if vols else 1
        blocks = "▁▂▃▄▅▆▇█"
        text.append(" " * 8, style=muted_style)
        text.append("│", style=grid_style)
        for i, v in enumerate(vols):
            if i >= chart_w:
                break
            # Choisir un block selon v / vol_max
            level = int(v / vol_max * (len(blocks) - 1)) if vol_max > 0 else 0
            bar_char = blocks[level]
            # Couleur selon direction de la bougie associée
            bar_style = _rgb_style(SAUGE_RGB) if visible[i].close >= visible[i].open else _rgb_style(TERRA_RGB)
            text.append(bar_char, style=bar_style)
        text.append(f"\n    VOL  max {vol_max/1e6:.1f}M", style=muted_style)

    return text
