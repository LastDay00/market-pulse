"""Télécharge la liste des composants du S&P 500 depuis Wikipedia
et l'écrit dans src/market_pulse/universe/data/sp500.csv.

À lancer une seule fois (ou à chaque rebalancement du S&P 500).
"""
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "src" / "market_pulse" / "universe" / "data" / "sp500.csv"

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def main() -> None:
    tables = pd.read_html(URL)
    df = tables[0]
    # Colonne 'Symbol' contient les tickers
    tickers = df["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    tickers = sorted(set(t.strip().upper() for t in tickers if t.strip()))
    OUT.write_text("ticker\n" + "\n".join(tickers) + "\n")
    print(f"wrote {OUT} ({len(tickers)} tickers)")


if __name__ == "__main__":
    main()
