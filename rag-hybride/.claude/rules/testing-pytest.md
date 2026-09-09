# Tests — rag-hybride

## Organisation

Les niveaux et leur critère d'appartenance sont définis une seule fois, pour
toute la solution, dans `../.claude/rules/testing-pyramid.md` — ce fichier ne
fait que dire ce que `rag-hybride` met dans chacun.

```
tests/
├── unit/          # niveau 1 — domain/ + application/, tous les ports mockés
├── integration/    # niveau 2 — infrastructure/, Testcontainers (Postgres+pgvector réel)
├── contract/       # niveau 3 — l'app FastAPI en mémoire (httpx.ASGITransport),
│                   #            adapters doublés : routes, codes, format d'erreur
├── acceptance/     # niveau 4 — vide : voir tests/acceptance/README.md
├── eval/           # hors pyramide — jeu `questions_rag.jsonl` + `run_eval.py`,
│                   #            outillage de mesure E6 (hybride vs vectoriel simple)
└── conftest.py     # fixtures partagées
```

**Le niveau 4 (acceptance / E2E) est câblé mais vide.** La cible `make test-e2e`
existe et démarre le Postgres/pgvector du `docker compose` de la racine, mais
`tests/acceptance/` ne contient aucun scénario. `tests/contract/` monte
l'application en mémoire avec ses adapters doublés : rien n'y prouve que le
service démarre avec sa configuration réelle. Détail et prérequis :
`tests/acceptance/README.md`. À signaler, pas à compenser en gonflant
`contract/`.
## Les deux cibles

| Cible | Contenu |
|---|---|
| `make test` | niveaux 1 à 3 — `pytest --ignore=tests/acceptance`, sans Docker |
| `make test-e2e` | niveau 4 seul — démarre les dépendances réelles, puis les arrête |

`make test-e2e` **échoue tant que `tests/acceptance/` ne contient aucun test**,
avec un message qui renvoie à `tests/acceptance/README.md`. C'est délibéré : une
cible verte qui n'exécute rien affirmerait une garantie inexistante. La garde
s'exécute avant tout démarrage de conteneur.


> Le fichier `contract/test_flow_complet.py` s'appelait `test_acceptance_flow.py` :
> le nom promettait une garantie de niveau 4 que ce test, entièrement en mémoire,
> n'apporte pas.

## Convention AAA

Chaque test suit **Arrange / Act / Assert**, avec un commentaire marquant chaque section
si le test dépasse quelques lignes :

```python
def test_fusion_favorise_le_resultat_present_dans_les_deux_classements():
    # Arrange
    dense_results = [...]
    sparse_results = [...]

    # Act
    fused = reciprocal_rank_fusion(dense_results, sparse_results)

    # Assert
    assert fused[0].chunk_id == "expected_chunk_id"
```

## Règles

- **Unit tests** : mockent uniquement les *ports* (`VectorStorePort`, `LLMPort`...), jamais un détail d'implémentation infrastructure. Aucune dépendance réseau/DB.
- **Contract tests** : montent `app.main:app` via `httpx.ASGITransport`, avec les use
  cases surchargés par `app.dependencies` — on y vérifie le **contrat HTTP** (route,
  code, forme de l'erreur selon `../.claude/rules/api-contracts.md`), jamais une règle
  métier : celle-ci se teste en niveau 1, où elle est isolable.
- **Integration tests** : utilisent **Testcontainers** pour lancer un Postgres/pgvector éphémère — jamais de mock sur la couche `infrastructure/postgres/`, sinon le test ne couvre rien de réel.
- Un cas de fusion RRF, un cas de chunking par section, un cas de refus (E1) sont couverts en priorité — ce sont les points les plus sensibles du pipeline.
- Nommage des tests : `test_<comportement>_<condition>` en français ou anglais, cohérent dans tout le fichier.

## Ce que Claude doit faire

- Ne jamais écrire un test d'intégration Postgres avec un mock à la place de Testcontainers.
- Toujours proposer un test pour toute nouvelle règle métier du domaine (fusion, seuil de refus, chunking).
- Signaler si un test unit dépend implicitement d'un état partagé entre tests (pas d'isolation).
- Ne jamais ranger un test dans `contract/` parce qu'il est « de bout en bout » : le critère
  est *l'application en mémoire, dépendances doublées*, pas la longueur du scénario.
