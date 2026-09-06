# api-gateway — Design du MVP

- **Date** : 2026-09-07
- **Statut** : validé, prêt pour plan d'implémentation
- **Portée** : premier incrément d'`api-gateway`, hub de routage pur de la solution Sorabel
- **Sources** : `docs/architecture/MCP.md`, `CLAUDE.md`, `api-gateway/CLAUDE.md`,
  `.claude/rules/{csharp-clean-architecture,api-contracts,security,makefile-conventions}.md`

---

## 1. Objectif et périmètre

`api-gateway` est le seul point d'entrée et de sortie de la solution Sorabel. Tout flux y
transite : les appels clients (*north-south*) comme les appels internes émis par `mcp` vers
ses backends (*service-to-service*). Il décide **par où ça passe**, jamais **qui a le droit
de faire quoi**.

### Dans le périmètre

- Les routes des cinq backends déclarées en configuration, avec leurs timeouts.
- Un correlation ID attaché à chaque requête et propagé aux backends.
- Une politique de retry qui garantit qu'une requête cliente ne provoque **jamais** plus
  d'une exécution backend.
- Un format d'erreur uniforme quand un backend est injoignable ou ne répond pas.
- Une image Docker qui se construit, se configure et démarre.

### Hors périmètre, par design

- Toute validation de JWT (signature, `iss`, `aud`, expiration) — portée par `mcp`.
- Toute matrice d'accès ou décision d'autorisation — portée par `mcp`.
- Toute règle métier.
- Toute transformation du corps des requêtes ou des réponses.

### État des backends au moment de l'écriture

Seul `text2sql-ai` a du code exécutable. `rag-hybride` a un squelette. `mcp`,
`sorabelsql-api` et `sorabel-idp` sont encore à l'état de documentation. Le choix retenu est
de **déclarer dès maintenant les routes des cinq backends** : le contrat de routage est ainsi
figé une fois pour toutes et les autres projets savent à quelle URL se brancher. Les backends
absents produisent naturellement un `502 BACKEND_UNREACHABLE`, ce qui est le comportement
correct et non un cas dégradé à traiter.

---

## 2. Décisions d'architecture

### 2.1 YARP porte tout le forwarding

YARP est configuré de façon déclarative (`Routes` / `Clusters` en `appsettings`) et assure le
transfert en streaming, sans matérialiser le corps des requêtes. Le code C# écrit à la main
se limite à trois préoccupations que YARP ne couvre pas nativement : le correlation ID, la
politique de retry, et la traduction d'un échec de transport en réponse d'erreur normalisée.

Cette contrainte est structurante : **il n'existe aucun handler de requête où de la logique
métier pourrait s'installer**. C'est ce qui rend le non-négociable « aucune règle métier ne
doit fuiter dans la couche de routage » vérifiable et non seulement déclaratif.

### 2.2 Trois projets, pas de couche Application

```
api-gateway/
├── Sorabel.ApiGateway.sln
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── src/
│   ├── Sorabel.ApiGateway.Domain/
│   │   ├── BackendId.cs           value object : mcp | text2sql | sql | rag | idp
│   │   ├── CorrelationId.cs       génération, parsing, validation
│   │   ├── RoutingError.cs        BackendUnreachable | BackendTimeout
│   │   └── RetryDecision.cs       « cet échec est-il rejouable ? »
│   ├── Sorabel.ApiGateway.Infrastructure/
│   │   ├── Resilience/            IForwarderHttpClientFactory + RetryHandler
│   │   ├── Correlation/           middleware + transform YARP
│   │   └── Errors/                RoutingError → réponse JSON
│   └── Sorabel.ApiGateway.Api/
│       ├── Program.cs             AddReverseProxy + MapReverseProxy
│       ├── appsettings.json
│       ├── appsettings.Routes.json
│       └── HealthChecks/
└── tests/
    ├── Sorabel.ApiGateway.Domain.Tests/    niveau 1
    ├── Sorabel.ApiGateway.Api.Tests/       niveaux 2 et 3
    └── Sorabel.ApiGateway.E2E.Tests/       niveau 4, exclu de `make test`
```

Les niveaux 2 et 3 partagent un projet (mêmes dépendances : WireMock.Net,
`WebApplicationFactory`) mais restent distingués par trait xUnit, afin que la règle de
pyramide reste vérifiable. Le niveau 4 est isolé dans son propre projet parce qu'il exige
Docker et ne doit pas tourner dans `make test`.

`Domain` ne référence ni ASP.NET, ni YARP, ni aucun SDK. `Infrastructure` dépend de `Domain`.
`Api` dépend des deux. Aucune dépendance en sens inverse.

**Pas de couche `Application`, et pas de MediatR.** Dans les autres projets de la solution,
la couche Application orchestre un cas d'usage métier ; ici il n'y en a aucun. Une couche
Application serait soit vide, soit l'endroit exact où le métier finirait par s'installer.
MediatR, qui présuppose des commandes et des queries à dispatcher, imposerait par ailleurs
d'écrire du routage impératif au-dessus de `IHttpForwarder` — contre la préférence
« configuration déclarative plutôt que code impératif » inscrite dans `CLAUDE.md`. MediatR
reste pertinent pour `sorabelsql-api`, qui a de vrais cas d'usage.

`RetryDecision` est isolé dans `Domain` parce que c'est la seule décision de la gateway ayant
des conséquences réelles — une double exécution SQL et une double entrée d'audit. Elle mérite
d'être un objet pur, testé exhaustivement.

### 2.3 Le point d'extension YARP à connaître

YARP ne forwarde pas via un `HttpClient` mais via un `HttpMessageInvoker` qu'il fabrique
lui-même. La politique de retry s'y greffe en fournissant une implémentation custom de
`IForwarderHttpClientFactory`, point d'extension prévu à cet effet. C'est le seul endroit
techniquement subtil du projet ; il vit dans `Infrastructure/Resilience/`.

---

## 3. Contrat de routage

Deux plans d'adressage distincts, qui matérialisent dans les URLs la distinction
*north-south* / *service-to-service* du `MCP.md` §6.1.

| Route entrante | ClusterId | Timeout | Appelée par |
|---|---|---|---|
| `/api/v1/auth/{**rest}` | `idp` | 10 s | Clients (obtention du JWT) |
| `/api/v1/mcp/{**rest}` | `mcp` | 120 s | Clients (`list_tools`, `call_tool`) |
| `/internal/v1/auth/{**rest}` | `idp` | 10 s | `mcp` (récupération JWKS) |
| `/internal/v1/text2sql/{**rest}` | `text2sql` | 90 s | `mcp` (`ask_database`) |
| `/internal/v1/sql/{**rest}` | `sql` | 30 s | `mcp` (`run_sql_query`, tools figés) |
| `/internal/v1/rag/{**rest}` | `rag` | 30 s | `mcp` (`search_documents` et briques) |
| `/health` | — (gateway elle-même) | — | Docker, supervision |

### 3.1 La route JWKS interne

`/internal/v1/auth` ne figure pas explicitement dans le `MCP.md`, mais son diagramme de
séquence §3 la rend nécessaire : le serveur MCP vérifie la signature du JWT via JWKS, et « la
gateway relaie (seul chemin d'accès à l'authn) ». Sans cette route, `mcp` devrait joindre
Keycloak directement, ce qui violerait le non-négociable « rester le seul chemin de sortie
vers Keycloak ».

### 3.2 Règle d'imbrication des timeouts

Un `call_tool("ask_database")` traverse la gateway **deux fois** :

```
client → GW → mcp → GW → text2sql-ai
        (/api/v1/mcp)   (/internal/v1/text2sql)
```

Si le timeout de la route externe était inférieur ou égal à celui de la route interne, la
gateway abandonnerait l'appel client alors que la génération interne tourne encore : le client
recevrait un 504, `mcp` une réponse dont plus personne ne veut, et l'audit E5 enregistrerait
une génération LLM facturée pour rien.

**Règle** : le timeout d'une route externe doit dépasser celui de la route interne la plus
lente qu'elle peut déclencher, avec une marge. D'où 120 s sur `/api/v1/mcp` face aux 90 s de
`/internal/v1/text2sql`.

### 3.3 Forme de la configuration

```jsonc
// appsettings.Routes.json
{
  "ReverseProxy": {
    "Routes": {
      "mcp-public": {
        "ClusterId": "mcp",
        "Match": { "Path": "/api/v1/mcp/{**rest}" },
        "Timeout": "00:02:00",
        "Transforms": [ { "PathRemovePrefix": "/api/v1/mcp" } ]
      },
      "text2sql-internal": {
        "ClusterId": "text2sql",
        "Match": { "Path": "/internal/v1/text2sql/{**rest}" },
        "Timeout": "00:01:30",
        "Transforms": [ { "PathRemovePrefix": "/internal/v1/text2sql" } ]
      }
      // … une entrée par ligne du tableau §3
    },
    "Clusters": {
      "mcp":      { "Destinations": { "d1": { "Address": "http://mcp:8000/" } } },
      "text2sql": { "Destinations": { "d1": { "Address": "http://text2sql-ai:8000/" } } }
      // …
    }
  }
}
```

Le préfixe est retiré avant transmission : `text2sql-ai` reçoit `/generate` comme s'il
était appelé directement. **Les backends n'ont pas à savoir qu'une gateway existe.**

Les adresses des clusters sont surchargeables par variable d'environnement
(`ReverseProxy__Clusters__mcp__Destinations__d1__Address`), pour ne pas figer les noms d'hôtes
Docker dans le fichier versionné.

L'en-tête `Authorization` est relayé **octet pour octet**, sans lecture ni validation.

---

## 4. Pipeline de la requête

```
1. CorrelationMiddleware      lit X-Correlation-Id ou en génère un (GUID)
                              → HttpContext + scope de log + en-tête de réponse
2. ForwarderErrorMiddleware   observe IForwarderErrorFeature au retour
3. MapReverseProxy            match route → cluster → transforms
      └→ IForwarderHttpClientFactory custom → RetryHandler → backend
```

Trois composants écrits à la main, pas un de plus.

---

## 5. Résilience et gestion d'erreur

### 5.1 Principe

**La gateway ne fabrique une réponse que lorsqu'il n'y a aucune réponse du backend.**

| Situation | Retry | Réponse de la gateway |
|---|---|---|
| Connexion refusée, échec DNS — **et requête sans corps** | Oui, 2 tentatives avec backoff | 502 `BACKEND_UNREACHABLE` si les tentatives échouent |
| Connexion refusée, échec DNS — **requête portant un corps** | Non (voir §5.1.1) | 502 `BACKEND_UNREACHABLE` |
| Timeout de réponse | Non | 504 `BACKEND_TIMEOUT` |
| Le backend répond, quel que soit le statut (200, 403, 500…) | Non | **Relais verbatim** — statut, corps et en-têtes inchangés |

Le retry est restreint aux échecs où l'on a la **certitude que le backend n'a rien reçu**.
Tout est en `POST` dans le catalogue MCP, et certains appels ont des effets audités
(`run_sql_query` s'exécute et se journalise) ou coûteux (`ask_database` déclenche une
génération LLM facturée). Rejouer sur un timeout produirait une seconde exécution et une
seconde entrée d'audit, rendant E5 trompeur.

**Garantie tenue : une requête cliente = au plus une exécution backend.**

#### 5.1.1 Le rejeu ne s'applique jamais à une requête portant un corps

Contrainte découverte lors de la préparation du plan d'implémentation, et vérifiée contre
YARP 2.3.0. YARP transmet le corps de la requête entrante en **streaming**, via un contenu
HTTP à usage unique. Rejouer une telle requête enverrait un corps **vide** au second essai —
une corruption silencieuse bien pire que l'échec qu'on cherchait à absorber.

Le rejeu couvre donc en pratique les `GET` sans corps, dont la récupération JWKS sur
`/internal/v1/auth`. Tous les `call_tool` en `POST` échouent immédiatement en 502. C'est un
**renforcement** de la garantie « au plus une exécution », pas un affaiblissement.

Encodé dans `RetryDecision.CanRetry(HttpRequestError error, bool requestHasBody)` et couvert
par un test de niveau 1 dédié.

### 5.2 Pourquoi un 5xx du backend n'est pas réécrit

Si `mcp` répond `200` avec un `isError: true`, ou `403`, ou `500`, c'est une réponse
applicative légitime. La réécrire en 502 détruirait le mécanisme sur lequel reposent E1 et
E5 : le client doit recevoir le `reason` typé (`NOT_FOUND_IN_CORPUS`, `UNAUTHORIZED_TOOL`,
`SCHEMA_MISMATCH`) tel que `mcp` l'a émis, et non un « backend en erreur » générique qui
l'empêcherait de distinguer un refus d'autorisation d'une panne.

### 5.3 Format d'erreur

Conforme à `.claude/rules/api-contracts.md`, uniquement pour les deux cas fabriqués :

```json
{
  "error_code": "BACKEND_UNREACHABLE",
  "message": "Le service demandé est momentanément indisponible",
  "correlation_id": "7f3a91e4-..."
}
```

`message` ne nomme **jamais** le backend ni son adresse : sinon la réponse d'erreur devient
une carte de la topologie interne.

---

## 6. Traçabilité et journalisation

### 6.1 Correlation ID

En-tête `X-Correlation-Id`. La gateway le lit s'il est présent, en génère un (GUID) sinon,
l'injecte vers le backend et le renvoie au client.

```
Client            → gateway   (pas d'en-tête)
gateway           : génère 7f3a91e4-…
gateway → mcp     : X-Correlation-Id: 7f3a91e4-…
mcp → gateway     : X-Correlation-Id: 7f3a91e4-…   (rejoué par mcp)
gateway → t2sql   : X-Correlation-Id: 7f3a91e4-…
gateway → client  : X-Correlation-Id: 7f3a91e4-…
```

Le choix d'un en-tête maison plutôt que `traceparent`/OpenTelemetry est délibéré : un
middleware ASP.NET d'un côté, un middleware FastAPI de l'autre, aucune infrastructure à
déployer, et une trace lisible à l'œil nu. Cela suffit à E5. Une bascule ultérieure vers
OpenTelemetry reste possible sans refonte.

**Contrat pour les backends** : chaque backend Python doit lire `X-Correlation-Id` et le
rejouer dans ses propres logs et dans ses appels sortants, faute de quoi la trace se rompt.

### 6.2 Journalisation

Une ligne structurée par requête relayée : `correlation_id`, méthode, chemin entrant,
`backend_id`, statut, durée en ms.

**Jamais** l'en-tête `Authorization`, jamais son contenu décodé, jamais le corps de la requête
ou de la réponse. Appliqué par une **liste de blocage explicite des en-têtes sensibles**, pas
par la seule discipline de rédaction.

---

## 7. Packaging

- `Dockerfile` multi-étages (`sdk:9.0` → `aspnet:9.0`), utilisateur non-root, écoute sur
  `8080`, `HEALTHCHECK` sur `/health`.
- `docker-compose.yml` local à `api-gateway/`, même schéma que `text2sql-ai/`.
- Adresses des clusters injectées par variables d'environnement, jamais en dur.
- `.env.example` versionné, sans valeurs réelles.
- Les *health checks actifs* de YARP restent **désactivés** au MVP : quatre backends sur cinq
  n'existent pas encore, une sonde périodique ne ferait que polluer les logs. À réactiver
  quand ils tourneront.

---

## 8. Stratégie de test

La stratégie de test est définie dans ce document. Forme attendue pour ce projet : **diamant**,
niveau 3 dominant — un socle unitaire fin est ici la conséquence directe de l'absence de
logique métier, non un défaut de couverture.

| Niveau | Contenu |
|---|---|
| **1 — Unitaire** | `RetryDecision` par table sur chaque type d'échec — le test le plus important du projet, il garde la garantie « au plus une exécution ». `CorrelationId` : génération, parsing, rejet d'une valeur malformée. `BackendId`. |
| **2 — Intégration** | La fabrique de client résiliente face à WireMock.Net : connexion refusée → 2 tentatives observées ; réponse lente → 1 seule tentative ; réponse 500 → 1 seule tentative. |
| **3 — Contrat** | `WebApplicationFactory` + WireMock : chacune des 6 routes atteint le bon cluster ; préfixe retiré ; `Authorization` relayé octet pour octet ; `X-Correlation-Id` généré, propagé, renvoyé ; backend éteint → 502 JSON conforme ; backend lent → 504 ; **backend répondant 403 → relayé verbatim, non réécrit**. |
| **4 — E2E** | `make test-e2e` : compose démarre la gateway et un backend factice conteneurisé ; une requête traverse réellement. Prouve que l'image se construit, se configure et démarre. |

Le test « backend répondant 403 → relayé verbatim » est le garde-fou de régression de la règle
§5.2. Seuil de couverture global : 80 % sur les niveaux 1 à 3.

---

## 9. Critères d'acceptation

- [ ] `make build && make test && make lint` passent.
- [ ] `make test-e2e` passe.
- [ ] `make docker-build && make docker-up` réussissent ; `/health` répond.
- [ ] Les 6 routes proxifiées du §3 (hors `/health`) sont déclarées et couvertes par un test de niveau 3.
- [ ] Aucune ligne de code ne lit, décode ou interprète un claim JWT, un rôle, ou la matrice
      RBAC. Vérifiable par recherche sur `Authorization`, `claim`, `role`, `profile`.
- [ ] Aucun test ne démontre qu'une requête cliente peut produire deux exécutions backend.
- [ ] `Sorabel.ApiGateway.Domain` ne référence aucun paquet externe.
- [ ] Aucun secret en dur ; `.env.example` versionné sans valeurs.

---

## 10. Travaux connexes identifiés, hors périmètre de cette spec

1. **`../.claude/rules/docker-conventions.md` n'existe pas.** À créer si une convention Docker transverse est souhaitée (aucun fichier ne l'importe actuellement).
2. **`.claude/rules/routing-proxy.md` est un TODO** : il recevra le plan d'adressage du §3
   comme contenu.
3. **La commande `/new-route` est un squelette non implémenté** : elle devient implémentable
   une fois ce contrat figé — ajouter une paire route/cluster dans `appsettings.Routes.json`
   plus le test de niveau 3 correspondant.
4. **`api-gateway/CLAUDE.md` § Critères de succès** mentionne
   `make build && make test && make lint` : à compléter avec `make test-e2e`.
5. **Contrat à propager aux backends Python** : lecture et rejeu de `X-Correlation-Id`
   (cf. §6.1). À porter dans les specs de `mcp`, `text2sql-ai` et `rag-hybride`.
