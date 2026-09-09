# Cibles standard — voir ../.claude/rules/makefile-conventions.md
#
# Exception locale : text2sql-ai a son propre Dockerfile (déploiement indépendant
# via l'API Gateway), contrairement à mcp/rag-hybride. Il continue de builder
# depuis le pyproject.toml partagé à la racine de la solution.

.PHONY: build test test-e2e lint docker-build docker-up docker-down clean

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
	docker compose up -d --build --wait || (docker compose down; exit 1)
	pytest tests/acceptance ; status=$$? ; docker compose down ; exit $$status

lint:
	ruff check .

docker-build:
	cd .. && docker build -f text2sql-ai/Dockerfile -t text2sql-ai .

docker-up:
	docker compose up

docker-down:
	docker compose down

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
