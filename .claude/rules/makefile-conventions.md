# Convention Makefile — Solution Sorabel

**Portée** : projets C# et Python développés en interne (`api-gateway`, `sorabelsql-api`,
`text2sql-ai`, `mcp`, `rag-hybride`). **Exclus** : `frontend` (stack non choisie),
`sorabel-idp` (service Keycloak conteneurisé, piloté par `docker compose`, pas par
`make`).

Chaque projet concerné a un `Makefile` à sa racine avec des cibles identiques dans leur
nom (implémentation différente selon la stack) :

| Cible | C# (`dotnet`) | Python |
|---|---|---|
| `make build` | `dotnet build` | `pip install -e .` / `poetry install` |
| `make test` | `dotnet test` | `pytest` |
| `make lint` | `dotnet format --verify-no-changes` | `ruff check .` |
| `make docker-build` | `docker build -t <projet> .` | `docker build -t <projet> .` |
| `make docker-up` | `docker compose up` | `docker compose up` |
| `make docker-down` | `docker compose down` | `docker compose down` |
| `make clean` | `dotnet clean` | suppression `__pycache__`, `.venv`, etc. |

Le Makefile normalise les **noms de cibles**, pas l'implémentation : chaque projet garde
son outillage natif derrière une interface commune. Le hook `.claude/hooks/dispatch-lint.sh`
s'appuie sur `make lint` plutôt que d'invoquer `ruff`/`dotnet format` directement, pour
rester agnostique de la stack.

## Exception — outillage Python partagé

Les 3 projets Python (`mcp`, `text2sql-ai`, `rag-hybride`) partagent un unique
`pyproject.toml`, un unique `docker-compose.yml` et un unique `.env` à la racine de la
solution (voir `../../CLAUDE.md` § Commandes) : chaque paquet `app` s'exécute depuis son
répertoire de travail, jamais installé en site-packages, et il n'y a pas de Dockerfile
par projet. Leur Makefile n'a donc que `build` (délègue à `cd .. && pip install -e ".[dev]"`),
`test`, `lint` et `clean` — pas de `docker-build`/`docker-up`/`docker-down`. Les projets
C# (`api-gateway`, `sorabelsql-api`) suivent le tableau standard sans exception.
