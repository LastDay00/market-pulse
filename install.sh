#!/usr/bin/env bash
# Market Pulse — installation script
#
# Crée un virtualenv propre, installe toutes les dépendances et le package.
# Idempotent : peut être relancé sans risque pour réparer un venv cassé.
#
# Usage :
#   ./install.sh           # install standard
#   ./install.sh --clean   # supprime l'ancien venv avant install
#   ./install.sh --dev     # installe aussi les dépendances de test (pytest, etc.)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

CLEAN=0
DEV=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        --dev)   DEV=1 ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "Argument inconnu : $arg" >&2
            exit 2
            ;;
    esac
done

# 1. Vérifier uv
if ! command -v uv >/dev/null 2>&1; then
    echo "uv n'est pas installé."
    echo "Installation rapide : curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "Voir https://docs.astral.sh/uv/ pour les autres méthodes."
    exit 1
fi

# 2. Clean éventuel
if [[ "$CLEAN" -eq 1 && -d .venv ]]; then
    echo "· suppression de l'ancien venv"
    rm -rf .venv
fi

# 3. Sync des dépendances
echo "· uv sync"
if [[ "$DEV" -eq 1 ]]; then
    uv sync --all-extras
else
    uv sync
fi

# 4. Workaround macOS : Python 3.12.5+ ignore les fichiers .pth marqués UF_HIDDEN.
#    Certains setups (Spotlight, attributs hérités) marquent les .pth créés par
#    uv comme « hidden », ce qui casse l'editable install. On enlève le flag.
if [[ "$OSTYPE" == "darwin"* ]]; then
    PTH_FILES=( .venv/lib/python*/site-packages/*.pth )
    if [[ -e "${PTH_FILES[0]}" ]]; then
        chflags nohidden "${PTH_FILES[@]}" 2>/dev/null || true
    fi
fi

# 5. Smoke test : le package est-il bien importable ?
if ! uv run python -c "import market_pulse" 2>/dev/null; then
    echo
    echo "Erreur : market_pulse n'est pas importable malgré l'install."
    echo "Tente : ./install.sh --clean"
    exit 1
fi

echo
echo "Installation terminée. Lance :"
echo "    uv run market-pulse"
