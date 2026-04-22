"""App Textual principale."""
from textual.app import App

from market_pulse.config import UserSettings
from market_pulse.data.providers.base import Provider
from market_pulse.engine.scanner import Opportunity
from market_pulse.ui.commands import SettingsProvider
from market_pulse.ui.screens.scanner import ScannerScreen


class MarketPulseApp(App):
    CSS_PATH = "theme.css"
    TITLE = "Market Pulse"
    SUB_TITLE = "· Trade Republic swing scanner ·"

    # Ajoute notre provider à la palette (Ctrl+P)
    COMMANDS = App.COMMANDS | {SettingsProvider}

    def __init__(self, opportunities: list[Opportunity],
                 provider: Provider | None = None,
                 settings: UserSettings | None = None) -> None:
        super().__init__()
        self.opportunities = opportunities
        self.provider = provider
        self.settings = settings or UserSettings.load()
        self.direction_filter = self.settings.direction_filter

    def on_mount(self) -> None:
        self.push_screen(ScannerScreen(self._filtered_opportunities()))

    def _filtered_opportunities(self) -> list[Opportunity]:
        """Filtre les opportunités selon la préférence direction courante."""
        if self.direction_filter == "both":
            return self.opportunities
        return [
            o for o in self.opportunities
            if o.trade_plan.direction == self.direction_filter
        ]

    def refresh_scanner_filter(self) -> None:
        """Recompose l'écran scanner avec le filtre direction courant."""
        try:
            self.pop_screen()
        except Exception:
            pass
        self.push_screen(ScannerScreen(self._filtered_opportunities()))
