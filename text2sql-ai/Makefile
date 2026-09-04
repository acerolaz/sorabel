# Cibles standard — voir ../.claude/rules/makefile-conventions.md
#
# Exception locale : text2sql-ai a son propre Dockerfile (déploiement indépendant
# via l'API Gateway), contrairement à mcp/rag-hybride. Il continue de builder
# depuis le pyproject.toml partagé à la racine de la solution.

.PHONY: build test lint docker-build docker-up docker-down clean

build:
	cd .. && pip install -e ".[dev]"

test:
	pytest

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
