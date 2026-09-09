# Tests — mcp

Les niveaux et leur critère d'appartenance sont définis une seule fois, pour
toute la solution, dans `../.claude/rules/testing-pyramid.md` — ce fichier ne
fait que dire ce que `mcp` met dans chacun. Convention Arrange / Act / Assert,
dans l'esprit de `rag-hybride/.claude/rules/testing-pytest.md`. L'interpréteur est partagé entre les
trois projets Python de la solution (`mcp`, `text2sql-ai`, `rag-hybride`) —
`pip install -e ".[dev]"` se lance depuis la racine du dépôt, mais `pytest`
se lance **depuis le répertoire du projet** (`cd mcp`), jamais depuis la
racine (cf. `../CLAUDE.md` § Commandes : certains tests résolvent leurs
fixtures par chemin relatif, et une exécution unique depuis la racine se
heurterait à terme à une collision du paquet `app`).

```
tests/
├── unit/          # niveau 1 — domaine, use cases, adapters : ports/réseau doublés
├── integration/    # niveau 2 — adapters contre une dépendance réellement exercée
├── contract/       # niveau 3 — serveur assemblé en mémoire, backends doublés
├── acceptance/     # niveau 4 — vide : voir tests/acceptance/README.md
└── harness.py      # doublures partagées entre niveaux (hors pyramide)
```

**Le niveau 4 (acceptance / E2E) est câblé mais vide.** La cible `make test-e2e`
existe et démarre le `docker compose` de la racine, mais `tests/acceptance/` ne
contient aucun scénario : `mcp` n'a pas de Dockerfile propre (cf.
`../.claude/rules/makefile-conventions.md`, § « Exception — outillage Python
partagé ») et le compose racine ne déclare pas encore ses vraies dépendances.
Rien de ce qui suit ne prouve donc que le service démarre avec sa configuration
réelle. Détail et prérequis : `tests/acceptance/README.md`.

Ne pas combler ce trou en gonflant `contract/` : un scénario qui ne démarre pas
le service tel qu'il sera déployé reste un test de niveau 3.
## Les deux cibles

| Cible | Contenu |
|---|---|
| `make test` | niveaux 1 à 3 — `pytest --ignore=tests/acceptance`, sans Docker |
| `make test-e2e` | niveau 4 seul — démarre les dépendances réelles, puis les arrête |

`make test-e2e` **échoue tant que `tests/acceptance/` ne contient aucun test**,
avec un message qui renvoie à `tests/acceptance/README.md`. C'est délibéré : une
cible verte qui n'exécute rien affirmerait une garantie inexistante. La garde
s'exécute avant tout démarrage de conteneur.


## `tests/unit/`

Aucun accès réseau réel (interdit par la spec de conception §11.1). Les ports
backend (`RagPort`, `Text2SqlPort`, `SqlExecutionPort`, `AuditLogPort`,
`TokenVerifierPort`) sont doublés par de simples objets en mémoire ; le seul
transport HTTP en jeu (`RagHttpClient`) est exercé contre un
`httpx.MockTransport`, jamais une socket réelle. C'est là que vivent les
règles : fail closed, barrières 1 et 2, exhaustivité catalogue/matrice,
composite `answer_question`, format du journal d'audit.

## `tests/integration/`

La seule exception assumée à la règle « pas de réseau » — limitée à la boucle
locale (`127.0.0.1`). `RagHttpClient` y est exercé contre un **vrai serveur**
`uvicorn`, démarré sur un port éphémère, qui sert une **doublure du contrat**
`rag-hybride` (pas l'application `rag-hybride` elle-même : les deux projets
exposent chacun un paquet `app`, les importer dans le même processus serait
la collision décrite dans `../CLAUDE.md`). Vrai socket, vrai `httpx`, vrais
délais — 200, `refused`, 500, timeout, connexion refusée, propagation du
`X-Correlation-Id`. Le même niveau couvre aussi `JwksTokenVerifier` et
`LocalKeyTokenVerifier` (cryptographie réelle) et le chargement du vrai
`access_matrix.yaml` du dépôt.

### Le marqueur `live`

Un test, `tests/integration/test_rag_client_http.py::test_contre_le_vrai_rag_hybride_s_il_ecoute`,
est marqué `@pytest.mark.live` : il tape le **vrai** `rag-hybride` sur
`http://localhost:8001` — le seul point de vérification réelle entre les deux
projets. Le marqueur est déclaré dans la section pytest du `pyproject.toml`
**racine** (partagé par les trois projets Python) :

```toml
[tool.pytest.ini_options]
markers = [
    "live: test optionnel nécessitant un backend réellement en écoute (sauté par défaut)",
]
addopts = '-m "not live"'
```

`addopts` l'exclut de toute exécution par défaut — `pytest -q` ne le lance
jamais. Sans cette ligne, ce test ne serait jamais exécuté par personne : il
faut l'opt-in explicite, `rag-hybride` réellement démarré sur le port
attendu :

```
cd mcp
../.venv/Scripts/python.exe -m pytest -m live
```

## `tests/contract/`

Sept scénarios (`test_personas.py`), un par persona (bot
Slack support, poste de vente, IDE développeur, question hors corpus, appel
sans token, backend injoignable), joués à travers un **vrai client MCP** (le
serveur assemblé par `dependencies.py`, la matrice réelle, le journal
d'audit de production) — seuls les trois ports backend restent doublés par
les stubs de `app/infrastructure/stub/`. Aucun objet interne, aucun
monkeypatch : ce que voit le test est ce que verrait le bot Slack.

Ces scénarios sont de **niveau 3, pas de niveau 4**, malgré leur allure de bout
en bout : l'application est assemblée en mémoire dans le processus de test et
ses trois ports backend sont doublés (« aucun accès réseau réel », spec de
conception §11.1). C'est exactement le critère du niveau 3. Le dossier
s'appelait `acceptance/` — le nom promettait une garantie de packaging et de
configuration réelle que ces tests n'apportent pas.

## Lancer les tests

```
cd mcp
../.venv/Scripts/python.exe -m pytest -q
```

Référence actuelle : 269 tests passants, 1 désélectionné (le test `live`).

## Ce que Claude doit faire

- Ne jamais introduire d'accès réseau réel dans `tests/unit/` — mocker le
  port, ou simuler le transport `httpx` (`httpx.MockTransport`).
- Ne jamais marquer un nouveau test `live` sans qu'il tape un vrai backend
  externe démarré indépendamment de la suite — ce marqueur est réservé à ce
  cas, pas un raccourci pour sauter un test lent.
- Tout nouveau tool passe par `tests/unit/test_exhaustivite.py` (cf.
  `.claude/rules/mcp-primitives.md`) avant tout test de plus haut niveau.
- Ne jamais ranger dans `tests/contract/` un scénario qui démarre le service
  réel : il relèverait du niveau 4, qui n'existe pas encore ici — le signaler
  plutôt que de le déguiser.
