"""Wrapper haut niveau autour de claude_agent_sdk pour le drawer Textual.

Une `ChatSession` =
  - un MCP server in-process avec les tools de l'Opportunity courante,
  - un `ClaudeSDKClient` ouvert pendant toute la durée du drawer (multi-tour),
  - un async iterator de `ChatEvent` qui simplifie le rendu côté UI.

On ne dépend pas des types internes du SDK (TextBlock, ToolUseBlock, etc.) :
on inspecte par nom de classe et duck-typing pour rester robuste si le SDK
renomme des choses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
)

from market_pulse.chat.prompt import SYSTEM_PROMPT
from market_pulse.chat.tools import make_tools_for_opportunity
from market_pulse.engine.scanner import Opportunity

# Nom du MCP server in-process. Chaque tool sera exposé à Claude sous le nom
# `mcp__market_pulse__<tool_name>`, format imposé par le SDK.
_MCP_SERVER_NAME = "market_pulse"


@dataclass
class ChatEvent:
    """Événement émis par la session vers la UI."""
    kind: Literal["text", "tool_use", "tool_result", "error", "end"]
    text: str = ""
    tool_name: str = ""


class ChatSession:
    """Session de chat liée à une Opportunity. Multi-tour.

    Usage :
        session = ChatSession(opp)
        await session.start()
        async for event in session.send("Que penses-tu du signal ?"):
            ...   # afficher event.text / event.tool_name
        await session.close()
    """

    def __init__(self, opp: Opportunity) -> None:
        self.opp = opp
        self._client: ClaudeSDKClient | None = None
        self._tools = make_tools_for_opportunity(opp)

    async def start(self) -> None:
        """Initialise le SDK client. À appeler une fois avant le premier send."""
        if self._client is not None:
            return

        mcp_server = create_sdk_mcp_server(
            name=_MCP_SERVER_NAME,
            tools=self._tools,
        )

        # Le SDK préfixe les tools MCP par mcp__<server>__<tool>. On doit
        # explicitement les autoriser.
        allowed = [
            f"mcp__{_MCP_SERVER_NAME}__{getattr(t, 'name', None) or t.__name__}"
            for t in self._tools
        ]

        options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={_MCP_SERVER_NAME: mcp_server},
            allowed_tools=allowed,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.__aenter__()

    async def send(self, user_message: str) -> AsyncIterator[ChatEvent]:
        """Envoie un message et yield les événements jusqu'à fin de tour."""
        if self._client is None:
            await self.start()
        assert self._client is not None
        try:
            await self._client.query(user_message)
            async for message in self._client.receive_response():
                async for event in self._iter_events(message):
                    yield event
        except Exception as e:
            yield ChatEvent(kind="error", text=f"Erreur SDK : {e}")
        yield ChatEvent(kind="end")

    async def _iter_events(self, message) -> AsyncIterator[ChatEvent]:
        """Convertit un message du SDK en ChatEvent(s).

        Les messages exposent typiquement un attribut `content` (liste de
        blocs). On reconnaît :
          - TextBlock     → kind='text'
          - ToolUseBlock  → kind='tool_use' (Claude appelle un de nos tools)
          - ToolResultBlock dans UserMessage → kind='tool_result' (le retour)
        Le ResultMessage final n'émet rien (le 'end' est ajouté par send()).
        """
        cls_name = type(message).__name__

        # Result final → on ignore, send() émettra un 'end'
        if cls_name == "ResultMessage":
            return

        content = getattr(message, "content", None)
        if content is None:
            return

        # content peut être une liste de blocs ou parfois directement une str
        if isinstance(content, str):
            if content.strip():
                yield ChatEvent(kind="text", text=content)
            return

        for block in content:
            block_cls = type(block).__name__
            if block_cls == "TextBlock":
                text = getattr(block, "text", "")
                if text:
                    yield ChatEvent(kind="text", text=text)
            elif block_cls == "ToolUseBlock":
                name = getattr(block, "name", "") or ""
                # Strip le préfixe mcp__market_pulse__ pour l'affichage
                short = name.split("__")[-1] if name else "?"
                yield ChatEvent(kind="tool_use", tool_name=short)
            elif block_cls == "ToolResultBlock":
                # On n'affiche pas le contenu du résultat (souvent verbeux),
                # juste le fait qu'on l'a reçu — Claude va l'utiliser ensuite.
                yield ChatEvent(kind="tool_result")
            # Les autres blocs (ThinkingBlock par ex.) sont ignorés silencieusement.

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None
