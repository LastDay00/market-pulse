"""Loaders d'univers statiques."""
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Nom lisible → nom du fichier CSV
AVAILABLE_INDICES = {
    # US
    "sp500":       "sp500.csv",          # S&P 500 large caps
    "nasdaq100":   "nasdaq100.csv",      # Nasdaq 100 tech-heavy
    "sp600":       "sp600.csv",          # S&P SmallCap 600 (équivalent Russell 2000 propre)
    # France
    "cac40":       "cac40.csv",
    "cac_next20":  "cac_next20.csv",
    # Allemagne / Autriche / Suisse
    "dax40":       "dax40.csv",
    "smi":         "smi.csv",
    # Benelux
    "aex25":       "aex25.csv",
    "bel20":       "bel20.csv",
    # UK
    "ftse100":     "ftse100.csv",
    # Sud Europe
    "ftsemib":     "ftsemib.csv",
    "ibex35":      "ibex35.csv",
    # Scandinavie
    "omxs30":      "omxs30.csv",
    # Pan-européen
    "stoxx50":     "stoxx50.csv",
    # ETFs UCITS (focus investisseur européen sur TR)
    "ucits_etfs":  "ucits_etfs.csv",
}


def _load_index_file(csv_file: Path) -> dict[str, str]:
    """Charge un CSV ticker,name et retourne {ticker: name}."""
    out: dict[str, str] = {}
    if not csv_file.exists():
        return out
    for line in csv_file.read_text().strip().split("\n")[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 1)
        if len(parts) != 2:
            continue
        ticker = parts[0].strip().upper()
        name = parts[1].strip().strip('"')
        if ticker:
            out[ticker] = name
    return out


def load_sp500() -> list[str]:
    return list(_load_index_file(DATA_DIR / "sp500.csv").keys())


def load_sp500_names() -> dict[str, str]:
    return _load_index_file(DATA_DIR / "sp500.csv")


def load_universe(indices: list[str] | None = None) -> dict[str, str]:
    """Charge un ou plusieurs indices et fusionne en un dict {ticker: name} dédupliqué.

    Args:
        indices: noms d'indices à charger (keys de AVAILABLE_INDICES). None = tous.

    Returns:
        Dict mapping ticker → nom de société, dédupliqué.
    """
    if indices is None:
        indices = list(AVAILABLE_INDICES.keys())
    merged: dict[str, str] = {}
    for name in indices:
        if name not in AVAILABLE_INDICES:
            continue
        merged.update(_load_index_file(DATA_DIR / AVAILABLE_INDICES[name]))
    return merged
