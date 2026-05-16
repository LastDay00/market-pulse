"""Session de chat Claude post-entonnoir : discuter des finalistes.

Une `FunnelChatSession` est créée à la fin du run de l'entonnoir avec la
liste finale des opportunités (typiquement le top 10). Le trader peut
ensuite poser des questions à Claude :
  - « Pourquoi AAPL est-il numéro 1 ? »
  - « Compare TSLA et GOOG sur les marges »
  - « Quel est le finaliste avec le meilleur R/R ? »

Architecture symétrique à `chat/client.py` (chat par-ticker) :
  - MCP server in-process avec des tools liés aux finalistes via closure,
  - ClaudeSDKClient multi-tour ouvert pendant toute la durée du drawer.

On réutilise les helpers de formatage de `chat/tools.py` pour rester
cohérent avec la vue détail.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
    tool,
)

from market_pulse.chat.tools import (
    _format_news,
    _format_overview,
    _format_signals,
    _format_trade_plan,
    _format_valuation,
    _format_volatility_stats,
    _fmt_pct,
    _fmt_ratio,
    _txt,
)
from market_pulse.engine.scanner import Opportunity


_MCP_SERVER_NAME = "market_pulse_funnel"


def _system_prompt(n_finalists: int) -> str:
    return (
        f"Tu es un analyste financier sénior intégré dans Market Pulse. "
        f"Tu viens de terminer un entonnoir d'analyse à 7 rounds qui a "
        f"réduit ~1500 opportunités de swing-trading à un top {n_finalists}. "
        f"Le trader veut maintenant te poser des questions sur cette "
        f"sélection finale.\n\n"
        f"CONTEXTE\n"
        f"- Tu as accès via des outils à la liste des finalistes et au "
        f"détail de chaque ticker (prix, signaux, plan de trade, ratios, "
        f"fondamentaux si chargés, news si chargées).\n"
        f"- Tu n'as PAS accès aux tickers éliminés en cours de route ni à "
        f"internet. Si on te demande un ticker hors-finalistes, dis-le "
        f"clairement.\n"
        f"- Quand une donnée renvoie « non chargée », signale-le.\n\n"
        f"STYLE\n"
        f"- Direct et concis. Pas de remplissage, pas de répétition de "
        f"la question.\n"
        f"- Cite tickers et chiffres systématiquement (avec la période).\n"
        f"- Tu peux comparer les finalistes, justifier un ordre de "
        f"priorité, signaler un risque que tu vois.\n"
        f"- Pas de disclaimer répété à chaque message — il est entendu."
    )


@dataclass
class ChatEvent:
    """Mêmes événements que la session par-ticker."""
    kind: Literal["text", "tool_use", "tool_result", "error", "end"]
    text: str = ""
    tool_name: str = ""


def _format_finalist_line(rank: int, opp: Opportunity) -> str:
    tp = opp.trade_plan
    sect = (opp.meta.sector if opp.meta and opp.meta.sector else "—")
    name = (opp.name or "")[:24]
    return (
        f"  {rank:2d}. {opp.ticker:<8} {name:<24} "
        f"[{sect[:15]:<15}] {tp.direction.upper():<5} "
        f"score={opp.score:5.1f} R/R={tp.risk_reward:4.2f} "
        f"entry={tp.entry:7.2f} TP={tp.target:7.2f} SL={tp.stop:7.2f}"
    )


def _format_compare(opps: list[Opportunity]) -> str:
    """Tableau côte-à-côte de 2 à 4 tickers."""
    if not opps:
        return "Aucun ticker à comparer."
    headers = ["Ticker", "Dir", "Score", "R/R", "Entry", "TP", "SL"]
    rows = [headers]
    for o in opps:
        tp = o.trade_plan
        rows.append([
            o.ticker,
            tp.direction.upper(),
            f"{o.score:.1f}",
            f"{tp.risk_reward:.2f}",
            f"{tp.entry:.2f}",
            f"{tp.target:.2f}",
            f"{tp.stop:.2f}",
        ])
    # Fondamentaux si dispo
    fundamental_keys = [
        ("PE", lambda m: _fmt_ratio(m.trailing_pe)),
        ("PEG", lambda m: _fmt_ratio(m.peg_ratio)),
        ("ROE", lambda m: _fmt_pct(m.return_on_equity)),
        ("MrgNet", lambda m: _fmt_pct(m.profit_margin)),
        ("ΔCA YoY", lambda m: _fmt_pct(m.revenue_growth)),
        ("D/E", lambda m: _fmt_ratio(m.debt_to_equity)),
    ]
    has_meta = any(o.meta is not None for o in opps)
    if has_meta:
        for label, getter in fundamental_keys:
            rows[0].append(label)
            for i, o in enumerate(opps, 1):
                rows[i].append(getter(o.meta) if o.meta else "—")
    widths = [max(len(str(r[c])) for r in rows) for c in range(len(rows[0]))]
    out = []
    for ri, row in enumerate(rows):
        out.append("  ".join(str(v).ljust(widths[ci])
                              for ci, v in enumerate(row)))
        if ri == 0:
            out.append("  ".join("-" * w for w in widths))
    perf_lines = ["", "Performances (1j / 5j / 20j / 60j / 1an) :"]
    for o in opps:
        from market_pulse.chat.tools import _pct_change
        perfs = []
        for d in (1, 5, 20, 60, 252):
            v = _pct_change(o, d)
            perfs.append(f"{v:+.1f}%" if v is not None else "—")
        perf_lines.append(f"  {o.ticker:<8} : " + " / ".join(perfs))
    return "\n".join(out) + "\n" + "\n".join(perf_lines)


def make_funnel_tools(finalists: list[Opportunity]) -> list:
    """Construit les tools MCP pour la session de chat de l'entonnoir."""
    by_ticker: dict[str, Opportunity] = {o.ticker: o for o in finalists}

    @tool(
        "list_finalists",
        "Liste les finalistes de l'entonnoir (ticker, nom, secteur, "
        "direction, score, R/R, plan de trade). À appeler en premier pour "
        "cadrer la conversation.",
        {},
    )
    async def list_finalists(args: dict) -> dict:
        lines = [f"Finalistes ({len(finalists)} tickers) :"]
        for i, o in enumerate(finalists, 1):
            lines.append(_format_finalist_line(i, o))
        return _txt("\n".join(lines))

    @tool(
        "get_ticker_details",
        "Détail complet d'un finaliste : overview, plan de trade, signaux "
        "techniques, ratios de valorisation, statistiques de volatilité. "
        "Si fondamentaux non chargés, le message le signalera.",
        {"ticker": str},
    )
    async def get_ticker_details(args: dict) -> dict:
        t = str(args.get("ticker", "")).upper().strip()
        if t not in by_ticker:
            return _txt(
                f"« {t} » n'est pas dans la liste des finalistes. "
                f"Appelle list_finalists pour voir les tickers disponibles."
            )
        o = by_ticker[t]
        parts = [
            _format_overview(o),
            "",
            _format_trade_plan(o),
            "",
            _format_signals(o),
            "",
            _format_volatility_stats(o),
            "",
            _format_valuation(o),
        ]
        return _txt("\n".join(parts))

    @tool(
        "get_ticker_news",
        "Actualités récentes pour un finaliste (si chargées). "
        "Si pas chargées, message explicatif.",
        {"ticker": str},
    )
    async def get_ticker_news(args: dict) -> dict:
        t = str(args.get("ticker", "")).upper().strip()
        if t not in by_ticker:
            return _txt(f"« {t} » n'est pas dans les finalistes.")
        return _txt(_format_news(by_ticker[t]))

    @tool(
        "compare_finalists",
        "Compare 2 à 4 finalistes côte à côte : score, R/R, plan de trade, "
        "fondamentaux (PE, PEG, ROE, marge, croissance, dette) et perfs "
        "multi-horizons. Passe les tickers en chaîne séparée par virgules "
        "(ex. 'AAPL,MSFT,GOOG').",
        {"tickers": str},
    )
    async def compare_finalists(args: dict) -> dict:
        raw = str(args.get("tickers", ""))
        tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
        if not 2 <= len(tickers) <= 4:
            return _txt("Donne 2 à 4 tickers (séparés par des virgules).")
        unknown = [t for t in tickers if t not in by_ticker]
        if unknown:
            return _txt(
                f"Ces tickers ne sont pas dans les finalistes : "
                f"{', '.join(unknown)}. Appelle list_finalists pour la "
                f"liste valide."
            )
        opps = [by_ticker[t] for t in tickers]
        return _txt(_format_compare(opps))

    @tool(
        "get_funnel_summary",
        "Synthèse statistique de la sélection finale : répartition "
        "LONG/SHORT, secteurs représentés, distribution des scores et "
        "des R/R. Utile pour cadrer l'analyse globale.",
        {},
    )
    async def get_funnel_summary(args: dict) -> dict:
        if not finalists:
            return _txt("Aucun finaliste.")
        n = len(finalists)
        n_long = sum(1 for o in finalists if o.trade_plan.direction == "long")
        n_short = n - n_long
        scores = [o.score for o in finalists]
        rrs = [o.trade_plan.risk_reward for o in finalists]
        sectors: dict[str, int] = {}
        for o in finalists:
            s = (o.meta.sector if o.meta and o.meta.sector else "Inconnu")
            sectors[s] = sectors.get(s, 0) + 1
        sect_str = ", ".join(
            f"{s} ({c})"
            for s, c in sorted(sectors.items(), key=lambda kv: -kv[1])
        )
        return _txt(
            f"Synthèse des {n} finalistes :\n"
            f"  · Direction : {n_long} LONG · {n_short} SHORT\n"
            f"  · Score : min {min(scores):.1f} · médian "
            f"{sorted(scores)[n//2]:.1f} · max {max(scores):.1f}\n"
            f"  · R/R : min {min(rrs):.2f} · médian "
            f"{sorted(rrs)[n//2]:.2f} · max {max(rrs):.2f}\n"
            f"  · Secteurs : {sect_str}"
        )

    return [
        list_finalists,
        get_ticker_details,
        get_ticker_news,
        compare_finalists,
        get_funnel_summary,
    ]


class FunnelChatSession:
    """Session multi-tour avec Claude pour discuter des finalistes."""

    def __init__(self, finalists: list[Opportunity]) -> None:
        self.finalists = finalists
        self._client: ClaudeSDKClient | None = None
        self._tools = make_funnel_tools(finalists)

    async def start(self) -> None:
        if self._client is not None:
            return
        mcp_server = create_sdk_mcp_server(
            name=_MCP_SERVER_NAME,
            tools=self._tools,
        )
        allowed = [
            f"mcp__{_MCP_SERVER_NAME}__{getattr(t, 'name', None) or t.__name__}"
            for t in self._tools
        ]
        options = ClaudeAgentOptions(
            system_prompt=_system_prompt(len(self.finalists)),
            mcp_servers={_MCP_SERVER_NAME: mcp_server},
            allowed_tools=allowed,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.__aenter__()

    async def send(self, user_message: str) -> AsyncIterator[ChatEvent]:
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
        cls_name = type(message).__name__
        if cls_name == "ResultMessage":
            return
        content = getattr(message, "content", None)
        if content is None:
            return
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
                short = name.split("__")[-1] if name else "?"
                yield ChatEvent(kind="tool_use", tool_name=short)
            elif block_cls == "ToolResultBlock":
                yield ChatEvent(kind="tool_result")

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None
