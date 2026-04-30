#!/usr/bin/env bash
# Market Pulse — installation script
#
# Crée un virtualenv propre, installe toutes les dépendances et le package.
# Idempotent : peut être relancé sans risque pour réparer un venv cassé.
#
# Sur macOS, si le projet est sous ~/Documents (synchronisé par iCloud par
# défaut), le venv est placé hors d'iCloud, dans
# ~/Library/Caches/<nom-projet>/venv, pour éviter qu'iCloud n'évince des
# fichiers du venv et casse les imports.
#
# Usage :
#   ./install.sh           # install standard
#   ./install.sh --clean   # supprime l'ancien venv avant install
#   ./install.sh --nuke    # supprime venv ET cache uv (recours en cas de cache corrompu)
#   ./install.sh --dev     # installe aussi les dépendances de test (pytest, etc.)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PROJECT_NAME="$(basename "$REPO_ROOT")"

CLEAN=0
NUKE=0
DEV=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        --nuke)  CLEAN=1; NUKE=1 ;;
        --dev)   DEV=1 ;;
        -h|--help)
            sed -n '2,18p' "$0"
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

# 2. Détecter si on est dans un dossier synchronisé (iCloud / Dropbox / OneDrive).
#    Si oui, on place le venv dans ~/Library/Caches/<projet>/venv pour échapper
#    à la sync — sinon iCloud peut évincer des fichiers du venv et casser les
#    imports (typique : numpy/pandas qui perdent leur __init__.py).
EXTERNAL_VENV=0
case "$REPO_ROOT" in
    "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Dropbox"*|*"OneDrive"*|*"iCloud"*|"$HOME/Library/Mobile Documents/"*)
        EXTERNAL_VENV=1
        ;;
esac

if [[ "$EXTERNAL_VENV" -eq 1 ]]; then
    VENV_PATH="$HOME/Library/Caches/$PROJECT_NAME/venv"
    mkdir -p "$(dirname "$VENV_PATH")"
    export UV_PROJECT_ENVIRONMENT="$VENV_PATH"
    echo "· dossier synchronisé détecté → venv hors-projet : $VENV_PATH"
else
    VENV_PATH="$REPO_ROOT/.venv"
    export UV_PROJECT_ENVIRONMENT="$VENV_PATH"
fi

# 3. Clean éventuel
if [[ "$CLEAN" -eq 1 && -d "$VENV_PATH" ]]; then
    echo "· suppression de l'ancien venv ($VENV_PATH)"
    rm -rf "$VENV_PATH"
fi
# Aussi nettoyer un éventuel .venv résiduel dans le projet (legacy).
if [[ "$EXTERNAL_VENV" -eq 1 && -e "$REPO_ROOT/.venv" ]]; then
    echo "· suppression du .venv local résiduel"
    rm -rf "$REPO_ROOT/.venv"
fi
if [[ "$NUKE" -eq 1 ]]; then
    echo "· purge du cache uv"
    uv cache clean >/dev/null 2>&1 || true
fi

# 4. Sync des dépendances
echo "· uv sync"
if [[ "$DEV" -eq 1 ]]; then
    uv sync --all-extras
else
    uv sync
fi

# 5. Workaround macOS : Python 3.12.5+ ignore les fichiers .pth marqués UF_HIDDEN.
#    On retire ce flag systématiquement.
if [[ "$OSTYPE" == "darwin"* ]]; then
    PTH_FILES=( "$VENV_PATH"/lib/python*/site-packages/*.pth )
    if [[ -e "${PTH_FILES[0]}" ]]; then
        chflags nohidden "${PTH_FILES[@]}" 2>/dev/null || true
    fi
fi

# 6. Détection d'install corrompue : un .dist-info présent sans le module qui
#    va avec (typique d'un cache uv abîmé). On retente une fois avec un venv
#    et un cache propres.
check_install() {
    local pkg
    for pkg in pandas pandas_ta numpy yfinance market_pulse; do
        if ! uv run python -c "import $pkg" >/dev/null 2>&1; then
            return 1
        fi
    done
    return 0
}

if ! check_install; then
    if [[ "$NUKE" -eq 1 ]]; then
        echo
        echo "Erreur : un module reste introuvable après --nuke." >&2
        echo "Lance ./install.sh --nuke à la main et inspecte la sortie." >&2
        exit 1
    fi
    echo
    echo "· install corrompue détectée — relance avec venv et cache propres"
    rm -rf "$VENV_PATH"
    uv cache clean >/dev/null 2>&1 || true
    if [[ "$DEV" -eq 1 ]]; then
        uv sync --all-extras
    else
        uv sync
    fi
    if [[ "$OSTYPE" == "darwin"* ]]; then
        PTH_FILES=( "$VENV_PATH"/lib/python*/site-packages/*.pth )
        if [[ -e "${PTH_FILES[0]}" ]]; then
            chflags nohidden "${PTH_FILES[@]}" 2>/dev/null || true
        fi
    fi
    if ! check_install; then
        echo
        echo "Erreur : install toujours cassée après recovery." >&2
        echo "Vérifie ta version de Python (>=3.12,<3.14) et la connexion réseau." >&2
        exit 1
    fi
fi

echo
echo "Installation terminée."
if [[ "$EXTERNAL_VENV" -eq 1 ]]; then
    echo
    echo "  Le venv est hors d'iCloud : $VENV_PATH"
    echo "  Lance via :  ./mp"
    echo "  Ou :         make run"
    echo
    echo "  Évite \`uv run market-pulse\` directement : sans la variable"
    echo "  UV_PROJECT_ENVIRONMENT, uv recréera un venv local dans iCloud."
else
    echo "  Lance :  uv run market-pulse"
fi
