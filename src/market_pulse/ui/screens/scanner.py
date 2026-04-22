"""Écran scanner : table des opportunités."""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from market_pulse.engine.scanner import Opportunity
from market_pulse.ui.widgets.score_bar import render_score_bar


class ScannerScreen(Screen):
    BINDINGS = [
        Binding("enter", "open_detail", "Detail", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "app.quit", "Quit", show=True),
    ]

    def __init__(self, opportunities: list[Opportunity]) -> None:
        super().__init__()
        self.opportunities = opportunities

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        n_long = sum(1 for o in self.opportunities if o.trade_plan.direction == "long")
        n_short = len(self.opportunities) - n_long
        yield Static(
            f"· market pulse · horizon 1W · {len(self.opportunities)} opportunities "
            f"({n_long} long · {n_short} short) ·",
            classes="highlight-amber",
        )
        table = DataTable(cursor_type="row", zebra_stripes=False, id="opps-table")
        table.add_columns(
            "#", "TICKER", "NAME", "DIR", "SCORE",
            "ENTRY", "TP", "SL", "R/R", "▲%"
        )
        for i, opp in enumerate(self.opportunities, start=1):
            tp = opp.trade_plan
            if tp.direction == "long":
                uplift = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
                dir_text = Text("LONG ", style="#7FB069 bold")
            else:
                uplift = (tp.entry - tp.target) / tp.entry * 100 if tp.entry else 0
                dir_text = Text("SHORT", style="#C97064 bold")
            score_str = f"{render_score_bar(opp.score)} {opp.score:5.1f}"
            name_short = (opp.name[:26] + "…") if len(opp.name) > 27 else opp.name
            table.add_row(
                f"{i:02d}",
                opp.ticker,
                name_short,
                dir_text,
                score_str,
                f"{tp.entry:>8.2f}",
                f"{tp.target:>8.2f}",
                f"{tp.stop:>8.2f}",
                f"{tp.risk_reward:>4.1f}",
                f"{uplift:>+5.1f}",
            )
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter sur une ligne → ouvre le détail. Géré comme event DataTable
        plutôt qu'un Binding 'enter' parce que DataTable consomme la touche."""
        self._open_detail()

    def action_open_detail(self) -> None:
        self._open_detail()

    def _open_detail(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if 0 <= row < len(self.opportunities):
            from market_pulse.ui.screens.detail import DetailScreen
            self.app.push_screen(DetailScreen(self.opportunities[row]))

    def action_refresh(self) -> None:
        self.app.exit(return_code=42)  # code sentinelle "rescan requested"
