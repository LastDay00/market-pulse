"""Drawer Claude en bas de l'écran détail.

UI :
  ┌─ Chat finance · TICKER ──────────────────────┐
  │ Vous : ...                                   │
  │ Claude : ...                                 │
  │   → outil : get_overview                     │
  │ Claude : ...                                 │
  ├──────────────────────────────────────────────┤
  │ > [zone de saisie]                           │
  └──────────────────────────────────────────────┘

Caché par défaut, toggle via la touche `c` de DetailScreen.
"""
from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static

from market_pulse.chat.client import ChatSession
from market_pulse.engine.scanner import Opportunity


class ChatDrawer(Vertical):
    """Container en bas de l'écran détail. Affiche un mini-chat avec Claude."""

    DEFAULT_CSS = ""  # styles dans theme.css

    def __init__(self, opp: Opportunity) -> None:
        super().__init__(id="chat-drawer")
        self.opp = opp
        self._session: ChatSession | None = None
        self._busy = False

    def _availability(self) -> tuple[bool | None, str]:
        """Lit l'état du chat sur l'app (vérifié au boot).
        Retourne (available, reason).
        """
        try:
            available = getattr(self.app, "chat_available", None)
            reason = getattr(self.app, "chat_unavailable_reason", "")
            return available, reason
        except Exception:
            return None, ""

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="chat-header", classes="panel-header")
        log = RichLog(id="chat-log", wrap=True, markup=False, highlight=False)
        log.can_focus = False
        yield log
        yield Input(placeholder="Pose ta question à Claude (Enter pour envoyer)…",
                    id="chat-input")

    def _header_text(self) -> str:
        return f"Chat finance · {self.opp.ticker}  ─  Esc ou 'c' pour fermer"

    def on_mount(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(Text(
            "Tu peux poser une question sur ce ticker. Claude a accès aux "
            "données déjà chargées (prix, indicateurs, fondamentaux si "
            "appui sur F effectué). Premier message = démarrage de la session.",
            style="#8A8680",
        ))

    def show(self) -> None:
        self.styles.display = "block"
        try:
            self.query_one("#chat-input", Input).focus()
        except Exception:
            pass

    def hide(self) -> None:
        self.styles.display = "none"

    def is_visible(self) -> bool:
        return self.styles.display != "none"

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input":
            return
        if self._busy:
            return
        text = (event.value or "").strip()
        if not text:
            return
        log = self.query_one("#chat-log", RichLog)
        # Check chat availability au moment d'envoyer (le check au boot peut
        # encore être en cours juste après le démarrage).
        available, reason = self._availability()
        if available is False:
            log.write(Text(f"Chat indisponible : {reason}", style="#C97064"))
            event.input.value = ""
            return
        if available is None:
            log.write(Text(
                "Vérification du binaire `claude` en cours… réessaie dans un instant.",
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
        """Worker Textual : crée la session si besoin, stream la réponse."""
        log = self.query_one("#chat-log", RichLog)
        if self._session is None:
            try:
                self._session = ChatSession(self.opp)
                await self._session.start()
            except Exception as e:
                err = Text(f"Impossible de démarrer la session Claude : {e}",
                           style="#C97064")
                log.write(err)
                self._busy = False
                self._enable_input()
                return

        # Pré-écrit "Claude : " puis ajoute le texte au fur et à mesure.
        # On accumule la réponse pour pouvoir l'afficher proprement même si
        # le SDK envoie un seul TextBlock par tour (pas de vrai token-stream).
        response_buffer = ""
        any_text = False
        try:
            async for ev in self._session.send(user_text):
                if ev.kind == "text":
                    response_buffer += ev.text
                    any_text = True
                elif ev.kind == "tool_use":
                    # Affiche un marqueur en gris pour l'appel de tool
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
        """À appeler quand le drawer est démonté (ex. retour scanner)."""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
