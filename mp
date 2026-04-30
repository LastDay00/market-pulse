#!/usr/bin/env bash
# Market Pulse — wrapper de lancement.
#
# But : forcer uv à utiliser un virtualenv situé HORS d'iCloud Drive (et autres
# systèmes de sync style Dropbox / OneDrive). En effet, si le projet est sous
# ~/Documents (synchronisé par iCloud sur macOS par défaut), iCloud évince
# régulièrement des fichiers du venv — les .dist-info restent mais les modules
# disparaissent, ce qui casse les imports (numpy, pandas, ...).
#
# La variable UV_PROJECT_ENVIRONMENT dit à uv où placer le venv ; on la pointe
# vers ~/Library/Caches/<nom-du-projet>/venv, qui n'est jamais synchronisé.
#
# Usage : ./mp [args...]   ─ équivalent de `uv run market-pulse [args...]`

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$REPO_ROOT")"

export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/Library/Caches/$PROJECT_NAME/venv}"

cd "$REPO_ROOT"
exec uv run market-pulse "$@"
