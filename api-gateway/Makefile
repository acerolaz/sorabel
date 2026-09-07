# Cibles standard — voir ../.claude/rules/makefile-conventions.md

.PHONY: build test test-e2e lint docker-build docker-up docker-down clean

build:
	dotnet build

test:
	dotnet test --filter "Category!=E2E"

test-e2e:
	docker compose up -d --build --wait
	dotnet test --filter "Category=E2E" ; status=$$? ; docker compose down ; exit $$status

lint:
	dotnet format --verify-no-changes

docker-build:
	docker build -t api-gateway .

docker-up:
	docker compose up

docker-down:
	docker compose down

clean:
	dotnet clean
