# Clean Architecture (C#) — Solution Sorabel

Règle commune aux projets C# de la solution (`api-gateway`, `sorabelsql-api`). Objectif :
le **domaine métier ne dépend d'aucun framework** (ASP.NET, EF Core, SDK externe...). Les
couches externes dépendent du domaine, jamais l'inverse.

> TODO : détailler la structure de couches (Domain / Application / Infrastructure / API),
> les règles de dépendance et les conventions DI, sur le modèle de
> `[[python-hexagonal]]` mais adapté à Clean Architecture .NET.

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
