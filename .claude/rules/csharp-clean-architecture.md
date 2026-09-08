# Clean Architecture (C#) — Solution Sorabel

Règle commune aux projets C# de la solution (`api-gateway`, `sorabelsql-api`). Objectif :
le **domaine métier ne dépend d'aucun framework** (ASP.NET, EF Core, SDK externe...). Les
couches externes dépendent du domaine, jamais l'inverse.

## Structure retenue (`api-gateway`)

`api-gateway` illustre la structure de référence — 3 projets, sans couche
Application dédiée puisqu'un hub de routage pur n'orchestre aucun cas d'usage :

```
api-gateway/
├── src/
│   ├── Sorabel.ApiGateway.Domain/          # Cœur métier — aucune dépendance NuGet
│   │   ├── RetryDecision.cs                 # règle : jamais de rejeu si corps de requête
│   │   ├── RoutingError.cs                  # normalisation des échecs (502/504)
│   │   ├── CorrelationId.cs, BackendId.cs, SensitiveHeaders.cs
│   ├── Sorabel.ApiGateway.Infrastructure/   # Implémentations concrètes (adapters)
│   │   ├── Correlation/                     # middleware + transform YARP du correlation ID
│   │   ├── Errors/                          # traduction des erreurs YARP en réponse normalisée
│   │   ├── Logging/                         # journalisation une ligne par requête, sans en-tête sensible
│   │   └── Resilience/                      # politique de retry (HttpClientFactory YARP)
│   └── Sorabel.ApiGateway.Api/              # Point d'entrée ASP.NET — configuration YARP
│       ├── Program.cs                       # câblage DI, middlewares, healthcheck
│       └── appsettings.Routes.json           # routes/clusters déclaratifs (pas de code impératif)
└── tests/                                   # un projet de test par niveau
    ├── Sorabel.ApiGateway.Domain.Tests/      # niveau 1 — règles pures, aucune I/O
    ├── Sorabel.ApiGateway.Api.Tests/         # niveaux 2 et 3 — WireMock.Net, WebApplicationFactory
    └── Sorabel.ApiGateway.E2E.Tests/         # niveau 4 — conteneur réel, exclu de `make test`
```

Les niveaux sont ceux de `testing-pyramid.md`, qui fait foi sur leur critère
d'appartenance.

**Les projets de test vivent sous `tests/`, sur disque *et* dans le `.sln`.** Les
deux doivent concorder : dans `GlobalSection(NestedProjects)`, chaque projet de
test est rattaché au GUID du dossier de solution `tests`, jamais à celui de
`src`. Un projet correctement placé sur disque mais rattaché à `src` dans le
`.sln` apparaît au milieu du code de production dans Rider/Visual Studio — c'est
invisible en ligne de commande (`dotnet build` et `dotnet test` s'en moquent) et
ne se voit qu'à la lecture du `.sln` ou dans l'IDE. `dotnet sln add` ne sait pas
déplacer une entrée existante entre dossiers de solution : corriger la ligne
`NestedProjects` à la main.

Pas de couche `Application/` : les projets sans logique d'orchestration à isoler
(proxy pur, cf. la forme « diamant » de `.claude/rules/testing-pyramid.md`)
n'ont pas à en créer une artificiellement. `sorabelsql-api`, qui a une chaîne de
garde-fous et du masquage de colonnes à orchestrer, en aura une.

Règle de dépendance : `Api` → `Infrastructure` → `Domain`. `Domain` n'expose ici
aucune interface/port : ses types (`RetryDecision`, `RoutingError`, ...) sont des
règles pures, sans état externe à abstraire — un hub de routage n'a rien à
substituer (pas de base de données, pas de fournisseur externe côté domaine).
`Infrastructure` consomme ces types directement ; aucune classe de `Domain` ne
référence YARP, ASP.NET ni aucun paquet NuGet.

## Analogie Python (hexagonale)

| C# (Clean Architecture) | Python (hexagonal) |
|---|---|
| Interface C# (`IVectorStorePort`) | `domain/ports.py` (Protocol/ABC) |
| Implémentation concrète injectée via DI | `infrastructure/postgres/` |
| Services applicatifs | `application/use_cases/` |
| `services.AddScoped<IVectorStorePort, PgVectorRepository>()` | Injection via constructeur + factory FastAPI (`Depends`) |

## Conventions

- Une interface = un port, défini dans la couche Domain ou Application, jamais dans
  Infrastructure.
- Aucune entité de domaine n'est exposée directement en API : toujours un DTO dédié.
- Les tests du domaine et de l'application ne mockent que les interfaces, jamais des
  détails d'implémentation Infrastructure.
- Un nouveau projet de test est ajouté au dossier de solution `tests` du `.sln`, jamais
  à `src` — vérifier la ligne `NestedProjects` après tout `dotnet sln add`.
