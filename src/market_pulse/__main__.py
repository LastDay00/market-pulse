"""CLI entry point : `python -m market_pulse` ou `market-pulse`."""
import asyncio
import sys
import time

from market_pulse.config import CACHE_DB, ensure_app_dir
from market_pulse.data.providers.yfinance_provider import YFinanceProvider
from market_pulse.engine.scanner import scan
from market_pulse.ui.app import MarketPulseApp
from market_pulse.universe.loaders import load_universe

RESCAN_RETURN_CODE = 42


async def _do_scan(force_refresh: bool = False):
    ensure_app_dir()
    # Univers combiné : S&P 500 + Nasdaq 100 + CAC 40 + CAC Next 20 + DAX + FTSE MIB + IBEX 35
    names = load_universe()
    tickers = sorted(names.keys())
    provider = YFinanceProvider(max_concurrency=10)

    mode = "force refresh (cache bypass)" if force_refresh else "cache-aware"
    print(f"· scanning {len(tickers)} tickers across 7 indices (horizon 1W, {mode}) ...")
    t0 = time.time()

    last_print = [0.0]
    def on_progress(done: int, total: int, ticker: str) -> None:
        now = time.time()
        if now - last_print[0] > 0.5 or done == total:
            pct = done / total * 100
            bar_len = 30
            filled = int(done / total * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"\r  {bar} {done:>3}/{total}  {pct:5.1f}%  {ticker:<8}",
                  end="", flush=True)
            last_print[0] = now

    opps = await scan(
        tickers=tickers,
        horizon="1w",
        provider=provider,
        cache_path=CACHE_DB,
        min_rr=2.0,
        names=names,
        force_refresh=force_refresh,
        progress_callback=on_progress,
    )
    elapsed = time.time() - t0
    print(f"\n· found {len(opps)} opportunities in {elapsed:.1f}s")
    return opps


def main() -> int:
    """Boucle scan → UI. Sur return_code=42, force-refresh et relance."""
    force_refresh = False
    try:
        while True:
            opps = asyncio.run(_do_scan(force_refresh=force_refresh))
            app = MarketPulseApp(opps)
            app.run()
            if app.return_code != RESCAN_RETURN_CODE:
                return 0
            # Relance avec force_refresh=True : R signifie "je veux des données fraîches"
            force_refresh = True
    except KeyboardInterrupt:
        print("\n· interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
