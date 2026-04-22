"""Télécharge les composants de plusieurs indices depuis Wikipedia
et les écrit dans src/market_pulse/universe/data/<index>.csv.

Couvre : S&P 500, Nasdaq 100, CAC 40, CAC Next 20, DAX 40, FTSE MIB, IBEX 35.
"""
from __future__ import annotations

import re
import ssl
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "src" / "market_pulse" / "universe" / "data"
OUT.mkdir(parents=True, exist_ok=True)

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _read_tables(url: str) -> list[pd.DataFrame]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=_CTX) as resp:
        html = resp.read().decode("utf-8")
    return pd.read_html(StringIO(html))


def _clean_ticker(raw: str, suffix: str) -> str:
    """Normalise un ticker Wikipedia en ajoutant le suffixe yfinance approprié.

    Exemples :
      _clean_ticker('MC', '.PA')                  -> 'MC.PA'
      _clean_ticker('MC.PA', '.PA')               -> 'MC.PA'
      _clean_ticker('EURONEXT PARIS: AC.PA', '.PA') -> 'AC.PA'
      _clean_ticker('XETRA: SAP.DE', '.DE')       -> 'SAP.DE'
    """
    t = str(raw).strip().upper()
    # Retire un éventuel préfixe "EXCHANGE NAME: "
    if ":" in t:
        t = t.split(":", 1)[1].strip()
    # Retire caractères parasites (liens Wikipedia)
    t = re.sub(r"\s+", "", t)
    # Si le ticker a déjà un suffixe (contient un point), on le garde tel quel
    if "." in t:
        return t
    return t + suffix


def _write_csv(rows: list[tuple[str, str]], out: Path) -> None:
    clean: set[tuple[str, str]] = set()
    for t, n in rows:
        t = t.strip().upper()
        n = str(n).strip()
        if not t or not n or t == "NAN":
            continue
        # Retire virgules du nom (notre CSV parser est basique)
        n = n.replace(",", "")
        clean.add((t, n))
    out.write_text("ticker,name\n" + "\n".join(f"{t},{n}" for t, n in sorted(clean)) + "\n")
    print(f"wrote {out.name:<18}  ({len(clean)} tickers)")


def _find_table(tables, ticker_keys=("ticker", "symbol"),
                name_keys=("company", "security", "name")) -> pd.DataFrame | None:
    """Trouve la première table Wikipedia avec une colonne 'ticker' et 'company'."""
    for t in tables:
        cols = {str(c).lower(): c for c in t.columns}
        ticker_col = next((cols[k] for k in cols if any(tk in k for tk in ticker_keys)), None)
        name_col = next((cols[k] for k in cols if any(nk in k for nk in name_keys)), None)
        if ticker_col is not None and name_col is not None:
            t = t[[ticker_col, name_col]].copy()
            t.columns = ["ticker", "name"]
            return t
    return None


def fetch_index(url: str, suffix: str, out_name: str) -> None:
    tables = _read_tables(url)
    t = _find_table(tables)
    if t is None:
        print(f"{out_name}: composition table not found")
        return
    rows = [(_clean_ticker(tk, suffix), nm) for tk, nm in zip(t["ticker"], t["name"])]
    _write_csv(rows, OUT / out_name)


def fetch_sp500() -> None:
    tables = _read_tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    df = tables[0]
    df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
    _write_csv(list(zip(df["Symbol"], df["Security"])), OUT / "sp500.csv")


if __name__ == "__main__":
    fetch_sp500()
    fetch_index("https://en.wikipedia.org/wiki/Nasdaq-100", "", "nasdaq100.csv")
    fetch_index("https://en.wikipedia.org/wiki/CAC_40", ".PA", "cac40.csv")
    fetch_index("https://en.wikipedia.org/wiki/CAC_Next_20", ".PA", "cac_next20.csv")
    fetch_index("https://en.wikipedia.org/wiki/DAX", ".DE", "dax40.csv")
    fetch_index("https://en.wikipedia.org/wiki/FTSE_MIB", ".MI", "ftsemib.csv")
    fetch_index("https://en.wikipedia.org/wiki/IBEX_35", ".MC", "ibex35.csv")
