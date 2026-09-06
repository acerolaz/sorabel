# Convention Makefile — Solution Sorabel

**Portée** : projets C# et Python développés en interne (`api-gateway`, `sorabelsql-api`,
`text2sql-ai`, `mcp`, `rag-hybride`). **Exclus** : `frontend` (stack non choisie),
`sorabel-idp` (service Keycloak conteneurisé, piloté par `docker compose`, pas par
`make`).

`text2sql-ai` suit le tableau standard C#-style (avec Docker), pas l'exception Python
partagée ci-dessous — voir « Exception — `text2sql-ai` » en fin de document.

Chaque projet concerné a un `Makefile` à sa racine avec des cibles **standardisées** : mêmes noms quand elles existent, mais certaines cibles peuvent être absentes selon les exceptions ci-dessous.

| Cible | C# (`dotnet`) | Python |
|---|---|---|
| `make build` | `dotnet build` | `pip install -e .` / `poetry install` (voir exception) |
| `make test` | `dotnet test` | `pytest` |
| `make test-e2e` | `dotnet test` (filtre E2E) + `docker compose` | `pytest` (filtre E2E) + dépendances réelles |
| `make lint` | `dotnet format --verify-no-changes` | `ruff check .` |
| `make docker-build` | `docker build -t <projet> .` | — (voir exception) |
| `make docker-up` | `docker compose up` | — (voir exception) |
| `make docker-down` | `docker compose down` | — (voir exception) |
| `make clean` | `dotnet clean` | suppression `__pycache__`, `.venv`, etc. |

Le Makefile normalise les **noms de cibles**, pas l'implémentation : chaque projet garde
son outillage natif derrière une interface commune. Le hook `.claude/hooks/dispatch-lint.sh`
s'appuie sur `make lint` plutôt que d'invoquer `ruff`/`dotnet format` directement, pour
rester agnostique de la stack.

`make test` couvre les niveaux 1 à 3 de la pyramide de tests et doit tourner **sans Docker** ;
`make test-e2e` couvre le seul niveau 4 et démarre les dépendances réelles. Le critère
d'appartenance de chaque test à un niveau est défini par
`.claude/rules/testing-pyramid.md`.

## Exception — outillage Python partagé

Les 2 projets Python restants (`mcp`, `rag-hybride`) partagent un unique
`pyproject.toml`, un unique `docker-compose.yml` et un unique `.env` à la racine de la
solution (voir `../../CLAUDE.md` § Commandes) : chaque paquet `app` s'exécute depuis son
répertoire de travail, jamais installé en site-packages, et il n'y a pas de Dockerfile
par projet. Leur Makefile n'a donc que `build` (délègue à `cd .. && pip install -e ".[dev]"`),
`test`, `test-e2e`, `lint` et `clean` — pas de `docker-build`/`docker-up`/`docker-down`. Les
projets C# (`api-gateway`, `sorabelsql-api`) suivent le tableau standard sans exception.

Leur `test-e2e` ne containerise pas le service (faute de Dockerfile) : il démarre les
dépendances réelles depuis la racine (`docker compose up -d --wait postgres`) et exécute
l'application contre celles-ci — cf. `.claude/rules/testing-pyramid.md`, § « Cas des projets
Python à outillage partagé ».

## Exception — `text2sql-ai`

Contrairement à `mcp` et `rag-hybride`, `text2sql-ai` n'est pas un processus de dev
co-localisé avec ses pairs Python : il n'est appelé que via l'API Gateway, depuis des
environnements distincts, et doit être déployable/scalable indépendamment. Il a donc son
propre `Dockerfile` et suit le tableau standard complet (`build`/`test`/`lint`/
`docker-build`/`docker-up`/`docker-down`/`clean`), comme les projets C#, tout en
continuant de builder depuis le `pyproject.toml` partagé à la racine (`docker-build`
exécute `pip install -e "..[dev]"` avec la racine de la solution comme contexte de
build, puis copie `text2sql-ai/app`). Voir
`text2sql-ai/docs/superpowers/specs/2026-09-04-text2sql-ai-mvp-design.md` pour le détail.
