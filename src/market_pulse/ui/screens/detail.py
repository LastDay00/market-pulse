"""Écran détail : chart candlestick + signaux + trade plan + stats."""
import math

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from market_pulse.data.models import Bar
from market_pulse.engine.scanner import Opportunity
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
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("q", "app.quit", "Quit", show=True),
    ]

    def __init__(self, opp: Opportunity) -> None:
        super().__init__()
        self.opp = opp

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
            with Horizontal(id="bottom-panels"):
                yield Static(self._stats_text(),
                             id="stats-panel", classes="panel")
                yield Static(self._trade_plan_text(),
                             id="plan-panel", classes="panel")
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
            yield Static(self._news_text(),
                         id="news-panel", classes="panel")
        yield Footer()

    def _title_line(self) -> str:
        o = self.opp
        name = o.meta.long_name if o.meta else ""
        name_part = f"  ·  {name}" if name else ""
        direction = o.trade_plan.direction.upper()
        return (f"{o.ticker}{name_part}"
                f"  ·  {direction}"
                f"  ·  SCORE {o.score:.1f} / 100"
                f"  ·  horizon {o.horizon.upper()}")

    def _subtitle_line(self) -> str:
        if not self.opp.meta:
            return f"{len(self.opp.recent_bars)}d history"
        m = self.opp.meta
        return (f"{m.sector}  ·  {m.industry}  ·  "
                f"{m.currency}  ·  {len(self.opp.recent_bars)}d history")

    def _signals_text(self) -> str:
        lines = ["SIGNALS"]
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
            return "STATS\n no data"
        last = bars[-1]
        d1 = _pct_change(bars, 1)
        d5 = _pct_change(bars, 5)
        d20 = _pct_change(bars, 20)
        d60 = _pct_change(bars, 60)
        d252 = _pct_change(bars, 252)
        hv20 = _annualized_vol(bars, window=20)
        lo52, hi52, pos52 = _range_position(bars, window=252)
        # Volume stats
        vols = [b.volume for b in bars[-20:]]
        avg_vol = sum(vols) / len(vols) if vols else 0

        lines = [
            "STATS",
            f" · Last close     {_fmt_num(last.close)}   {last.date.isoformat()}",
            f" · Day            {_fmt_pct(d1)}",
            f" · Week (5d)      {_fmt_pct(d5)}",
            f" · Month (20d)    {_fmt_pct(d20)}",
            f" · Quarter (60d)  {_fmt_pct(d60)}",
            f" · Year (252d)    {_fmt_pct(d252)}",
            "",
            f" · HV 20d         {hv20:>9.1f}%" if hv20 is not None else " · HV 20d            n/a",
            f" · Avg vol 20d    {avg_vol/1e6:>8.2f}M",
            "",
            f" · 52w range      {_fmt_num(lo52)} → {_fmt_num(hi52)}",
            f"   {_pos_bar(pos52)}  pos {pos52:.0f}%",
        ]
        return "\n".join(lines)

    def _valuation_text(self) -> str:
        m = self.opp.meta
        if not m:
            return "VALUATION & RATIOS\n (meta not loaded yet)"

        def fn(v: float | None, pct: bool = False, scale: float = 1.0, unit: str = "") -> str:
            if v is None:
                return "     —"
            if pct:
                return f"{v * 100:>6.2f}%"
            v *= scale
            if abs(v) >= 1e9:
                return f"{v/1e9:>6.2f}B{unit}"
            if abs(v) >= 1e6:
                return f"{v/1e6:>6.2f}M{unit}"
            return f"{v:>6.2f}{unit}"

        lines = [
            "VALUATION & RATIOS",
            f" VALORISATION                                 RENTABILITÉ",
            f"  · Market Cap      {fn(m.market_cap, unit=f' {m.currency}')}        · Gross margin      {fn(m.gross_margin, pct=True)}",
            f"  · Enterprise Val  {fn(m.enterprise_value, unit=f' {m.currency}')}        · Operating margin  {fn(m.operating_margin, pct=True)}",
            f"  · Trailing P/E    {fn(m.trailing_pe)}         · Profit margin     {fn(m.profit_margin, pct=True)}",
            f"  · Forward P/E     {fn(m.forward_pe)}         · Return on Equity  {fn(m.return_on_equity, pct=True)}",
            f"  · PEG ratio       {fn(m.peg_ratio)}         · Return on Assets  {fn(m.return_on_assets, pct=True)}",
            f"  · Price / Book    {fn(m.price_to_book)}",
            f"  · Price / Sales   {fn(m.price_to_sales)}       CROISSANCE (YoY)",
            f"  · EV / EBITDA     {fn(m.ev_to_ebitda)}         · Revenue growth    {fn(m.revenue_growth, pct=True)}",
            "                                               · Earnings growth   " + fn(m.earnings_growth, pct=True),
            "",
            f" SOLIDITÉ BILAN                                DIVIDENDE & ANALYSTES",
            f"  · Debt / Equity   {fn(m.debt_to_equity)}         · Dividend yield    {fn(m.dividend_yield, pct=True)}",
            f"  · Current ratio   {fn(m.current_ratio)}         · Payout ratio      {fn(m.payout_ratio, pct=True)}",
            f"  · Quick ratio     {fn(m.quick_ratio)}         · Recommandation    {m.recommendation or '—':>6}",
            f"  · Total cash      {fn(m.total_cash, unit=f' {m.currency}')}        · Target moyen      {fn(m.target_mean_price)} ({m.number_analysts or '—'} an.)",
            f"  · Total debt      {fn(m.total_debt, unit=f' {m.currency}')}",
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

    def _render_financial_block(self, title: str, lines) -> str:
        f = self.opp.fundamentals
        if not f or not lines:
            return f"{title}\n (no data)"
        periods = f.periods[:3] if f.periods else []
        header = f"{title}\n  " + " " * 28 + "  ".join(f"{p:>9}" for p in periods)
        out = [header]
        for line in lines:
            vals = line.values[:3]
            val_str = "  ".join(self._fmt_financial_value(v) for v in vals)
            out.append(f"  · {line.label:<28} {val_str}")
        return "\n".join(out)

    def _income_text(self) -> str:
        f = self.opp.fundamentals
        return self._render_financial_block("INCOME STATEMENT",
                                             f.income if f else [])

    def _balance_text(self) -> str:
        f = self.opp.fundamentals
        return self._render_financial_block("BALANCE SHEET",
                                             f.balance if f else [])

    def _cashflow_text(self) -> str:
        f = self.opp.fundamentals
        return self._render_financial_block("CASH FLOW",
                                             f.cashflow if f else [])

    def _news_text(self) -> str:
        lines = ["RECENT NEWS"]
        if not self.opp.news:
            lines.append(" · no recent news")
            return "\n".join(lines)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        for item in self.opp.news[:5]:
            pub = item.published
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            delta = now - pub
            if delta.days >= 1:
                age = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                age = f"{delta.seconds // 3600}h ago"
            else:
                age = f"{max(1, delta.seconds // 60)}m ago"
            title = item.title[:140]
            publisher = (item.publisher or "?")[:20]
            lines.append(f" · [{age:>7}] {publisher:<20} · {title}")
        return "\n".join(lines)

    def _trade_plan_text(self) -> str:
        tp = self.opp.trade_plan
        target_pct = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
        stop_pct = (tp.stop - tp.entry) / tp.entry * 100 if tp.entry else 0
        horizon_desc = {
            "1d": "1 day", "1w": "5-10 trading days",
            "1m": "3-6 weeks", "1y": "6-18 months",
        }.get(tp.horizon, "—")
        action = "BUY (long)" if tp.direction == "long" else "SELL SHORT"
        return (
            f"TRADE PLAN · {tp.horizon.upper()} · {tp.direction.upper()}\n"
            f" · Action        {action}\n"
            f" · Entry         {tp.entry:>10.2f}\n"
            f" · Target (TP)   {tp.target:>10.2f}   {target_pct:+6.2f}%\n"
            f" · Stop (SL)     {tp.stop:>10.2f}   {stop_pct:+6.2f}%\n"
            f" · Risk/Reward   {tp.risk_reward:>10.2f}\n"
            f" · Horizon       {horizon_desc}"
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
