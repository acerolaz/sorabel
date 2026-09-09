# Tests — text2sql-ai

Les niveaux et leur critère d'appartenance sont définis une seule fois, pour
toute la solution, dans `../.claude/rules/testing-pyramid.md` — ce fichier ne
fait que dire ce que `text2sql-ai` met dans chacun.

L'interpréteur est partagé entre les trois projets Python de la solution
(`mcp`, `text2sql-ai`, `rag-hybride`) : `pip install -e ".[dev]"` se lance
depuis la racine du dépôt, mais `pytest` se lance **depuis le répertoire du
projet** (`cd text2sql-ai`), jamais depuis la racine (cf. `../CLAUDE.md`
§ Commandes — collision du paquet `app` entre projets).

## Organisation

```
tests/
├── unit/          # niveau 1 — domaine, use cases, garde-fous : ports doublés
├── contract/       # niveau 3 — l'app FastAPI en mémoire (httpx.ASGITransport)
├── acceptance/     # niveau 4 — vide : voir tests/acceptance/README.md
├── eval/           # hors pyramide — golden dataset + `run_eval.py`
└── conftest.py     # fixtures partagées
```

## `tests/unit/`

Aucune I/O, aucun réseau, aucun framework web. C'est là que vivent les règles
qui portent E3 : validation read-only (`test_guardrails.py`), filtrage du schéma
par profil (`test_schema_repository.py`), construction du prompt
(`test_prompt.py`), use case de génération (`test_generate_sql.py`). Le client
Azure et le juge sont doublés par leurs ports.

## `tests/contract/`

`test_generate.py` monte `app.main:app` via `httpx.ASGITransport`, avec les
dépendances Azure surchargées (`conftest.py` pose des variables d'environnement
factices et vide les `lru_cache` de `get_settings`/`get_azure_client`). On y
vérifie le **contrat HTTP** — route, code, forme de l'erreur selon
`../.claude/rules/api-contracts.md` — jamais une règle métier : celle-ci se
teste en niveau 1, où elle est isolable sans framework.

## `tests/eval/`

`golden_dataset.jsonl` + `run_eval.py` : rejeu manuel du golden dataset contre
le **vrai** pipeline de génération (vrais appels Azure OpenAI, jamais
d'exécution SQL), avec un taux de correspondance par catégorie
(`Text2SQL_Sorabel.md` §2). Ce n'est pas un niveau de la pyramide et ce n'est
pas branché sur `make test` : c'est l'outillage de mesure, lancé à la main.

```
cd text2sql-ai
python -m tests.eval.run_eval
```

## Niveaux absents

**Niveau 2 (intégration technique) : absent.** Aucun adapter n'est aujourd'hui
exercé contre sa vraie dépendance ou un double fidèle (`httpx.MockTransport`,
WireMock).

**Niveau 4 (acceptance / E2E) : câblé mais vide.** La cible `make test-e2e`
existe et construit l'image puis démarre le conteneur — `text2sql-ai` a son
propre Dockerfile (cf. `../.claude/rules/makefile-conventions.md`, § « Exception
— `text2sql-ai` »), c'est donc le projet Python le mieux placé pour porter un
vrai niveau 4. Mais `tests/acceptance/` ne contient aucun scénario. Détail et
question ouverte (Azure OpenAI) : `tests/acceptance/README.md`.

Absences signalées, pas compensées : ne pas gonfler `unit/` ou `contract/` pour
faire nombre.
## Les deux cibles

| Cible | Contenu |
|---|---|
| `make test` | niveaux 1 à 3 — `pytest --ignore=tests/acceptance`, sans Docker |
| `make test-e2e` | niveau 4 seul — démarre les dépendances réelles, puis les arrête |

`make test-e2e` **échoue tant que `tests/acceptance/` ne contient aucun test**,
avec un message qui renvoie à `tests/acceptance/README.md`. C'est délibéré : une
cible verte qui n'exécute rien affirmerait une garantie inexistante. La garde
s'exécute avant tout démarrage de conteneur.


## Convention AAA

Chaque test suit **Arrange / Act / Assert**, avec un commentaire marquant chaque
section si le test dépasse quelques lignes (même convention que `rag-hybride` et
`mcp`).

## Ce que Claude doit faire

- Ne jamais introduire d'accès réseau réel dans `tests/unit/` — doubler le port,
  ou simuler le transport `httpx` (`httpx.MockTransport`).
- Ne jamais ranger dans `contract/` un test qui démarre le service réel : il
  relèverait du niveau 4, qui n'existe pas encore ici.
- Toute nouvelle règle de garde-fou read-only (E3) est couverte en niveau 1
  **avant** tout test de plus haut niveau.
- Ne jamais écrire un test qui exécute réellement le SQL généré — `text2sql-ai`
  génère, `sorabelsql-api` exécute (E3).
