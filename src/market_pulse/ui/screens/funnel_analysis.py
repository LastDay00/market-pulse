"""Écran d'analyse IA en entonnoir : ~1500 → 750 → 375 → 188 → 94 → 47 → 23 → 10.

Déclenché depuis le scanner par la touche `a`. Les premiers rounds sont
parallélisés (plusieurs subprocess `claude` simultanés) ; les rounds tardifs
sont séquentiels. Le verdict final inclut une analyse détaillée des 10
finalistes.

Touche `c` pour ouvrir un drawer Claude en bas et discuter des finalistes
(symétrique au chat de la vue détail mais sur la liste des finalistes
plutôt que sur un seul ticker).

Esc/q pour fermer, `r` pour relancer.
"""
from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from market_pulse.chat.funnel_analysis import FunnelAnalysisSession, ROUNDS
from market_pulse.engine.scanner import Opportunity
from market_pulse.ui.widgets.funnel_chat_drawer import FunnelChatDrawer

# Au-delà de N tickers retenus, on tronque l'affichage de la liste « retenus »
# pour ne pas inonder l'écran (un round 1 peut garder 750 tickers).
_RETAINED_PREVIEW = 20


class FunnelAnalysisScreen(Screen):
    BINDINGS = [
        Binding("escape", "back_or_close_chat", "Retour", show=True),
        Binding("q", "back_or_close_chat", "Retour", show=False),
        Binding("c", "toggle_chat", "Chat finalistes", show=True),
        Binding("r", "rerun", "Relancer", show=True),
    ]

    def __init__(self, opportunities: list[Opportunity]) -> None:
        super().__init__()
        self.opps = list(opportunities)
        self._busy = False
        # Finalistes courants (mis à jour à chaque round_done). Initialement
        # vide : le drawer affiche un message d'attente jusqu'au 1er round.
        self._finalists: list[Opportunity] = []
        # Drawer créé dans compose, caché par défaut.
        self._chat_drawer: FunnelChatDrawer | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        n = len(self.opps)
        progression = f"{n} → " + " → ".join(str(r.target) for r in ROUNDS)
        yield Static(
            f"· entonnoir IA · {n} candidats · {progression} · "
            f"{len(ROUNDS)} rounds, rounds 1-3 en parallèle ·",
            classes="highlight-amber",
            id="ga-header",
        )
        log = RichLog(id="ga-log", wrap=True, markup=False, highlight=False)
        log.can_focus = True
        yield log
        # Drawer Claude : caché par défaut, visible quand on appuie sur 'c'
        self._chat_drawer = FunnelChatDrawer()
        self._chat_drawer.styles.display = "none"
        yield self._chat_drawer
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

    # ── Bindings ──────────────────────────────────────────────────────────

    def action_rerun(self) -> None:
        if self._busy:
            return
        log = self.query_one("#ga-log", RichLog)
        log.clear()
        self._finalists = []
        if self._chat_drawer is not None:
            self._chat_drawer.set_finalists([])
        self._run_analysis()

    def action_toggle_chat(self) -> None:
        if self._chat_drawer is None:
            return
        if self._chat_drawer.is_visible():
            self._chat_drawer.hide()
        else:
            self._chat_drawer.show()

    def action_back_or_close_chat(self) -> None:
        """Esc : ferme le chat s'il est ouvert, sinon retour scanner."""
        if (self._chat_drawer is not None
                and self._chat_drawer.is_visible()):
            self._chat_drawer.hide()
            return
        self.app.pop_screen()

    async def on_unmount(self) -> None:
        """Ferme proprement la session Claude du drawer au retour scanner."""
        if self._chat_drawer is not None:
            await self._chat_drawer.shutdown()

    # ── Funnel run ────────────────────────────────────────────────────────

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
            "Les rounds 1-3 tournent en parallèle (plusieurs subprocess "
            "`claude` simultanés). Compte ~3-6 min selon la taille.",
            style="#8A8680",
        ))
        log.write(Text(
            "Astuce : appuie sur 'c' une fois les finalistes affichés pour "
            "discuter de la sélection avec Claude.",
            style="#6B8CAE",
        ))
        self._busy = True
        session = FunnelAnalysisSession(self.opps, provider)
        # Pour suivre la liste survivante au fil des rounds — on alimente
        # le drawer avec la dernière liste (utile si l'utilisateur ouvre
        # le chat avant la fin).
        current_survivors: list[Opportunity] = list(self.opps)
        try:
            async for ev in session.stream():
                if ev.kind == "info":
                    log.write(Text(ev.text, style="bold #8A8680"))
                elif ev.kind == "round_start":
                    log.write(Text(""))
                    line = Text()
                    line.append("▶ ", style="bold #E8B45D")
                    line.append(ev.text, style="bold #E8B45D")
                    log.write(line)
                elif ev.kind == "enrich":
                    log.write(Text(ev.text, style="#8A8680"))
                elif ev.kind == "chunk_start":
                    log.write(Text(ev.text, style="#6B8CAE"))
                elif ev.kind == "chunk_done":
                    log.write(Text(ev.text, style="#7FB069"))
                elif ev.kind == "text":
                    log.write(Text(ev.text, style="#E8E6E3"))
                elif ev.kind == "round_done":
                    line = Text()
                    line.append("  ✓ retenus : ", style="#7FB069")
                    if len(ev.selected) > _RETAINED_PREVIEW:
                        preview = ", ".join(ev.selected[:_RETAINED_PREVIEW])
                        line.append(preview, style="#E8E6E3")
                        line.append(
                            f"  (+{len(ev.selected) - _RETAINED_PREVIEW} autres)",
                            style="#8A8680",
                        )
                    else:
                        line.append(", ".join(ev.selected), style="#E8E6E3")
                    log.write(line)
                    # Met à jour la liste survivante. Le drawer ne maintient
                    # une session active qu'à partir de petites listes pour
                    # éviter de générer un MCP avec 750 tickers.
                    selected_set = set(ev.selected)
                    current_survivors = [
                        o for o in current_survivors
                        if o.ticker in selected_set
                    ]
                    # Mise à jour du drawer seulement quand la liste est
                    # raisonnable pour le chat (≤ 50 tickers).
                    if (self._chat_drawer is not None
                            and len(current_survivors) <= 50):
                        self._finalists = list(current_survivors)
                        self._chat_drawer.set_finalists(self._finalists)
                elif ev.kind == "error":
                    log.write(Text(ev.text, style="#C97064"))
                elif ev.kind == "end":
                    log.write(Text(""))
                    log.write(Text("=== Entonnoir terminé ===",
                                    style="bold #E8B45D"))
                    if self._finalists:
                        log.write(Text(
                            f"Appuie sur 'c' pour discuter des "
                            f"{len(self._finalists)} finalistes avec Claude.",
                            style="bold #6B8CAE",
                        ))
        except Exception as e:
            log.write(Text(f"Erreur : {e}", style="#C97064"))
        finally:
            self._busy = False
