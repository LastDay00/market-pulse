"""Loaders d'univers statiques."""
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def load_sp500() -> list[str]:
    """Charge la liste figée des tickers S&P 500."""
    lines = (DATA_DIR / "sp500.csv").read_text().strip().split("\n")
    return [line.strip().upper() for line in lines[1:] if line.strip()]
