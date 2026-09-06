# sorabelsql-api | Context v1.0 | Updated: 2026-09-06

@../CLAUDE.md
@../.claude/rules/csharp-clean-architecture.md
@../.claude/rules/makefile-conventions.md
@../.claude/rules/docker-conventions.md

## Contexte spécifique
Service C# (Clean Architecture) responsable de l'**exécution** SQL en lecture seule sur PostgreSQL, ainsi que des tools figés (stock, commandes, historique). Consommé exclusivement par le serveur `mcp/` via l'`api-gateway` — jamais d'accès direct depuis un autre projet ou un client externe.

Ce projet ne **génère** jamais de SQL : la génération est portée par `text2sql-ai/`. `sorabelsql-api` reçoit du SQL déjà écrit (par `text2sql-ai` ou fourni tel quel par un client `dev`) et se contente de le valider puis de l'exécuter.

## Non-négociables
- Toute requête (fixe ou dynamique) passe par la chaîne de garde-fous avant exécution — jamais de SQL brut non validé
- Lecture seule stricte : le rôle DB utilisé n'a aucun droit d'écriture (`INSERT`/`UPDATE`/`DELETE`/DDL)
- Exécution sur réplica PostgreSQL dédié, jamais sur la base primaire
- PostgreSQL tourne dans son propre conteneur, jamais partagé avec un autre projet en dev
- Masquage de colonnes appliqué avant retour du résultat (ex: `purchase_price`, `margin` filtrés selon profil)
- Accessible uniquement via l'`api-gateway` — aucun accès direct depuis `mcp/` ni les clients
- Toujours buildable via `make build && make test && make lint` ; activer `make docker-build && make docker-up` dès que `Dockerfile`/Compose et le projet .NET sont ajoutés

## Chaîne de garde-fous (ordre d'application strict)
1. Rôle DB en lecture seule
2. Blocklist de mots-clés/commandes interdits
3. Analyse AST de la requête SQL
4. Guardrail sémantique (cohérence métier)
5. `LIMIT` + `timeout` imposés
6. Exécution sur réplica

## Fallback
- Si un tool figé ne couvre pas la demande → retourner une erreur explicite, ne jamais improviser de SQL ad hoc
- Si la chaîne de garde-fous rejette une requête → réponse structurée typée (erreur), jamais de tentative de correction automatique du SQL reçu

## Critères de succès
- `make build && make test && make lint` passent
- `docker build` réussit et `docker compose up` démarre l'API + PostgreSQL dédié
- Aucune requête n'atteint la base sans passage complet et testé par la chaîne de garde-fous

## Anti-patterns
- Ne jamais ajouter de logique de génération SQL ici (relève de `text2sql-ai/`)
- Ne jamais exposer un endpoint qui contourne la chaîne de garde-fous, même pour du debug
- Ne jamais partager la connexion PostgreSQL avec un autre projet, même en environnement de dev

## Règles locales
@.claude/rules/sql-execution-guardrails.md
