# text2sql-ai

@../CLAUDE.md
@../.claude/rules/python-hexagonal.md
@../.claude/rules/makefile-conventions.md

## Contexte spécifique

Agent Text-to-SQL, exposé via FastAPI. Génère une requête SQL en lecture seule à partir
d'une question en langage naturel + schéma statique commenté filtré par profil. N'exécute
jamais de SQL lui-même — accessible uniquement via l'API Gateway (aucun accès direct
depuis `mcp` ni les clients).

## Règles locales

@.claude/rules/sql-generation-readonly.md
