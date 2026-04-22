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


def _fmt_full_int(v: float | None) -> str:
    """Formate un montant en entier avec espace comme séparateur de milliers.
    523000000 -> '523 000 000'. None -> '—'.
    """
    if v is None:
        return "—"
    return f"{int(round(v)):,}".replace(",", " ")


def _fmt_full_or_decimal(v: float | None) -> str:
    """Si > 1000 : entier avec séparateur. Sinon décimal 2 chiffres."""
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return _fmt_full_int(v)
    return f"{v:.2f}"


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
            # Row 1 : Chart | Signals | Trade Plan | Stats (tout horizontal)
            with Horizontal(id="top-panels"):
                yield Static(_render_candles(self.opp),
                             id="chart-panel", classes="panel")
                yield Static(self._signals_text(),
                             id="signals-panel", classes="panel")
                yield Static(self._trade_plan_text(),
                             id="plan-panel", classes="panel")
                yield Static(self._stats_text(),
                             id="stats-panel", classes="panel")
            # Row 2 : News full width
            yield Static(self._news_text(),
                         id="news-panel", classes="panel")
            # Fondamentaux : valorisation, rentabilité, croissance, santé bilan
            yield Static(self._valuation_text(),
                         id="valuation-panel", classes="panel")
            # États financiers : stack vertical pour avoir la largeur complète
            # et afficher les chiffres sans abréviation (ex. "523 000 000 000")
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

    def _stats_text(self) -> Text:
        text = Text()
        bars = self.opp.recent_bars
        if not bars:
            text.append("STATISTIQUES\n", style="bold #E8B45D")
            text.append(" aucune donnée", style="#8A8680")
            return text
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

        def append_perf(label: str, v: float | None) -> None:
            text.append(f" · {label:<21}")
            if v is None:
                text.append(" n/a\n", style="#8A8680")
                return
            style = "#7FB069" if v > 0 else ("#C97064" if v < 0 else "")
            s = f"{v:+6.2f}%"
            if style:
                text.append(s, style=style)
            else:
                text.append(s)
            text.append("\n")

        text.append("STATISTIQUES\n", style="bold #E8B45D")
        text.append(f" · Dernière clôture     {_fmt_num(last.close)}   {last.date.isoformat()}\n")
        append_perf("Jour", d1)
        append_perf("Semaine (5j)", d5)
        append_perf("Mois (20j)", d20)
        append_perf("Trimestre (60j)", d60)
        append_perf("Année (252j)", d252)
        text.append("\n")
        if hv20 is not None:
            text.append(f" · Vol. annualisée 20j  {hv20:>9.1f}%\n")
        else:
            text.append(" · Vol. annualisée 20j    n/a\n", style="#8A8680")
        text.append(f" · Volume moyen 20j     {avg_vol/1e6:>8.2f}M\n")
        text.append("\n")
        text.append(f" · Plage 52 semaines    {_fmt_num(lo52)} → {_fmt_num(hi52)}\n")
        text.append(f"   {_pos_bar(pos52)}  position {pos52:.0f}%")
        return text

    # Seuils bon / mauvais pour la valorisation (valeurs indicatives, pas absolues).
    # Format : champ → (good_max, bad_min) pour "bas = bon"
    #     ou : champ → (good_min, bad_max) pour "haut = bon", tag 'high'
    _VAL_RULES = {
        # bas = bon (valorisation pure)
        "trailing_pe":     ("low", 15, 30),
        "forward_pe":      ("low", 15, 25),
        "peg_ratio":       ("low", 1.0, 2.0),
        "price_to_book":   ("low", 2.0, 5.0),
        "price_to_sales":  ("low", 2.0, 8.0),
        "ev_to_ebitda":    ("low", 10, 20),
        "payout_ratio":    ("low", 0.70, 1.0),
        "debt_to_equity":  ("low", 100, 300),  # yfinance renvoie en %, d/e=100 = 1:1
        # haut = bon (rentabilité, croissance, dividende)
        "gross_margin":     ("high", 0.40, 0.15),
        "operating_margin": ("high", 0.20, 0.05),
        "profit_margin":    ("high", 0.15, 0.03),
        "return_on_equity": ("high", 0.15, 0.05),
        "return_on_assets": ("high", 0.08, 0.02),
        "revenue_growth":   ("high", 0.10, 0.00),
        "earnings_growth":  ("high", 0.10, 0.00),
        "dividend_yield":   ("high", 0.03, 0.00),
        "current_ratio":    ("high", 1.5, 1.0),
        "quick_ratio":      ("high", 1.0, 0.5),
    }

    def _classify_ratio(self, field: str, value: float | None) -> str:
        """Retourne un style Rich ('#7FB069' vert, '#C97064' rouge, '' neutre)."""
        if value is None:
            return ""
        rule = self._VAL_RULES.get(field)
        if not rule:
            return ""
        direction, threshold_good, threshold_bad = rule
        if direction == "low":
            if value <= threshold_good:
                return "#7FB069"
            if value >= threshold_bad:
                return "#C97064"
            return ""
        # high
        if value >= threshold_good:
            return "#7FB069"
        if value <= threshold_bad:
            return "#C97064"
        return ""

    def _valuation_text(self) -> Text:
        m = self.opp.meta
        text = Text()
        if not m:
            text.append("VALORISATION & RATIOS\n", style="bold #E8B45D")
            text.append(" (métadonnées non chargées — appuie sur F pour forcer le chargement)",
                        style="#8A8680")
            return text

        def append_val(v: float | None, unit: str = "") -> None:
            if v is None:
                text.append("—")
            else:
                text.append(f"{_fmt_full_int(v)}{unit}")

        def append_ratio(field: str, v: float | None) -> None:
            color = self._classify_ratio(field, v)
            s = f"{v:.2f}" if v is not None else "—"
            if color:
                text.append(s, style=color)
            else:
                text.append(s)

        def append_pct(field: str, v: float | None) -> None:
            color = self._classify_ratio(field, v)
            s = f"{v * 100:.2f}%" if v is not None else "—"
            if color:
                text.append(s, style=color)
            else:
                text.append(s)

        reco_key = (m.recommendation or "").lower()
        reco_fr = {
            "strong_buy": "achat fort", "buy": "achat",
            "hold": "conserver", "sell": "vendre",
            "strong_sell": "vente forte", "none": "—", "": "—",
        }.get(reco_key, m.recommendation or "—")
        reco_color = {
            "strong_buy": "#7FB069", "buy": "#7FB069",
            "hold": "", "sell": "#C97064", "strong_sell": "#C97064",
        }.get(reco_key, "")

        text.append("VALORISATION & RATIOS\n\n", style="bold #E8B45D")

        text.append(" VALORISATION\n", style="#8A8680")
        text.append(f"  · Capitalisation           ");         append_val(m.market_cap, f" {m.currency}"); text.append("\n")
        text.append(f"  · Valeur d'entreprise      ");         append_val(m.enterprise_value, f" {m.currency}"); text.append("\n")
        text.append(f"  · PER historique           ");         append_ratio("trailing_pe", m.trailing_pe); text.append("\n")
        text.append(f"  · PER prévisionnel         ");         append_ratio("forward_pe", m.forward_pe); text.append("\n")
        text.append(f"  · Ratio PEG                ");         append_ratio("peg_ratio", m.peg_ratio); text.append("\n")
        text.append(f"  · Cours / Valeur comptable ");         append_ratio("price_to_book", m.price_to_book); text.append("\n")
        text.append(f"  · Cours / Chiffre d'aff.   ");         append_ratio("price_to_sales", m.price_to_sales); text.append("\n")
        text.append(f"  · VE / EBITDA              ");         append_ratio("ev_to_ebitda", m.ev_to_ebitda); text.append("\n")

        text.append("\n RENTABILITÉ\n", style="#8A8680")
        text.append(f"  · Marge brute              ");         append_pct("gross_margin", m.gross_margin); text.append("\n")
        text.append(f"  · Marge opérationnelle     ");         append_pct("operating_margin", m.operating_margin); text.append("\n")
        text.append(f"  · Marge nette              ");         append_pct("profit_margin", m.profit_margin); text.append("\n")
        text.append(f"  · ROE (rentab. capitaux)   ");         append_pct("return_on_equity", m.return_on_equity); text.append("\n")
        text.append(f"  · ROA (rentab. actifs)     ");         append_pct("return_on_assets", m.return_on_assets); text.append("\n")

        text.append("\n CROISSANCE (sur un an glissant)\n", style="#8A8680")
        text.append(f"  · Croissance CA            ");         append_pct("revenue_growth", m.revenue_growth); text.append("\n")
        text.append(f"  · Croissance résultat      ");         append_pct("earnings_growth", m.earnings_growth); text.append("\n")

        text.append("\n SOLIDITÉ BILAN\n", style="#8A8680")
        text.append(f"  · Trésorerie totale        ");         append_val(m.total_cash, f" {m.currency}"); text.append("\n")
        text.append(f"  · Dette totale             ");         append_val(m.total_debt, f" {m.currency}"); text.append("\n")
        text.append(f"  · Dette / Fonds propres    ");         append_ratio("debt_to_equity", m.debt_to_equity); text.append("\n")
        text.append(f"  · Liquidité générale       ");         append_ratio("current_ratio", m.current_ratio); text.append("\n")
        text.append(f"  · Liquidité immédiate      ");         append_ratio("quick_ratio", m.quick_ratio); text.append("\n")

        text.append("\n DIVIDENDE & ANALYSTES\n", style="#8A8680")
        text.append(f"  · Rendement dividende      ");         append_pct("dividend_yield", m.dividend_yield); text.append("\n")
        text.append(f"  · Taux de distribution     ");         append_pct("payout_ratio", m.payout_ratio); text.append("\n")
        text.append(f"  · Recommandation analystes ")
        if reco_color:
            text.append(reco_fr, style=reco_color)
        else:
            text.append(reco_fr)
        text.append("\n")
        text.append(f"  · Objectif analystes moyen ")
        text.append(f"{_fmt_full_or_decimal(m.target_mean_price)} ({m.number_analysts or '—'} analystes)")
        return text

# Direction préférentielle par ligne d'état financier :
    #   "up_good"   : hausse = bonne nouvelle (CA, marge, résultat net, FCF…)
    #   "down_good" : baisse = bonne nouvelle (dette, coût des ventes…)
    #   "neutral"   : ni bon ni mauvais en soi (flux d'investissement, capex…)
    DIRECTION_PREFERENCE = {
        # Compte de résultat
        "Total Revenue":                    "up_good",
        "Cost Of Revenue":                  "down_good",
        "Gross Profit":                     "up_good",
        "Operating Income":                 "up_good",
        "EBIT":                             "up_good",
        "EBITDA":                           "up_good",
        "Net Income":                       "up_good",
        "Net Income Common Stockholders":   "up_good",
        "Diluted EPS":                      "up_good",
        "Basic EPS":                        "up_good",
        # Bilan — actifs
        "Total Assets":                     "up_good",
        "Total Equity Gross Minority Interest": "up_good",
        "Stockholders Equity":              "up_good",
        "Cash And Cash Equivalents":        "up_good",
        "Cash Cash Equivalents And Short Term Investments": "up_good",
        "Working Capital":                  "up_good",
        # Bilan — passifs / dette (baisse = sain)
        "Total Liabilities Net Minority Interest": "down_good",
        "Total Debt":                       "down_good",
        "Long Term Debt":                   "down_good",
        "Current Debt":                     "down_good",
        # Cash flow — positif = bon
        "Operating Cash Flow":              "up_good",
        "Free Cash Flow":                   "up_good",
        # Cash flow — contextuel
        "Investing Cash Flow":              "neutral",
        "Financing Cash Flow":              "neutral",
        "Capital Expenditure":              "neutral",
        "Cash Dividends Paid":              "neutral",
        "Repurchase Of Capital Stock":      "neutral",
    }

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

    def _color_for_direction(
        self, current: float | None, previous: float | None, preference: str
    ) -> str:
        """Retourne un style Rich selon l'évolution current vs previous
        et la préférence 'up_good' / 'down_good' / 'neutral'.
        """
        if current is None or previous is None or preference == "neutral":
            return ""
        if abs(current - previous) < 1e-6:
            return ""
        going_up = current > previous
        if preference == "up_good":
            return "#7FB069" if going_up else "#C97064"
        if preference == "down_good":
            return "#7FB069" if not going_up else "#C97064"
        return ""

    def _render_financial_block(self, title: str, lines) -> Text:
        """Rend un bloc financier en Rich Text avec chiffres colorés + % variation."""
        f = self.opp.fundamentals
        text = Text()
        if not f or not lines:
            text.append(f"{title}\n", style="bold")
            text.append(" (aucune donnée — appuie sur F pour forcer le chargement)",
                        style="#8A8680")
            return text

        periods = f.periods[:3] if f.periods else []
        currency = self.opp.meta.currency if self.opp.meta else ""
        title_full = f"{title}" + (f" · en {currency}" if currency else "")

        text.append(f"{title_full}\n", style="bold #E8B45D")
        # Cell : chiffre (15) + 2 espaces + % (7) = 24 chars par colonne
        text.append("  " + " " * 34
                    + "  ".join(f"{p:>24}" for p in periods) + "\n",
                    style="#8A8680")

        for line in lines:
            vals = line.values[:3]
            label_fr = self._translate_label(line.label)
            preference = self.DIRECTION_PREFERENCE.get(line.label, "neutral")

            text.append(f"  · {label_fr:<32}")
            for i, v in enumerate(vals):
                prev = vals[i + 1] if i + 1 < len(vals) else None
                color = self._color_for_direction(v, prev, preference)
                num = "—" if v is None else _fmt_full_int(v)
                # % variation vs période précédente
                if v is None or prev is None or abs(prev) < 1e-9:
                    pct_str = "       "
                else:
                    pct = (v - prev) / abs(prev) * 100
                    pct_str = f"{pct:+6.1f}%"
                cell = f"{num:>15}  {pct_str}"
                text.append("  ")
                if color:
                    text.append(cell, style=color)
                else:
                    text.append(cell)
            text.append("\n")
        return text

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
