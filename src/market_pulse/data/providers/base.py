"""Interface abstraite pour un provider de données de marché."""
from abc import ABC, abstractmethod
from datetime import date

from market_pulse.data.models import Bar


class Provider(ABC):
    """Un provider récupère des bars OHLCV pour un ticker donné."""

    @abstractmethod
    async def fetch_bars(
        self, ticker: str, start: date, end: date
    ) -> list[Bar]:
        """Récupère les bars entre start et end inclus. Retourne [] si erreur."""
