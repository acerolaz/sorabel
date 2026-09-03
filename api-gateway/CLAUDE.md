# api-gateway

@../CLAUDE.md
@../.claude/rules/csharp-clean-architecture.md
@../.claude/rules/makefile-conventions.md

## Contexte

Hub de routage pur (C#, Clean Architecture) de la solution Sorabel — voir `README.md`
pour le détail du rôle et des flux relayés.

## Règles locales

@.claude/rules/routing-proxy.md

## Point d'attention

`api-gateway` ne porte **aucune** logique d'autorisation — c'est la responsabilité de
`mcp` en aval. Ce projet suppose qu'il relaie transparemment, sans jamais inspecter le
JWT ni la matrice d'accès.
