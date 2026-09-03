# Garde-fous d'exécution SQL — sorabelsql-api

Chaîne de garde-fous exécution (`run_sql_query`), tools figés, PostgreSQL en lecture
seule.

> TODO : détailler chaque barrière (rôle DB read-only, blocklist de mots-clés,
> validation AST, guardrail sémantique, `LIMIT`/timeout, exécution sur réplica) — cf.
> `README.md` §5 pour la vue d'ensemble à reprendre ici.
