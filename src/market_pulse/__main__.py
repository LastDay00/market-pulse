"""CLI entry point : `python -m market_pulse` ou `market-pulse`."""
import asyncio
import sys

from market_pulse.config import CACHE_DB, ensure_app_dir
from market_pulse.data.providers.yfinance_provider import YFinanceProvider
from market_pulse.engine.scanner import scan
from market_pulse.ui.app import MarketPulseApp
from market_pulse.universe.loaders import load_sp500, load_sp500_names

RESCAN_RETURN_CODE = 42


async def _do_scan():
    ensure_app_dir()
    tickers = load_sp500()
    names = load_sp500_names()
    provider = YFinanceProvider(max_concurrency=10)
    print(f"· scanning {len(tickers)} tickers (horizon 1W) ...")
    opps = await scan(
        tickers=tickers,
        horizon="1w",
        provider=provider,
        cache_path=CACHE_DB,
        min_rr=2.0,
        names=names,
    )
    print(f"· found {len(opps)} opportunities")
    return opps


def main() -> int:
    """Boucle scan → UI. Si l'UI sort avec return_code=42, on rescan et on relance."""
    try:
        while True:
            opps = asyncio.run(_do_scan())
            app = MarketPulseApp(opps)
            app.run()
            if app.return_code != RESCAN_RETURN_CODE:
                return 0
            # else : rescan et relance
    except KeyboardInterrupt:
        print("\n· interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
