# api-gateway | Context v1.0 | Updated: 2026-09-06

@../CLAUDE.md
@../.claude/rules/csharp-clean-architecture.md
@../.claude/rules/makefile-conventions.md
@../.claude/rules/docker-conventions.md
@../.claude/rules/api-contracts.md
@../.claude/rules/security.md

## Contexte spécifique
Hub de routage pur (C#, Clean Architecture) — analogie YARP/Ocelot. Seul point d'accès
(north-south **et** service-to-service) vers `sorabel-idp` (Keycloak), `mcp`, `text2sql-ai`,
`sorabelsql-api` et `rag-hybride`. Aucun de ces services n'est jamais appelé directement,
ni par un client, ni entre eux.

## Non-négociables
- Ne jamais implémenter de logique d'autorisation ou de matrice RBAC ici — portée par `mcp/`
- Relayer les JWT de façon transparente, sans inspecter signature/claims — c'est le rôle du serveur MCP
- Rester le seul chemin de sortie vers Keycloak, `mcp`, `text2sql-ai`, `sorabelsql-api`, `rag-hybride`
- Toujours buildable et démarrable via `make docker-build && make docker-up`
- Aucune règle métier ne doit fuiter dans la couche de routage

## Règles strictes
- Toute nouvelle route passe par `/new-route` (scaffolding) — jamais de route ajoutée manuellement hors convention
- Timeout + retry définis par route backend (résilience type Polly)
- Chaque requête relayée est tracée (correlation ID) — jamais le contenu du JWT dans les logs

## Préférences
- Préférer un reverse-proxy générique (YARP) à un routage réécrit à la main
- Préférer la configuration déclarative des routes (appsettings/YAML) au code impératif

## Anti-patterns
- Ne jamais lire ou interpréter un claim JWT pour une décision d'autorisation
- Ne jamais recréer une matrice RBAC locale, même partielle ou "temporaire"
- Ne jamais laisser un client contourner la gateway pour atteindre un backend directement

## Fallback
- Backend cible indisponible → erreur de routage standardisée (502/504), jamais de repli silencieux vers un autre backend

## Critères de succès
- `make build && make test && make lint` passent
- `make docker-build && make docker-up` réussissent
- Aucune ligne de code n'interprète un rôle, un claim ou la matrice RBAC

## Règles locales
@.claude/rules/routing-proxy.md
