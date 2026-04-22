"""Écran détail : graphe + signaux + trade plan d'un ticker."""
import plotext as plt
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from market_pulse.engine.scanner import Opportunity


SAUGE = (127, 176, 105)     # Nothing vert sauge
TERRA = (201, 112, 100)     # Nothing terre cuite
AMBRE = (232, 180, 93)      # Nothing ambre
SMOKE_BLUE = (107, 140, 174)  # Nothing bleu fumée
OFF_WHITE = (232, 230, 227)


def _render_price_chart(opp: Opportunity, width: int = 70, height: int = 16) -> Text:
    """Candlestick chart sur les bars récentes, avec couleurs Nothing douces.
    Retourne un rich.Text (ANSI→Rich markup) pour rendu Textual propre.
    """
    plt.clf()
    plt.theme("pro")
    plt.plotsize(width, height)
    plt.date_form("Y-m-d")
    if not opp.recent_bars:
        return Text("no price history")

    bars = opp.recent_bars
    dates = [b.date.strftime("%Y-%m-%d") for b in bars]
    data = {
        "Open":  [b.open for b in bars],
        "High":  [b.high for b in bars],
        "Low":   [b.low for b in bars],
        "Close": [b.close for b in bars],
    }
    # plotext.candlestick : colors = [up_color, down_color]
    plt.candlestick(dates, data, colors=[SAUGE, TERRA])

    # Lignes horizontales du trade plan, en tons doux
    plt.hline(opp.trade_plan.entry, color=OFF_WHITE)
    plt.hline(opp.trade_plan.target, color=SAUGE)
    plt.hline(opp.trade_plan.stop, color=TERRA)

    return Text.from_ansi(plt.build())


def _format_score_bar(score: float, width: int = 8) -> str:
    blocks = "▏▎▍▌▋▊▉█"
    score = max(0.0, min(100.0, score))
    full = int(score / 100 * width)
    part = int(((score / 100 * width) - full) * len(blocks))
    out = "█" * full
    if full < width and part > 0:
        out += blocks[part - 1]
    return out.ljust(width)


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("q", "app.quit", "Quit", show=True),
    ]

    def __init__(self, opp: Opportunity) -> None:
        super().__init__()
        self.opp = opp

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="detail-scroll"):
            yield Static(self._title_line(), classes="highlight-amber", id="title")
            with Horizontal(id="top-panels"):
                yield Static(_render_price_chart(self.opp),
                             id="chart-panel", classes="panel")
                yield Static(self._signals_text(),
                             id="signals-panel", classes="panel")
            yield Static(self._trade_plan_text(),
                         id="plan-panel", classes="panel")
        yield Footer()

    def _title_line(self) -> str:
        o = self.opp
        return (f"{o.ticker}  ·  SCORE {o.score:.1f} / 100"
                f"  ·  horizon {o.horizon.upper()}"
                f"  ·  {len(o.recent_bars)}d history")

    def _signals_text(self) -> str:
        """Une ligne par signal : `NAME ........... SCORE bar`.
        Volontairement compact pour tenir dans le panneau de droite."""
        lines = ["SIGNALS"]
        for name, score, metadata in self.opp.signal_details:
            bar = _format_score_bar(score, width=6)
            lines.append(f" · {name:<24} {score:5.1f}  {bar}")
            meta_str = _format_metadata(metadata)
            if meta_str:
                lines.append(f"     {meta_str}")
        return "\n".join(lines)

    def _trade_plan_text(self) -> str:
        tp = self.opp.trade_plan
        uplift = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
        downside = (tp.stop - tp.entry) / tp.entry * 100 if tp.entry else 0
        return (
            f"TRADE PLAN · {tp.horizon.upper()}\n"
            f" · Entry         {tp.entry:>10.2f}\n"
            f" · Target (TP)   {tp.target:>10.2f}   {uplift:+6.2f}%\n"
            f" · Stop (SL)     {tp.stop:>10.2f}   {downside:+6.2f}%\n"
            f" · Risk/Reward   {tp.risk_reward:>10.2f}\n"
            f" · Horizon       5-10 trading days"
        )


def _format_metadata(metadata: dict) -> str:
    """Extrait la valeur la plus parlante du metadata pour une ligne d'explication."""
    if metadata.get("skipped"):
        return "(no data)"
    if "rsi" in metadata:
        return f"RSI {metadata['rsi']:.1f}"
    if "hist" in metadata:
        return f"hist {metadata['hist']:+.3f}"
    if "width_percentile" in metadata:
        bo = "breakout" if metadata.get("breakout") else "no breakout"
        return f"width pct {metadata['width_percentile']:.0f}, {bo}"
    if "ma5_minus_ma20" in metadata:
        return f"MA5-MA20 {metadata['ma5_minus_ma20']:+.2f}"
    if "volume_ratio" in metadata:
        return f"vol ratio {metadata['volume_ratio']:.2f}x"
    if "excess_return_5d" in metadata:
        return f"excess {metadata['excess_return_5d']*100:+.1f}%"
    return ""
