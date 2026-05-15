"""Écran d'analyse IA globale du top N : Claude commente la sélection.

Déclenché depuis le scanner par la touche `a`. Stream la réponse de Claude
dans un RichLog. Esc/q pour fermer, `r` pour relancer.
"""
from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from market_pulse.chat.global_analysis import GlobalAnalysisSession
from market_pulse.engine.scanner import Opportunity

DEFAULT_TOP_N = 50


class GlobalAnalysisScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Retour", show=True),
        Binding("q", "app.pop_screen", "Retour", show=True),
        Binding("r", "rerun", "Relancer", show=True),
    ]

    def __init__(self, opportunities: list[Opportunity],
                 top_n: int = DEFAULT_TOP_N) -> None:
        super().__init__()
        self.opps = opportunities[:top_n]
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        n_long = sum(1 for o in self.opps if o.trade_plan.direction == "long")
        n_short = len(self.opps) - n_long
        yield Static(
            f"· analyse IA · top {len(self.opps)} ({n_long} long · "
            f"{n_short} short) · Claude commente la sélection ·",
            classes="highlight-amber",
            id="ga-header",
        )
        log = RichLog(id="ga-log", wrap=True, markup=False, highlight=False)
        log.can_focus = True
        yield log
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#ga-log", RichLog)
        available = getattr(self.app, "chat_available", None)
        reason = getattr(self.app, "chat_unavailable_reason", "")
        if available is False:
            log.write(Text(
                f"Chat Claude indisponible : {reason}",
                style="#C97064",
            ))
            return
        if available is None:
            log.write(Text(
                "Vérification du binaire `claude` en cours… "
                "réessaie dans un instant avec `r`.",
                style="#8A8680",
            ))
            return
        self._run_analysis()

    def action_rerun(self) -> None:
        if self._busy:
            return
        log = self.query_one("#ga-log", RichLog)
        log.clear()
        self._run_analysis()

    @work(exclusive=True)
    async def _run_analysis(self) -> None:
        log = self.query_one("#ga-log", RichLog)
        log.write(Text(
            f"Claude analyse les {len(self.opps)} opportunités… "
            "(30s à 1 min selon la verbosité)",
            style="#8A8680",
        ))
        self._busy = True
        session = GlobalAnalysisSession(self.opps)
        buffer = ""
        try:
            async for ev in session.stream():
                if ev.kind == "text":
                    buffer += ev.text
                elif ev.kind == "error":
                    log.write(Text(ev.text, style="#C97064"))
                elif ev.kind == "end":
                    if buffer.strip():
                        log.write(Text(buffer, style="#E8E6E3"))
                    else:
                        log.write(Text("(aucune réponse)", style="#8A8680"))
                    buffer = ""
        except Exception as e:
            log.write(Text(f"Erreur de stream : {e}", style="#C97064"))
        finally:
            self._busy = False
