.PHONY: install install-dev clean run test lint help

help:
	@echo "Market Pulse — Makefile"
	@echo ""
	@echo "  make install       Installe le projet et ses dépendances"
	@echo "  make install-dev   Installe aussi les dépendances de test"
	@echo "  make clean         Supprime venv, caches et artefacts de build"
	@echo "  make run           Lance le scanner (uv run market-pulse)"
	@echo "  make test          Lance la suite pytest"

install:
	./install.sh

install-dev:
	./install.sh --dev

clean:
	rm -rf .venv build dist *.egg-info .pytest_cache .coverage htmlcov
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +

run:
	uv run market-pulse

test:
	uv run --extra dev pytest -q
