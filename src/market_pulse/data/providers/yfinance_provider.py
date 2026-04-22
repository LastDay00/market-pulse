"""Provider yfinance avec fetch asynchrone via run_in_executor."""
import asyncio
import logging
from datetime import date, datetime

import yfinance as yf

from market_pulse.data.models import Bar
from market_pulse.data.providers.base import (
    FinancialLine, Fundamentals, NewsItem, Provider, TickerMeta,
)

# Silence les loggers yfinance (les messages 'possibly delisted' passent parfois
# par des prints directs stderr qu'on ne peut pas capturer de façon async-safe —
# on a nettoyé la liste UCITS ETFs pour que les tickers invalides soient rares)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)


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

            def _fetch_info_and_cal():
                t = yf.Ticker(ticker)
                info = t.info
                # calendar : dict avec "Earnings Date" (liste de 1 ou 2 timestamps),
                # "Earnings Average", etc.
                try:
                    cal = t.calendar or {}
                except Exception:
                    cal = {}
                # earnings_dates : DataFrame des dates passées + futures
                try:
                    ed = t.earnings_dates
                except Exception:
                    ed = None
                return info, cal, ed

            try:
                info, cal, earnings_df = await loop.run_in_executor(
                    None, _fetch_info_and_cal
                )
            except Exception:
                return None
            if not info:
                return None

            # Extraction dates d'earnings (past + next)
            from datetime import datetime, timezone
            import pandas as pd
            last_date: str | None = None
            next_date: str | None = None
            try:
                if earnings_df is not None and not earnings_df.empty:
                    # earnings_df index = pd.Timestamp, en ordre décroissant (futures en haut)
                    now = datetime.now(timezone.utc)
                    past = [idx for idx in earnings_df.index
                            if idx.to_pydatetime() < now]
                    future = [idx for idx in earnings_df.index
                              if idx.to_pydatetime() >= now]
                    if past:
                        last_date = max(past).date().isoformat()
                    if future:
                        next_date = min(future).date().isoformat()
                # Fallback : calendar dict (classe selon date passée ou future)
                if cal:
                    raw = cal.get("Earnings Date")
                    if isinstance(raw, list) and raw:
                        first = raw[0]
                        if hasattr(first, "isoformat"):
                            from datetime import date as _date
                            ds = first.isoformat()[:10]
                            try:
                                d = _date.fromisoformat(ds)
                                today = _date.today()
                                if d >= today and next_date is None:
                                    next_date = ds
                                elif d < today and last_date is None:
                                    last_date = ds
                            except Exception:
                                if next_date is None:
                                    next_date = ds
            except Exception:
                pass

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
                last_earnings_date=last_date,
                next_earnings_date=next_date,
            )

    async def fetch_fundamentals(self, ticker: str) -> Fundamentals | None:
        async with self._sem:
            loop = asyncio.get_running_loop()

            def _fetch():
                t = yf.Ticker(ticker)
                return (
                    t.financials,             # income statement annuel
                    t.balance_sheet,          # bilan annuel
                    t.cashflow,               # cash flow annuel
                    t.quarterly_financials,   # compte de résultat trimestriel
                    t.quarterly_balance_sheet,
                    t.quarterly_cashflow,
                )

            try:
                (income_df, balance_df, cashflow_df,
                 income_q_df, balance_q_df, cashflow_q_df) = await loop.run_in_executor(None, _fetch)
            except Exception:
                return None

            def _period_label(col, quarterly: bool) -> str:
                if not hasattr(col, "year"):
                    return str(col)
                if not quarterly:
                    return str(col.year)
                q = (col.month - 1) // 3 + 1
                return f"Q{q}-{col.year % 100:02d}"

            def _df_to_lines(df, wanted: list[str], quarterly: bool = False,
                             max_cols: int = 3) -> tuple[list[str], list[FinancialLine]]:
                if df is None or df.empty:
                    return [], []
                # On garde uniquement les N colonnes les plus récentes
                cols = list(df.columns)[:max_cols]
                periods = [_period_label(c, quarterly) for c in cols]
                lines: list[FinancialLine] = []
                for label in wanted:
                    if label in df.index:
                        row = df.loc[label][cols]
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

            # Annuel — 3 colonnes
            periods, income_lines = _df_to_lines(income_df, income_labels, max_cols=3)
            if not periods:
                periods, _ = _df_to_lines(balance_df, balance_labels, max_cols=3)
            _, balance_lines = _df_to_lines(balance_df, balance_labels, max_cols=3)
            _, cashflow_lines = _df_to_lines(cashflow_df, cashflow_labels, max_cols=3)

            # Trimestriel — 4 colonnes
            periods_q, income_q_lines = _df_to_lines(
                income_q_df, income_labels, quarterly=True, max_cols=4)
            if not periods_q:
                periods_q, _ = _df_to_lines(
                    balance_q_df, balance_labels, quarterly=True, max_cols=4)
            _, balance_q_lines = _df_to_lines(
                balance_q_df, balance_labels, quarterly=True, max_cols=4)
            _, cashflow_q_lines = _df_to_lines(
                cashflow_q_df, cashflow_labels, quarterly=True, max_cols=4)

            return Fundamentals(
                ticker=ticker,
                periods=periods,
                income=income_lines,
                balance=balance_lines,
                cashflow=cashflow_lines,
                periods_q=periods_q,
                income_q=income_q_lines,
                balance_q=balance_q_lines,
                cashflow_q=cashflow_q_lines,
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
