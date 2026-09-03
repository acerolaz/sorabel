# Cibles standard — voir ../.claude/rules/makefile-conventions.md
#
# Exception outillage Python : pas d'installation ni de Dockerfile par projet.
# Le pyproject.toml, le docker-compose.yml et le .env sont partagés à la racine
# de la solution (voir ../CLAUDE.md § Commandes) — ce projet s'exécute depuis
# son propre répertoire de travail, jamais installé en site-packages.

.PHONY: build test lint clean

build:
	cd .. && pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
