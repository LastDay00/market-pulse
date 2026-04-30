.PHONY: install install-dev clean run test help

# Sur macOS, si le projet est sous ~/Documents (synchronisé par iCloud), on
# place le venv hors du projet pour qu'iCloud n'évince pas les modules. La
# logique de détection est dans install.sh ; ici on se contente d'utiliser le
# wrapper ./mp qui exporte UV_PROJECT_ENVIRONMENT au lancement.

help:
	@echo "Market Pulse — Makefile"
	@echo ""
	@echo "  make install       Installe le projet et ses dépendances"
	@echo "  make install-dev   Installe aussi les dépendances de test"
	@echo "  make clean         Supprime venv (local et externe), caches et builds"
	@echo "  make run           Lance le scanner (via ./mp)"
	@echo "  make test          Lance la suite pytest"

install:
	./install.sh

install-dev:
	./install.sh --dev

clean:
	rm -rf .venv build dist *.egg-info .pytest_cache .coverage htmlcov
	rm -rf "$$HOME/Library/Caches/market-pulse"
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +

run:
	./mp

test:
	UV_PROJECT_ENVIRONMENT="$$HOME/Library/Caches/market-pulse/venv" uv run --extra dev pytest -q
