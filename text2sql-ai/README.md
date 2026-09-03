# text2sql-ai

> Agent Text-to-SQL dédié : **génération seule** d'une requête SQL en lecture seule à
> partir d'une question en langage naturel et d'un schéma statique commenté filtré par
> profil. N'exécute jamais de SQL lui-même — l'exécution est déléguée à
> [`sorabelsql-api`](../sorabelsql-api/README.md).

## 1. Rôle

`text2sql-ai` reçoit une question en langage naturel + le profil de l'appelant, génère
une requête SQL candidate, et la retourne telle quelle sans l'exécuter. Cette séparation
génération/exécution donne un point d'inspection entre l'étape probabiliste (LLM) et
l'étape gouvernée (chaîne de garde-fous de `sorabelsql-api`).

## 2. Ce que `text2sql-ai` ne fait pas

- Pas d'exécution SQL — jamais de connexion à PostgreSQL.
- Pas de garde-fous d'exécution (rôle DB read-only, AST, `LIMIT`, timeout) — portés par
  `sorabelsql-api`.

## 3. Stack technique

- Python, architecture hexagonale (cf. `.claude/rules/python-hexagonal.md` à la racine
  de la solution)

## 4. Exigences servies

E3 (Text-to-SQL lecture seule) — pour la partie génération uniquement ; l'exécution
gouvernée est portée par `sorabelsql-api`.

---
*Projet en cours de mise en place — voir `../CLAUDE.md` pour le contexte de la solution
Sorabel et la répartition des responsabilités entre projets.*
