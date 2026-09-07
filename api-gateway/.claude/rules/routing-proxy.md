# Routage/proxy — api-gateway

Conventions de routage pur — **pas de logique RBAC ici** (cf. `mcp/`).

## Plan d'adressage

Deux espaces distincts, qui matérialisent la séparation north-south /
service-to-service. Table vérifiée contre
`src/Sorabel.ApiGateway.Api/appsettings.Routes.json` — en cas de divergence entre
ce fichier et le code, le code fait foi.

| Route entrante | Cluster | Timeout | Appelée par |
|---|---|---|---|
| `/api/v1/auth/{**rest}` | `idp` | 10 s | Clients (obtention du JWT) |
| `/api/v1/mcp/{**rest}` | `mcp` | 120 s | Clients (`list_tools`, `call_tool`) |
| `/internal/v1/auth/{**rest}` | `idp` | 10 s | `mcp` (récupération JWKS) |
| `/internal/v1/text2sql/{**rest}` | `text2sql` | 90 s | `mcp` (`ask_database`) |
| `/internal/v1/sql/{**rest}` | `sql` | 30 s | `mcp` (`run_sql_query`, tools figés) |
| `/internal/v1/rag/{**rest}` | `rag` | 30 s | `mcp` (`search_documents` et briques) |

## Règles

- Le préfixe est **toujours** retiré avant transmission (`PathRemovePrefix`) :
  les backends n'ont pas à savoir qu'une gateway existe.
- Le timeout d'une route externe doit **dépasser** celui de la route interne la
  plus lente qu'elle peut déclencher. Sinon la gateway abandonne l'appel client
  pendant qu'un traitement facturé tourne encore côté backend. Vérifié ici :
  `mcp-public` (120 s) dépasse chacune des routes internes que `mcp` peut
  déclencher (`auth-internal` 10 s, `text2sql-internal` 90 s, `sql-internal`
  30 s, `rag-internal` 30 s).
- Les adresses de clusters sont surchargeables par variable d'environnement
  (`ReverseProxy__Clusters__<id>__Destinations__d1__Address`), jamais figées.
- `Authorization` est relayé octet pour octet et n'est jamais lu.
- Le rejeu ne s'applique qu'aux échecs de connexion **sans corps de requête**
  (cf. `Domain/RetryDecision.cs`).
- Toute réponse reçue d'un backend est relayée verbatim — la gateway ne fabrique
  une réponse que lorsqu'il n'y en a aucune.

Détail et justification : `docs/superpowers/specs/2026-09-07-api-gateway-design.md`.
