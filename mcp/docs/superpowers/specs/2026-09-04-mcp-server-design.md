# Serveur MCP `mcp` — Design

> Spec de conception du serveur MCP unifié de la solution Sorabel (projet `mcp`).
> Sources : `MCP.md` (cadrage détaillé), `mcp/README.md`, `../CLAUDE.md`, règles
> transverses `.claude/rules/`.

## 1. Objectif

Construire le serveur MCP `mcp` : un catalogue de 13 tools exposés en HTTP, gouverné par
une matrice d'accès centralisée (profil × tool × collections/tables), authentifié par JWT
et journalisé intégralement.

`mcp` ne stocke rien, n'indexe rien et ne génère aucun texte. Sa seule logique propre est
la **décision d'autorisation**, la **projection du catalogue** selon le profil, le
**typage des erreurs**, l'**audit** et la **composition** d'`answer_question`. Tout le
reste est de l'adaptation vers des backends.

Exigences servies : **E4** (architecture MCP unifiée, matrice centralisée) et **E5**
(auditabilité). E1 est relayée — le refus hors corpus est propagé tel quel, jamais
reformulé.

## 2. État des lieux au moment de la conception

| Constat | Conséquence sur ce lot |
|---|---|
| `mcp/` ne contient aucun code (README, CLAUDE.md, Makefile, 2 fichiers `.claude/`) | Lot fondateur : arborescence hexagonale complète à créer |
| Seul `rag-hybride` est implémenté ; il n'expose que `POST /api/v1/query` et `POST /api/v1/ingest` | Une seule liaison backend réelle possible ; aucune brique RAG n'a d'endpoint |
| `api-gateway`, `text2sql-ai`, `sorabelsql-api` sont des README sans code | Leurs appels passent par des adapters stub |
| Keycloak n'est ni conteneurisé ni configuré (`docker-compose.yml` ne lance que Postgres) | Vérification JWT à deux adapters, dont un utilisable sans Keycloak |
| Le SDK MCP n'est pas dans `pyproject.toml` | Dépendances à ajouter |
| Aucun interpréteur compatible localement (Python 3.9 et 3.14 seulement, pas de venv) | Prérequis du plan d'implémentation : venv 3.12 |

## 3. Décisions de cadrage

| # | Décision | Justification |
|---|---|---|
| D1 | Serveur **complet** (13 tools, matrice, JWT, audit), backends derrière des ports avec adapters stub | La gouvernance est la valeur du projet ; elle est implémentable et testable sans les backends |
| D2 | Transport **HTTP streamable uniquement** | Seul transport portant un en-tête `Authorization` ; conforme aux séquences `MCP.md` §3 et §6.1 (client → api-gateway → mcp) |
| D3 | Vérification JWT par **port + 2 adapters** (JWKS Keycloak / clé locale de dev) | Le lot reste complet sans Keycloak ; bascule par configuration, sans modification de code |
| D4 | **Une base URL par backend**, configurable | Le code ignore s'il parle à l'`api-gateway` ou au service ; la règle « aucun appel direct » devient une contrainte de déploiement, pas de code |
| D5 | Journal d'audit : **port + adapter stdout JSON** | Append-only par construction, zéro infrastructure, cohérent avec « `mcp` ne stocke rien » |
| D6 | `answer_question` câblé sur `POST /api/v1/query`, **texte généré écarté** | Respecte `MCP.md` §1 (aucune génération côté serveur) tout en donnant de vraies sources |
| D7 | **Catalogue domaine + fonctions typées, réconciliés par un test** | Conserve le typage `mypy strict` et les docstrings idiomatiques, tout en rendant impossible un tool sans droit déclaré |

## 4. Architecture

Architecture hexagonale, conforme à `.claude/rules/python-hexagonal.md` : `domain/`
n'importe ni FastMCP, ni httpx, ni pydantic-settings.

```
mcp/
├── access_matrix.yaml
├── app/
│   ├── domain/
│   │   ├── models.py               # Profile, ToolName, ToolCall, Decision, AuditEntry, Identity
│   │   ├── catalog.py              # ToolDescriptor : nom, famille, backend requis
│   │   ├── access_matrix.py        # AccessMatrix + decide(profile, tool) -> Decision
│   │   ├── errors.py               # erreurs métier typées
│   │   └── ports.py                # TokenVerifierPort, AuditLogPort, RagPort, Text2SqlPort, SqlExecutionPort
│   ├── application/use_cases/
│   │   ├── list_available_tools.py # projection du catalogue selon le profil
│   │   ├── authorize_tool_call.py  # barrière 1 : profil × tool
│   │   ├── answer_question.py      # composite : orchestre 3 appels RagPort
│   │   └── forward_to_backend.py   # barrière 2 : périmètre issu de la matrice, puis délégation
│   ├── infrastructure/
│   │   ├── keycloak/jwks_verifier.py
│   │   ├── keycloak/local_key_verifier.py
│   │   ├── http/{rag_client,text2sql_client,sqlapi_client}.py
│   │   ├── stub/{rag_stub,text2sql_stub,sqlapi_stub}.py
│   │   ├── matrix/yaml_loader.py
│   │   └── audit/stdout_audit_log.py
│   ├── api/
│   │   ├── server.py               # instance FastMCP, app ASGI, middleware de gouvernance
│   │   ├── tools/{rag,sql}.py      # les 13 fonctions @mcp.tool() et leurs docstrings
│   │   └── schemas/                # DTO Pydantic d'entrée/sortie
│   ├── config.py
│   └── dependencies.py             # câblage ports -> adapters selon la configuration
└── tests/
    ├── unit/          # domain/ + application/ + adapters isolés, aucun I/O
    ├── integration/    # adapters contre une vraie dépendance (serveur HTTP, fichiers)
    ├── acceptance/     # scénarios de bout en bout par persona, via un vrai client MCP
    └── conftest.py
```

### 4.1 Pas de use case par tool

Les tools sont majoritairement du passe-plat. Quatre use cases suffisent :
`list_available_tools`, `authorize_tool_call`, `answer_question` (seule orchestration
réelle du projet) et `forward_to_backend`, paramétré par le port cible et le périmètre
issu de la matrice. Les 13 fonctions `@mcp.tool()` restent des signatures typées portant
leur docstring ; elles ne contiennent aucune logique.

### 4.2 Les deux barrières de `MCP.md` §3

| Barrière | Emplacement | Rôle |
|---|---|---|
| 1 — grossière | Middleware FastMCP, avant dispatch | `list_tools` ne renvoie que le sous-ensemble autorisé ; `call_tool` sur un tool non autorisé est rejeté sans jamais atteindre la fonction |
| 2 — fine | `forward_to_backend` | Le périmètre (collections RAG, tables SQL) est lu dans la matrice et transmis au backend, jamais choisi par l'appelant |

Le **masquage de colonnes** n'est pas appliqué par `mcp` : il est porté par
`sorabelsql-api`, qui seul voit les lignes. La matrice de `mcp` le déclare pour que la
politique reste centralisée en un seul fichier, et le transmet au backend.

## 5. Identité et vérification du token

`TokenVerifierPort.verify(token) -> Identity(subject, profile, expires_at)`.

| Adapter | Vérifie | Sélection |
|---|---|---|
| `JwksTokenVerifier` | signature via JWKS Keycloak (clés en cache TTL), `iss`, `aud`, `exp` | `MCP_TOKEN_VERIFIER=jwks` |
| `LocalKeyTokenVerifier` | signature symétrique, secret lu dans le `.env` racine | `MCP_TOKEN_VERIFIER=local` |

Deux garde-fous sur l'adapter de développement :

1. le démarrage échoue si `MCP_TOKEN_VERIFIER=local` alors que `MCP_ENV != dev` ;
2. le démarrage échoue si le secret est vide — aucune valeur par défaut en dur,
   conformément à `.claude/rules/security.md`.

Le profil provient du claim `sorabel_profile` émis par `sorabel-idp`. Claim absent ou
profil inconnu de la matrice : **refus** (fail closed), jamais un défaut permissif.

## 6. Matrice d'accès

Fichier `access_matrix.yaml` versionné, chargé au démarrage, converti en objet domaine
immuable.

```yaml
version: 1
profiles:
  support:
    tools: [search_documents, lookup_by_reference, ask_database, get_stock, get_order_status]
    rag_collections: [procedure_sav, manuel]
    sql_tables: [products, stock, orders]
    masked_columns: [purchase_price, margin]
  sales:
    tools: [answer_question, search_documents, lookup_by_reference, get_document_metadata,
            check_answer_confidence, list_document_types, ask_database, get_stock,
            get_order_status, get_customer_order_history]
    rag_collections: [datasheet, manuel, procedure_sav]
    sql_tables: [products, stock, orders]
    masked_columns: [purchase_price, margin]
  dev:
    tools: [search_documents, get_document_metadata, check_answer_confidence,
            list_document_types, get_schema_info, get_query_history, run_sql_query]
    rag_collections: [datasheet, manuel, procedure_sav]
    sql_tables: [products, stock, orders]
    masked_columns: [purchase_price, margin]
```

Transcription de `MCP.md` §6.4 : `support` 5 tools, `sales` 10, `dev` 7. `ask_database`
(génération) est ouvert à `support` et `sales` ; `run_sql_query` (exécution) au seul
profil `dev`.

`decide(profile, tool)` renvoie `Allowed(scope)` ou `Denied(code, rule)`. Le message d'un
refus ne confirme jamais l'existence d'une ressource non autorisée.

## 7. Erreurs typées

Tout refus ou échec produit un `CallToolResult` avec `isError: true` et un contenu
structuré — jamais un texte narratif qu'un LLM client pourrait paraphraser en réponse.

| Code | Origine |
|---|---|
| `UNAUTHENTICATED` | token absent, invalide ou expiré |
| `UNAUTHORIZED_TOOL` | tool hors matrice du profil |
| `UNAUTHORIZED_COLLECTION` | collection RAG hors périmètre |
| `UNAUTHORIZED_TABLE` | table SQL hors périmètre |
| `NOT_FOUND_IN_CORPUS` | `rag-hybride` répond `refused` (E1) |
| `SCHEMA_MISMATCH` | table/colonne inconnue signalée par un backend |
| `BACKEND_UNAVAILABLE` | backend injoignable ou 5xx |

Le corps structuré reprend les champs de `.claude/rules/api-contracts.md` :
`error_code`, `message`, `correlation_id`.

### 7.1 Appel non authentifié

Cas non couvert par `MCP.md`, tranché ici : `list_tools` sans token valide renvoie un
catalogue **vide** — un appelant non authentifié n'apprend pas quels tools existent — et
`call_tool` renvoie `UNAUTHENTICATED`. Les deux événements sont journalisés.

## 8. Journal d'audit (E5)

Une entrée JSON par appel sur stdout, **autorisé comme refusé** :

| Champ | Contenu |
|---|---|
| `timestamp`, `correlation_id` | horodatage et corrélation des round-trips |
| `subject`, `profile` | identité issue du token |
| `tool`, `arguments` | tool appelé et ses arguments (question NL, SQL) |
| `decision`, `rule` | `allow`/`deny` et règle de matrice appliquée |
| `backend` | `http` ou `stub` |
| `row_count`, `latency_ms` | volume et latence |
| `error_code` | présent si `isError` |

**Frontière de journalisation** : la *requête* est journalisée — c'est elle qu'on audite,
`MCP.md` §4 l'exige ; le *résultat* ne l'est jamais, seul son `row_count` l'est
(`.claude/rules/security.md`).

Le `correlation_id` est généré à l'entrée, renvoyé dans les erreurs et propagé aux
backends via un en-tête.

## 9. Catalogue des tools et câblage

| Tool | Port | Câblage dans ce lot |
|---|---|---|
| `answer_question` | `RagPort` (composite) | **réel** pour les citations, stub pour métadonnées et catalogue |
| `search_documents` | `RagPort` | stub |
| `lookup_by_reference` | `RagPort` | stub |
| `get_document_metadata` | `RagPort` | stub |
| `check_answer_confidence` | `RagPort` | stub |
| `list_document_types` | `RagPort` | stub |
| `ask_database` | `Text2SqlPort` | stub |
| `run_sql_query` | `SqlExecutionPort` | stub |
| `get_stock` | `SqlExecutionPort` | stub |
| `get_order_status` | `SqlExecutionPort` | stub |
| `get_customer_order_history` | `SqlExecutionPort` | stub |
| `get_schema_info` | `SqlExecutionPort` | stub |
| `get_query_history` | `SqlExecutionPort` | stub |

### 9.1 Le composite est écrit intégralement

`answer_question` orchestre les trois appels décrits dans `MCP.md` §1 :
`RagPort.answer()` (réel — `POST /api/v1/query`, dont seuls citations et confidence sont
conservés), `RagPort.document_metadata()` et `RagPort.document_types()` (stubs). C'est la
seule orchestration réelle du projet : elle est écrite et testée maintenant.

Le mélange réel/stub tient dans l'adapter, pas dans le use case : `RAG_BACKEND` reste une
valeur unique, et l'adapter HTTP `RagHttpClient` implémente `answer()` contre l'endpoint
réel tout en **déléguant au stub** les méthodes dont l'endpoint n'existe pas encore dans
`rag-hybride`, chaque délégation marquant son bloc `source: "stub"`. Chaque endpoint
ajouté à `rag-hybride` remplace une délégation, sans toucher ni au use case ni au port.
Un test vérifie que les méthodes encore déléguées sont exactement celles attendues, pour
qu'une délégation oubliée ne survive pas à l'arrivée de son endpoint.

### 9.2 Provenance des données

Toute réponse issue d'un adapter stub porte `source: "stub"` dans son bloc, et son entrée
d'audit porte `backend: "stub"`. Une donnée fictive ne peut être confondue avec une donnée
réelle, ni en démonstration ni dans un journal.

### 9.3 Docstrings

Les 13 docstrings de `MCP.md` §2 sont reprises telles quelles, consignes de priorité
comprises (« À utiliser EN PRIORITÉ », « NE L'EXÉCUTE PAS », « NE GÉNÈRE AUCUN SQL »,
préfixe `CRITICAL:`). Elles *sont* la description lue par le LLM client lors de
`list_tools`. Un test vérifie qu'aucune n'est vide.

## 10. Configuration

Variables lues dans le `.env` unique à la racine de la solution, via `app/config.py`
construit sur le modèle de `rag-hybride/app/config.py` — chemin résolu depuis le fichier,
pas depuis le répertoire courant.

| Variable | Rôle |
|---|---|
| `MCP_ENV` | `dev` / `prod` — verrouille l'adapter de token local |
| `MCP_TOKEN_VERIFIER` | `jwks` ou `local` |
| `MCP_JWKS_URL`, `MCP_JWT_ISSUER`, `MCP_JWT_AUDIENCE` | validation Keycloak |
| `MCP_DEV_JWT_SECRET` | secret de signature des tokens de test, vide par défaut |
| `MCP_ACCESS_MATRIX_PATH` | chemin de `access_matrix.yaml` |
| `RAG_BASE_URL`, `TEXT2SQL_BASE_URL`, `SQLAPI_BASE_URL` | en dev : le service ; en cible : l'`api-gateway` |
| `RAG_BACKEND`, `TEXT2SQL_BACKEND`, `SQLAPI_BACKEND` | `http` ou `stub` — un adapter HTTP peut déléguer au stub les méthodes sans endpoint (§9.1) |
| `MCP_HTTP_TIMEOUT_S` | timeout des appels sortants |

Dépendances à ajouter au `pyproject.toml` racine : `mcp` (SDK), `pyjwt[crypto]`, et
`httpx` déplacé de `[dev]` vers les dépendances principales — il devient une dépendance
d'exécution.

## 11. Tests

Trois niveaux, dans l'esprit de `rag-hybride/.claude/rules/testing-pytest.md` (convention
Arrange / Act / Assert, ports mockés en unitaire seulement). Implémentation en TDD :
test rouge avant chaque bloc.

| Niveau | Répertoire | Ce qui est réel | Ce qui est doublé |
|---|---|---|---|
| Unitaire | `tests/unit/` | domaine, use cases, logique d'un adapter | tous les ports ; transport `httpx` simulé |
| Intégration | `tests/integration/` | vrai serveur HTTP, vrai socket, vrai système de fichiers | le service distant (doublure de contrat) |
| Acceptance | `tests/acceptance/` | l'application assemblée, protocole MCP compris | les backends, par leurs adapters stub |

### 11.1 Unitaires — `tests/unit/`

Domaine et application avec faux ports, aucun I/O. C'est là que vivent les règles.

| Test | Ce qu'il verrouille |
|---|---|
| Exhaustivité tools ↔ catalogue ↔ YAML | Un tool ajouté sans ligne de matrice fait échouer la CI — contrepartie de D7 |
| Grille 3 profils × 13 tools | Les 39 décisions de `MCP.md` §6.4, en table de données |
| Fail closed | Profil inconnu, claim absent, tool hors catalogue → refus, jamais un défaut permissif |
| Refus avant dispatch | `isError` + `UNAUTHORIZED_TOOL`, **et** le faux port backend enregistre zéro appel |
| Périmètre (barrière 2) | Collection hors matrice → `UNAUTHORIZED_COLLECTION` ; le périmètre transmis au port vient de la matrice, pas de l'appelant |
| Composite | `answer_question` appelle les 3 méthodes du port une fois chacune et propage le `correlation_id` |
| Audit (E5) | Une entrée par appel autorisé et par appel refusé, champs obligatoires présents, et aucune ligne de résultat dans le journal — seul `row_count` |
| Adapter HTTP RAG | Transport `httpx` simulé : 200 → citations, `refused` → `NOT_FOUND_IN_CORPUS`, 5xx → `BACKEND_UNAVAILABLE` |
| Docstrings | Les 13 tools ont une docstring non vide |
| Délégations stub | Les méthodes encore déléguées au stub par l'adapter HTTP sont exactement la liste attendue (§9.1) |

### 11.2 Intégration — `tests/integration/`

Les adapters d'infrastructure contre une dépendance **réellement** exercée. Pas de
Testcontainers ici — ce projet n'a ni base ni migration ; ce qu'il a de réel à éprouver,
c'est du réseau, de la cryptographie et des fichiers.

| Test | Dépendance réelle |
|---|---|
| `RagHttpClient` contre un serveur HTTP éphémère | Un `uvicorn` sur port libre sert une doublure du contrat `rag-hybride` : 200, `refused`, 500, timeout, connexion refusée — vrai socket, vrai `httpx`, vrais délais |
| Propagation du `correlation_id` | L'en-tête est réellement reçu par le serveur distant |
| `JwksTokenVerifier` contre un JWKS servi en HTTP | Paire RSA générée dans le test, JWKS réel : signature valide, clé inconnue, rotation de clé, cache respecté (un seul appel réseau pour deux vérifications) |
| `LocalKeyTokenVerifier` | Token expiré, `iss`/`aud` faux, signature fausse ; démarrage refusé si verifier `local` hors `dev`, ou secret vide |
| `YamlAccessMatrixLoader` | Chargement du vrai `access_matrix.yaml` du dépôt, puis d'un fichier malformé → échec au démarrage, pas de matrice vide silencieuse |
| Cross-projet, opt-in | Marqué `@pytest.mark.live`, sauté par défaut : tape le vrai `rag-hybride` si `RAG_BASE_URL` répond — seul point de vérification réelle entre les deux projets |

> Pourquoi une doublure de contrat plutôt que l'application `rag-hybride` importée dans le
> test : les deux projets exposent chacun un paquet de premier niveau `app`, et les
> importer dans le même processus est exactement la collision décrite dans
> `../CLAUDE.md` § Commandes. La doublure est servie par un vrai serveur HTTP, ce qui
> laisse le test exercer le transport pour de bon.

Deux points d'outillage : le marqueur `live` est déclaré dans la section pytest du
`pyproject.toml` racine (un marqueur non déclaré devient un avertissement, puis une
erreur en mode strict), et la génération de la paire RSA du test JWKS s'appuie sur
`cryptography`, déjà tiré par `pyjwt[crypto]` (§10). `uvicorn` est déjà une dépendance
principale de la solution.

### 11.3 Acceptance — `tests/acceptance/`

Scénarios de bout en bout, un par persona de `MCP.md`, joués à travers un **vrai client
MCP** (session du SDK sur le transport HTTP streamable) contre l'application assemblée par
`dependencies.py` — aucun accès aux objets internes, aucun monkeypatch : ce que voit le
test est ce que verra le bot Slack.

| Scénario | Exigence |
|---|---|
| Bot Slack support : `list_tools` renvoie exactement 5 tools ; `get_customer_order_history` répond `UNAUTHORIZED_TOOL` ; deux entrées d'audit, une `allow` une `deny` | E4, E5 |
| Poste de vente : `answer_question` renvoie des citations exploitables, et le texte généré par `rag-hybride` n'apparaît nulle part dans la réponse | E1, E4 |
| IDE développeur : `run_sql_query` autorisé ; `ask_database` absent du catalogue *et* refusé s'il est appelé quand même — l'invisibilité n'est pas la seule protection | E3, E4 |
| Question hors corpus : `isError` + `NOT_FOUND_IN_CORPUS`, jamais une réponse rédigée | E1 |
| Appel sans token : catalogue vide, `call_tool` → `UNAUTHENTICATED`, les deux journalisés | E5 |
| Backend injoignable : `BACKEND_UNAVAILABLE` typé, pas de trace d'exception remontée au client | E5 |

## 12. Écarts relevés dans les documents sources

| # | Écart | Traitement retenu |
|---|---|---|
| É1 | `mcp/README.md` décrit 12 tools, `run_sql_query` génératif (`question: str`), pas d'`ask_database` — `MCP.md` et `../CLAUDE.md` décrivent 13 tools et la séparation génération/exécution | `MCP.md` fait foi ; `README.md` est mis à jour dans ce lot |
| É2 | `MCP.md` §5 nomme le champ d'erreur `reason` ; `api-contracts.md` impose `error_code`/`message`/`correlation_id` | Le trio de `api-contracts.md` est retenu — une seule convention d'erreur pour la solution |
| É3 | `MCP.md` §4 demande de journaliser question et SQL ; `security.md` interdit de journaliser le contenu métier | Frontière explicitée : la requête est journalisée, le résultat ne l'est jamais (seul `row_count`) |
| É4 | `MCP.md` §6.4 masque `purchase_price`/`margin` pour les trois profils ; `sorabelsql-api/README.md` §4 écrit « jamais visibles hors profil `sales` » | `MCP.md` est suivi (masqué partout) ; l'écart est signalé, l'arbitrage appartient à `sorabelsql-api`, qui applique le masquage |
| É5 | `MCP.md` §6.1 impose que tout appel sortant transite par l'`api-gateway`, qui n'existe pas | Une base URL configurable par backend (D4) : contrainte de déploiement, pas de code |
| É6 | `MCP.md` §1 exige qu'`answer_question` compose 3 briques ; aucune brique n'a d'endpoint dans `rag-hybride` | Le composite est écrit ; 1 appel réel, 2 stubs, bascule par configuration (D6) |

Trois écarts constatés en cours d'implémentation, arbitrés à ce moment-là mais
jamais consignés ailleurs qu'un journal de session — ils survivent donc ici :

| # | Écart | Traitement retenu |
|---|---|---|
| É7 | Le périmètre documentaire résolu par la barrière 2 n'est pas transmis au backend RAG réel. `RagHttpClient.answer()` appelle `POST /api/v1/query` de `rag-hybride`, dont le schéma `QueryRequest` ne porte aujourd'hui aucun champ de collection (seulement `query`, `product_ref`, `top_k`) ; le corriger imposerait de modifier `rag-hybride`, hors périmètre (§14) | Le périmètre reste appliqué côté `mcp` — un périmètre vide lève `NotFoundInCorpusError` avant tout appel réseau — mais un profil dont le périmètre RAG serait un sous-ensemble strict non vide ne verrait pas ce filtre appliqué par le backend réel. Un test verrouille la forme exacte du corps HTTP émis, pour forcer une relecture de l'adapter le jour où `rag-hybride` transportera les collections |
| É8 | Le plan prévoyait `top_k: 5` dans le corps émis vers `rag-hybride` ; `RagHttpClient.answer()` ne le transmet pas | Choix conservé : `mcp` n'a pas à arbitrer la largeur du retrieval, qui reste une décision de `rag-hybride`. Le défaut `top_k=20` de `QueryRequest` s'applique donc — une recherche quatre fois plus large que ce que le plan prévoyait, sans effet sur aucune propriété de gouvernance |
| É9 | La différenciation par tables et le masquage de colonnes (barrière 2 côté SQL) ne sont démontrés par aucun scénario de `tests/acceptance/` — non par oubli, mais parce que les trois profils de `access_matrix.yaml` partagent aujourd'hui exactement les mêmes `sql_tables` et les mêmes `masked_columns` : aucun sous-ensemble strict n'existe côté SQL, donc aucun scénario ne peut mettre la barrière 2 côté tables en évidence | Fait de conception de la matrice, à revoir si un profil doit un jour être réellement restreint côté données transactionnelles. Le pendant côté RAG, lui, **est** démontré : `support` a un périmètre documentaire (`rag_collections`) strictement plus petit que `sales`/`dev`, et un scénario d'acceptance l'éprouve |

## 13. Livrables

Tous dans `mcp/` — une PR, un scope (`.claude/rules/git-conventions.md`) :

- `app/` complet et `access_matrix.yaml` ;
- les trois niveaux de tests du §11 (`unit/`, `integration/`, `acceptance/`) ;
- `.claude/rules/testing-pytest.md` local au projet, calqué sur celui de `rag-hybride` mais
  décrivant les trois niveaux retenus ici, et référencé depuis `mcp/CLAUDE.md` ;
- `README.md` mis à jour : 13 tools, `ask_database`/`run_sql_query`, matrice de `MCP.md` §6.4 ;
- `.claude/rules/mcp-primitives.md` : le TODO remplacé par le format de la matrice et la convention de docstring ;
- `.claude/commands/new-tool.md` : squelette scaffoldant fonction + entrée de matrice + entrée de catalogue ;
- deux fichiers racine touchés par nécessité : `pyproject.toml` (3 dépendances) et `.env.example` (variables `MCP_*` et `*_BASE_URL`).

Branche `feat/mcp/serveur-mcp-gouverne`.

## 14. Hors périmètre

`api-gateway`, la configuration du realm Keycloak dans `sorabel-idp`, les endpoints de
briques de `rag-hybride`, le masquage de colonnes (porté par `sorabelsql-api`), et tout
Dockerfile — les projets Python de la solution n'en ont pas
(`.claude/rules/makefile-conventions.md`).

**Prérequis d'environnement** : créer un venv Python 3.12 avant la première exécution de
`pytest` — aucun interpréteur compatible n'est installé sur le poste.
