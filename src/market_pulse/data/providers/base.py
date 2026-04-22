"""Interface abstraite pour un provider de données de marché."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
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
