"""CLI entry point : `python -m market_pulse` ou `market-pulse`."""
import asyncio
import sys

from market_pulse.config import CACHE_DB, ensure_app_dir
from market_pulse.data.providers.yfinance_provider import YFinanceProvider
from market_pulse.engine.scanner import scan
from market_pulse.ui.app import MarketPulseApp
from market_pulse.universe.loaders import load_sp500


async def _do_scan():
    ensure_app_dir()
    tickers = load_sp500()
    provider = YFinanceProvider(max_concurrency=10)
    print(f"· scanning {len(tickers)} tickers (horizon 1W) ...")
    opps = await scan(
        tickers=tickers,
        horizon="1w",
        provider=provider,
        cache_path=CACHE_DB,
        min_rr=2.0,
    )
    print(f"· found {len(opps)} opportunities")
    return opps


def main() -> int:
    try:
        opps = asyncio.run(_do_scan())
    except KeyboardInterrupt:
        print("\n· interrupted")
        return 130

    app = MarketPulseApp(opps)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
