"""Chemins et paramètres globaux."""
from pathlib import Path

APP_DIR = Path.home() / ".market-pulse"
CACHE_DB = APP_DIR / "cache.db"


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
