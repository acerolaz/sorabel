---
description: Scaffold une route proxifiée vers un backend
---

# /new-route

Ajoute une route de routage pur, conformément à `.claude/rules/routing-proxy.md`.

Demander à l'utilisateur, s'ils ne sont pas fournis en argument :

1. **Plan** : `/api/v1` (appelé par un client) ou `/internal/v1` (appelé par `mcp`) ?
2. **Backend cible** : `idp`, `mcp`, `text2sql`, `sql`, `rag`.
3. **Segment de route** et **timeout**.

Puis :

1. Ajouter la paire route/cluster dans
   `src/Sorabel.ApiGateway.Api/appsettings.Routes.json`, avec un
   `PathRemovePrefix` correspondant au préfixe complet.
2. Vérifier la règle d'imbrication des timeouts : si cette route peut être
   déclenchée par une route externe, le timeout de cette dernière doit être
   supérieur. Le signaler si ce n'est pas le cas.
3. Ajouter la ligne correspondante dans `RoutingContractTests.Routes`
   (`tests/Sorabel.ApiGateway.Api.Tests/RoutingContractTests.cs`) — c'est un
   `TheoryData<string, string, string>` (`clusterId`, `cheminEntrant`,
   `cheminAttendu`), une ligne suffit.
4. Ajouter la ligne dans le tableau de `.claude/rules/routing-proxy.md`.
5. Lancer `make test` et vérifier que la nouvelle route passe.

Ne jamais ajouter de code de routage impératif : une route est une entrée de
configuration, rien d'autre.
