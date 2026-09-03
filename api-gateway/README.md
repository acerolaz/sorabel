# api-gateway

> Hub de routage pur (analogie YARP/Ocelot) pour tous les flux de la solution Sorabel,
> y compris les appels *internes* émis par [`mcp`](../mcp/README.md) vers ses backends.
> Ne porte **aucune logique d'autorisation** : la matrice d'accès (profil × tool ×
> collections/tables) est entièrement portée par `mcp`.

## 1. Rôle

`api-gateway` relaie les requêtes entre les clients (bot Slack support, poste de vente,
IDE développeur), [`sorabel-idp`](../sorabel-idp/README.md) (authentification), `mcp`
(catalogue de tools) et les backends internes (`rag-hybride`, `text2sql-ai`,
[`sorabelsql-api`](../sorabelsql-api/README.md)) — sans jamais inspecter ni décider des
droits d'accès.

> Analogie : un reverse proxy applicatif (YARP/Ocelot) — routage, relais transparent du
> Bearer JWT, pas de policy `[Authorize]` évaluée ici.

## 2. Ce que `api-gateway` ne fait pas

- Pas de vérification JWT/JWKS — relayée telle quelle, vérifiée par `mcp`.
- Pas de matrice d'accès dupliquée — reste entièrement dans `mcp`.
- Pas de logique métier — uniquement du routage/proxy.

## 3. Stack technique

- C#, Clean Architecture (cf. `.claude/rules/csharp-clean-architecture.md` à la racine
  de la solution)

## 4. Exigences servies

Support de E4 (architecture MCP unifiée) — c'est le point d'entrée réseau unique de la
solution, mais l'exigence elle-même (gouvernance centralisée) est portée par `mcp`.

---
*Projet en cours de mise en place — voir `../CLAUDE.md` pour le contexte de la solution
Sorabel et la répartition des responsabilités entre projets.*
