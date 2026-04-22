"""Interface abstraite pour un provider de données de marché."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

from market_pulse.data.models import Bar


@dataclass(frozen=True)
class TickerMeta:
    ticker: str
    long_name: str
    short_name: str
    sector: str
    industry: str
    currency: str
    # Valorisation
    market_cap: float | None = None
    enterprise_value: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    ev_to_ebitda: float | None = None
    # Rentabilité
    profit_margin: float | None = None       # net margin
    operating_margin: float | None = None
    gross_margin: float | None = None
    return_on_equity: float | None = None
    return_on_assets: float | None = None
    # Croissance
    revenue_growth: float | None = None       # YoY
    earnings_growth: float | None = None
    # Dividende
    dividend_yield: float | None = None
    payout_ratio: float | None = None
    # Solidité bilan
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None
    # Analyste
    recommendation: str | None = None
    target_mean_price: float | None = None
    number_analysts: int | None = None
    # Earnings
    last_earnings_date: str | None = None   # ISO date, dernière publication
    next_earnings_date: str | None = None   # ISO date, prochaine publication (estimée)


@dataclass(frozen=True)
class FinancialLine:
    """Une ligne d'état financier : libellé + valeurs par période (récent → ancien)."""
    label: str
    values: list[float | None]          # len = nombre de périodes
    periods: list[str] = field(default_factory=list)  # ex. ['2024', '2023', '2022']


@dataclass(frozen=True)
class Fundamentals:
    """États financiers annuels ET trimestriels."""
    ticker: str
    # Annuel (3 dernières années)
    periods: list[str]
    income: list[FinancialLine] = field(default_factory=list)
    balance: list[FinancialLine] = field(default_factory=list)
    cashflow: list[FinancialLine] = field(default_factory=list)
    # Trimestriel (4 derniers trimestres, ex. ['Q1-26', 'Q4-25', 'Q3-25', 'Q2-25'])
    periods_q: list[str] = field(default_factory=list)
    income_q: list[FinancialLine] = field(default_factory=list)
    balance_q: list[FinancialLine] = field(default_factory=list)
    cashflow_q: list[FinancialLine] = field(default_factory=list)


@dataclass(frozen=True)
class NewsItem:
    title: str
    publisher: str
    published: datetime
    link: str


class Provider(ABC):
    """Un provider récupère des bars OHLCV pour un ticker donné."""

    @abstractmethod
    async def fetch_bars(
        self, ticker: str, start: date, end: date
    ) -> list[Bar]:
        """Récupère les bars entre start et end inclus. Retourne [] si erreur."""

    async def fetch_meta(self, ticker: str) -> TickerMeta | None:
        """Récupère les métadonnées du ticker (nom, secteur, etc.). None si erreur."""
        return None

    async def fetch_news(self, ticker: str, max_items: int = 5) -> list[NewsItem]:
        """Récupère les news récentes. Liste vide si erreur."""
        return []

    async def fetch_fundamentals(self, ticker: str) -> Fundamentals | None:
        """Récupère les états financiers annuels (income/balance/cashflow). None si erreur."""
        return None
