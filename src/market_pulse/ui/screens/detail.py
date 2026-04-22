"""Écran détail : graphe + signaux + trade plan d'un ticker."""
import plotext as plt
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from market_pulse.engine.scanner import Opportunity


def _render_plotext_chart(opp: Opportunity, width: int = 60, height: int = 15) -> str:
    """Placeholder Phase 1 : un trait simple au niveau de l'entrée.
    Phase 2 branchera les vraies données de prix."""
    plt.clf()
    plt.theme("clear")
    plt.plotsize(width, height)
    plt.title(f"{opp.ticker} · {opp.horizon}")
    plt.plot([0, 10], [opp.trade_plan.entry, opp.trade_plan.entry])
    return plt.build()


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, opp: Opportunity) -> None:
        super().__init__()
        self.opp = opp

    def compose(self) -> ComposeResult:
        yield Header()
        tp = self.opp.trade_plan
        yield Static(
            f"· {self.opp.ticker} · score {self.opp.score:.1f} · horizon {self.opp.horizon} ·",
            classes="highlight-amber",
        )
        yield Static(_render_plotext_chart(self.opp))

        signals_text = "\n".join(
            f"  · {name:<28} {score:5.1f}  {md}"
            for name, score, md in self.opp.signal_details
        )
        yield Static(f"Signals:\n{signals_text}")

        uplift = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
        downside = (tp.stop - tp.entry) / tp.entry * 100 if tp.entry else 0
        plan_text = (
            f"Trade Plan:\n"
            f"  · Entry         {tp.entry:>8.2f}\n"
            f"  · Target (TP)   {tp.target:>8.2f}   {uplift:+.1f}%\n"
            f"  · Stop (SL)     {tp.stop:>8.2f}   {downside:+.1f}%\n"
            f"  · Risk/Reward   {tp.risk_reward:>4.1f}"
        )
        yield Static(plan_text)
        yield Footer()
