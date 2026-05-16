"""Drawer Claude en bas de l'écran d'entonnoir.

Symétrique à `chat_drawer.py` (par-ticker) mais opère sur la liste des
finalistes au lieu d'une seule Opportunity. La session est créée
paresseusement au premier message et fermée au shutdown du drawer.

Le drawer reste invisible tant que l'entonnoir n'a pas produit de
finalistes. Une fois l'entonnoir terminé (ou en cours d'élimination —
on peut chatter sur les survivants intermédiaires), `set_finalists()`
est appelé pour mettre à jour la liste.
"""
from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static

from market_pulse.chat.funnel_chat import FunnelChatSession
from market_pulse.engine.scanner import Opportunity


class FunnelChatDrawer(Vertical):
    """Container en bas de FunnelAnalysisScreen avec un mini-chat Claude."""

    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__(id="chat-drawer")
        self._finalists: list[Opportunity] = []
        self._session: FunnelChatSession | None = None
        self._busy = False

    # ── State ─────────────────────────────────────────────────────────────

    def set_finalists(self, finalists: list[Opportunity]) -> None:
        """Mise à jour de la liste après chaque round / fin d'entonnoir.

        Une nouvelle liste invalide la session courante (history → ferme et
        recrée au prochain message). C'est intentionnel : si les finalistes
        changent, l'historique de discussion porterait sur une liste périmée.
        """
        previous_count = len(self._finalists)
        self._finalists = list(finalists)
        try:
            header = self.query_one("#chat-header", Static)
            header.update(self._header_text())
        except Exception:
            pass
        # Invalide la session si la liste change
        if previous_count and self._session is not None:
            self._invalidate_session_async()

    def _invalidate_session_async(self) -> None:
        """Ferme la session précédente sans bloquer (worker)."""
        old = self._session
        self._session = None
        if old is None:
            return

        @work(exclusive=False)
        async def _close():
            try:
                await old.close()
            except Exception:
                pass
        _close()

    # ── Composition ───────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="chat-header",
                     classes="panel-header")
        log = RichLog(id="chat-log", wrap=True, markup=False, highlight=False)
        log.can_focus = False
        yield log
        yield Input(placeholder="Pose ta question sur les finalistes "
                                  "(Enter pour envoyer)…",
                    id="chat-input")

    def _header_text(self) -> str:
        n = len(self._finalists)
        if n == 0:
            return "Chat finalistes ─  Esc ou 'c' pour fermer  ─  (entonnoir non terminé)"
        return (
            f"Chat finalistes · top {n}  ─  "
            f"Esc ou 'c' pour fermer"
        )

    def on_mount(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(Text(
            "Tu peux poser une question sur les finalistes : justification "
            "d'un choix, comparaison entre tickers, points forts/faibles, "
            "ordre de priorité… Premier message = démarrage de la session.",
            style="#8A8680",
        ))

    # ── Show / hide ───────────────────────────────────────────────────────

    def show(self) -> None:
        self.styles.display = "block"
        if not self._finalists:
            try:
                log = self.query_one("#chat-log", RichLog)
                log.write(Text(
                    "L'entonnoir n'est pas encore terminé. Attends la "
                    "présélection finale pour avoir des finalistes à "
                    "questionner.",
                    style="#E8B45D",
                ))
            except Exception:
                pass
        try:
            self.query_one("#chat-input", Input).focus()
        except Exception:
            pass

    def hide(self) -> None:
        self.styles.display = "none"

    def is_visible(self) -> bool:
        return self.styles.display != "none"

    # ── Input handling ────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input":
            return
        if self._busy:
            return
        text = (event.value or "").strip()
        if not text:
            return
        log = self.query_one("#chat-log", RichLog)
        # Pas de finalistes → pas de session possible
        if not self._finalists:
            log.write(Text(
                "Aucun finaliste disponible — l'entonnoir doit produire "
                "au moins quelques tickers avant de discuter.",
                style="#C97064",
            ))
            event.input.value = ""
            return
        # Check chat availability
        available = getattr(self.app, "chat_available", None)
        reason = getattr(self.app, "chat_unavailable_reason", "")
        if available is False:
            log.write(Text(f"Chat indisponible : {reason}", style="#C97064"))
            event.input.value = ""
            return
        if available is None:
            log.write(Text(
                "Vérification du binaire `claude` en cours… réessaie dans "
                "un instant.",
                style="#8A8680",
            ))
            event.input.value = ""
            return
        event.input.value = ""
        prompt_line = Text()
        prompt_line.append("Vous : ", style="bold #E8B45D")
        prompt_line.append(text, style="#E8E6E3")
        log.write(prompt_line)
        self._busy = True
        event.input.disabled = True
        self._stream_response(text)

    @work(exclusive=False)
    async def _stream_response(self, user_text: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        if self._session is None:
            try:
                self._session = FunnelChatSession(self._finalists)
                await self._session.start()
            except Exception as e:
                err = Text(
                    f"Impossible de démarrer la session Claude : {e}",
                    style="#C97064",
                )
                log.write(err)
                self._busy = False
                self._enable_input()
                return

        response_buffer = ""
        any_text = False
        try:
            async for ev in self._session.send(user_text):
                if ev.kind == "text":
                    response_buffer += ev.text
                    any_text = True
                elif ev.kind == "tool_use":
                    line = Text()
                    line.append("  → outil : ", style="#8A8680")
                    line.append(ev.tool_name, style="#6B8CAE")
                    log.write(line)
                elif ev.kind == "error":
                    log.write(Text(ev.text, style="#C97064"))
                elif ev.kind == "end":
                    if any_text and response_buffer:
                        out = Text()
                        out.append("Claude : ", style="bold #7FB069")
                        out.append(response_buffer, style="#E8E6E3")
                        log.write(out)
                    elif not any_text:
                        log.write(Text("(aucune réponse)", style="#8A8680"))
                    response_buffer = ""
                    any_text = False
        except Exception as e:
            log.write(Text(f"Erreur de stream : {e}", style="#C97064"))
        finally:
            self._busy = False
            self._enable_input()

    def _enable_input(self) -> None:
        try:
            inp = self.query_one("#chat-input", Input)
            inp.disabled = False
            inp.focus()
        except Exception:
            pass

    async def shutdown(self) -> None:
        """Appelé quand le drawer est démonté (retour scanner)."""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
