"""App Textual principale."""
from textual.app import App

from market_pulse.data.providers.base import Provider
from market_pulse.engine.scanner import Opportunity
from market_pulse.ui.screens.scanner import ScannerScreen


class MarketPulseApp(App):
    CSS_PATH = "theme.css"
    TITLE = "Market Pulse"
    SUB_TITLE = "· Trade Republic swing scanner ·"

    def __init__(self, opportunities: list[Opportunity],
                 provider: Provider | None = None) -> None:
        super().__init__()
        self.opportunities = opportunities
        # Provider exposé pour charger meta/news/fondamentaux à la demande
        # depuis l'écran détail (top 20 seulement sont pré-enrichis)
        self.provider = provider

    def on_mount(self) -> None:
        self.push_screen(ScannerScreen(self.opportunities))
