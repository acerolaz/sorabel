# Cibles standard — voir ../.claude/rules/makefile-conventions.md
#
# Exception outillage Python : pas d'installation ni de Dockerfile par projet.
# Le pyproject.toml, le docker-compose.yml et le .env sont partagés à la racine
# de la solution (voir ../CLAUDE.md § Commandes) — ce projet s'exécute depuis
# son propre répertoire de travail, jamais installé en site-packages.

.PHONY: build test test-e2e lint clean

build:
	cd .. && pip install -e ".[dev]"

# Niveaux 1 a 3 (voir ../.claude/rules/testing-pyramid.md) : rapide, sans le
# niveau 4, qui a sa propre cible parce qu'il demarre des conteneurs.
test:
	pytest --ignore=tests/acceptance

# Niveau 4 uniquement : demarre les dependances reelles, puis les arrete.
test-e2e:
	@test -n "$$(find tests/acceptance -name 'test_*.py' -print -quit)" || \
	  { echo "make test-e2e : niveau 4 non implemente — tests/acceptance/ ne contient aucun test"; \
	    echo "                voir tests/acceptance/README.md pour ce qu'il doit contenir"; exit 1; }
	(cd .. && docker compose up -d --wait postgres) || (cd .. && docker compose down; exit 1)
	pytest tests/acceptance ; status=$$? ; (cd .. && docker compose down) ; exit $$status

lint:
	ruff check .

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
