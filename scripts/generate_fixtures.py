"""Génère les fixtures CSV depuis yfinance (à lancer une seule fois).
Les CSV produits sont ensuite commités pour que les tests tournent offline.
"""
from pathlib import Path

import yfinance as yf

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)


def dump_bars(ticker: str, period: str, out: Path) -> None:
    df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    df = df[["Open", "High", "Low", "Close", "Volume"]].round(4)
    df.index = df.index.tz_localize(None)
    df.to_csv(out, index_label="date")
    print(f"wrote {out} ({len(df)} rows)")


if __name__ == "__main__":
    dump_bars("ASML", "1y", FIXTURES / "asml_bars_1y.csv")

    sample_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META",
                      "NVDA", "TSLA", "JPM", "JNJ", "V"]
    (FIXTURES / "sp500_sample.csv").write_text(
        "ticker\n" + "\n".join(sample_tickers) + "\n"
    )
    print(f"wrote sp500_sample.csv ({len(sample_tickers)} tickers)")
