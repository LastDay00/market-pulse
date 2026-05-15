"""Entonnoir d'analyse IA multi-rounds : 200 → 100 → 50 → 25 → 12 → 6 → 3.

À chaque round, Claude reçoit la liste courante des candidats avec un niveau
de détail croissant, élimine la moitié, et passe au round suivant. Au round
final (verdict), il produit une analyse détaillée des 3 finalistes.

Le module ne dépend pas de MCP : on passe tout le contexte dans le prompt
utilisateur. Une seule `ClaudeSDKClient` est ouverte et réutilisée pour les
6 tours (multi-tour natif du SDK).

Parsing : Claude doit terminer chaque réponse par un bloc
    === SELECTED ===
    TICKER1
    TICKER2
    ...
    === END ===
qu'on extrait par regex. Si le parse échoue, on retombe sur les N premiers
candidats par score (fallback safe).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from market_pulse.data.providers.base import Provider
from market_pulse.engine.scanner import Opportunity, enrich_opportunity


DEFAULT_SCOPE = 200

# Chaque round : (target_size, label_court)
ROUNDS: list[tuple[int, str]] = [
    (100, "tri rapide"),
    (50, "filtrage technique"),
    (25, "validation fondamentale"),
    (12, "examen approfondi"),
    (6, "présélection finale"),
    (3, "verdict"),
]


SYSTEM_PROMPT_FUNNEL = """Tu es un analyste financier sénior pilotant un \
processus d'entonnoir d'analyse à 6 rounds : on part de 200 opportunités \
techniques de swing-trading et on réduit progressivement la liste jusqu'à un \
top 3 sur lequel tu dois avoir une forte conviction.

À chaque round on te donne la liste courante des candidats, un niveau de \
détail croissant, et la taille cible pour le round suivant. Tu élimines les \
plus faibles et tu gardes EXACTEMENT le nombre demandé.

Format de réponse OBLIGATOIRE à chaque round :
1. Une explication courte (3-5 lignes max) de tes critères de coupe avec \
tickers et chiffres. Pour le round final, donne en plus une analyse détaillée \
des 3 finalistes (voir ci-dessous).
2. Termine TOUJOURS par un bloc strictement formaté :

=== SELECTED ===
TICKER1
TICKER2
...
=== END ===

RÈGLES STRICTES
- Le nombre de tickers entre les balises DOIT correspondre exactement à la \
cible demandée.
- Un ticker par ligne, sans puce, sans numéro, sans commentaire.
- N'invente pas de tickers — uniquement ceux de la liste fournie.

ROUND FINAL (verdict top 3)
Avant la liste finale, pour chaque finaliste, écris :
  ### TICKER — Nom
  **Thèse (LONG ou SHORT)** : pourquoi cette direction.
  **Technique** : score, R/R, indicateurs clés, momentum, niveaux du plan.
  **Fondamental** : valorisation, marges, croissance, solidité du bilan (si dispo).
  **Catalyseur / risque** : news, contexte sectoriel, point de vigilance.
  **Conviction** : note 1-10 + une phrase de justification."""


# ─── Helpers de formatage des candidats ────────────────────────────────────

def _pct(opp: Opportunity, back: int) -> str:
    bars = opp.recent_bars
    if not bars or len(bars) <= back:
        return "—"
    last, past = bars[-1].close, bars[-(back + 1)].close
    return f"{(last - past) / past * 100:+.1f}%" if past else "—"


def _key_inds(opp: Opportunity, max_items: int = 4) -> str:
    interesting = ("rsi", "hist", "prev_hist", "volume_ratio",
                   "ma5_minus_ma20", "width_percentile",
                   "excess_return_5d", "underperf_5d", "ret_5d")
    out: list[str] = []
    for _name, _score, meta in opp.signal_details:
        for k, v in meta.items():
            if k in interesting and isinstance(v, (int, float)):
                out.append(f"{k}={v:.2f}")
                if len(out) >= max_items:
                    return ", ".join(out)
    return ", ".join(out) if out else "—"


def _fmt_basic(rank: int, opp: Opportunity) -> str:
    """Ligne ultra-compacte, rounds 1-2 (200→100→50)."""
    tp = opp.trade_plan
    sect = (opp.meta.sector[:10] if opp.meta and opp.meta.sector else "—")
    return (
        f"{rank:03d}. {opp.ticker:<7} [{sect:<10}] "
        f"{tp.direction.upper():<5} sc={opp.score:5.1f} "
        f"R/R={tp.risk_reward:4.2f} "
        f"5j={_pct(opp,5):<7} 20j={_pct(opp,20):<7} 60j={_pct(opp,60):<7} "
        f"ind: {_key_inds(opp, 3)}"
    )


def _fmt_extended(rank: int, opp: Opportunity) -> str:
    """Rounds 3-4 (50→25→12), ajoute valorisation/fondamentaux compacts."""
    tp = opp.trade_plan
    name = (opp.name or "")[:18]
    sect = (opp.meta.sector[:14] if opp.meta and opp.meta.sector else "—")
    val_bits: list[str] = []
    if opp.meta:
        m = opp.meta
        if m.trailing_pe is not None:
            val_bits.append(f"PE={m.trailing_pe:.1f}")
        if m.peg_ratio is not None:
            val_bits.append(f"PEG={m.peg_ratio:.2f}")
        if m.return_on_equity is not None:
            val_bits.append(f"ROE={m.return_on_equity * 100:.1f}%")
        if m.revenue_growth is not None:
            val_bits.append(f"ΔCA={m.revenue_growth * 100:+.1f}%")
        if m.profit_margin is not None:
            val_bits.append(f"netmrg={m.profit_margin * 100:+.1f}%")
        if m.debt_to_equity is not None:
            val_bits.append(f"D/E={m.debt_to_equity:.2f}")
    val = " ".join(val_bits[:5]) if val_bits else "—"
    return (
        f"{rank:03d}. {opp.ticker:<7} {name:<18} [{sect:<14}] "
        f"{tp.direction.upper():<5} sc={opp.score:5.1f} R/R={tp.risk_reward:4.2f} | "
        f"plan entry={tp.entry:.2f} TP={tp.target:.2f} SL={tp.stop:.2f} | "
        f"perfs 5/20/60/252j={_pct(opp,5)}/{_pct(opp,20)}/{_pct(opp,60)}/{_pct(opp,252)} | "
        f"ind: {_key_inds(opp, 4)} | val: {val}"
    )


def _fmt_deep(rank: int, opp: Opportunity) -> str:
    """Rounds 5-6 : bloc multi-lignes par candidat avec tout ce qu'on a."""
    tp = opp.trade_plan
    m = opp.meta
    lines = [f"### #{rank} — {opp.ticker} · {opp.name or '?'}"]
    if m:
        lines.append(
            f"  Secteur : {m.sector or '—'} · Industrie : {m.industry or '—'} "
            f"· Devise : {m.currency or '?'}"
        )
    score_line = f"  Direction : {tp.direction.upper()} · Score : {opp.score:.1f}/100"
    if opp.blended and opp.technical_score is not None and opp.fundamental_score is not None:
        score_line += (f" (tech {opp.technical_score:.1f} + "
                       f"fonda {opp.fundamental_score:.1f})")
    lines.append(score_line)
    lines.append(
        f"  Plan : entry={tp.entry:.2f} · TP={tp.target:.2f} · SL={tp.stop:.2f} "
        f"· R/R={tp.risk_reward:.2f}"
    )
    lines.append(
        f"  Perfs : 1j={_pct(opp,1)} · 5j={_pct(opp,5)} · 20j={_pct(opp,20)} "
        f"· 60j={_pct(opp,60)} · 1an={_pct(opp,252)}"
    )
    lines.append(f"  Indicateurs : {_key_inds(opp, 6)}")
    if m:
        v_bits: list[str] = []
        if m.market_cap:
            v_bits.append(f"mkt_cap={m.market_cap / 1e9:.1f}G")
        if m.trailing_pe is not None:
            v_bits.append(f"PE={m.trailing_pe:.1f}")
        if m.forward_pe is not None:
            v_bits.append(f"fwd_PE={m.forward_pe:.1f}")
        if m.peg_ratio is not None:
            v_bits.append(f"PEG={m.peg_ratio:.2f}")
        if m.price_to_book is not None:
            v_bits.append(f"P/B={m.price_to_book:.2f}")
        if m.ev_to_ebitda is not None:
            v_bits.append(f"VE/EBITDA={m.ev_to_ebitda:.1f}")
        if v_bits:
            lines.append("  Valorisation : " + " · ".join(v_bits))
        r_bits: list[str] = []
        if m.gross_margin is not None:
            r_bits.append(f"mrg brute={m.gross_margin * 100:.1f}%")
        if m.operating_margin is not None:
            r_bits.append(f"op={m.operating_margin * 100:.1f}%")
        if m.profit_margin is not None:
            r_bits.append(f"nette={m.profit_margin * 100:.1f}%")
        if m.return_on_equity is not None:
            r_bits.append(f"ROE={m.return_on_equity * 100:.1f}%")
        if m.return_on_assets is not None:
            r_bits.append(f"ROA={m.return_on_assets * 100:.1f}%")
        if r_bits:
            lines.append("  Rentabilité : " + " · ".join(r_bits))
        g_bits: list[str] = []
        if m.revenue_growth is not None:
            g_bits.append(f"ΔCA YoY={m.revenue_growth * 100:+.1f}%")
        if m.earnings_growth is not None:
            g_bits.append(f"ΔBNPA YoY={m.earnings_growth * 100:+.1f}%")
        if m.debt_to_equity is not None:
            g_bits.append(f"D/E={m.debt_to_equity:.2f}")
        if m.current_ratio is not None:
            g_bits.append(f"liq gén={m.current_ratio:.2f}")
        if g_bits:
            lines.append("  Croissance / solvabilité : " + " · ".join(g_bits))
        if m.recommendation or m.target_mean_price:
            lines.append(
                f"  Analystes : reco={m.recommendation or '—'} · "
                f"objectif moyen={m.target_mean_price or '—'} "
                f"({m.number_analysts or '—'} analystes)"
            )
    if opp.news:
        lines.append("  News récentes :")
        for n in opp.news[:3]:
            lines.append(f"    · {n.publisher} — {n.title[:100]}")
    return "\n".join(lines)


# ─── Construction des prompts par round ────────────────────────────────────

_ROUND_CRITERIA: list[str] = [
    # Round 1 : 200 → 100
    "Élimine en priorité :\n"
    "- Les R/R < 2 si le score n'est pas excellent (<70).\n"
    "- LONG sur tickers en chute lourde 20-60j (perf très négative).\n"
    "- SHORT sur tickers en forte hausse 20-60j.\n"
    "- Scores faibles à conviction quasi nulle.\n"
    "À ce stade tu n'as que du technique — sois généreux, garde tout ce qui "
    "n'a pas de drapeau rouge.",
    # Round 2 : 100 → 50
    "Garde ceux qui ont :\n"
    "- Score solide ET R/R confortable.\n"
    "- Indicateurs cohérents avec la direction (RSI, MACD hist, momentum 5j).\n"
    "- Pas de sur-extension manifeste sur perf 20-60j.\n"
    "Élimine les signaux ambigus ou contradictoires.",
    # Round 3 : 50 → 25
    "À partir de ce round, intègre les fondamentaux quand ils sont dispos :\n"
    "- LONG : préfère valorisation raisonnable (PEG < 2 si dispo, marges "
    "positives, croissance CA YoY non négative, dette maîtrisée).\n"
    "- SHORT : préfère valorisation tendue (PE élevé, ROE médiocre, "
    "croissance en décélération).\n"
    "- Conserve un ticker sans fonda UNIQUEMENT si le signal technique est "
    "exceptionnel.",
    # Round 4 : 25 → 12
    "Croise technique × fondamental. Élimine :\n"
    "- LONG sur boîtes avec marges qui s'effondrent ou dette qui explose.\n"
    "- SHORT sur boîtes ultra-solides (marges hautes, croissance forte, "
    "peu de dette).\n"
    "- Doublons sectoriels (si 5 banques se présentent, garde les 2 meilleures).",
    # Round 5 : 12 → 6
    "Présélection finale, analyse fine de chaque candidat :\n"
    "- Confluence des signaux (score, R/R, indicateurs, momentum).\n"
    "- Solidité fondamentale (marges, ROE, dette).\n"
    "- Catalyseurs dans les news récentes (positives pour LONG, négatives "
    "pour SHORT).\n"
    "- Diversification sectorielle entre les 6 retenus.",
    # Round 6 : 6 → 3 (verdict)
    "ROUND FINAL. Tu dois choisir les 3 opportunités à plus forte conviction.\n"
    "Avant la liste finale, donne pour CHAQUE finaliste une analyse "
    "structurée (Thèse, Technique, Fondamental, Catalyseur/risque, "
    "Conviction 1-10 avec justification) — voir le format dans le system "
    "prompt.",
]

_ROUND_FMT = [_fmt_basic, _fmt_basic, _fmt_extended, _fmt_extended, _fmt_deep, _fmt_deep]


def build_round_prompt(round_index: int, target: int,
                        candidates: list[Opportunity]) -> str:
    n = len(candidates)
    _target_size, label = ROUNDS[round_index]
    fmt = _ROUND_FMT[round_index]
    criteria = _ROUND_CRITERIA[round_index]
    if fmt is _fmt_deep:
        body = "\n\n".join(fmt(i + 1, o) for i, o in enumerate(candidates))
    else:
        body = "\n".join(fmt(i + 1, o) for i, o in enumerate(candidates))
    return (
        f"# Round {round_index + 1}/6 — {label}\n\n"
        f"Tu as {n} candidats. Conserve EXACTEMENT **{target}** "
        f"pour le round suivant.\n\n"
        f"## Critères pour ce round\n{criteria}\n\n"
        f"## Candidats\n{body}\n\n"
        f"## Tâche\n"
        f"1. Explique en 3-5 lignes ta logique de coupe — sauf au round final "
        f"où tu dois donner l'analyse détaillée des 3 finalistes avant la liste.\n"
        f"2. Termine par exactement {target} tickers entre `=== SELECTED ===` "
        f"et `=== END ===`, un par ligne, sans puce ni numéro."
    )


# ─── Parsing de la sélection ───────────────────────────────────────────────

_TICKER_LINE_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")


def parse_selected(text: str, valid_tickers: set[str], target: int) -> list[str]:
    """Extrait la liste des tickers conservés entre les balises."""
    m = re.search(r"===\s*SELECTED\s*===(.*?)===\s*END\s*===",
                  text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    block = m.group(1)
    out: list[str] = []
    for line in block.splitlines():
        raw = line.strip().strip("-*•·").strip()
        raw = re.sub(r"^\d+[\.\)]\s*", "", raw)  # "1. AAPL" → "AAPL"
        if not raw:
            continue
        # Prendre le premier token uppercase
        tok = raw.split()[0].upper().strip(",.;")
        if tok in valid_tickers and tok not in out:
            out.append(tok)
        if len(out) >= target:
            break
    return out


# ─── Session ───────────────────────────────────────────────────────────────

@dataclass
class FunnelEvent:
    """Événement émis vers la UI au fil de l'entonnoir."""
    kind: Literal["round_start", "enrich", "text", "round_done", "error", "end"]
    round_index: int = 0
    text: str = ""
    selected: list[str] = field(default_factory=list)
    remaining: int = 0


class FunnelAnalysisSession:
    """Entonnoir multi-rounds. Une instance = un run complet."""

    def __init__(self, opps: list[Opportunity], provider: Provider | None,
                 scope: int = DEFAULT_SCOPE) -> None:
        self.opps = opps[:scope]
        self.provider = provider

    async def _enrich_missing(self, candidates: list[Opportunity]) -> int:
        """Charge meta+fonda pour les tickers sans meta. Best-effort."""
        if self.provider is None:
            return 0
        missing = [o for o in candidates if o.meta is None]
        if not missing:
            return 0
        sem = asyncio.Semaphore(5)

        async def _one(o: Opportunity) -> None:
            async with sem:
                try:
                    await enrich_opportunity(o, self.provider,
                                              blend_fundamentals=False)
                except Exception:
                    pass

        await asyncio.gather(*(_one(o) for o in missing))
        return len(missing)

    async def stream(self) -> AsyncIterator[FunnelEvent]:
        if not self.opps:
            yield FunnelEvent(kind="error",
                              text="Aucune opportunité à analyser.")
            yield FunnelEvent(kind="end")
            return

        options = ClaudeAgentOptions(system_prompt=SYSTEM_PROMPT_FUNNEL)
        client = ClaudeSDKClient(options=options)
        try:
            await client.__aenter__()
            current = list(self.opps)

            for i, (target, label) in enumerate(ROUNDS):
                if len(current) <= target:
                    yield FunnelEvent(
                        kind="round_start", round_index=i,
                        text=f"Round {i+1}/6 sauté ({len(current)} ≤ {target}).",
                        remaining=len(current),
                    )
                    continue

                # Enrichissement progressif à partir du round 3 (index 2)
                if i >= 2:
                    n_enriched = await self._enrich_missing(current)
                    if n_enriched:
                        yield FunnelEvent(
                            kind="enrich", round_index=i,
                            text=f"  · enrichissement de {n_enriched} "
                                 f"tickers (fondamentaux)…",
                        )

                yield FunnelEvent(
                    kind="round_start", round_index=i,
                    text=f"Round {i+1}/6 · {label} · "
                         f"{len(current)} → {target}",
                    remaining=len(current),
                )

                prompt = build_round_prompt(i, target, current)
                valid = {o.ticker for o in current}
                buffer = ""
                try:
                    await client.query(prompt)
                    async for msg in client.receive_response():
                        if type(msg).__name__ == "ResultMessage":
                            continue
                        content = getattr(msg, "content", None)
                        if content is None:
                            continue
                        if isinstance(content, str):
                            buffer += content
                            continue
                        for block in content:
                            if type(block).__name__ == "TextBlock":
                                t = getattr(block, "text", "")
                                if t:
                                    buffer += t
                except Exception as e:
                    yield FunnelEvent(kind="error",
                                      text=f"Erreur round {i+1} : {e}")
                    yield FunnelEvent(kind="end")
                    return

                # On masque la liste brute dans l'affichage (on ne garde que
                # le commentaire / analyse). round_done réaffichera la liste
                # proprement.
                display = re.sub(
                    r"===\s*SELECTED\s*===.*?===\s*END\s*===",
                    "", buffer, flags=re.DOTALL | re.IGNORECASE,
                ).strip()
                if display:
                    yield FunnelEvent(kind="text", round_index=i, text=display)

                selected = parse_selected(buffer, valid, target)
                if not selected:
                    yield FunnelEvent(
                        kind="error",
                        text=f"Round {i+1} : balise SELECTED illisible — "
                             f"fallback sur les {target} meilleurs par score.",
                    )
                    selected = [o.ticker for o in current[:target]]

                selected_set = set(selected)
                current = [o for o in current if o.ticker in selected_set]
                yield FunnelEvent(
                    kind="round_done", round_index=i,
                    selected=[o.ticker for o in current],
                    remaining=len(current),
                )
        finally:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
        yield FunnelEvent(kind="end")
