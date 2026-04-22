"""Écran détail : chart candlestick + signaux + trade plan + stats."""
import math
import os
import tempfile

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from textual_image.widget import AutoImage as TxtImage

from market_pulse.data.models import Bar
from market_pulse.engine.scanner import Opportunity, enrich_opportunity
from market_pulse.ui.widgets.candle_chart import render_candlestick_chart
from market_pulse.ui.widgets.chart_image import save_chart_to_temp

SAUGE = (127, 176, 105)
TERRA = (201, 112, 100)
AMBRE = (232, 180, 93)
SMOKE_BLUE = (107, 140, 174)
OFF_WHITE = (232, 230, 227)


def _render_candles(opp: Opportunity, width: int | None = None,
                     chart_height: int | None = None) -> Text:
    """Chart inline, quart de largeur du terminal (proportions conservées)."""
    if width is None:
        import shutil
        term_w = shutil.get_terminal_size((180, 50)).columns
        # Quart-largeur du terminal moins bordures/padding
        width = max(50, (term_w - 8) // 4)
    if chart_height is None:
        # Proportion ~5:1 (chart plus large que haut, plus carré quand petit)
        chart_height = max(8, width // 5)
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
        Binding("g", "open_chart_external", "Chart en plein écran", show=True),
        Binding("p", "diag_protocol", "Diag protocole image", show=False),
        Binding("q", "app.quit", "Quitter", show=True),
    ]

    def __init__(self, opp: Opportunity) -> None:
        super().__init__()
        self.opp = opp
        self._loading = False
        # Chart PNG généré au mount, fichier temp
        self._chart_png_path = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="detail-scroll"):
            yield Static(self._title_line(), classes="highlight-amber", id="title")
            yield Static(self._subtitle_line(), id="subtitle")
            # Row 1 : Chart + Plan de trade + Stats (3 colonnes)
            with Horizontal(id="top-row"):
                yield Static(_render_candles(self.opp),
                             id="chart-panel", classes="panel")
                yield Static(self._trade_plan_text(),
                             id="plan-panel", classes="panel")
                yield Static(self._stats_text(),
                             id="stats-panel", classes="panel")
            # Row 2 : News + Signaux côte à côte
            with Horizontal(id="news-row"):
                yield Static(self._news_text(),
                             id="news-panel", classes="panel")
                yield Static(self._signals_text(),
                             id="signals-panel", classes="panel")
            # Fondamentaux : valorisation, rentabilité, croissance, santé bilan
            yield Static(self._valuation_text(),
                         id="valuation-panel", classes="panel")
            # États financiers ANNUELS (3 dernières années) full width
            yield Static(self._income_text(),
                         id="income-panel", classes="panel")
            yield Static(self._balance_text(),
                         id="balance-panel", classes="panel")
            yield Static(self._cashflow_text(),
                         id="cashflow-panel", classes="panel")
            # États financiers TRIMESTRIELS (4 derniers trimestres) full width
            yield Static(self._income_q_text(),
                         id="income-q-panel", classes="panel")
            yield Static(self._balance_q_text(),
                         id="balance-q-panel", classes="panel")
            yield Static(self._cashflow_q_text(),
                         id="cashflow-q-panel", classes="panel")
        yield Footer()

    def _chart_header_text(self) -> Text:
        """Header au-dessus du chart : stats clés (Dernier / Haut / Bas / Moyenne)."""
        bars = self.opp.recent_bars[-120:] if self.opp.recent_bars else []
        text = Text()
        if not bars:
            text.append("—", style="#8A8680")
            return text
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        from statistics import mean
        last = closes[-1]
        hi_val = max(highs)
        hi_date = bars[highs.index(hi_val)].date.isoformat()
        lo_val = min(lows)
        lo_date = bars[lows.index(lo_val)].date.isoformat()
        avg_val = mean(closes)
        text.append(" Dernier ", style="#8A8680")
        text.append(f"{last:>8.2f}", style="#E8E6E3")
        text.append("     ▲ Haut ", style="#8A8680")
        text.append(f"{hi_val:>8.2f}", style="#7FB069")
        text.append(f" ({hi_date})", style="#8A8680")
        text.append("     ▼ Bas ", style="#8A8680")
        text.append(f"{lo_val:>8.2f}", style="#C97064")
        text.append(f" ({lo_date})", style="#8A8680")
        text.append("     Moyenne ", style="#8A8680")
        text.append(f"{avg_val:>8.2f}", style="#E8B45D")
        return text

    def _chart_legend_text(self) -> Text:
        """Légende sous le chart pour identifier les 3 lignes horizontales."""
        text = Text()
        text.append(" Lignes : ", style="#8A8680")
        text.append("entry ", style="#E8E6E3")
        text.append("·  ", style="#8A8680")
        text.append("TP ", style="#7FB069")
        text.append("·  ", style="#8A8680")
        text.append("SL", style="#C97064")
        return text

    def on_unmount(self) -> None:
        """Nettoie le fichier PNG temporaire à la fermeture de l'écran."""
        if self._chart_png_path and self._chart_png_path.exists():
            try:
                self._chart_png_path.unlink()
            except Exception:
                pass

    def action_diag_protocol(self) -> None:
        """Affiche le protocole d'image détecté par textual-image au démarrage."""
        import os
        from textual_image.renderable import Image as DetectedRenderable
        term_program = os.environ.get("TERM_PROGRAM", "?")
        term = os.environ.get("TERM", "?")
        # __module__ nous dit quelle impl a été retenue : sixel, tgp, halfcell, unicode
        module = DetectedRenderable.__module__.split(".")[-1]
        self.notify(
            f"TERM_PROGRAM={term_program}  TERM={term}  protocole={module}",
            timeout=15.0,
        )

    def action_open_chart_external(self) -> None:
        """Ouvre le chart PNG dans le viewer système (Preview.app sur macOS,
        xdg-open sur Linux). Permet d'avoir un vrai chart pixel-perfect
        même depuis Terminal.app qui ne supporte pas les protocoles inline.
        """
        import subprocess
        import sys

        # Régénère un chart haute résolution pour un affichage externe propre
        try:
            hi_res = save_chart_to_temp(
                self.opp.recent_bars[-120:] if self.opp.recent_bars else [],
                self.opp.trade_plan,
                width_px=2400, height_px=1000,
            )
        except Exception as e:
            self.notify(f"Erreur génération chart : {e}", severity="error")
            return

        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(hi_res)])
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(hi_res)])
            elif sys.platform == "win32":
                os.startfile(str(hi_res))  # type: ignore
            else:
                self.notify("OS non supporté pour l'ouverture externe",
                            severity="warning")
                return
            self.notify(f"Chart ouvert dans le viewer système ({hi_res.name})")
        except Exception as e:
            self.notify(f"Erreur ouverture : {e}", severity="error")

    def _title_line(self) -> str:
        o = self.opp
        name = (o.meta.long_name if o.meta else None) or o.name or ""
        name_part = f"  ·  {name}" if name else ""
        direction_fr = "LONG" if o.trade_plan.direction == "long" else "SHORT"
        status = "  ·  ⏳ chargement…" if self._loading else ""
        if o.blended and o.technical_score is not None and o.fundamental_score is not None:
            score_part = (f"  ·  SCORE {o.score:.1f} / 100"
                          f"  (tech {o.technical_score:.0f}"
                          f"  ·  fonda {o.fundamental_score:.0f})")
        else:
            score_part = f"  ·  SCORE {o.score:.1f} / 100"
        return (f"{o.ticker}{name_part}"
                f"  ·  {direction_fr}"
                f"{score_part}"
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
            mode = getattr(self.app.settings, "scoring_mode", "blended")
            blend = mode == "blended"
            await enrich_opportunity(self.opp, provider, blend_fundamentals=blend)
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
            self.query_one("#income-q-panel", Static).update(self._income_q_text())
            self.query_one("#balance-q-panel", Static).update(self._balance_q_text())
            self.query_one("#cashflow-q-panel", Static).update(self._cashflow_q_text())
        except Exception:
            pass

    def _subtitle_line(self) -> str:
        if not self.opp.meta:
            return f"{len(self.opp.recent_bars)} jours d'historique"
        m = self.opp.meta
        parts = [m.sector, m.industry, m.currency,
                 f"{len(self.opp.recent_bars)} jours d'historique"]
        if m.last_earnings_date:
            parts.append(f"dernière pub. {m.last_earnings_date}")
        if m.next_earnings_date:
            parts.append(f"prochaine {m.next_earnings_date}")
        return "  ·  ".join(parts)

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

    def _render_financial_block(
        self, title: str, lines, periods: list[str]
    ) -> Text:
        """Rend un bloc financier en Rich Text avec chiffres colorés + % variation.

        periods : liste des labels de colonne (années pour annuel, Qn-YY pour trimestriel).
        """
        text = Text()
        f = self.opp.fundamentals
        if not f or not lines:
            text.append(f"{title}\n", style="bold")
            text.append(" (aucune donnée — appuie sur F pour forcer le chargement)",
                        style="#8A8680")
            return text

        currency = self.opp.meta.currency if self.opp.meta else ""
        title_full = f"{title}" + (f" · en {currency}" if currency else "")

        text.append(f"{title_full}\n", style="bold #E8B45D")
        text.append("  " + " " * 34
                    + "  ".join(f"{p:>24}" for p in periods) + "\n",
                    style="#8A8680")

        n_cols = len(periods)
        for line in lines:
            vals = line.values[:n_cols]
            label_fr = self._translate_label(line.label)
            preference = self.DIRECTION_PREFERENCE.get(line.label, "neutral")

            text.append(f"  · {label_fr:<32}")
            for i, v in enumerate(vals):
                prev = vals[i + 1] if i + 1 < len(vals) else None
                color = self._color_for_direction(v, prev, preference)
                num = "—" if v is None else _fmt_full_int(v)
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

    def _income_text(self) -> Text:
        f = self.opp.fundamentals
        return self._render_financial_block(
            "COMPTE DE RÉSULTAT · ANNUEL",
            f.income if f else [],
            f.periods if f else [],
        )

    def _balance_text(self) -> Text:
        f = self.opp.fundamentals
        return self._render_financial_block(
            "BILAN · ANNUEL",
            f.balance if f else [],
            f.periods if f else [],
        )

    def _cashflow_text(self) -> Text:
        f = self.opp.fundamentals
        return self._render_financial_block(
            "FLUX DE TRÉSORERIE · ANNUEL",
            f.cashflow if f else [],
            f.periods if f else [],
        )

    def _income_q_text(self) -> Text:
        f = self.opp.fundamentals
        return self._render_financial_block(
            "COMPTE DE RÉSULTAT · TRIMESTRIEL (4 derniers trimestres)",
            f.income_q if f else [],
            f.periods_q if f else [],
        )

    def _balance_q_text(self) -> Text:
        f = self.opp.fundamentals
        return self._render_financial_block(
            "BILAN · TRIMESTRIEL (4 derniers trimestres)",
            f.balance_q if f else [],
            f.periods_q if f else [],
        )

    def _cashflow_q_text(self) -> Text:
        f = self.opp.fundamentals
        return self._render_financial_block(
            "FLUX DE TRÉSORERIE · TRIMESTRIEL (4 derniers trimestres)",
            f.cashflow_q if f else [],
            f.periods_q if f else [],
        )

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

    def _trade_plan_text(self) -> Text:
        tp = self.opp.trade_plan
        target_pct = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
        stop_pct = (tp.stop - tp.entry) / tp.entry * 100 if tp.entry else 0
        horizon_desc = {
            "1d": "1 jour", "1w": "5 à 10 jours de bourse",
            "1m": "3 à 6 semaines", "1y": "6 à 18 mois",
        }.get(tp.horizon, "—")
        is_long = tp.direction == "long"
        action = "ACHETER" if is_long else "VENDRE À DÉCOUVERT"
        action_color = "#7FB069" if is_long else "#C97064"
        direction_fr = "ACHAT (long)" if is_long else "VENTE À DÉCOUVERT (short)"

        text = Text()
        text.append(f"PLAN DE TRADE · {tp.horizon.upper()} · ", style="bold #E8B45D")
        text.append(direction_fr, style=f"bold {action_color}")
        text.append("\n")
        text.append(" · Action               ")
        text.append(action, style=f"bold {action_color}")
        text.append("\n")
        text.append(f" · Prix d'entrée        {tp.entry:>10.2f}\n")
        text.append(f" · Objectif (TP)        {tp.target:>10.2f}   ")
        text.append(f"{target_pct:+6.2f}%",
                    style="#7FB069" if target_pct > 0 else "#C97064")
        text.append("\n")
        text.append(f" · Stop-loss (SL)       {tp.stop:>10.2f}   ")
        text.append(f"{stop_pct:+6.2f}%",
                    style="#7FB069" if stop_pct > 0 else "#C97064")
        text.append("\n")
        text.append(f" · Ratio risque/gain    {tp.risk_reward:>10.2f}\n")
        text.append(f" · Horizon estimé       {horizon_desc}")
        return text


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
