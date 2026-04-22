"""Écran détail : graphe + signaux + trade plan d'un ticker."""
import plotext as plt
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from market_pulse.engine.scanner import Opportunity


def _render_price_chart(opp: Opportunity, width: int = 68, height: int = 14) -> str:
    """Trace le prix de clôture sur l'historique disponible."""
    plt.clf()
    plt.theme("pro")
    plt.plotsize(width, height)
    if not opp.price_history:
        plt.text("no price history", 0.5, 0.5)
        return plt.build()
    xs = list(range(len(opp.price_history)))
    closes = [p[1] for p in opp.price_history]
    plt.plot(xs, closes, marker="braille")
    plt.hline(opp.trade_plan.entry, color="white")
    plt.hline(opp.trade_plan.target, color="green")
    plt.hline(opp.trade_plan.stop, color="red")
    plt.xticks([0, len(xs) - 1],
               [opp.price_history[0][0].isoformat(),
                opp.price_history[-1][0].isoformat()])
    return plt.build()


def _format_score_bar(score: float, width: int = 10) -> str:
    blocks = "▏▎▍▌▋▊▉█"
    score = max(0.0, min(100.0, score))
    full = int(score / 100 * width)
    part = int(((score / 100 * width) - full) * len(blocks))
    out = "█" * full
    if full < width and part > 0:
        out += blocks[part - 1]
    return out.ljust(width)


def _dotted_row(label: str, value: str, total_width: int = 40) -> str:
    """'RSI(14) ........ 28' style."""
    label = f" · {label}"
    dots_len = max(3, total_width - len(label) - len(value) - 1)
    return f"{label} {'.' * dots_len} {value}"


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
                f"  ·  {len(o.price_history)}d history")

    def _signals_text(self) -> str:
        lines = ["SIGNALS"]
        for name, score, metadata in self.opp.signal_details:
            val_str = _format_metadata(metadata)
            bar = _format_score_bar(score, width=8)
            lines.append(f" · {name:<26} {val_str:>10}  {bar}  {score:5.1f}")
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
    """Extrait la valeur la plus parlante d'un metadata dict pour affichage court."""
    if metadata.get("skipped"):
        return "skipped"
    if "rsi" in metadata:
        return f"{metadata['rsi']:.1f}"
    if "hist" in metadata:
        return f"{metadata['hist']:+.3f}"
    if "width_percentile" in metadata:
        return f"pct {metadata['width_percentile']:.0f}"
    if "ma5_minus_ma20" in metadata:
        return f"{metadata['ma5_minus_ma20']:+.2f}"
    if "volume_ratio" in metadata:
        return f"{metadata['volume_ratio']:.2f}x"
    if "excess_return_5d" in metadata:
        return f"{metadata['excess_return_5d']*100:+.1f}%"
    return "-"
