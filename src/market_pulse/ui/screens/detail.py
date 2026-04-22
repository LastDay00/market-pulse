"""Écran détail : chart candlestick + signaux + trade plan + stats."""
import math

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from market_pulse.data.models import Bar
from market_pulse.engine.scanner import Opportunity, enrich_opportunity
from market_pulse.ui.widgets.candle_chart import render_candlestick_chart

SAUGE = (127, 176, 105)
TERRA = (201, 112, 100)
AMBRE = (232, 180, 93)
SMOKE_BLUE = (107, 140, 174)
OFF_WHITE = (232, 230, 227)


def _render_candles(opp: Opportunity, width: int = 70, chart_height: int = 17) -> Text:
    """Area chart (ligne + remplissage) du close, plus lisible que des bougies en terminal.

    Largeur par défaut 70 = largeur interne du chart-panel (#chart-panel width:74
    − border 2 − padding 2). Au-delà, Textual wrappe les lignes.
    """
    bars = opp.recent_bars[-120:] if opp.recent_bars else []
    return render_candlestick_chart(
        bars=bars, trade_plan=opp.trade_plan,
        width=width, chart_height=chart_height,
    )


def _pct_change(bars: list[Bar], back_days: int) -> float | None:
    if len(bars) <= back_days:
        return None
    last = bars[-1].close
    past = bars[-(back_days + 1)].close
    if past == 0:
        return None
    return (last - past) / past * 100


def _annualized_vol(bars: list[Bar], window: int = 20) -> float | None:
    if len(bars) <= window:
        return None
    closes = [b.close for b in bars[-(window + 1):]]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100


def _range_position(bars: list[Bar], window: int = 252) -> tuple[float, float, float]:
    """Retourne (low_52w, high_52w, position%) où position = (last-low)/(high-low)."""
    tail = bars[-window:] if len(bars) >= window else bars
    highs = [b.high for b in tail]
    lows = [b.low for b in tail]
    last = bars[-1].close
    hi = max(highs)
    lo = min(lows)
    rng = hi - lo
    pos = (last - lo) / rng * 100 if rng > 0 else 50.0
    return lo, hi, pos


def _pos_bar(pos: float, width: int = 12) -> str:
    """░░░░█░░░░░ : marqueur à la position (0-100)."""
    pos = max(0.0, min(100.0, pos))
    idx = int(pos / 100 * (width - 1))
    return "".join("█" if i == idx else "░" for i in range(width))


def _fmt_pct(v: float | None) -> str:
    return f"{v:+6.2f}%" if v is not None else "   n/a"


def _fmt_num(v: float) -> str:
    return f"{v:>10.2f}"


def _format_score_bar(score: float, width: int = 6) -> str:
    blocks = "▏▎▍▌▋▊▉█"
    score = max(0.0, min(100.0, score))
    full = int(score / 100 * width)
    part = int(((score / 100 * width) - full) * len(blocks))
    out = "█" * full
    if full < width and part > 0:
        out += blocks[part - 1]
    return out.ljust(width)


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Retour", show=True),
        Binding("f", "load_data", "Charger/Rafraîchir données", show=True),
        Binding("q", "app.quit", "Quitter", show=True),
    ]

    def __init__(self, opp: Opportunity) -> None:
        super().__init__()
        self.opp = opp
        self._loading = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="detail-scroll"):
            yield Static(self._title_line(), classes="highlight-amber", id="title")
            yield Static(self._subtitle_line(), id="subtitle")
            with Horizontal(id="top-panels"):
                yield Static(_render_candles(self.opp),
                             id="chart-panel", classes="panel")
                yield Static(self._signals_text(),
                             id="signals-panel", classes="panel")
            # Trade plan en premier sous le chart
            yield Static(self._trade_plan_text(),
                         id="plan-panel", classes="panel")
            # News juste après le plan (avant les stats selon demande user)
            yield Static(self._news_text(),
                         id="news-panel", classes="panel")
            # Stats prix/volume/range
            yield Static(self._stats_text(),
                         id="stats-panel", classes="panel")
            # Fondamentaux : valorisation, rentabilité, croissance, santé bilan
            yield Static(self._valuation_text(),
                         id="valuation-panel", classes="panel")
            # États financiers
            with Horizontal(id="financials-row"):
                yield Static(self._income_text(),
                             id="income-panel", classes="panel")
                yield Static(self._balance_text(),
                             id="balance-panel", classes="panel")
                yield Static(self._cashflow_text(),
                             id="cashflow-panel", classes="panel")
        yield Footer()

    def _title_line(self) -> str:
        o = self.opp
        name = (o.meta.long_name if o.meta else None) or o.name or ""
        name_part = f"  ·  {name}" if name else ""
        direction_fr = "LONG" if o.trade_plan.direction == "long" else "SHORT"
        status = "  ·  ⏳ chargement…" if self._loading else ""
        return (f"{o.ticker}{name_part}"
                f"  ·  {direction_fr}"
                f"  ·  SCORE {o.score:.1f} / 100"
                f"  ·  horizon {o.horizon.upper()}{status}")

    def action_load_data(self) -> None:
        """Touche F : charge meta + news + fondamentaux à la demande."""
        if self._loading:
            return
        provider = getattr(self.app, "provider", None)
        if provider is None:
            self.notify("Aucun provider disponible", severity="error")
            return
        self._loading = True
        self._refresh_all_panels()  # affiche l'état "chargement…"
        self._fetch_worker()

    @work(exclusive=True)
    async def _fetch_worker(self) -> None:
        """Worker Textual : enrichit l'Opportunity puis rerend les panneaux."""
        provider = self.app.provider
        try:
            await enrich_opportunity(self.opp, provider)
        except Exception as e:
            self.notify(f"Erreur chargement : {e}", severity="error")
        finally:
            self._loading = False
            self._refresh_all_panels()

    def _refresh_all_panels(self) -> None:
        """Rerend tous les panneaux dont le contenu dépend de meta/news/fundamentals."""
        try:
            self.query_one("#title", Static).update(self._title_line())
            self.query_one("#subtitle", Static).update(self._subtitle_line())
            self.query_one("#news-panel", Static).update(self._news_text())
            self.query_one("#valuation-panel", Static).update(self._valuation_text())
            self.query_one("#income-panel", Static).update(self._income_text())
            self.query_one("#balance-panel", Static).update(self._balance_text())
            self.query_one("#cashflow-panel", Static).update(self._cashflow_text())
        except Exception:
            # Les widgets peuvent ne pas être encore montés si on appelle tôt
            pass

    def _subtitle_line(self) -> str:
        if not self.opp.meta:
            return f"{len(self.opp.recent_bars)} jours d'historique"
        m = self.opp.meta
        return (f"{m.sector}  ·  {m.industry}  ·  "
                f"{m.currency}  ·  {len(self.opp.recent_bars)} jours d'historique")

    def _signals_text(self) -> str:
        lines = ["SIGNAUX"]
        for name, score, metadata in self.opp.signal_details:
            bar = _format_score_bar(score, width=6)
            lines.append(f" · {name:<24} {score:5.1f}  {bar}")
            meta_str = _format_metadata(metadata)
            if meta_str:
                lines.append(f"     {meta_str}")
        return "\n".join(lines)

    def _stats_text(self) -> str:
        bars = self.opp.recent_bars
        if not bars:
            return "STATISTIQUES\n aucune donnée"
        last = bars[-1]
        d1 = _pct_change(bars, 1)
        d5 = _pct_change(bars, 5)
        d20 = _pct_change(bars, 20)
        d60 = _pct_change(bars, 60)
        d252 = _pct_change(bars, 252)
        hv20 = _annualized_vol(bars, window=20)
        lo52, hi52, pos52 = _range_position(bars, window=252)
        vols = [b.volume for b in bars[-20:]]
        avg_vol = sum(vols) / len(vols) if vols else 0

        lines = [
            "STATISTIQUES",
            f" · Dernière clôture     {_fmt_num(last.close)}   {last.date.isoformat()}",
            f" · Jour                 {_fmt_pct(d1)}",
            f" · Semaine (5j)         {_fmt_pct(d5)}",
            f" · Mois (20j)           {_fmt_pct(d20)}",
            f" · Trimestre (60j)      {_fmt_pct(d60)}",
            f" · Année (252j)         {_fmt_pct(d252)}",
            "",
            f" · Vol. annualisée 20j  {hv20:>9.1f}%" if hv20 is not None else " · Vol. annualisée 20j    n/a",
            f" · Volume moyen 20j     {avg_vol/1e6:>8.2f}M",
            "",
            f" · Plage 52 semaines    {_fmt_num(lo52)} → {_fmt_num(hi52)}",
            f"   {_pos_bar(pos52)}  position {pos52:.0f}%",
        ]
        return "\n".join(lines)

    def _valuation_text(self) -> str:
        m = self.opp.meta
        if not m:
            return "VALORISATION & RATIOS\n (métadonnées non chargées — ticker hors top 20)"

        def fn(v: float | None, pct: bool = False, unit: str = "") -> str:
            if v is None:
                return "     —"
            if pct:
                return f"{v * 100:>6.2f}%"
            if abs(v) >= 1e9:
                return f"{v/1e9:>6.2f}Md{unit}"
            if abs(v) >= 1e6:
                return f"{v/1e6:>6.2f}M{unit}"
            return f"{v:>6.2f}{unit}"

        reco_fr = {
            "strong_buy": "achat fort", "buy": "achat",
            "hold": "conserver", "sell": "vendre",
            "strong_sell": "vente forte", "none": "—", "": "—",
        }.get((m.recommendation or "").lower(), m.recommendation or "—")

        lines = [
            "VALORISATION & RATIOS",
            " VALORISATION                                RENTABILITÉ",
            f"  · Capitalisation         {fn(m.market_cap, unit=f' {m.currency}')}    · Marge brute          {fn(m.gross_margin, pct=True)}",
            f"  · Valeur d'entreprise    {fn(m.enterprise_value, unit=f' {m.currency}')}    · Marge opérationnelle {fn(m.operating_margin, pct=True)}",
            f"  · PER historique         {fn(m.trailing_pe)}       · Marge nette          {fn(m.profit_margin, pct=True)}",
            f"  · PER prévisionnel       {fn(m.forward_pe)}       · ROE (rentab. CP)     {fn(m.return_on_equity, pct=True)}",
            f"  · Ratio PEG              {fn(m.peg_ratio)}       · ROA (rentab. actifs) {fn(m.return_on_assets, pct=True)}",
            f"  · Cours / Valeur compt.  {fn(m.price_to_book)}",
            f"  · Cours / CA             {fn(m.price_to_sales)}     CROISSANCE (an. glissant)",
            f"  · VE / EBITDA            {fn(m.ev_to_ebitda)}       · Croissance CA        {fn(m.revenue_growth, pct=True)}",
            f"                                          · Croissance résultat  {fn(m.earnings_growth, pct=True)}",
            "",
            " SOLIDITÉ BILAN                              DIVIDENDE & ANALYSTES",
            f"  · Dette / Fonds propres  {fn(m.debt_to_equity)}       · Rendement dividende  {fn(m.dividend_yield, pct=True)}",
            f"  · Liquidité générale     {fn(m.current_ratio)}       · Taux de distribution {fn(m.payout_ratio, pct=True)}",
            f"  · Liquidité immédiate    {fn(m.quick_ratio)}       · Recommandation       {reco_fr:>10}",
            f"  · Trésorerie totale      {fn(m.total_cash, unit=f' {m.currency}')}    · Objectif analystes   {fn(m.target_mean_price)} ({m.number_analysts or '—'} an.)",
            f"  · Dette totale           {fn(m.total_debt, unit=f' {m.currency}')}",
        ]
        return "\n".join(lines)

    def _fmt_financial_value(self, v: float | None) -> str:
        if v is None:
            return "     —"
        if abs(v) >= 1e9:
            return f"{v/1e9:>8.2f}B"
        if abs(v) >= 1e6:
            return f"{v/1e6:>8.2f}M"
        if abs(v) >= 1e3:
            return f"{v/1e3:>8.2f}K"
        return f"{v:>9.2f}"

    # Libellés yfinance (anglais) → français, pour affichage uniquement
    FR_LABELS = {
        # Compte de résultat
        "Total Revenue":                  "Chiffre d'affaires",
        "Cost Of Revenue":                "Coût des ventes",
        "Gross Profit":                   "Marge brute",
        "Operating Income":               "Résultat opérationnel",
        "EBIT":                           "EBIT",
        "EBITDA":                         "EBITDA",
        "Net Income":                     "Résultat net",
        "Net Income Common Stockholders": "Résultat net (actionnaires)",
        "Diluted EPS":                    "BPA dilué",
        "Basic EPS":                      "BPA de base",
        # Bilan
        "Total Assets":                                  "Total actifs",
        "Total Liabilities Net Minority Interest":       "Total passifs",
        "Total Equity Gross Minority Interest":          "Capitaux propres",
        "Stockholders Equity":                           "Capitaux propres (actionnaires)",
        "Total Debt":                                    "Dette totale",
        "Long Term Debt":                                "Dette long terme",
        "Current Debt":                                  "Dette court terme",
        "Cash And Cash Equivalents":                     "Trésorerie",
        "Cash Cash Equivalents And Short Term Investments": "Trésorerie + placements",
        "Working Capital":                               "Fonds de roulement",
        # Cash flow
        "Operating Cash Flow":        "Flux opérationnels",
        "Investing Cash Flow":        "Flux d'investissement",
        "Financing Cash Flow":        "Flux de financement",
        "Free Cash Flow":             "Flux trésorerie libre (FCF)",
        "Capital Expenditure":        "Investissements (CAPEX)",
        "Cash Dividends Paid":        "Dividendes versés",
        "Repurchase Of Capital Stock": "Rachats d'actions",
    }

    def _translate_label(self, label: str) -> str:
        return self.FR_LABELS.get(label, label)

    def _render_financial_block(self, title: str, lines) -> str:
        f = self.opp.fundamentals
        if not f or not lines:
            return f"{title}\n (aucune donnée — ticker hors top 20 ou données indisponibles)"
        periods = f.periods[:3] if f.periods else []
        header = f"{title}\n  " + " " * 30 + "  ".join(f"{p:>9}" for p in periods)
        out = [header]
        for line in lines:
            vals = line.values[:3]
            val_str = "  ".join(self._fmt_financial_value(v) for v in vals)
            label_fr = self._translate_label(line.label)
            out.append(f"  · {label_fr:<30} {val_str}")
        return "\n".join(out)

    def _income_text(self) -> str:
        f = self.opp.fundamentals
        return self._render_financial_block("COMPTE DE RÉSULTAT",
                                             f.income if f else [])

    def _balance_text(self) -> str:
        f = self.opp.fundamentals
        return self._render_financial_block("BILAN",
                                             f.balance if f else [])

    def _cashflow_text(self) -> str:
        f = self.opp.fundamentals
        return self._render_financial_block("FLUX DE TRÉSORERIE",
                                             f.cashflow if f else [])

    def _news_text(self) -> str:
        lines = ["ACTUALITÉS RÉCENTES"]
        if not self.opp.news:
            lines.append(" · aucune actualité récente (ticker hors top 20 ou pas de news)")
            return "\n".join(lines)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        for item in self.opp.news[:5]:
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
            title = item.title[:140]
            publisher = (item.publisher or "?")[:20]
            lines.append(f" · [{age:>11}] {publisher:<20} · {title}")
        return "\n".join(lines)

    def _trade_plan_text(self) -> str:
        tp = self.opp.trade_plan
        target_pct = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
        stop_pct = (tp.stop - tp.entry) / tp.entry * 100 if tp.entry else 0
        horizon_desc = {
            "1d": "1 jour", "1w": "5 à 10 jours de bourse",
            "1m": "3 à 6 semaines", "1y": "6 à 18 mois",
        }.get(tp.horizon, "—")
        direction_fr = "ACHAT (long)" if tp.direction == "long" else "VENTE À DÉCOUVERT (short)"
        action = "ACHETER" if tp.direction == "long" else "VENDRE À DÉCOUVERT"
        return (
            f"PLAN DE TRADE · {tp.horizon.upper()} · {direction_fr}\n"
            f" · Action               {action}\n"
            f" · Prix d'entrée        {tp.entry:>10.2f}\n"
            f" · Objectif (TP)        {tp.target:>10.2f}   {target_pct:+6.2f}%\n"
            f" · Stop-loss (SL)       {tp.stop:>10.2f}   {stop_pct:+6.2f}%\n"
            f" · Ratio risque/gain    {tp.risk_reward:>10.2f}\n"
            f" · Horizon estimé       {horizon_desc}"
        )


def _format_metadata(metadata: dict) -> str:
    if metadata.get("skipped"):
        return "(no data)"
    if "rsi" in metadata:
        return f"RSI {metadata['rsi']:.1f}"
    if "hist" in metadata:
        return f"hist {metadata['hist']:+.3f}"
    if "width_percentile" in metadata:
        bo = "breakout" if metadata.get("breakout") else "no breakout"
        return f"width pct {metadata['width_percentile']:.0f}, {bo}"
    if "ma5_minus_ma20" in metadata:
        return f"MA5-MA20 {metadata['ma5_minus_ma20']:+.2f}"
    if "volume_ratio" in metadata:
        return f"vol ratio {metadata['volume_ratio']:.2f}x"
    if "excess_return_5d" in metadata:
        return f"excess {metadata['excess_return_5d']*100:+.1f}%"
    return ""
