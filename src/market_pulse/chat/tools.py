"""Tools custom exposés à Claude — lecture seule sur l'Opportunity en mémoire.

Les tools renvoient du texte structuré (pas du JSON), pour que Claude puisse
le lire directement et le citer. Si une donnée n'est pas chargée (typiquement
le top 20 a été enrichi mais pas l'opportunité courante), on dit explicitement
« non chargée — l'utilisateur doit appuyer sur F ».
"""
from __future__ import annotations

import math
from typing import Any

from claude_agent_sdk import tool

from market_pulse.engine.scanner import Opportunity


def _txt(text: str) -> dict[str, Any]:
    """Wrap pour la convention de retour des tools du SDK."""
    return {"content": [{"type": "text", "text": text}]}


def _fmt_pct(v: float | None) -> str:
    return f"{v * 100:+.2f}%" if v is not None else "—"


def _fmt_ratio(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "—"


def _fmt_int(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{int(round(v)):,}".replace(",", " ")


def _pct_change(opp: Opportunity, back_days: int) -> float | None:
    bars = opp.recent_bars
    if not bars or len(bars) <= back_days:
        return None
    last = bars[-1].close
    past = bars[-(back_days + 1)].close
    if past == 0:
        return None
    return (last - past) / past * 100


def _format_overview(opp: Opportunity) -> str:
    m = opp.meta
    bars = opp.recent_bars
    last = bars[-1] if bars else None
    name = (m.long_name if m else None) or opp.name or "?"
    sector = m.sector if m else "—"
    industry = m.industry if m else "—"
    currency = m.currency if m else "?"

    lines = [
        f"Ticker : {opp.ticker} ({name})",
        f"Secteur : {sector} · Industrie : {industry}",
        f"Devise : {currency}",
        f"Direction du signal : {opp.trade_plan.direction.upper()}",
        f"Horizon : {opp.horizon}",
        f"Score global : {opp.score:.1f}/100",
    ]
    if opp.blended and opp.technical_score is not None and opp.fundamental_score is not None:
        lines.append(
            f"  · technique : {opp.technical_score:.1f} · "
            f"fondamental : {opp.fundamental_score:.1f}  (mix 80/20)"
        )
    if last:
        lines.append(
            f"Dernière clôture : {last.close:.2f} {currency} ({last.date.isoformat()})"
        )
        for label, days in [("1j", 1), ("5j", 5), ("20j", 20),
                              ("60j", 60), ("252j (1 an)", 252)]:
            v = _pct_change(opp, days)
            lines.append(f"Perf {label} : {v:+.2f}%" if v is not None
                         else f"Perf {label} : —")
    if m and m.last_earnings_date:
        lines.append(f"Dernière publication : {m.last_earnings_date}")
    if m and m.next_earnings_date:
        lines.append(f"Prochaine publication estimée : {m.next_earnings_date}")
    if m is None:
        lines.append("\n[meta non chargées — appuie sur F dans la vue détail]")
    return "\n".join(lines)


def _format_signals(opp: Opportunity) -> str:
    if not opp.signal_details:
        return "Aucun signal disponible."
    lines = ["Signaux du scanner (nom · score sur 100 · métadonnées) :"]
    for name, score, metadata in opp.signal_details:
        meta_parts = []
        for k, v in metadata.items():
            if isinstance(v, float):
                meta_parts.append(f"{k}={v:.3f}")
            else:
                meta_parts.append(f"{k}={v}")
        meta_str = ", ".join(meta_parts) if meta_parts else "—"
        lines.append(f"  · {name:<32} {score:5.1f}   ({meta_str})")
    return "\n".join(lines)


def _format_trade_plan(opp: Opportunity) -> str:
    tp = opp.trade_plan
    target_pct = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0.0
    stop_pct = (tp.stop - tp.entry) / tp.entry * 100 if tp.entry else 0.0
    horizon_desc = {
        "1d": "1 jour", "1w": "5 à 10 jours de bourse",
        "1m": "3 à 6 semaines", "1y": "6 à 18 mois",
    }.get(tp.horizon, "—")
    return (
        f"Plan de trade calculé par le scanner :\n"
        f"  · Direction : {'LONG (achat)' if tp.direction == 'long' else 'SHORT (vente à découvert)'}\n"
        f"  · Horizon : {tp.horizon} ({horizon_desc})\n"
        f"  · Entrée : {tp.entry:.2f}\n"
        f"  · Objectif (TP) : {tp.target:.2f}  ({target_pct:+.2f}%)\n"
        f"  · Stop-loss (SL) : {tp.stop:.2f}  ({stop_pct:+.2f}%)\n"
        f"  · Ratio risque/gain : {tp.risk_reward:.2f}"
    )


def _format_valuation(opp: Opportunity) -> str:
    m = opp.meta
    if m is None:
        return ("Métadonnées de valorisation non chargées. "
                "L'utilisateur doit appuyer sur F dans la vue détail "
                "pour forcer le chargement depuis yfinance.")
    cur = m.currency or ""
    return (
        f"Valorisation et fondamentaux ({m.ticker}) :\n\n"
        f"VALORISATION\n"
        f"  · Capitalisation        {_fmt_int(m.market_cap)} {cur}\n"
        f"  · Valeur d'entreprise   {_fmt_int(m.enterprise_value)} {cur}\n"
        f"  · PER historique        {_fmt_ratio(m.trailing_pe)}\n"
        f"  · PER prévisionnel      {_fmt_ratio(m.forward_pe)}\n"
        f"  · PEG                   {_fmt_ratio(m.peg_ratio)}\n"
        f"  · Cours / book          {_fmt_ratio(m.price_to_book)}\n"
        f"  · Cours / sales         {_fmt_ratio(m.price_to_sales)}\n"
        f"  · VE / EBITDA           {_fmt_ratio(m.ev_to_ebitda)}\n\n"
        f"RENTABILITÉ\n"
        f"  · Marge brute           {_fmt_pct(m.gross_margin)}\n"
        f"  · Marge opérationnelle  {_fmt_pct(m.operating_margin)}\n"
        f"  · Marge nette           {_fmt_pct(m.profit_margin)}\n"
        f"  · ROE                   {_fmt_pct(m.return_on_equity)}\n"
        f"  · ROA                   {_fmt_pct(m.return_on_assets)}\n\n"
        f"CROISSANCE (YoY)\n"
        f"  · Croissance CA         {_fmt_pct(m.revenue_growth)}\n"
        f"  · Croissance résultat   {_fmt_pct(m.earnings_growth)}\n\n"
        f"BILAN\n"
        f"  · Trésorerie totale     {_fmt_int(m.total_cash)} {cur}\n"
        f"  · Dette totale          {_fmt_int(m.total_debt)} {cur}\n"
        f"  · Dette / capitaux      {_fmt_ratio(m.debt_to_equity)}\n"
        f"  · Liquidité générale    {_fmt_ratio(m.current_ratio)}\n"
        f"  · Liquidité immédiate   {_fmt_ratio(m.quick_ratio)}\n\n"
        f"DIVIDENDE & ANALYSTES\n"
        f"  · Rendement dividende   {_fmt_pct(m.dividend_yield)}\n"
        f"  · Taux de distribution  {_fmt_pct(m.payout_ratio)}\n"
        f"  · Recommandation        {m.recommendation or '—'}\n"
        f"  · Objectif moyen        {_fmt_ratio(m.target_mean_price)} ({m.number_analysts or '—'} analystes)"
    )


def _format_financial_statement(opp: Opportunity, statement: str, period: str) -> str:
    f = opp.fundamentals
    if f is None:
        return ("États financiers non chargés. L'utilisateur doit appuyer "
                "sur F dans la vue détail pour forcer le chargement.")
    statement = statement.lower().strip()
    period = period.lower().strip()

    mapping = {
        ("income", "annual"): (f.income, f.periods, "Compte de résultat · annuel"),
        ("income", "quarterly"): (f.income_q, f.periods_q, "Compte de résultat · trimestriel"),
        ("balance", "annual"): (f.balance, f.periods, "Bilan · annuel"),
        ("balance", "quarterly"): (f.balance_q, f.periods_q, "Bilan · trimestriel"),
        ("cashflow", "annual"): (f.cashflow, f.periods, "Flux de trésorerie · annuel"),
        ("cashflow", "quarterly"): (f.cashflow_q, f.periods_q, "Flux de trésorerie · trimestriel"),
    }
    key = (statement, period)
    if key not in mapping:
        return (f"Paramètres invalides : statement='{statement}' period='{period}'. "
                f"Attendu : statement ∈ {{income, balance, cashflow}}, "
                f"period ∈ {{annual, quarterly}}.")
    lines_data, periods, title = mapping[key]
    if not lines_data or not periods:
        return f"{title} : aucune donnée disponible pour ce ticker."

    cur = opp.meta.currency if opp.meta else ""
    out = [f"{title}" + (f" (en {cur})" if cur else "")]
    out.append("Périodes (récent → ancien) : " + " | ".join(periods))
    out.append("")
    for line in lines_data:
        vals = " | ".join(_fmt_int(v) for v in line.values[:len(periods)])
        out.append(f"  · {line.label:<40} {vals}")
    return "\n".join(out)


def _format_news(opp: Opportunity) -> str:
    if not opp.news:
        return ("Aucune actualité chargée pour ce ticker. "
                "Si l'utilisateur n'a pas appuyé sur F, les news ne sont pas dispos.")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = ["Actualités récentes :"]
    for item in opp.news[:8]:
        pub = item.published
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        delta = now - pub
        if delta.days >= 1:
            age = f"il y a {delta.days}j"
        elif delta.seconds >= 3600:
            age = f"il y a {delta.seconds // 3600}h"
        else:
            age = f"il y a {max(1, delta.seconds // 60)}m"
        out.append(f"  · [{age}] {item.publisher} — {item.title}")
    return "\n".join(out)


def _format_recent_prices(opp: Opportunity, n: int) -> str:
    bars = opp.recent_bars[-n:] if opp.recent_bars else []
    if not bars:
        return "Aucune barre OHLCV disponible."
    cur = opp.meta.currency if opp.meta else ""
    out = [f"{len(bars)} dernières barres quotidiennes ({cur}) :"]
    out.append(f"{'Date':<12}{'Open':>10}{'High':>10}{'Low':>10}{'Close':>10}{'Volume':>14}")
    for b in bars:
        out.append(
            f"{b.date.isoformat():<12}{b.open:>10.2f}{b.high:>10.2f}"
            f"{b.low:>10.2f}{b.close:>10.2f}{b.volume:>14}"
        )
    return "\n".join(out)


def _annualized_vol(opp: Opportunity, window: int = 20) -> float | None:
    bars = opp.recent_bars
    if not bars or len(bars) <= window:
        return None
    closes = [b.close for b in bars[-(window + 1):]]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100


def _format_volatility_stats(opp: Opportunity) -> str:
    bars = opp.recent_bars
    if not bars:
        return "Aucune donnée de prix disponible."
    hv20 = _annualized_vol(opp, window=20)
    hv60 = _annualized_vol(opp, window=60)
    tail = bars[-252:] if len(bars) >= 252 else bars
    hi = max(b.high for b in tail)
    lo = min(b.low for b in tail)
    last = bars[-1].close
    pos = (last - lo) / (hi - lo) * 100 if hi > lo else 50.0
    avg_vol = sum(b.volume for b in bars[-20:]) / max(1, min(len(bars), 20))
    return (
        f"Volatilité et plage 52 semaines :\n"
        f"  · Vol. annualisée 20j : {hv20:.1f}%" if hv20 is not None else "  · Vol. annualisée 20j : —"
    ) + "\n" + (
        f"  · Vol. annualisée 60j : {hv60:.1f}%" if hv60 is not None else "  · Vol. annualisée 60j : —"
    ) + "\n" + (
        f"  · Plage 52 semaines : {lo:.2f} → {hi:.2f}\n"
        f"  · Position dans la plage : {pos:.0f}% (0% = plus bas, 100% = plus haut)\n"
        f"  · Volume moyen 20j : {avg_vol:,.0f}".replace(",", " ")
    )


def make_tools_for_opportunity(opp: Opportunity) -> list:
    """Construit les tools liés à l'Opportunity courante via closures.

    Le décorateur `@tool` enregistre chaque fonction comme un tool MCP avec
    son schéma. Les fonctions accèdent à `opp` via la closure — elles voient
    donc toujours l'état courant de l'Opportunity (utile si l'utilisateur
    appuie sur F pendant la conversation, les tools verront les nouvelles
    données).
    """

    @tool(
        "get_overview",
        "Vue d'ensemble du ticker en cours : nom, secteur, devise, direction "
        "du signal scanner, score, dernier prix, performances 1j/5j/20j/60j/1an, "
        "dates de publications. À appeler en premier pour cadrer le contexte.",
        {},
    )
    async def get_overview(args: dict) -> dict:
        return _txt(_format_overview(opp))

    @tool(
        "get_signals",
        "Détail des signaux techniques calculés par le scanner pour ce ticker "
        "(nom du signal, score sur 100, métadonnées chiffrées comme RSI, MACD "
        "histogramme, etc.). Utile si l'utilisateur questionne la qualité du "
        "signal global.",
        {},
    )
    async def get_signals(args: dict) -> dict:
        return _txt(_format_signals(opp))

    @tool(
        "get_trade_plan",
        "Plan de trade calculé : direction (long/short), horizon, prix d'entrée, "
        "objectif (TP), stop-loss (SL), ratio risque/gain.",
        {},
    )
    async def get_trade_plan(args: dict) -> dict:
        return _txt(_format_trade_plan(opp))

    @tool(
        "get_valuation_and_ratios",
        "Ratios de valorisation, rentabilité, croissance et solidité du bilan : "
        "PER, PEG, P/B, P/S, VE/EBITDA, marges (brute/op/nette), ROE/ROA, "
        "croissance CA/résultat, dette, ratios de liquidité, dividende, "
        "recommandation analystes. Renvoie un message « non chargé » si "
        "l'utilisateur n'a pas encore appuyé sur F.",
        {},
    )
    async def get_valuation_and_ratios(args: dict) -> dict:
        return _txt(_format_valuation(opp))

    @tool(
        "get_financial_statements",
        "États financiers du ticker. Paramètres : statement ∈ {income, balance, "
        "cashflow}, period ∈ {annual, quarterly}. 'income' = compte de résultat, "
        "'balance' = bilan, 'cashflow' = flux de trésorerie. Renvoie 3 dernières "
        "années en annuel ou 4 derniers trimestres en quarterly. Renvoie un "
        "message « non chargé » si l'utilisateur n'a pas encore appuyé sur F.",
        {"statement": str, "period": str},
    )
    async def get_financial_statements(args: dict) -> dict:
        statement = str(args.get("statement", "income"))
        period = str(args.get("period", "annual"))
        return _txt(_format_financial_statement(opp, statement, period))

    @tool(
        "get_news",
        "Actualités récentes pour le ticker (titre + éditeur + ancienneté). "
        "Renvoie un message « aucune news » si l'utilisateur n'a pas encore "
        "appuyé sur F.",
        {},
    )
    async def get_news(args: dict) -> dict:
        return _txt(_format_news(opp))

    @tool(
        "get_recent_prices",
        "Renvoie les N dernières barres quotidiennes OHLCV (date, open, high, "
        "low, close, volume) du ticker. Paramètre n entre 5 et 252. Utile pour "
        "questions sur l'évolution récente, gaps, journées atypiques, etc.",
        {"n": int},
    )
    async def get_recent_prices(args: dict) -> dict:
        n = max(5, min(252, int(args.get("n", 30))))
        return _txt(_format_recent_prices(opp, n))

    @tool(
        "get_volatility_stats",
        "Volatilité annualisée 20j et 60j, plage 52 semaines (haut/bas), "
        "position du dernier prix dans la plage, volume moyen 20j.",
        {},
    )
    async def get_volatility_stats(args: dict) -> dict:
        return _txt(_format_volatility_stats(opp))

    return [
        get_overview,
        get_signals,
        get_trade_plan,
        get_valuation_and_ratios,
        get_financial_statements,
        get_news,
        get_recent_prices,
        get_volatility_stats,
    ]
