"""Dataclasses des données de marché."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Bar:
    """Une barre OHLCV quotidienne."""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError("high must be >= low")
        if self.volume < 0:
            raise ValueError("volume must be >= 0")
