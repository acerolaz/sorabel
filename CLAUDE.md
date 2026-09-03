# Sorabel — Contexte solution

## Vision

Sorabel Data Gateway : point d'accès unifié aux données de l'entreprise (documentation
technique + données transactionnelles) pour des clients internes hétérogènes (bot Slack
support, poste de vente, IDE développeur), via un **unique serveur MCP** gouverné par une
matrice d'accès centralisée (profil × tool × collections/tables).

Deux capacités métier composent la gateway :
- **RAG documentaire hybride** (dense + BM25 + reranking) sur le corpus technique (fiches
  produit, manuels, procédures SAV) — porté par `rag-hybride`.
- **Text-to-SQL gouverné** en lecture seule sur les données transactionnelles (stock,
  commandes) — génération et exécution séparées entre `text2sql-ai` et `sorabelsql-api`.

Le tout exposé via `mcp` (catalogue de tools + matrice d'accès), sécurisé par `sorabel-idp`
(Keycloak, authentification, JWT) et routé par `api-gateway` (hub de routage pur, sans
logique d'autorisation), avec `frontend` comme interface(s) cliente(s) restant à définir.

## Exigences du cahier des charges (E1–E6)

| ID | Périmètre | Exigence |
|---|---|---|
| E1 | RAG & attribution | Chaque réponse documentaire cite ses sources ; refus explicite si le corpus ne contient pas la réponse (pas d'hallucination) |
| E2 | Retrieval hybride | Gérer aussi bien les lookups exacts par référence (`REF-8842`) que les requêtes en langage naturel |
| E3 | Text-to-SQL lecture seule | SQL généré strictement read-only, restreint aux tables autorisées par profil, journalisé |
| E4 | Architecture MCP unifiée | Un seul serveur MCP pour tous les clients, gouverné par une matrice d'accès centralisée |
| E5 | Auditabilité & masquage | Tout appel (autorisé ou refusé) journalisé ; colonnes sensibles masquées selon le profil |
| E6 | Évaluation du RAG | Gain du retrieval hybride + reranking mesuré et documenté vs recherche vectorielle simple |

## Projets et responsabilités

| Projet | Stack / archi | Rôle dans la gateway | Exigences servies |
|---|---|---|---|
| `sorabel-idp` | Keycloak, conteneurisé | Authentification, émission JWT (claim `sorabel_profile`) — pas d'archi applicative custom, pas de Makefile | — (support de E4/E5) |
| `api-gateway` | C#, clean architecture | Hub de routage pur (analogie YARP/Ocelot) : proxy vers `mcp`/`text2sql-ai`/`sorabelsql-api` — **aucune logique d'autorisation** (portée entièrement par `mcp`) | — (support de E4) |
| `mcp` | Python, hexagonale | Serveur MCP : catalogue des tools (composite `answer_question` + briques), matrice d'accès (profil × tool × collections/tables), filtrage `list_tools`/`call_tool`, journalisation | E4, E5 |
| `rag-hybride` | Python, hexagonale | Ingestion, hybrid retrieval (dense + BM25), reranking, citations systématiques | E1, E2, E6 |
| `text2sql-ai` | Python, hexagonale | Agent Text-to-SQL : **génération seule** de SQL lecture seule à partir du schéma commenté filtré par profil, n'exécute jamais | E3 |
| `sorabelsql-api` | C# + PostgreSQL, clean architecture | **Exécution seule** du SQL (déjà généré ou fourni tel quel), chaîne de garde-fous, tools figés (stock, commandes), masquage colonnes | E3, E5 |
| `frontend` | à déterminer | Interface(s) cliente(s) / administration | — |

> Évolutions depuis la version précédente : `identity-provider` → `sorabel-idp` (bascule
> Keycloak) ; `authorization-gateway` → `api-gateway` (recentré sur le routage pur, la
> matrice d'accès reste côté `mcp`) ; `tools-api` supprimé et remplacé par
> `sorabelsql-api` (exécution) ; `text2sql-ai` ajouté (génération). Cette séparation
> génération/exécution donne au client un point d'inspection entre l'étape probabiliste
> (LLM) et l'étape gouvernée (garde-fous).

## Flux global

`api-gateway` est le **hub unique** de tous les flux, y compris les appels *internes*
émis par `mcp` vers ses backends — il n'existe aucun lien direct `mcp` ↔ `rag-hybride` /
`text2sql-ai` / `sorabelsql-api`.

```mermaid
flowchart LR
    Client(["Clients<br/>Slack / Poste vente / IDE"]) <-->|"① auth<br/>② JWT + profil"| AG
    Client <-->|"③ list_tools / call_tool<br/>Bearer JWT · ⑥ résultat"| AG["api-gateway<br/>(hub de routage pur, aucune autz)"]

    AG <-.->|"relais transparent"| IDP["sorabel-idp<br/>(Keycloak, JWT + profil)"]
    AG <-->|"③bis relais<br/>sans inspection RBAC · ⑥ résultat"| MCP["mcp<br/>(vérif JWT, matrice d'accès,<br/>catalogue de tools)"]

    AG <-.->|"⑤ter search_documents<br/>et briques RAG"| RAG["rag-hybride<br/>(retrieval hybride)"]
    AG <-.->|"⑤bis ask_database<br/>(génération)"| T2S["text2sql-ai<br/>(génération SQL seule)"]
    AG <-.->|"⑤ run_sql_query<br/>+ tools figés"| SQLAPI["sorabelsql-api<br/>(exécution + garde-fous)"]
```

## Commandes

Le répertoire d'exécution fait partie du contrat : l'outillage Python est mutualisé à la
racine (`mcp`, `text2sql-ai`, `rag-hybride`), mais chaque projet garde son propre paquet
`app`. Les projets C# (`api-gateway`, `sorabelsql-api`) et Python suivent des cibles
Makefile standardisées — voir `.claude/rules/makefile-conventions.md`.

| Commande | Depuis |
|---|---|
| `pip install -e ".[dev]"` | racine du dépôt |
| `docker compose up -d --wait postgres` | racine du dépôt |
| `ruff check .` / `ruff format .` | racine du dépôt (couvre tous les projets Python) |
| `pytest` | le répertoire du projet Python (`cd rag-hybride`) |
| `mypy app` | le répertoire du projet Python |
| `alembic upgrade head` | le répertoire du projet Python |
| `dotnet build` / `dotnet test` | le répertoire du projet C# |

`pytest` et `mypy` s'exécutent projet par projet, pour deux raisons distinctes :

- **Aujourd'hui** : certains tests résolvent leurs fixtures par chemin relatif au
  répertoire courant (`tests/eval/questions_rag.jsonl`) — lancés depuis la racine,
  ils échouent.
- **À terme** : `mcp` et `text2sql-ai` exposeront eux aussi un paquet de premier
  niveau `app` ; une exécution unique depuis la racine se heurterait alors à une
  collision de noms.

## Règles transverses

@.claude/rules/git-conventions.md
@.claude/rules/security.md
@.claude/rules/api-contracts.md
@.claude/rules/makefile-conventions.md

## Règles d'architecture par stack

- Projets Python hexagonaux (`mcp`, `rag-hybride`, `text2sql-ai`) → @.claude/rules/python-hexagonal.md
- Projets C# clean architecture (`api-gateway`, `sorabelsql-api`) → @.claude/rules/csharp-clean-architecture.md
- `sorabel-idp` n'hérite d'aucune règle d'architecture ni du Makefile standard (service Keycloak à configurer, pas une app développée en interne)

## Documentation de cadrage

Les documents conceptuels détaillés (non importés automatiquement — volumineux, à
consulter à la demande) :
- `docs/architecture/MCP.md` — catalogue des tools, matrice d'accès, séquences auth, séparation génération/exécution SQL
- `docs/architecture/Text2SQL_Sorabel.md` — pipeline Text-to-SQL, garde-fous, golden dataset
- `docs/architecture/Advanced_RAG.md` — ingestion, chunking, hybrid retrieval, évaluation
- `docs/architecture/organisation-dossier-claude-sorabel.md` — organisation du dossier `.claude/` du monorepo (héritage, Makefiles, mutualisé vs local)

Chaque projet a son propre `CLAUDE.md` pour le contexte métier local.
