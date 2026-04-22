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


def _render_candles(opp: Opportunity, width: int = 70, chart_height: int = 14) -> Text:
    """Custom candlestick chart via Rich Text.

    Largeur par défaut 70 = largeur interne du chart-panel (#chart-panel width:74
    − border 2 − padding 2). Au-delà, Textual wrappe chaque ligne et double l'affichage.
    """
    bars = opp.recent_bars[-(width - 9):] if opp.recent_bars else []
    return render_candlestick_chart(
        bars=bars, trade_plan=opp.trade_plan,
        width=width, chart_height=chart_height, volume_height=3,
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
            yield Static(self._news_text(),
                         id="news-panel", classes="panel")
        yield Footer()

    def _title_line(self) -> str:
        o = self.opp
        name = o.meta.long_name if o.meta else ""
        name_part = f"  ·  {name}" if name else ""
        return (f"{o.ticker}{name_part}"
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
        uplift = (tp.target - tp.entry) / tp.entry * 100 if tp.entry else 0
        downside = (tp.stop - tp.entry) / tp.entry * 100 if tp.entry else 0
        horizon_desc = {
            "1d": "1 day", "1w": "5-10 trading days",
            "1m": "3-6 weeks", "1y": "6-18 months",
        }.get(tp.horizon, "—")
        return (
            f"TRADE PLAN · {tp.horizon.upper()}\n"
            f" · Entry         {tp.entry:>10.2f}\n"
            f" · Target (TP)   {tp.target:>10.2f}   {uplift:+6.2f}%\n"
            f" · Stop (SL)     {tp.stop:>10.2f}   {downside:+6.2f}%\n"
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
