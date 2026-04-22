"""Provider yfinance avec fetch asynchrone via run_in_executor."""
import asyncio
import contextlib
import io
import logging
import os
from datetime import date, datetime

import yfinance as yf

from market_pulse.data.models import Bar
from market_pulse.data.providers.base import (
    FinancialLine, Fundamentals, NewsItem, Provider, TickerMeta,
)

# Silence les "possibly delisted" / HTTP 404 imprimés par yfinance sur stderr/log
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)


@contextlib.contextmanager
def _silence_stderr():
    """Redirige stderr vers /dev/null pour la durée du bloc."""
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    try:
        os.dup2(devnull.fileno(), 2)
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()


class YFinanceProvider(Provider):
    """Provider yfinance — wrap les appels bloquants dans un executor."""

    def __init__(self, max_concurrency: int = 20) -> None:
        self._sem = asyncio.Semaphore(max_concurrency)

    async def fetch_bars(
        self, ticker: str, start: date, end: date
    ) -> list[Bar]:
        async with self._sem:
            loop = asyncio.get_running_loop()

            def _fetch():
                with _silence_stderr():
                    return yf.Ticker(ticker).history(
                        start=start.isoformat(),
                        end=end.isoformat(),
                        auto_adjust=False,
                    )

            try:
                df = await loop.run_in_executor(None, _fetch)
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

            def _fetch():
                with _silence_stderr():
                    return yf.Ticker(ticker).info

            try:
                info = await loop.run_in_executor(None, _fetch)
            except Exception:
                return None
            if not info:
                return None

            def f(key: str) -> float | None:
                v = info.get(key)
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            def i(key: str) -> int | None:
                v = info.get(key)
                try:
                    return int(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            return TickerMeta(
                ticker=ticker,
                long_name=str(info.get("longName") or info.get("shortName") or ticker),
                short_name=str(info.get("shortName") or ticker),
                sector=str(info.get("sector") or "—"),
                industry=str(info.get("industry") or "—"),
                currency=str(info.get("currency") or "—"),
                market_cap=f("marketCap"),
                enterprise_value=f("enterpriseValue"),
                trailing_pe=f("trailingPE"),
                forward_pe=f("forwardPE"),
                peg_ratio=f("pegRatio") or f("trailingPegRatio"),
                price_to_book=f("priceToBook"),
                price_to_sales=f("priceToSalesTrailing12Months"),
                ev_to_ebitda=f("enterpriseToEbitda"),
                profit_margin=f("profitMargins"),
                operating_margin=f("operatingMargins"),
                gross_margin=f("grossMargins"),
                return_on_equity=f("returnOnEquity"),
                return_on_assets=f("returnOnAssets"),
                revenue_growth=f("revenueGrowth"),
                earnings_growth=f("earningsGrowth"),
                dividend_yield=f("dividendYield"),
                payout_ratio=f("payoutRatio"),
                debt_to_equity=f("debtToEquity"),
                current_ratio=f("currentRatio"),
                quick_ratio=f("quickRatio"),
                total_cash=f("totalCash"),
                total_debt=f("totalDebt"),
                recommendation=str(info.get("recommendationKey") or ""),
                target_mean_price=f("targetMeanPrice"),
                number_analysts=i("numberOfAnalystOpinions"),
            )

    async def fetch_fundamentals(self, ticker: str) -> Fundamentals | None:
        async with self._sem:
            loop = asyncio.get_running_loop()

            def _fetch():
                with _silence_stderr():
                    t = yf.Ticker(ticker)
                    return (
                        t.financials,        # income statement annuel
                        t.balance_sheet,     # bilan annuel
                        t.cashflow,          # cash flow annuel
                    )

            try:
                income_df, balance_df, cashflow_df = await loop.run_in_executor(None, _fetch)
            except Exception:
                return None

            # yfinance renvoie des DataFrames avec colonnes = dates (récentes à gauche),
            # lignes = libellés. Certaines peuvent être vides selon le ticker.
            def _df_to_lines(df, wanted: list[str]) -> tuple[list[str], list[FinancialLine]]:
                if df is None or df.empty:
                    return [], []
                # Périodes = colonnes, formatées en année
                periods = [str(c.year) if hasattr(c, "year") else str(c) for c in df.columns]
                lines: list[FinancialLine] = []
                for label in wanted:
                    if label in df.index:
                        row = df.loc[label]
                        vals = [
                            (float(v) if v is not None and str(v) != "nan" else None)
                            for v in row.tolist()
                        ]
                        lines.append(FinancialLine(label=label, values=vals, periods=periods))
                return periods, lines

            income_labels = [
                "Total Revenue", "Cost Of Revenue", "Gross Profit",
                "Operating Income", "EBIT", "EBITDA",
                "Net Income", "Net Income Common Stockholders",
                "Diluted EPS", "Basic EPS",
            ]
            balance_labels = [
                "Total Assets", "Total Liabilities Net Minority Interest",
                "Total Equity Gross Minority Interest", "Stockholders Equity",
                "Total Debt", "Long Term Debt", "Current Debt",
                "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments",
                "Working Capital",
            ]
            cashflow_labels = [
                "Operating Cash Flow", "Investing Cash Flow", "Financing Cash Flow",
                "Free Cash Flow", "Capital Expenditure",
                "Cash Dividends Paid", "Repurchase Of Capital Stock",
            ]

            periods, income_lines = _df_to_lines(income_df, income_labels)
            if not periods:
                periods_b, balance_lines = _df_to_lines(balance_df, balance_labels)
                periods = periods_b
            else:
                _, balance_lines = _df_to_lines(balance_df, balance_labels)
            _, cashflow_lines = _df_to_lines(cashflow_df, cashflow_labels)

            return Fundamentals(
                ticker=ticker,
                periods=periods,
                income=income_lines,
                balance=balance_lines,
                cashflow=cashflow_lines,
            )

    async def fetch_news(self, ticker: str, max_items: int = 5) -> list[NewsItem]:
        async with self._sem:
            loop = asyncio.get_running_loop()

            def _fetch():
                with _silence_stderr():
                    return yf.Ticker(ticker).news

            try:
                raw = await loop.run_in_executor(None, _fetch)
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
