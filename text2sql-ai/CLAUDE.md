# text2sql-ai | Context v1.2 | Updated: 2026-09-07

@../CLAUDE.md
@../.claude/rules/python-hexagonal.md
@../.claude/rules/makefile-conventions.md
@../.claude/rules/docker-conventions.md

## Contexte spécifique
Agent Text-to-SQL exposé via FastAPI (architecture hexagonale, domain pur).
Convertit une question en langage naturel + schéma statique commenté (filtré
par profil) en une requête SQL PostgreSQL **lecture seule**. Ne l'exécute
jamais : c'est `sorabelsql-api` qui exécute, jamais ce projet.

Pipeline : schéma statique (`schema_context.md`, chargé une fois au démarrage,
mis en cache mémoire) + valeurs d'énum + few-shot (Golden Dataset) + règles
métier → prompt → génération SQL → barrières 1 à 4 de défense en profondeur
(instruction système, blocklist de mots-clés, AST via `sqlglot`) → renvoi au
`mcp` pour la suite de la chaîne (guardrail sémantique, LLM as judge, exécution).

## Non-négociables
- Ne jamais exécuter de SQL, ni ouvrir de connexion en écriture à PostgreSQL — génération uniquement
- Ne jamais exposer le schéma complet : filtrage par profil (`{profil: [tables_autorisées]}`) obligatoire avant injection au prompt
- Ne jamais injecter le type de colonne seul pour un enum : toujours les valeurs réelles en toutes lettres (ex. `status IN ('pending','shipped',...)`)
- Toujours inclure l'instruction `CRITICAL:` interdisant l'invention de noms de colonnes
- Accessible uniquement via `api-gateway` — aucun accès direct depuis `mcp/` ni les clients finaux
- Toujours buildable et démarrable via `make docker-build && make docker-up`

## Règles strictes
- Toute réponse du LLM générateur passe par la blocklist (`INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/GRANT/REVOKE`) puis par une validation AST (`sqlglot`, dialect `postgres`) avant d'être renvoyée
- `schema_context.md` est la seule source de vérité du schéma — jamais d'introspection dynamique de la base depuis ce service
- Le dictionnaire de filtrage par profil vit dans le domaine (pas dans l'adapter FastAPI) — testable sans framework web
- Toute requête générée est journalisée (E5), y compris les rejets, avant de quitter le service

## Préférences
- Préférer enrichir `schema_context.md` et les few-shot plutôt que complexifier le prompt système
- Préférer une erreur structurée à une requête approximative en cas de schéma insuffisant

## Anti-patterns
- Ne jamais faire porter à ce service la moindre logique d'exécution ou de connexion en écriture
- Ne jamais dupliquer la matrice RBAC (elle vit dans `mcp/`) : ce service ne fait que filtrer le schéma qu'il reçoit en paramètre de profil
- Ne jamais remplacer le schéma statique par un RAG vectoriel sans validation explicite (hors périmètre tant que < 15 tables)

## Critères de succès
- `make build && make test && make lint` passent
- Le Golden Dataset (§2 `Text2SQL_Sorabel.md`) est rejoué en CI sans régression
- `docker build` réussit et le conteneur démarre via `make docker-up`
- Aucune requête générée ne contient de verbe de la blocklist ni ne référence une table hors périmètre profil

## Fallback
- Si la question ne peut pas être résolue avec le schéma filtré disponible → retourner une erreur structurée, jamais une requête approximative
- Si la boucle d'auto-correction atteint son nombre max de tentatives → basculer en demande de clarification, ne pas forcer une dernière génération

## Règles locales
@.claude/rules/sql-generation-readonly.md
@.claude/rules/testing-pytest.md

## Routage de contexte
- Détail génération/garde-fous 1-4 → `.claude/rules/sql-generation-readonly.md`
- Détail pipeline complet (schéma, RBAC, exécution) → `Text2SQL_Sorabel.md` (racine solution)
