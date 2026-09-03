# sorabel-idp

@../CLAUDE.md

## Contexte

Fournisseur d'identité Keycloak (conteneurisé), authentification et émission du JWT
(claim `sorabel_profile`) consommé par `mcp`. Voir `README.md` pour le détail du realm,
des clients OAuth et du flux d'authentification.

## Point d'attention

`sorabel-idp` n'hérite d'aucune règle d'architecture (ni hexagonale, ni clean
architecture) ni du Makefile standard de la solution : c'est un service Keycloak à
configurer, pas une application développée en interne. Son cycle de vie est piloté par
`docker compose`, pas par `make build`/`make test`.
