"""Analyse IA globale du top N : Claude commente la sélection du scanner.

Contrairement au chat par-ticker (cf. `chat/client.py`), cette session est
one-shot et sans tools : on construit un gros payload texte avec un résumé
de chaque opportunité (ticker, secteur, plan de trade, perfs, indicateurs)
et on demande à Claude une analyse structurée. Pas de MCP — l'analyse repose
uniquement sur les chiffres injectés dans le prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from market_pulse.engine.scanner import Opportunity


SYSTEM_PROMPT_GLOBAL = """Tu es un analyste financier sénior intégré dans Market Pulse, \
un scanner de swing-trading. Tu reçois la liste des meilleures opportunités \
techniques détectées et tu donnes ton avis critique en français.

CONTEXTE
- Les opportunités sont triées par score décroissant. Le score (0-100) agrège \
plusieurs signaux techniques (RSI, MACD, Bollinger, momentum 5j, volume).
- Pour chaque opportunité tu as : ticker, nom, secteur si chargé, direction \
(LONG / SHORT), score, plan de trade (entry, take-profit, stop-loss, R/R), \
performances multi-horizons et quelques indicateurs clés.
- Tu n'as PAS internet, pas d'accès aux fondamentaux, pas d'accès aux peers. \
Raisonne uniquement sur les chiffres fournis.

STYLE
- Direct, factuel, sans flatterie. Cite toujours les tickers et les chiffres.
- Pas de disclaimer répétitif : le trader sait que c'est de la pédagogie.
- Structure ta réponse en sections claires avec titres en markdown."""


def _pct_change(opp: Opportunity, back_days: int) -> str:
    bars = opp.recent_bars
    if not bars or len(bars) <= back_days:
        return "—"
    last = bars[-1].close
    past = bars[-(back_days + 1)].close
    if past == 0:
        return "—"
    return f"{(last - past) / past * 100:+.1f}%"


def _key_indicators(opp: Opportunity, max_items: int = 4) -> str:
    """Extrait quelques indicateurs des metadata des signaux."""
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


def _fmt_opp_line(rank: int, opp: Opportunity) -> str:
    tp = opp.trade_plan
    sector = "—"
    if opp.meta and opp.meta.sector:
        sector = opp.meta.sector[:14]
    name = (opp.name or "")[:22]
    return (
        f"{rank:02d}. {opp.ticker:<8} {name:<22} "
        f"[{sector:<14}] {tp.direction.upper():<5} "
        f"score={opp.score:5.1f} "
        f"entry={tp.entry:7.2f} TP={tp.target:7.2f} SL={tp.stop:7.2f} "
        f"R/R={tp.risk_reward:4.2f} | "
        f"perfs 1j={_pct_change(opp, 1)} 5j={_pct_change(opp, 5)} "
        f"20j={_pct_change(opp, 20)} 60j={_pct_change(opp, 60)} "
        f"1y={_pct_change(opp, 252)} | "
        f"ind: {_key_indicators(opp)}"
    )


def build_user_prompt(opps: list[Opportunity]) -> str:
    n_long = sum(1 for o in opps if o.trade_plan.direction == "long")
    n_short = len(opps) - n_long
    header = (
        f"Voici les {len(opps)} meilleures opportunités du scanner "
        f"(horizon 1 semaine, {n_long} LONG · {n_short} SHORT, "
        f"triées par score décroissant).\n\n"
        f"Format de chaque ligne :\n"
        f"  rang. TICKER NOM [SECTEUR] DIR score=X entry=… TP=… SL=… R/R=… | "
        f"perfs 1j/5j/20j/60j/1y | ind: indicateurs clés\n\n"
        f"--- LISTE ---\n"
    )
    body = "\n".join(_fmt_opp_line(i + 1, o) for i, o in enumerate(opps))
    questions = """

--- ANALYSE DEMANDÉE ---

Structure ta réponse en quatre sections markdown :

## 1. Top 5 selon toi
Parmi cette liste, choisis 5 opportunités avec la plus forte conviction. Pour \
chacune : pourquoi (score, R/R, indicateurs cohérents, momentum) en une ou \
deux phrases. Cite les chiffres.

## 2. À éviter
Trois à cinq opportunités qui te semblent douteuses : R/R trop serré, \
sur-extension après une forte hausse, indicateurs contradictoires, etc. \
Donne la raison précise pour chaque.

## 3. Patterns d'ensemble
Secteurs surreprésentés, biais directionnel (LONG vs SHORT), ce que la \
distribution suggère sur l'environnement de marché probable.

## 4. Vigilance globale
Pièges potentiels sur l'ensemble de la sélection : overcrowding sectoriel, \
R/R moyen faible, dispersion des scores, signaux qui peuvent tous échouer \
ensemble si un thème commun se retourne.
"""
    return header + body + questions


@dataclass
class GlobalAnalysisEvent:
    """Événement émis vers la UI."""
    kind: Literal["text", "error", "end"]
    text: str = ""


class GlobalAnalysisSession:
    """Session one-shot : envoie un prompt avec le top N et stream la réponse."""

    def __init__(self, opps: list[Opportunity]) -> None:
        self.opps = opps

    async def stream(self) -> AsyncIterator[GlobalAnalysisEvent]:
        options = ClaudeAgentOptions(system_prompt=SYSTEM_PROMPT_GLOBAL)
        client = ClaudeSDKClient(options=options)
        try:
            await client.__aenter__()
            await client.query(build_user_prompt(self.opps))
            async for message in client.receive_response():
                if type(message).__name__ == "ResultMessage":
                    continue
                content = getattr(message, "content", None)
                if content is None:
                    continue
                if isinstance(content, str):
                    if content.strip():
                        yield GlobalAnalysisEvent(kind="text", text=content)
                    continue
                for block in content:
                    if type(block).__name__ == "TextBlock":
                        text = getattr(block, "text", "")
                        if text:
                            yield GlobalAnalysisEvent(kind="text", text=text)
        except Exception as e:
            yield GlobalAnalysisEvent(kind="error", text=f"Erreur SDK : {e}")
        finally:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
        yield GlobalAnalysisEvent(kind="end")
