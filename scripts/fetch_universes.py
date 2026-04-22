"""Télécharge les composants de plusieurs indices depuis Wikipedia
et les écrit dans src/market_pulse/universe/data/<index>.csv.
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
    with urllib.request.urlopen(req, context=_CTX, timeout=30) as resp:
        html = resp.read().decode("utf-8")
    return pd.read_html(StringIO(html))


def _clean_ticker(raw: str, suffix: str) -> str:
    t = str(raw).strip().upper()
    if ":" in t:
        t = t.split(":", 1)[1].strip()
    t = re.sub(r"\s+", "", t)
    if "." in t:  # déjà suffixé
        return t
    return t + suffix if suffix else t


def _write_csv(rows: list[tuple[str, str]], out: Path) -> None:
    clean: set[tuple[str, str]] = set()
    for t, n in rows:
        t = str(t).strip().upper()
        n = str(n).strip().replace(",", "")
        if not t or not n or t == "NAN":
            continue
        clean.add((t, n))
    out.write_text("ticker,name\n" + "\n".join(f"{t},{n}" for t, n in sorted(clean)) + "\n")
    print(f"wrote {out.name:<18}  ({len(clean)} tickers)")


def _find_table(tables, ticker_keys=("ticker", "symbol"),
                name_keys=("company", "security", "name")) -> pd.DataFrame | None:
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
    try:
        tables = _read_tables(url)
    except Exception as e:
        print(f"{out_name}: FETCH FAILED ({e})")
        return
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


def fetch_sp600() -> None:
    """S&P SmallCap 600 : alternative propre à Russell 2000 (600 small caps US)."""
    tables = _read_tables("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies")
    df = tables[0]
    df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
    _write_csv(list(zip(df["Symbol"], df["Security"])), OUT / "sp600.csv")


if __name__ == "__main__":
    # Large caps US
    fetch_sp500()
    fetch_index("https://en.wikipedia.org/wiki/Nasdaq-100", "", "nasdaq100.csv")

    # Small caps US (équivalent Russell 2000 avec data propre)
    fetch_sp600()

    # Large caps Europe
    fetch_index("https://en.wikipedia.org/wiki/CAC_40", ".PA", "cac40.csv")
    fetch_index("https://en.wikipedia.org/wiki/CAC_Next_20", ".PA", "cac_next20.csv")
    fetch_index("https://en.wikipedia.org/wiki/DAX", ".DE", "dax40.csv")
    fetch_index("https://en.wikipedia.org/wiki/Swiss_Market_Index", ".SW", "smi.csv")
    fetch_index("https://en.wikipedia.org/wiki/AEX_index", ".AS", "aex25.csv")
    fetch_index("https://en.wikipedia.org/wiki/FTSE_100_Index", ".L", "ftse100.csv")
    fetch_index("https://en.wikipedia.org/wiki/FTSE_MIB", ".MI", "ftsemib.csv")
    fetch_index("https://en.wikipedia.org/wiki/IBEX_35", ".MC", "ibex35.csv")
    fetch_index("https://en.wikipedia.org/wiki/BEL_20", ".BR", "bel20.csv")
    fetch_index("https://en.wikipedia.org/wiki/OMX_Stockholm_30", ".ST", "omxs30.csv")

    # Pan-européen : les tickers sont déjà suffixés (ADS.DE, ASML.AS, etc.)
    fetch_index("https://en.wikipedia.org/wiki/EURO_STOXX_50", "", "stoxx50.csv")
