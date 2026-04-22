"""Classe abstraite Signal."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SignalResult:
    """Résultat d'un signal : score 0-100 + métadonnées explicatives."""
    score: float
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError(f"score must be 0-100, got {self.score}")


class Signal(ABC):
    """Un signal analyse un DataFrame OHLCV et retourne un SignalResult."""

    name: str
    weight: float  # poids par défaut dans le scoring

    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        """df a au minimum les colonnes Open, High, Low, Close, Volume, indexé par date."""
