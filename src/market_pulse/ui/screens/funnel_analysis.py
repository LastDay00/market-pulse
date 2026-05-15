"""Écran d'analyse IA en entonnoir : 200 → 100 → 50 → 25 → 12 → 6 → 3.

Déclenché depuis le scanner par la touche `a`. Stream les commentaires de
Claude à chaque round dans un RichLog, plus la liste des tickers conservés
en fin de round. Le verdict final inclut une analyse détaillée des 3
finalistes.

Esc/q pour fermer, `r` pour relancer.
"""
from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from market_pulse.chat.funnel_analysis import (
    DEFAULT_SCOPE,
    FunnelAnalysisSession,
)
from market_pulse.engine.scanner import Opportunity


class FunnelAnalysisScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Retour", show=True),
        Binding("q", "app.pop_screen", "Retour", show=True),
        Binding("r", "rerun", "Relancer", show=True),
    ]

    def __init__(self, opportunities: list[Opportunity],
                 scope: int = DEFAULT_SCOPE) -> None:
        super().__init__()
        self.opps = opportunities[:scope]
        self.scope = scope
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        n = len(self.opps)
        yield Static(
            f"· entonnoir IA · {n} candidats · "
            f"{n}→100→50→25→12→6→3 · 6 rounds d'élimination ·",
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
                f"Chat Claude indisponible : {reason}", style="#C97064"))
            return
        if available is None:
            log.write(Text(
                "Vérification du binaire `claude` en cours… "
                "réessaie avec `r`.",
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
        provider = getattr(self.app, "provider", None)
        if provider is None:
            log.write(Text(
                "Provider yfinance indisponible — l'enrichissement progressif "
                "des fondamentaux sera sauté.",
                style="#8A8680",
            ))
        log.write(Text(
            f"Lancement de l'entonnoir sur {len(self.opps)} candidats. "
            "6 rounds, ~2-4 min au total selon la verbosité de Claude.",
            style="#8A8680",
        ))
        self._busy = True
        session = FunnelAnalysisSession(self.opps, provider, scope=self.scope)
        try:
            async for ev in session.stream():
                if ev.kind == "round_start":
                    log.write(Text(""))  # blank line
                    line = Text()
                    line.append("▶ ", style="bold #E8B45D")
                    line.append(ev.text, style="bold #E8B45D")
                    log.write(line)
                elif ev.kind == "enrich":
                    log.write(Text(ev.text, style="#8A8680"))
                elif ev.kind == "text":
                    log.write(Text(ev.text, style="#E8E6E3"))
                elif ev.kind == "round_done":
                    line = Text()
                    line.append("  ✓ retenus : ", style="#7FB069")
                    line.append(", ".join(ev.selected), style="#E8E6E3")
                    log.write(line)
                elif ev.kind == "error":
                    log.write(Text(ev.text, style="#C97064"))
                elif ev.kind == "end":
                    log.write(Text(""))
                    log.write(Text("=== Entonnoir terminé ===",
                                    style="bold #E8B45D"))
        except Exception as e:
            log.write(Text(f"Erreur : {e}", style="#C97064"))
        finally:
            self._busy = False
