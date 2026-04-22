"""CLI entry point : `python -m market_pulse` ou `market-pulse`."""
import asyncio
import sys
import time

from market_pulse.config import CACHE_DB, UserSettings, ensure_app_dir
from market_pulse.data.providers.yfinance_provider import YFinanceProvider
from market_pulse.engine.scanner import scan
from market_pulse.ui.app import MarketPulseApp
from market_pulse.universe.loaders import load_universe

RESCAN_RETURN_CODE = 42

# Provider partagé entre scan et UI (pour chargement on-demand dans le détail)
_LAST_PROVIDER: "YFinanceProvider | None" = None


async def _do_scan(force_refresh: bool = False, settings: UserSettings | None = None):
    ensure_app_dir()
    settings = settings or UserSettings.load()
    names = load_universe()
    tickers = sorted(names.keys())
    provider = YFinanceProvider(max_concurrency=10)
    global _LAST_PROVIDER
    _LAST_PROVIDER = provider

    mode = "force refresh (cache bypass)" if force_refresh else "cache-aware"
    print(f"· scanning {len(tickers)} tickers "
          f"(horizon {settings.horizon.upper()}, "
          f"R/R ≥ {settings.min_rr}, "
          f"{mode}) ...")
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
        horizon=settings.horizon,
        provider=provider,
        cache_path=CACHE_DB,
        min_rr=settings.min_rr,
        names=names,
        force_refresh=force_refresh,
        progress_callback=on_progress,
    )
    elapsed = time.time() - t0
    print(f"\n· found {len(opps)} opportunities in {elapsed:.1f}s")
    return opps


def main() -> int:
    """Boucle scan → UI. Les changements de settings dans la palette
    déclenchent un exit(42) qui relance le scan avec les nouveaux params."""
    force_refresh = False
    try:
        while True:
            settings = UserSettings.load()
            opps = asyncio.run(_do_scan(force_refresh=force_refresh,
                                         settings=settings))
            app = MarketPulseApp(opps, provider=_LAST_PROVIDER,
                                 settings=settings)
            app.run()
            if app.return_code != RESCAN_RETURN_CODE:
                return 0
            force_refresh = True
    except KeyboardInterrupt:
        print("\n· interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
