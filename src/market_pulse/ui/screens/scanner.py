"""Écran scanner : table des opportunités."""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from market_pulse.engine.scanner import Opportunity
from market_pulse.ui.widgets.score_bar import render_score_bar


class ScannerScreen(Screen):
    BINDINGS = [
        Binding("enter", "open_detail", "Detail", show=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "app.quit", "Quit", show=True),
        Binding("escape", "clear_search", "Clear search", show=False),
    ]

    def __init__(self, opportunities: list[Opportunity]) -> None:
        super().__init__()
        self.opportunities = opportunities
        self._filter_query = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        n_long = sum(1 for o in self.opportunities if o.trade_plan.direction == "long")
        n_short = len(self.opportunities) - n_long
        yield Static(
            f"· market pulse · horizon 1W · {len(self.opportunities)} opportunities "
            f"({n_long} long · {n_short} short) ·",
            classes="highlight-amber",
            id="header-info",
        )
        yield Input(placeholder="/  search by ticker or name  (Esc to clear)",
                    id="search-input")
        table = DataTable(cursor_type="row", zebra_stripes=False, id="opps-table")
        table.add_columns(
            "#", "TICKER", "NAME", "DIR", "SCORE",
            "ENTRY", "TP", "SL", "R/R", "▲%"
        )
        self._populate_table(table, "")
        yield table
        yield Footer()

    def _populate_table(self, table: DataTable, query: str) -> None:
        """Remplit / met à jour la table selon un filtre texte (ticker ou nom)."""
        table.clear()
        q = query.strip().lower()
        filtered = self.opportunities
        if q:
            filtered = [
                o for o in self.opportunities
                if q in o.ticker.lower() or q in o.name.lower()
            ]
        for i, opp in enumerate(filtered, start=1):
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
        # Stocker la liste filtrée pour que Enter ouvre le bon ticker
        self._filtered_opps = list(filtered)

    def on_mount(self) -> None:
        self.query_one(DataTable).focus()
        self._filtered_opps = list(self.opportunities)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_detail()

    def action_open_detail(self) -> None:
        self._open_detail()

    def _open_detail(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._filtered_opps):
            from market_pulse.ui.screens.detail import DetailScreen
            self.app.push_screen(DetailScreen(self._filtered_opps[row]))

    def action_refresh(self) -> None:
        self.app.exit(return_code=42)

    def action_focus_search(self) -> None:
        """Touche '/' → focus sur l'input de recherche."""
        self.query_one("#search-input", Input).focus()

    def action_clear_search(self) -> None:
        """Esc → efface la recherche et rend focus à la table."""
        search = self.query_one("#search-input", Input)
        if search.value:
            search.value = ""
        else:
            self.query_one(DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filtrage live au fil de la frappe."""
        if event.input.id == "search-input":
            self._filter_query = event.value
            self._populate_table(self.query_one(DataTable), event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter dans la search → si 1 match, ouvre le détail directement."""
        if event.input.id == "search-input":
            if len(self._filtered_opps) == 1:
                from market_pulse.ui.screens.detail import DetailScreen
                self.app.push_screen(DetailScreen(self._filtered_opps[0]))
            else:
                self.query_one(DataTable).focus()
