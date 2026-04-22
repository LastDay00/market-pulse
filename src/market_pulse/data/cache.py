"""Cache SQLite pour les barres OHLCV."""
import sqlite3
from datetime import date, datetime
from pathlib import Path

from market_pulse.data.models import Bar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_bars_ticker_date ON bars(ticker, date);
"""


class BarCache:
    """Couche de persistance SQLite pour les bars OHLCV."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def upsert_bars(self, ticker: str, bars: list[Bar]) -> None:
        rows = [
            (ticker, b.date.isoformat(), b.open, b.high, b.low, b.close, b.volume)
            for b in bars
        ]
        self._conn.executemany(
            """INSERT INTO bars (ticker, date, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ticker, date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume,
                 fetched_at=CURRENT_TIMESTAMP""",
            rows,
        )
        self._conn.commit()

    def get_bars(self, ticker: str) -> list[Bar]:
        cur = self._conn.execute(
            """SELECT date, open, high, low, close, volume
               FROM bars WHERE ticker = ? ORDER BY date ASC""",
            (ticker,),
        )
        return [
            Bar(date.fromisoformat(d), o, h, l, c, v)
            for d, o, h, l, c, v in cur.fetchall()
        ]

    def latest_date(self, ticker: str) -> date | None:
        cur = self._conn.execute(
            "SELECT MAX(date) FROM bars WHERE ticker = ?", (ticker,)
        )
        row = cur.fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None

    def latest_fetched_at(self, ticker: str) -> datetime | None:
        """Timestamp du dernier fetch pour ce ticker, None si aucun."""
        cur = self._conn.execute(
            "SELECT MAX(fetched_at) FROM bars WHERE ticker = ?", (ticker,)
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def close(self) -> None:
        self._conn.close()
