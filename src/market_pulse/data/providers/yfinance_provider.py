"""Provider yfinance avec fetch asynchrone via run_in_executor."""
import asyncio
from datetime import date

import yfinance as yf

from market_pulse.data.models import Bar
from market_pulse.data.providers.base import Provider


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
