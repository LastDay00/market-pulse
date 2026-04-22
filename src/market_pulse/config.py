"""Chemins et paramètres globaux."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

APP_DIR = Path.home() / ".market-pulse"
CACHE_DB = APP_DIR / "cache.db"
SETTINGS_FILE = APP_DIR / "settings.json"


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class UserSettings:
    """Préférences utilisateur persistées dans ~/.market-pulse/settings.json."""
    horizon: str = "1w"
    min_rr: float = 2.0
    direction_filter: str = "both"       # "long" | "short" | "both"
    blend_fundamentals: bool = True      # top 20 : blend score tech + fonda

    @classmethod
    def load(cls) -> "UserSettings":
        if not SETTINGS_FILE.exists():
            return cls()
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            # Ignore les clés inconnues (compat forward)
            known = {f.name for f in cls.__dataclass_fields__.values()}
            return cls(**{k: v for k, v in data.items() if k in known})
        except Exception:
            return cls()

    def save(self) -> None:
        ensure_app_dir()
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2))
