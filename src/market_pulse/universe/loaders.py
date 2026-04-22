"""Loaders d'univers statiques."""
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def load_sp500() -> list[str]:
    """Charge la liste figée des tickers S&P 500."""
    lines = (DATA_DIR / "sp500.csv").read_text().strip().split("\n")
    return [line.split(",")[0].strip().upper() for line in lines[1:] if line.strip()]


def load_sp500_names() -> dict[str, str]:
    """Charge le mapping ticker → nom de société pour le S&P 500."""
    out: dict[str, str] = {}
    lines = (DATA_DIR / "sp500.csv").read_text().strip().split("\n")
    for line in lines[1:]:
        parts = line.split(",", 1)
        if len(parts) == 2:
            out[parts[0].strip().upper()] = parts[1].strip().strip('"')
    return out
