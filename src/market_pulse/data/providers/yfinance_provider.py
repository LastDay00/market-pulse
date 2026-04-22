"""Provider yfinance avec fetch asynchrone via run_in_executor."""
import asyncio
from datetime import date, datetime

import yfinance as yf

from market_pulse.data.models import Bar
from market_pulse.data.providers.base import NewsItem, Provider, TickerMeta


class YFinanceProvider(Provider):
    """Provider yfinance — wrap les appels bloquants dans un executor."""

    def __init__(self, max_concurrency: int = 20) -> None:
        self._sem = asyncio.Semaphore(max_concurrency)

    async def fetch_bars(
        self, ticker: str, start: date, end: date
    ) -> list[Bar]:
        async with self._sem:
            loop = asyncio.get_running_loop()
            try:
                df = await loop.run_in_executor(
                    None, lambda: yf.Ticker(ticker).history(
                        start=start.isoformat(),
                        end=end.isoformat(),
                        auto_adjust=False,
                    )
                )
            except Exception:
                return []
            if df is None or df.empty:
                return []
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            bars = []
            for idx, row in df.iterrows():
                d = idx.date() if hasattr(idx, "date") else idx
                bars.append(Bar(
                    date=d,
                    open=float(row.Open),
                    high=float(row.High),
                    low=float(row.Low),
                    close=float(row.Close),
                    volume=int(row.Volume),
                ))
            return bars

    async def fetch_meta(self, ticker: str) -> TickerMeta | None:
        async with self._sem:
            loop = asyncio.get_running_loop()
            try:
                info = await loop.run_in_executor(
                    None, lambda: yf.Ticker(ticker).info
                )
            except Exception:
                return None
            if not info:
                return None
            return TickerMeta(
                ticker=ticker,
                long_name=str(info.get("longName") or info.get("shortName") or ticker),
                short_name=str(info.get("shortName") or ticker),
                sector=str(info.get("sector") or "—"),
                industry=str(info.get("industry") or "—"),
                currency=str(info.get("currency") or "—"),
            )

    async def fetch_news(self, ticker: str, max_items: int = 5) -> list[NewsItem]:
        async with self._sem:
            loop = asyncio.get_running_loop()
            try:
                raw = await loop.run_in_executor(
                    None, lambda: yf.Ticker(ticker).news
                )
            except Exception:
                return []
            if not raw:
                return []
            items: list[NewsItem] = []
            for entry in raw[:max_items]:
                # Nouveau format yfinance : entry['content'] contient titre/pubDate/clickThroughUrl
                content = entry.get("content") or entry
                title = content.get("title") or entry.get("title") or ""
                publisher = (content.get("provider") or {}).get("displayName") \
                            or entry.get("publisher", "")
                # Date au format ISO (yfinance >= 0.2.47) ou timestamp int (ancien)
                pub_date = content.get("pubDate") or content.get("displayTime")
                if isinstance(pub_date, str):
                    try:
                        published = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    except ValueError:
                        published = datetime.now()
                else:
                    ts = entry.get("providerPublishTime", 0)
                    published = datetime.fromtimestamp(ts) if ts else datetime.now()
                link = ((content.get("clickThroughUrl") or {}).get("url") or
                        (content.get("canonicalUrl") or {}).get("url") or
                        entry.get("link", ""))
                if title:
                    items.append(NewsItem(
                        title=title, publisher=str(publisher),
                        published=published, link=str(link),
                    ))
            return items
