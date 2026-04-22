"""Command palette (Ctrl+P) : paramétrage rapide de Market Pulse.

Expose les horizons, filtres direction, seuils R/R et actions globales.
Un changement qui nécessite un rescan (horizon, min R/R) sauvegarde les
settings puis sort l'app avec return_code=42 → le main loop relance un
scan avec les nouveaux paramètres.
"""
from __future__ import annotations

from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider

from market_pulse.config import UserSettings

RESCAN_RETURN_CODE = 42


class SettingsProvider(Provider):
    """Fournisseur de commandes pour la palette Ctrl+P."""

    def _build_commands(self) -> list[tuple[str, callable, str]]:
        commands: list[tuple[str, callable, str]] = []

        # --- Horizon ---
        for code, label, desc in [
            ("1d", "Horizon · 1 jour",     "Intraday / day trading"),
            ("1w", "Horizon · 1 semaine",  "Swing trading court (défaut)"),
            ("1m", "Horizon · 1 mois",     "Swing trading moyen"),
            ("1y", "Horizon · 1 an",       "Position trading / investissement court"),
            ("3y", "Horizon · 3 ans",      "Investissement moyen terme"),
            ("5y", "Horizon · 5 ans",      "Investissement long terme"),
            ("10y", "Horizon · 10 ans",    "Buy & hold / retraite"),
        ]:
            commands.append((label, partial(self._set_horizon, code), desc))

        # --- Direction filter ---
        commands.extend([
            ("Filtre · Afficher LONG + SHORT",
             partial(self._set_direction, "both"),
             "Montrer toutes les opportunités"),
            ("Filtre · LONG uniquement",
             partial(self._set_direction, "long"),
             "Cacher les shorts"),
            ("Filtre · SHORT uniquement",
             partial(self._set_direction, "short"),
             "Cacher les longs"),
        ])

        # --- Min R/R ---
        for rr in [1.5, 2.0, 2.5, 3.0]:
            commands.append((
                f"Ratio R/R minimum · {rr}",
                partial(self._set_min_rr, rr),
                "Filtre : seulement les trades avec reward/risk ≥ seuil",
            ))

        # --- Scoring mode ---
        commands.extend([
            ("Scoring · Technique pur",
             partial(self._set_scoring, "technical"),
             "Score 100% basé sur les signaux techniques (RSI, MACD, volumes…)"),
            ("Scoring · Blend tech + fonda (80/20)",
             partial(self._set_scoring, "blended"),
             "Top 20 re-scoré en mixant technique (80%) et fondamentaux (20%)"),
            ("Scoring · Fondamental pur",
             partial(self._set_scoring, "fundamental"),
             "Score = ratios financiers uniquement — enrichit 200 tickers "
             "(scan +1-3 min). Idéal pour l'investissement long terme."),
        ])

        # --- Actions globales ---
        commands.extend([
            ("Relancer le scan (force refresh)",
             self._force_refresh,
             "Re-fetch toutes les bars depuis yfinance (bypass du cache)"),
            ("Afficher les paramètres courants",
             self._show_settings,
             "Affiche horizon, R/R min, filtre direction, blend"),
        ])
        return commands

    async def discover(self) -> Hits:
        """Affiché quand la palette s'ouvre sans texte tapé."""
        for name, cb, help_text in self._build_commands():
            yield DiscoveryHit(name, cb, help=help_text)

    async def search(self, query: str) -> Hits:
        """Filtre selon la chaîne tapée par l'utilisateur."""
        matcher = self.matcher(query)
        for name, cb, help_text in self._build_commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    cb,
                    help=help_text,
                )

    # --- Handlers ---

    def _set_horizon(self, horizon: str) -> None:
        s = UserSettings.load()
        s.horizon = horizon
        s.save()
        self.app.notify(f"Horizon → {horizon} · relance du scan …",
                        timeout=3.0)
        self.app.exit(return_code=RESCAN_RETURN_CODE)

    def _set_min_rr(self, rr: float) -> None:
        s = UserSettings.load()
        s.min_rr = rr
        s.save()
        self.app.notify(f"R/R min → {rr} · relance du scan …", timeout=3.0)
        self.app.exit(return_code=RESCAN_RETURN_CODE)

    def _set_direction(self, direction: str) -> None:
        s = UserSettings.load()
        s.direction_filter = direction
        s.save()
        # Filtre purement affichage : on le relit depuis le scanner au runtime
        self.app.direction_filter = direction
        self.app.refresh_scanner_filter()
        label = {"both": "long + short", "long": "long", "short": "short"}[direction]
        self.app.notify(f"Filtre direction → {label}")

    def _set_scoring(self, mode: str) -> None:
        s = UserSettings.load()
        s.scoring_mode = mode
        s.save()
        label = {"technical": "technique pur",
                 "blended": "blend 80/20",
                 "fundamental": "fondamental pur"}[mode]
        self.app.notify(f"Scoring → {label} · relance du scan …", timeout=3.0)
        self.app.exit(return_code=RESCAN_RETURN_CODE)

    def _force_refresh(self) -> None:
        self.app.notify("Refresh forcé · bars re-fetchées depuis yfinance …",
                        timeout=3.0)
        self.app.exit(return_code=RESCAN_RETURN_CODE)

    def _show_settings(self) -> None:
        s = UserSettings.load()
        self.app.notify(
            f"horizon={s.horizon}  ·  R/R min={s.min_rr}"
            f"  ·  direction={s.direction_filter}"
            f"  ·  scoring={s.scoring_mode}",
            timeout=10.0,
        )