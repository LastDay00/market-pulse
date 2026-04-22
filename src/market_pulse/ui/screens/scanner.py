"""Écran scanner : table des opportunités."""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from market_pulse.engine.scanner import Opportunity
from market_pulse.ui.widgets.score_bar import render_score_bar


class ScannerScreen(Screen):
    BINDINGS = [
        Binding("enter", "open_detail", "Detail"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, opportunities: list[Opportunity]) -> None:
        super().__init__()
        self.opportunities = opportunities

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"· market pulse · horizon 1W · {len(self.opportunities)} opportunities ·",
            classes="highlight-amber",
        )
        table = DataTable(cursor_type="row", zebra_stripes=False)
        table.add_columns("#", "TICKER", "SCORE", "ENTRY", "TP", "SL", "R/R", "▲%")
        for i, opp in enumerate(self.opportunities, start=1):
            tp = opp.trade_plan
            uplift = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
            score_str = f"{render_score_bar(opp.score)} {opp.score:5.1f}"
            table.add_row(
                f"{i:02d}",
                opp.ticker,
                score_str,
                f"{tp.entry:>8.2f}",
                f"{tp.target:>8.2f}",
                f"{tp.stop:>8.2f}",
                f"{tp.risk_reward:>4.1f}",
                f"{uplift:>+5.1f}",
            )
        yield table
        yield Footer()

    def action_open_detail(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if 0 <= row < len(self.opportunities):
            from market_pulse.ui.screens.detail import DetailScreen
            self.app.push_screen(DetailScreen(self.opportunities[row]))

    def action_refresh(self) -> None:
        self.app.exit(return_code=42)  # code sentinelle "rescan requested"
