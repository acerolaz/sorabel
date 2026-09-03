# Cibles standard — voir ../.claude/rules/makefile-conventions.md

.PHONY: build test lint docker-build docker-up docker-down clean

build:
	dotnet build

test:
	dotnet test

lint:
	dotnet format --verify-no-changes

docker-build:
	docker build -t sorabelsql-api .

docker-up:
	docker compose up

docker-down:
	docker compose down

clean:
	dotnet clean
