"""Entonnoir d'analyse IA multi-rounds : ~1500 → 750 → 375 → 188 → 94 → 47 → 23 → 10.

À chaque round, Claude reçoit la liste courante des candidats avec un niveau
de détail croissant, élimine la moitié, et passe au round suivant. Au round
final (verdict), il produit une analyse détaillée des 10 finalistes.

PARALLÉLISME — Les premiers rounds (gros volumes) sont parallélisés par
chunks : la liste est découpée en morceaux de ~150 candidats, et un
subprocess `claude` est lancé pour chaque chunk via `ClaudeSDKClient`.
Jusqu'à `MAX_PARALLEL_CLAUDE` subprocess tournent en concurrence (limité
par sémaphore pour ne pas saturer la machine sur macOS). Les rounds tardifs
(<= 188 candidats) tournent en un seul appel séquentiel.

Parsing : Claude doit terminer chaque réponse par un bloc strict

    === SELECTED ===
    TICKER1
    TICKER2
    ...
    === END ===

qu'on extrait par regex. Si le parse échoue, fallback sur les N premiers
candidats par score (l'entonnoir ne se bloque jamais).
"""
from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from market_pulse.data.providers.base import Provider
from market_pulse.engine.scanner import Opportunity, enrich_opportunity


# Limite concurrente de subprocess `claude` simultanés. 5 = bon compromis
# sur macOS (chaque subprocess prend ~100-200 MB de RAM + 1 connexion API).
MAX_PARALLEL_CLAUDE = 5

# À partir de quel round (0-indexed) on enrichit les fondamentaux des
# candidats sans meta — round 4 (index 3) correspond au passage en format
# "extended" qui exploite valuation/marges/croissance.
ENRICH_FROM_ROUND = 3

# Concurrence yfinance pour l'enrichissement progressif (separate from the
# scan-time concurrency configured in __main__.py).
ENRICH_CONCURRENCY = 8


@dataclass
class RoundConfig:
    target: int
    label: str
    fmt: Literal["basic", "extended", "deep"]
    # Si fixé, le round est parallélisé par chunks de cette taille.
    # Sinon, un seul appel Claude sur tous les candidats.
    chunk_size: int | None = None


# 7 rounds : 1500 → 750 → 375 → 188 → 94 → 47 → 23 → 10.
# Chaque round halve approximativement la liste. Les 3 premiers tournent
# en parallèle par chunks ; les 4 derniers en single-call séquentiel.
ROUNDS: list[RoundConfig] = [
    RoundConfig(target=750, label="présélection massive",       fmt="basic",    chunk_size=150),
    RoundConfig(target=375, label="tri rapide",                  fmt="basic",    chunk_size=150),
    RoundConfig(target=188, label="filtrage technique",          fmt="basic",    chunk_size=140),
    RoundConfig(target=94,  label="consolidation technique",     fmt="extended"),
    RoundConfig(target=47,  label="validation fondamentale",     fmt="extended"),
    RoundConfig(target=23,  label="examen approfondi",           fmt="deep"),
    RoundConfig(target=10,  label="verdict — top 10",            fmt="deep"),
]


SYSTEM_PROMPT_FUNNEL = """Tu es un analyste financier sénior pilotant un \
processus d'entonnoir d'analyse multi-rounds. On part d'environ 1500 \
opportunités techniques de swing-trading et on réduit progressivement la \
liste jusqu'à un top 10 sur lequel tu dois avoir une forte conviction.

Les premiers rounds (gros volumes) sont parallélisés : on te donne un \
sous-ensemble (chunk) des candidats et tu sélectionnes une proportion. \
Les rounds tardifs te donnent l'ensemble survivant en un seul appel. À \
chaque appel le prompt te dit combien de candidats tu as et combien tu \
dois conserver — sois précis sur ce nombre.

FORMAT DE RÉPONSE OBLIGATOIRE
1. Une explication courte (3-5 lignes) de tes critères de coupe avec \
tickers et chiffres. Pour le round VERDICT (top 10 final), donne en plus \
une analyse détaillée des 10 finalistes (voir ci-dessous).
2. Termine TOUJOURS par un bloc strictement formaté :

=== SELECTED ===
TICKER1
TICKER2
...
=== END ===

RÈGLES STRICTES
- Nombre de tickers entre les balises = exactement la cible demandée.
- Un ticker par ligne, sans puce, sans numéro, sans commentaire.
- N'invente pas de tickers — uniquement ceux de la liste fournie.

ROUND FINAL (verdict top 10)
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
    """Ligne ultra-compacte, rounds 1-3 (parallèle)."""
    tp = opp.trade_plan
    sect = (opp.meta.sector[:10] if opp.meta and opp.meta.sector else "—")
    return (
        f"{rank:04d}. {opp.ticker:<7} [{sect:<10}] "
        f"{tp.direction.upper():<5} sc={opp.score:5.1f} "
        f"R/R={tp.risk_reward:4.2f} "
        f"5j={_pct(opp,5):<7} 20j={_pct(opp,20):<7} 60j={_pct(opp,60):<7} "
        f"ind: {_key_inds(opp, 3)}"
    )


def _fmt_extended(rank: int, opp: Opportunity) -> str:
    """Rounds 4-5, ajoute valorisation/fondamentaux compacts."""
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
    """Rounds 6-7 : bloc multi-lignes avec tout ce qu'on a."""
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


_FMT_FUNCS = {"basic": _fmt_basic, "extended": _fmt_extended, "deep": _fmt_deep}


# ─── Critères par round ────────────────────────────────────────────────────

_ROUND_CRITERIA: list[str] = [
    # Round 1 : présélection massive (1500 → 750)
    "Élimine la moitié la plus faible :\n"
    "- R/R sous 2 quand le score est moyen (<70).\n"
    "- LONG sur tickers en chute lourde 20-60j (perf très négative).\n"
    "- SHORT sur tickers en forte hausse 20-60j.\n"
    "- Scores faibles à conviction quasi nulle.\n"
    "Sois généreux : à ce stade tu n'as que du technique, garde tout ce qui "
    "n'a pas de drapeau rouge évident.",
    # Round 2 : tri rapide (750 → 375)
    "Coupe encore de moitié :\n"
    "- Garde les meilleurs scores avec R/R confortable.\n"
    "- Élimine les momentum incohérents avec la direction du signal.\n"
    "- Privilégie la cohérence des indicateurs (RSI, MACD hist, momentum 5j).",
    # Round 3 : filtrage technique (375 → 188)
    "Filtrage fin sur la cohérence des signaux :\n"
    "- Garde ceux où score, R/R et indicateurs racontent la même histoire.\n"
    "- Élimine les sur-extensions manifestes (perf 60j extrême dans le sens "
    "du signal — risque de retournement).\n"
    "- Élimine les signaux ambigus ou contradictoires.",
    # Round 4 : consolidation technique (188 → 94)
    "Garde les 94 meilleurs candidats techniques :\n"
    "- Plus haut score + R/R confortable + perfs cohérentes.\n"
    "- Si les fondamentaux sont chargés, ils confortent ou nuancent le signal "
    "technique — sers-toi en pour départager les cas serrés.\n"
    "- Élimine les R/R serrés sans excellence technique compensatrice.",
    # Round 5 : validation fondamentale (94 → 47)
    "Intègre pleinement les fondamentaux :\n"
    "- LONG : préfère valorisation raisonnable (PEG < 2 si dispo, marges "
    "positives, croissance CA YoY non négative, dette maîtrisée).\n"
    "- SHORT : préfère valorisation tendue (PE élevé, ROE médiocre, "
    "croissance en décélération).\n"
    "- Conserve un ticker sans fondamentaux UNIQUEMENT si le signal technique "
    "est exceptionnel.",
    # Round 6 : examen approfondi (47 → 23)
    "Examen approfondi de chaque candidat :\n"
    "- Confluence technique × fondamental (élimine les LONG sur boîtes en "
    "détresse, les SHORT sur boîtes ultra-solides).\n"
    "- Doublons sectoriels (si 5 banques se présentent, garde les 2 meilleures).\n"
    "- Catalyseurs dans les news récentes (positives pour LONG, négatives "
    "pour SHORT) si disponibles.",
    # Round 7 : verdict — top 10 (23 → 10)
    "ROUND FINAL — VERDICT TOP 10.\n"
    "Tu dois choisir les 10 opportunités avec la plus forte conviction.\n"
    "Avant la liste finale, donne pour CHAQUE finaliste une analyse "
    "structurée (Thèse, Technique, Fondamental, Catalyseur/risque, "
    "Conviction 1-10 avec justification) — voir le format dans le system prompt.\n"
    "Vise une diversification sectorielle raisonnable et un mix LONG/SHORT "
    "cohérent avec ce que tu as observé dans la sélection.",
]


def build_round_prompt(round_idx: int, target: int,
                        candidates: list[Opportunity],
                        chunk_info: tuple[int, int] | None = None) -> str:
    """Construit le prompt envoyé à Claude pour un round.

    Si `chunk_info=(idx, total)` est fourni, le prompt mentionne qu'il s'agit
    d'un chunk parmi N (mode parallèle). Sinon mode séquentiel.
    """
    cfg = ROUNDS[round_idx]
    n = len(candidates)
    fmt = _FMT_FUNCS[cfg.fmt]
    criteria = _ROUND_CRITERIA[round_idx]

    if cfg.fmt == "deep":
        body = "\n\n".join(fmt(i + 1, o) for i, o in enumerate(candidates))
    else:
        body = "\n".join(fmt(i + 1, o) for i, o in enumerate(candidates))

    chunk_label = ""
    if chunk_info is not None:
        idx, total = chunk_info
        chunk_label = f" · chunk {idx + 1}/{total} (parallèle)"

    return (
        f"# Round {round_idx + 1}/{len(ROUNDS)} — {cfg.label}{chunk_label}\n\n"
        f"Tu as {n} candidats. Conserve EXACTEMENT **{target}** pour la suite.\n\n"
        f"## Critères pour ce round\n{criteria}\n\n"
        f"## Candidats\n{body}\n\n"
        f"## Tâche\n"
        f"1. Explique en 3-5 lignes ta logique de coupe — sauf au round verdict "
        f"où tu dois donner l'analyse détaillée des 10 finalistes.\n"
        f"2. Termine par exactement {target} tickers entre `=== SELECTED ===` "
        f"et `=== END ===`, un par ligne, sans puce ni numéro."
    )


# ─── Parsing de la sélection ───────────────────────────────────────────────

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
    kind: Literal[
        "info",           # message d'information (démarrage, fin de phase)
        "round_start",    # début d'un round
        "enrich",         # enrichissement yfinance en cours
        "chunk_start",    # un chunk parallèle vient de démarrer
        "chunk_done",     # un chunk parallèle vient de finir
        "text",           # texte/commentaire de Claude (rounds séquentiels)
        "round_done",     # fin d'un round, candidats retenus
        "error",
        "end",
    ]
    round_index: int = 0
    text: str = ""
    selected: list[str] = field(default_factory=list)
    remaining: int = 0


class FunnelAnalysisSession:
    """Entonnoir multi-rounds. Une instance = un run complet."""

    def __init__(self, opps: list[Opportunity], provider: Provider | None,
                 scope: int | None = None) -> None:
        self.opps = list(opps) if scope is None else opps[:scope]
        self.provider = provider

    # ── Claude calls ──────────────────────────────────────────────────────

    @staticmethod
    async def _one_claude_call(prompt: str) -> str:
        """Un appel Claude indépendant (subprocess `claude` dédié).

        Chaque appel utilise sa propre `ClaudeSDKClient` → son propre
        subprocess. C'est ce qui permet le parallélisme entre chunks.
        """
        options = ClaudeAgentOptions(system_prompt=SYSTEM_PROMPT_FUNNEL)
        client = ClaudeSDKClient(options=options)
        buffer = ""
        try:
            await client.__aenter__()
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
        finally:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
        return buffer

    # ── Enrichissement yfinance ───────────────────────────────────────────

    async def _enrich_missing(self, candidates: list[Opportunity]) -> int:
        """Charge meta+fonda pour les tickers sans meta. Best-effort."""
        if self.provider is None:
            return 0
        missing = [o for o in candidates if o.meta is None]
        if not missing:
            return 0
        sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

        async def _one(o: Opportunity) -> None:
            async with sem:
                try:
                    await enrich_opportunity(o, self.provider,
                                              blend_fundamentals=False)
                except Exception:
                    pass

        await asyncio.gather(*(_one(o) for o in missing))
        return len(missing)

    # ── Rounds parallèles (chunks) ────────────────────────────────────────

    async def _run_round_parallel(
        self,
        round_idx: int,
        candidates: list[Opportunity],
        queue: "asyncio.Queue[FunnelEvent | None]",
    ) -> list[Opportunity]:
        """Découpe les candidats en chunks, lance N subprocess Claude en
        parallèle (limités par sémaphore), agrège les résultats."""
        cfg = ROUNDS[round_idx]
        assert cfg.chunk_size is not None
        chunks = [
            candidates[i:i + cfg.chunk_size]
            for i in range(0, len(candidates), cfg.chunk_size)
        ]
        num_chunks = len(chunks)
        per_chunk = math.ceil(cfg.target / num_chunks)

        await queue.put(FunnelEvent(
            kind="info", round_index=round_idx,
            text=f"  ⇉ {num_chunks} chunks × {per_chunk} retenus "
                 f"= ~{num_chunks * per_chunk} (cible {cfg.target}, "
                 f"max {MAX_PARALLEL_CLAUDE} en parallèle)",
        ))

        sem = asyncio.Semaphore(MAX_PARALLEL_CLAUDE)

        async def chunk_task(idx: int, chunk: list[Opportunity]) -> list[str]:
            async with sem:
                await queue.put(FunnelEvent(
                    kind="chunk_start", round_index=round_idx,
                    text=f"  ▷ chunk {idx + 1}/{num_chunks} "
                         f"démarré ({len(chunk)} → {per_chunk})",
                ))
                try:
                    prompt = build_round_prompt(
                        round_idx, per_chunk, chunk,
                        chunk_info=(idx, num_chunks),
                    )
                    text = await self._one_claude_call(prompt)
                    valid = {o.ticker for o in chunk}
                    sel = parse_selected(text, valid, per_chunk)
                    if not sel:
                        sel = [o.ticker for o in chunk[:per_chunk]]
                        await queue.put(FunnelEvent(
                            kind="error", round_index=round_idx,
                            text=f"  chunk {idx + 1} : SELECTED illisible — "
                                 f"fallback sur top-{per_chunk} par score",
                        ))
                    await queue.put(FunnelEvent(
                        kind="chunk_done", round_index=round_idx,
                        text=f"  ✓ chunk {idx + 1}/{num_chunks} : "
                             f"{len(sel)} retenus",
                    ))
                    return sel
                except Exception as e:
                    await queue.put(FunnelEvent(
                        kind="error", round_index=round_idx,
                        text=f"  chunk {idx + 1} : {e}",
                    ))
                    return [o.ticker for o in chunk[:per_chunk]]

        results = await asyncio.gather(
            *(chunk_task(i, c) for i, c in enumerate(chunks))
        )
        await queue.put(None)  # sentinel

        selected_set: set[str] = set()
        for r in results:
            selected_set.update(r)
        kept = [o for o in candidates if o.ticker in selected_set]
        # Si l'arrondi a fait dépasser la cible, on coupe (score décroissant)
        if len(kept) > cfg.target:
            kept = kept[:cfg.target]
        return kept

    # ── Rounds séquentiels (un seul appel) ────────────────────────────────

    async def _run_round_sequential(
        self, round_idx: int, candidates: list[Opportunity],
    ) -> tuple[str, list[Opportunity]]:
        cfg = ROUNDS[round_idx]
        prompt = build_round_prompt(round_idx, cfg.target, candidates)
        text = await self._one_claude_call(prompt)
        valid = {o.ticker for o in candidates}
        sel = parse_selected(text, valid, cfg.target)
        if not sel:
            sel = [o.ticker for o in candidates[:cfg.target]]
        sel_set = set(sel)
        kept = [o for o in candidates if o.ticker in sel_set]
        display = re.sub(
            r"===\s*SELECTED\s*===.*?===\s*END\s*===",
            "", text, flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        return display, kept

    # ── Stream principal ──────────────────────────────────────────────────

    async def stream(self) -> AsyncIterator[FunnelEvent]:
        if not self.opps:
            yield FunnelEvent(kind="error",
                              text="Aucune opportunité à analyser.")
            yield FunnelEvent(kind="end")
            return

        candidates = list(self.opps)
        yield FunnelEvent(
            kind="info",
            text=f"Entonnoir démarré sur {len(candidates)} candidats — "
                 f"objectif : top 10 en {len(ROUNDS)} rounds.",
        )

        for i, cfg in enumerate(ROUNDS):
            if len(candidates) <= cfg.target:
                yield FunnelEvent(
                    kind="round_start", round_index=i,
                    text=f"Round {i + 1}/{len(ROUNDS)} sauté "
                         f"({len(candidates)} ≤ {cfg.target}).",
                    remaining=len(candidates),
                )
                continue

            # Enrichissement progressif
            if i >= ENRICH_FROM_ROUND:
                n_enriched = await self._enrich_missing(candidates)
                if n_enriched:
                    yield FunnelEvent(
                        kind="enrich", round_index=i,
                        text=f"  · enrichissement de {n_enriched} tickers "
                             f"(fondamentaux yfinance, concurrence "
                             f"{ENRICH_CONCURRENCY})…",
                    )

            parallel = (cfg.chunk_size is not None
                        and len(candidates) > cfg.chunk_size)
            mode = "parallèle" if parallel else "séquentiel"
            yield FunnelEvent(
                kind="round_start", round_index=i,
                text=f"Round {i + 1}/{len(ROUNDS)} · {cfg.label} · "
                     f"{len(candidates)} → {cfg.target} · mode {mode}",
                remaining=len(candidates),
            )

            try:
                if parallel:
                    queue: asyncio.Queue[FunnelEvent | None] = asyncio.Queue()
                    task = asyncio.create_task(
                        self._run_round_parallel(i, candidates, queue)
                    )
                    while True:
                        ev = await queue.get()
                        if ev is None:
                            break
                        yield ev
                    candidates = await task
                else:
                    commentary, candidates = await self._run_round_sequential(
                        i, candidates
                    )
                    if commentary:
                        yield FunnelEvent(kind="text", round_index=i,
                                           text=commentary)
            except Exception as e:
                yield FunnelEvent(kind="error",
                                   text=f"Erreur round {i + 1} : {e}")
                yield FunnelEvent(kind="end")
                return

            yield FunnelEvent(
                kind="round_done", round_index=i,
                selected=[o.ticker for o in candidates],
                remaining=len(candidates),
            )

        yield FunnelEvent(kind="end")
