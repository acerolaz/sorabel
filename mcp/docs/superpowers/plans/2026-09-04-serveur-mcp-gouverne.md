# Serveur MCP gouverné (`mcp`) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le serveur MCP `mcp` : 13 tools exposés en HTTP, filtrés et gardés par une matrice d'accès centralisée, authentifiés par JWT, intégralement journalisés, et délégant à des backends derrière des ports (réel pour `rag-hybride`, stub pour les autres).

**Architecture:** Hexagonale (`.claude/rules/python-hexagonal.md`). `domain/` porte les modèles, le catalogue des 13 tools, la matrice d'accès, les erreurs typées et les ports — zéro import externe. `application/use_cases/` orchestre via les ports. `infrastructure/` implémente les ports (vérificateurs de token, clients HTTP, stubs, chargeur YAML, journal stdout). `api/` assemble un `FastMCP` sous-classé : un middleware ASGI capte l'`Authorization`, la sous-classe surcharge `list_tools()`/`call_tool()` pour appliquer la barrière 1 avant tout dispatch.

**Tech Stack:** Python 3.12, SDK `mcp` (FastMCP, transport HTTP streamable), `pyjwt[crypto]`, `httpx`, PyYAML, `pydantic-settings`, `uvicorn`, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-04-mcp-server-design.md`

## Global Constraints

- Répertoire de travail de toutes les commandes : `mcp/` (jamais la racine) — `../CLAUDE.md` § Commandes.
- Tout le code passe `ruff check .`, `ruff format .` et `mypy app` ; annotations de type sur chaque fonction — `../CLAUDE.md`.
- `domain/` n'a **aucun** import externe : ni `mcp`, ni `httpx`, ni `pydantic`, ni `yaml` — `python-hexagonal.md`.
- `application/` ne dépend que des `Protocol` de `domain/ports.py`, jamais d'une classe d'infrastructure — `python-hexagonal.md`.
- Aucun secret en dur, même en exemple : tout par variable d'environnement, `.env.example` sans valeur réelle — `security.md`.
- Corps d'erreur uniforme `{error_code, message, correlation_id}` ; `message` ne confirme jamais l'existence d'une ressource non autorisée — `api-contracts.md`.
- Champs JSON en `snake_case` — `api-contracts.md`.
- Tout appel, autorisé **ou refusé**, est journalisé ; jamais de contenu métier complet dans le journal, seulement des métadonnées (`row_count`, `latency_ms`) — `security.md`, spec §8.
- Fail closed : profil inconnu, claim absent, tool hors catalogue ⇒ refus — spec §5.
- Tests en Arrange / Act / Assert, avec commentaires de section dès que le test dépasse quelques lignes — `rag-hybride/.claude/rules/testing-pytest.md`.
- Les tests unitaires ne mockent que des **ports**, jamais un détail d'infrastructure — même règle.
- Commits en Conventional Commits, scope `mcp`, sans métadonnée d'IA dans le message — `git-conventions.md`.
- Branche de travail : `feat/mcp/serveur-mcp-gouverne`. Jamais de commit sur `main`.

## Nomenclature verrouillée

Ces noms sont utilisés à l'identique dans toutes les tâches :

| Symbole | Définition | Tâche |
|---|---|---|
| `Identity(subject, profile, expires_at)` | identité résolue depuis le JWT | 2 |
| `Scope(rag_collections, sql_tables, masked_columns)` | périmètre d'un profil, tuples de `str` | 2 |
| `Allowed(scope, rule)` / `Denied(error_code, rule)` / `Decision` | résultat de la matrice | 2 |
| `AuditEntry(...)` | entrée de journal | 2 |
| `ToolError(error_code, message, correlation_id)` | erreur typée, `str()` = JSON | 2 |
| `ToolDescriptor(name, family, backend)` / `CATALOG` / `CATALOG_BY_NAME` | catalogue | 3 |
| `AccessMatrix.decide(profile, tool)` / `.tools_for(profile)` | matrice | 4 |
| `TokenVerifierPort.verify(token) -> Identity` | port d'authentification | 6 |
| `AuditLogPort.record(entry) -> None` | port de journal | 6 |
| `RagPort` / `Text2SqlPort` / `SqlExecutionPort` | ports backends | 6 |
| `current_identity` / `current_correlation_id` / `current_scope` | `ContextVar` de `app/api/context.py` | 10 |
| `GovernedFastMCP` | sous-classe appliquant la barrière 1 | 10 |

---

## Task 1: Environnement, dépendances et vérification de la surface du SDK

Rien d'autre ne peut être écrit tant que le SDK n'est pas installé **et** que ses points d'interception sont vérifiés : toute la barrière 1 repose sur `FastMCP.list_tools()` / `FastMCP.call_tool()`.

**Files:**
- Modify: `../pyproject.toml`
- Modify: `../.env.example`
- Create: `app/__init__.py`, `app/domain/__init__.py`, `app/application/__init__.py`, `app/application/use_cases/__init__.py`, `app/infrastructure/__init__.py`, `app/api/__init__.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/acceptance/__init__.py`
- Test: `tests/unit/test_sdk_surface.py`

**Interfaces:**
- Consumes: rien.
- Produces: un venv 3.12 actif, les paquets `mcp`, `pyjwt[crypto]`, `httpx` installés, et la garantie que les méthodes surchargées en tâche 10 existent.

- [ ] **Step 1: Créer le venv Python 3.12**

Aucun interpréteur compatible n'est installé (3.9 et 3.14 seulement). Installer d'abord CPython 3.12, puis, depuis la racine de la solution :

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
```

Si `py -3.12` n'existe pas : installer Python 3.12 (winget `Python.Python.3.12`) et recommencer. Ne pas se rabattre sur 3.14 : `pyproject.toml` cible `python_version = "3.12"` pour mypy.

- [ ] **Step 2: Ajouter les dépendances au `pyproject.toml` racine**

Dans `[project].dependencies`, ajouter `mcp` et `pyjwt[crypto]`, et déplacer `httpx` depuis `[project.optional-dependencies].dev` — il devient une dépendance d'exécution :

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "pgvector>=0.3",
    "alembic>=1.13",
    "openai>=1.35",
    "sentence-transformers>=3.0",
    "pdfplumber>=0.11",
    "pyyaml>=6.0",
    "python-multipart>=0.0.9",
    "mcp>=1.2",
    "pyjwt[crypto]>=2.9",
    "httpx>=0.27",
]
```

Retirer la ligne `"httpx>=0.27",` de la section `dev` (elle y ferait doublon).

- [ ] **Step 3: Déclarer le marqueur pytest `live`**

Dans `[tool.pytest.ini_options]` du même fichier, sous `asyncio_mode = "auto"` :

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "live: test optionnel nécessitant un backend réellement en écoute (sauté par défaut)",
]
```

- [ ] **Step 4: Compléter le `.env.example` racine**

Ajouter à la fin de `../.env.example`, sans aucune valeur secrète :

```bash
# --- Serveur MCP (projet mcp) ---
MCP_ENV=dev
MCP_TOKEN_VERIFIER=local
MCP_JWKS_URL=http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/certs
MCP_JWT_ISSUER=http://localhost:8080/realms/sorabel-data-gate
MCP_JWT_AUDIENCE=sorabel-mcp
MCP_DEV_JWT_SECRET=
MCP_ACCESS_MATRIX_PATH=access_matrix.yaml
MCP_HTTP_TIMEOUT_S=10

RAG_BACKEND=stub
RAG_BASE_URL=http://localhost:8001
TEXT2SQL_BACKEND=stub
TEXT2SQL_BASE_URL=http://localhost:8002
SQLAPI_BACKEND=stub
SQLAPI_BASE_URL=http://localhost:8003
```

- [ ] **Step 5: Installer**

```bash
cd .. && ../.venv/Scripts/python -m pip install -e ".[dev]"
```

Ou, depuis `mcp/` : `make build`.

- [ ] **Step 6: Créer l'arborescence de paquets vide**

Créer les onze `__init__.py` listés dans **Files**, tous vides.

- [ ] **Step 7: Écrire le test de surface du SDK**

`tests/unit/test_sdk_surface.py` :

```python
import inspect

from mcp.server.fastmcp import FastMCP


def test_fastmcp_expose_les_points_d_interception_du_design():
    # Arrange
    server = FastMCP("smoke")

    # Act / Assert — la barrière 1 surcharge ces deux méthodes (tâche 10)
    assert inspect.iscoroutinefunction(server.list_tools)
    assert inspect.iscoroutinefunction(server.call_tool)
    # Le transport HTTP streamable est le seul retenu (spec D2)
    assert callable(server.streamable_http_app)
```

- [ ] **Step 8: Lancer le test**

Run: `pytest tests/unit/test_sdk_surface.py -v`
Expected: PASS.

**Si une assertion échoue, s'arrêter et le signaler** : la stratégie d'interception de la tâche 10 doit être revue avant d'écrire quoi que ce soit d'autre. Ne pas contourner en accédant à `server._mcp_server`.

- [ ] **Step 9: Commit**

```bash
git add ../pyproject.toml ../.env.example app tests
git commit -m "chore(mcp): initialise l'arborescence et les dépendances du serveur MCP"
```

---

## Task 2: Domaine — modèles et erreurs typées

**Files:**
- Create: `app/domain/models.py`
- Create: `app/domain/errors.py`
- Test: `tests/unit/test_errors.py`

**Interfaces:**
- Consumes: rien.
- Produces: `Identity`, `Scope`, `Allowed`, `Denied`, `Decision`, `AuditEntry`, `ToolError` et ses sept sous-classes.

- [ ] **Step 1: Écrire le test d'erreur**

`tests/unit/test_errors.py` :

```python
import json

from app.domain.errors import ToolError, UnauthorizedToolError


def test_le_message_d_erreur_est_un_json_au_format_api_contracts():
    # Arrange
    error = UnauthorizedToolError(correlation_id="corr-1")

    # Act
    payload = json.loads(str(error))

    # Assert
    assert payload == {
        "error_code": "UNAUTHORIZED_TOOL",
        "message": "Accès non autorisé pour ce profil",
        "correlation_id": "corr-1",
    }


def test_le_message_ne_nomme_jamais_la_ressource_demandee():
    # Arrange
    error = UnauthorizedToolError(correlation_id="corr-2")

    # Assert — le nom du tool ne doit pas fuiter dans le message rendu au client
    assert "get_customer_order_history" not in str(error)
    assert isinstance(error, ToolError)
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.errors'`.

- [ ] **Step 3: Écrire `app/domain/models.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Identity:
    """Identité résolue depuis le JWT vérifié."""

    subject: str
    profile: str
    expires_at: datetime


@dataclass(frozen=True)
class Scope:
    """Périmètre de données autorisé pour un profil."""

    rag_collections: tuple[str, ...]
    sql_tables: tuple[str, ...]
    masked_columns: tuple[str, ...]


@dataclass(frozen=True)
class Allowed:
    scope: Scope
    rule: str


@dataclass(frozen=True)
class Denied:
    error_code: str
    rule: str


Decision = Allowed | Denied


@dataclass(frozen=True)
class AuditEntry:
    """Une ligne de journal par appel, autorisé comme refusé (E5).

    `arguments` porte la requête (question, SQL) : c'est elle qu'on audite.
    Le résultat n'y figure jamais — seul `row_count` le décrit.
    """

    timestamp: datetime
    correlation_id: str
    subject: str | None
    profile: str | None
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    decision: str = "deny"
    rule: str = ""
    backend: str | None = None
    row_count: int | None = None
    latency_ms: int | None = None
    error_code: str | None = None
```

- [ ] **Step 4: Écrire `app/domain/errors.py`**

```python
import json


class InvalidTokenError(Exception):
    """Le token est absent, mal formé, expiré ou mal signé."""


class ToolError(Exception):
    """Erreur rendue au client dans un CallToolResult `isError`.

    Le SDK MCP transforme une exception levée pendant `call_tool` en résultat
    `isError: true` dont le contenu est `str(exception)`. On y place donc
    directement le corps d'erreur uniforme de `api-contracts.md`.
    """

    error_code = "INTERNAL_ERROR"
    message = "Erreur interne"

    def __init__(self, correlation_id: str) -> None:
        self.correlation_id = correlation_id
        super().__init__(str(self))

    def __str__(self) -> str:
        return json.dumps(
            {
                "error_code": self.error_code,
                "message": self.message,
                "correlation_id": self.correlation_id,
            },
            ensure_ascii=False,
        )


class UnauthenticatedError(ToolError):
    error_code = "UNAUTHENTICATED"
    message = "Authentification requise"


class UnauthorizedToolError(ToolError):
    error_code = "UNAUTHORIZED_TOOL"
    message = "Accès non autorisé pour ce profil"


class UnauthorizedCollectionError(ToolError):
    error_code = "UNAUTHORIZED_COLLECTION"
    message = "Périmètre documentaire non autorisé pour ce profil"


class UnauthorizedTableError(ToolError):
    error_code = "UNAUTHORIZED_TABLE"
    message = "Périmètre de données non autorisé pour ce profil"


class NotFoundInCorpusError(ToolError):
    error_code = "NOT_FOUND_IN_CORPUS"
    message = "Information absente du corpus documentaire"


class SchemaMismatchError(ToolError):
    error_code = "SCHEMA_MISMATCH"
    message = "Requête invalide au regard du schéma accessible"


class BackendUnavailableError(ToolError):
    error_code = "BACKEND_UNAVAILABLE"
    message = "Service en aval indisponible"
```

- [ ] **Step 5: Lancer le test**

Run: `pytest tests/unit/test_errors.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add app/domain/models.py app/domain/errors.py tests/unit/test_errors.py
git commit -m "feat(mcp): ajoute les modèles de domaine et les erreurs typées"
```

---

## Task 3: Domaine — catalogue des 13 tools

**Files:**
- Create: `app/domain/catalog.py`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: rien.
- Produces: `ToolDescriptor(name, family, backend)`, `CATALOG: tuple[ToolDescriptor, ...]` (13 entrées), `CATALOG_BY_NAME: dict[str, ToolDescriptor]`.

- [ ] **Step 1: Écrire le test**

`tests/unit/test_catalog.py` :

```python
from app.domain.catalog import CATALOG, CATALOG_BY_NAME

TOOLS_ATTENDUS = {
    "answer_question",
    "search_documents",
    "lookup_by_reference",
    "get_document_metadata",
    "check_answer_confidence",
    "list_document_types",
    "ask_database",
    "run_sql_query",
    "get_stock",
    "get_order_status",
    "get_customer_order_history",
    "get_schema_info",
    "get_query_history",
}


def test_le_catalogue_contient_exactement_les_treize_tools_du_cadrage():
    assert {descriptor.name for descriptor in CATALOG} == TOOLS_ATTENDUS
    assert len(CATALOG) == 13


def test_chaque_tool_declare_un_backend_connu():
    assert {d.backend for d in CATALOG} == {"rag", "text2sql", "sqlapi"}


def test_l_index_par_nom_couvre_tout_le_catalogue():
    assert set(CATALOG_BY_NAME) == TOOLS_ATTENDUS
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_catalog.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/domain/catalog.py`**

```python
from dataclasses import dataclass
from typing import Literal

Family = Literal["rag", "sql"]
Backend = Literal["rag", "text2sql", "sqlapi"]


@dataclass(frozen=True)
class ToolDescriptor:
    """Identité d'un tool, indépendamment de son implémentation.

    Source unique consommée par la matrice d'accès et par le filtrage du
    catalogue : un tool absent d'ici n'existe pas pour la gouvernance.
    """

    name: str
    family: Family
    backend: Backend


CATALOG: tuple[ToolDescriptor, ...] = (
    ToolDescriptor("answer_question", "rag", "rag"),
    ToolDescriptor("search_documents", "rag", "rag"),
    ToolDescriptor("lookup_by_reference", "rag", "rag"),
    ToolDescriptor("get_document_metadata", "rag", "rag"),
    ToolDescriptor("check_answer_confidence", "rag", "rag"),
    ToolDescriptor("list_document_types", "rag", "rag"),
    ToolDescriptor("ask_database", "sql", "text2sql"),
    ToolDescriptor("run_sql_query", "sql", "sqlapi"),
    ToolDescriptor("get_stock", "sql", "sqlapi"),
    ToolDescriptor("get_order_status", "sql", "sqlapi"),
    ToolDescriptor("get_customer_order_history", "sql", "sqlapi"),
    ToolDescriptor("get_schema_info", "sql", "sqlapi"),
    ToolDescriptor("get_query_history", "sql", "sqlapi"),
)

CATALOG_BY_NAME: dict[str, ToolDescriptor] = {d.name: d for d in CATALOG}
```

- [ ] **Step 4: Lancer le test**

Run: `pytest tests/unit/test_catalog.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/domain/catalog.py tests/unit/test_catalog.py
git commit -m "feat(mcp): déclare le catalogue des 13 tools"
```

---

## Task 4: Domaine — matrice d'accès et décision

**Files:**
- Create: `app/domain/access_matrix.py`
- Test: `tests/unit/test_access_matrix.py`

**Interfaces:**
- Consumes: `Scope`, `Allowed`, `Denied`, `Decision` (tâche 2) ; `CATALOG_BY_NAME` (tâche 3).
- Produces: `ProfileEntry(tools, scope)`, `AccessMatrix(version, profiles)`, `AccessMatrix.decide(profile, tool) -> Decision`, `AccessMatrix.tools_for(profile) -> tuple[str, ...]`.

- [ ] **Step 1: Écrire le test — la grille 3 × 13 et le fail closed**

`tests/unit/test_access_matrix.py` :

```python
import pytest

from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.catalog import CATALOG
from app.domain.models import Allowed, Denied, Scope

TOUTES_COLLECTIONS = ("datasheet", "manuel", "procedure_sav")
TABLES = ("products", "stock", "orders")
MASQUEES = ("purchase_price", "margin")

TOOLS_PAR_PROFIL = {
    "support": (
        "search_documents",
        "lookup_by_reference",
        "ask_database",
        "get_stock",
        "get_order_status",
    ),
    "sales": (
        "answer_question",
        "search_documents",
        "lookup_by_reference",
        "get_document_metadata",
        "check_answer_confidence",
        "list_document_types",
        "ask_database",
        "get_stock",
        "get_order_status",
        "get_customer_order_history",
    ),
    "dev": (
        "search_documents",
        "get_document_metadata",
        "check_answer_confidence",
        "list_document_types",
        "get_schema_info",
        "get_query_history",
        "run_sql_query",
    ),
}


@pytest.fixture
def matrix() -> AccessMatrix:
    return AccessMatrix(
        version=1,
        profiles={
            "support": ProfileEntry(
                tools=frozenset(TOOLS_PAR_PROFIL["support"]),
                scope=Scope(("procedure_sav", "manuel"), TABLES, MASQUEES),
            ),
            "sales": ProfileEntry(
                tools=frozenset(TOOLS_PAR_PROFIL["sales"]),
                scope=Scope(TOUTES_COLLECTIONS, TABLES, MASQUEES),
            ),
            "dev": ProfileEntry(
                tools=frozenset(TOOLS_PAR_PROFIL["dev"]),
                scope=Scope(TOUTES_COLLECTIONS, TABLES, MASQUEES),
            ),
        },
    )


@pytest.mark.parametrize("profile", ["support", "sales", "dev"])
@pytest.mark.parametrize("descriptor", CATALOG, ids=lambda d: d.name)
def test_grille_complete_profil_par_tool(matrix, profile, descriptor):
    # Act
    decision = matrix.decide(profile, descriptor.name)

    # Assert — les 39 cases de MCP.md §6.4
    if descriptor.name in TOOLS_PAR_PROFIL[profile]:
        assert isinstance(decision, Allowed)
        assert decision.scope == matrix.profiles[profile].scope
    else:
        assert isinstance(decision, Denied)
        assert decision.error_code == "UNAUTHORIZED_TOOL"


def test_les_effectifs_de_catalogue_par_profil(matrix):
    assert len(matrix.tools_for("support")) == 5
    assert len(matrix.tools_for("sales")) == 10
    assert len(matrix.tools_for("dev")) == 7


def test_profil_inconnu_refuse_tout(matrix):
    assert isinstance(matrix.decide("marketing", "get_stock"), Denied)
    assert matrix.tools_for("marketing") == ()


def test_profil_absent_refuse_tout(matrix):
    assert isinstance(matrix.decide(None, "get_stock"), Denied)
    assert matrix.tools_for(None) == ()


def test_tool_hors_catalogue_refuse_meme_si_present_dans_la_matrice():
    # Arrange — une matrice qui accorde un tool inexistant
    matrix = AccessMatrix(
        version=1,
        profiles={
            "support": ProfileEntry(
                tools=frozenset({"drop_everything"}),
                scope=Scope((), (), ()),
            )
        },
    )

    # Act / Assert — le catalogue fait autorité, pas le YAML
    assert isinstance(matrix.decide("support", "drop_everything"), Denied)
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_access_matrix.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/domain/access_matrix.py`**

```python
from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.catalog import CATALOG_BY_NAME
from app.domain.models import Allowed, Decision, Denied, Scope


@dataclass(frozen=True)
class ProfileEntry:
    tools: frozenset[str]
    scope: Scope


@dataclass(frozen=True)
class AccessMatrix:
    """Matrice profil × tool × périmètre, source unique d'autorisation."""

    version: int
    profiles: Mapping[str, ProfileEntry]

    def decide(self, profile: str | None, tool: str) -> Decision:
        """Autorise ou refuse un appel. Fail closed en toutes circonstances."""
        if profile is None:
            return Denied("UNAUTHORIZED_TOOL", "profil absent du token")
        entry = self.profiles.get(profile)
        if entry is None:
            return Denied("UNAUTHORIZED_TOOL", f"profil inconnu: {profile}")
        if tool not in CATALOG_BY_NAME:
            return Denied("UNAUTHORIZED_TOOL", f"tool hors catalogue: {tool}")
        if tool not in entry.tools:
            return Denied("UNAUTHORIZED_TOOL", f"{profile} n'a pas {tool}")
        return Allowed(entry.scope, f"{profile}.tools")

    def tools_for(self, profile: str | None) -> tuple[str, ...]:
        """Projection du catalogue pour ce profil, dans l'ordre du catalogue."""
        if profile is None or profile not in self.profiles:
            return ()
        allowed = self.profiles[profile].tools
        return tuple(name for name in CATALOG_BY_NAME if name in allowed)
```

- [ ] **Step 4: Lancer le test**

Run: `pytest tests/unit/test_access_matrix.py -v`
Expected: PASS — 39 cas paramétrés + 4 tests.

- [ ] **Step 5: Commit**

```bash
git add app/domain/access_matrix.py tests/unit/test_access_matrix.py
git commit -m "feat(mcp): implémente la matrice d'accès et sa décision fail closed"
```

---

## Task 5: Matrice versionnée et son chargeur YAML

**Files:**
- Create: `access_matrix.yaml`
- Create: `app/infrastructure/matrix/__init__.py`
- Create: `app/infrastructure/matrix/yaml_loader.py`
- Test: `tests/integration/test_yaml_matrix_loader.py`

**Interfaces:**
- Consumes: `AccessMatrix`, `ProfileEntry`, `Scope` (tâches 2 et 4).
- Produces: `load_access_matrix(path: Path) -> AccessMatrix`, `InvalidMatrixError`.

- [ ] **Step 1: Écrire `access_matrix.yaml`**

Transcription de `MCP.md` §6.4 :

```yaml
# Matrice d'accès du serveur MCP Sorabel — profil × tool × périmètre.
# Source unique : aucun droit n'est codé en dur ailleurs.
version: 1
profiles:
  support:
    tools: [search_documents, lookup_by_reference, ask_database, get_stock, get_order_status]
    rag_collections: [procedure_sav, manuel]
    sql_tables: [products, stock, orders]
    masked_columns: [purchase_price, margin]
  sales:
    tools:
      - answer_question
      - search_documents
      - lookup_by_reference
      - get_document_metadata
      - check_answer_confidence
      - list_document_types
      - ask_database
      - get_stock
      - get_order_status
      - get_customer_order_history
    rag_collections: [datasheet, manuel, procedure_sav]
    sql_tables: [products, stock, orders]
    masked_columns: [purchase_price, margin]
  dev:
    tools:
      - search_documents
      - get_document_metadata
      - check_answer_confidence
      - list_document_types
      - get_schema_info
      - get_query_history
      - run_sql_query
    rag_collections: [datasheet, manuel, procedure_sav]
    sql_tables: [products, stock, orders]
    masked_columns: [purchase_price, margin]
```

- [ ] **Step 2: Écrire le test d'intégration (vrai fichier, vrai disque)**

`tests/integration/test_yaml_matrix_loader.py` :

```python
from pathlib import Path

import pytest

from app.domain.models import Allowed
from app.infrastructure.matrix.yaml_loader import InvalidMatrixError, load_access_matrix

MATRICE_REELLE = Path(__file__).resolve().parents[2] / "access_matrix.yaml"


def test_charge_la_matrice_reelle_du_depot():
    # Act
    matrix = load_access_matrix(MATRICE_REELLE)

    # Assert — les effectifs de MCP.md §6.4
    assert matrix.version == 1
    assert len(matrix.tools_for("support")) == 5
    assert len(matrix.tools_for("sales")) == 10
    assert len(matrix.tools_for("dev")) == 7


def test_le_perimetre_du_profil_support_est_restreint_a_deux_collections():
    # Act
    decision = load_access_matrix(MATRICE_REELLE).decide("support", "search_documents")

    # Assert
    assert isinstance(decision, Allowed)
    assert decision.scope.rag_collections == ("procedure_sav", "manuel")
    assert decision.scope.masked_columns == ("purchase_price", "margin")


def test_un_fichier_malforme_echoue_au_chargement(tmp_path: Path):
    # Arrange — `tools` doit être une liste, pas une chaîne
    fichier = tmp_path / "matrice.yaml"
    fichier.write_text("version: 1\nprofiles:\n  support:\n    tools: get_stock\n", "utf-8")

    # Act / Assert — jamais de matrice vide silencieuse
    with pytest.raises(InvalidMatrixError):
        load_access_matrix(fichier)


def test_un_fichier_absent_echoue_au_chargement(tmp_path: Path):
    with pytest.raises(InvalidMatrixError):
        load_access_matrix(tmp_path / "inexistant.yaml")
```

- [ ] **Step 3: Lancer le test pour le voir échouer**

Run: `pytest tests/integration/test_yaml_matrix_loader.py -v`
Expected: FAIL — module absent.

- [ ] **Step 4: Écrire `app/infrastructure/matrix/yaml_loader.py`**

```python
from pathlib import Path
from typing import Any

import yaml

from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.models import Scope


class InvalidMatrixError(Exception):
    """La matrice est absente, illisible ou mal formée.

    Levée au démarrage : mieux vaut ne pas démarrer qu'exposer une matrice
    partiellement chargée, qui accorderait ou refuserait au hasard.
    """


def _liste_de_chaines(valeur: Any, chemin: str) -> tuple[str, ...]:
    if not isinstance(valeur, list) or not all(isinstance(item, str) for item in valeur):
        raise InvalidMatrixError(f"{chemin} doit être une liste de chaînes")
    return tuple(valeur)


def load_access_matrix(path: Path) -> AccessMatrix:
    """Charge et valide la matrice versionnée depuis le disque."""
    try:
        brut = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InvalidMatrixError(f"matrice illisible: {path}") from exc

    if not isinstance(brut, dict):
        raise InvalidMatrixError("la matrice doit être un mapping YAML")
    version = brut.get("version")
    if not isinstance(version, int):
        raise InvalidMatrixError("`version` manquante ou non entière")
    profils_bruts = brut.get("profiles")
    if not isinstance(profils_bruts, dict):
        raise InvalidMatrixError("`profiles` manquante ou non mapping")

    profils: dict[str, ProfileEntry] = {}
    for nom, entree in profils_bruts.items():
        if not isinstance(entree, dict):
            raise InvalidMatrixError(f"profiles.{nom} doit être un mapping")
        profils[nom] = ProfileEntry(
            tools=frozenset(_liste_de_chaines(entree.get("tools"), f"profiles.{nom}.tools")),
            scope=Scope(
                rag_collections=_liste_de_chaines(
                    entree.get("rag_collections"), f"profiles.{nom}.rag_collections"
                ),
                sql_tables=_liste_de_chaines(
                    entree.get("sql_tables"), f"profiles.{nom}.sql_tables"
                ),
                masked_columns=_liste_de_chaines(
                    entree.get("masked_columns"), f"profiles.{nom}.masked_columns"
                ),
            ),
        )
    return AccessMatrix(version=version, profiles=profils)
```

- [ ] **Step 5: Lancer le test**

Run: `pytest tests/integration/test_yaml_matrix_loader.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add access_matrix.yaml app/infrastructure/matrix tests/integration/test_yaml_matrix_loader.py
git commit -m "feat(mcp): ajoute la matrice versionnée et son chargeur YAML validé"
```

---

## Task 6: Configuration et ports

**Files:**
- Create: `app/config.py`
- Create: `app/domain/ports.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `Identity`, `AuditEntry` (tâche 2).
- Produces: `Settings`, `get_settings()`, et les cinq `Protocol` : `TokenVerifierPort`, `AuditLogPort`, `RagPort`, `Text2SqlPort`, `SqlExecutionPort`.

- [ ] **Step 1: Écrire le test de configuration**

`tests/unit/test_config.py` :

```python
from pathlib import Path

from app.config import Settings


def test_les_valeurs_par_defaut_sont_les_plus_fermees(monkeypatch):
    # Arrange — aucun .env chargé
    settings = Settings(_env_file=None)

    # Assert — stub partout, jamais un backend réel par défaut
    assert settings.rag_backend == "stub"
    assert settings.text2sql_backend == "stub"
    assert settings.sqlapi_backend == "stub"
    assert settings.mcp_dev_jwt_secret == ""


def test_le_chemin_de_matrice_est_resolu_depuis_la_racine_du_projet():
    # Act
    settings = Settings(_env_file=None)

    # Assert — indépendant du répertoire courant d'exécution
    assert settings.access_matrix_file().is_absolute()
    assert settings.access_matrix_file().name == "access_matrix.yaml"


def test_un_chemin_de_matrice_absolu_est_respecte(tmp_path: Path):
    # Arrange
    cible = tmp_path / "autre.yaml"

    # Act
    settings = Settings(_env_file=None, mcp_access_matrix_path=str(cible))

    # Assert
    assert settings.access_matrix_file() == cible
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/config.py`**

Même stratégie que `rag-hybride/app/config.py` : le `.env` unique est résolu depuis ce fichier, pas depuis le répertoire courant.

```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/ -> mcp/ -> src/ : le .env est unique pour toute la solution.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOLUTION_ROOT = _PROJECT_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_SOLUTION_ROOT / ".env", extra="ignore")

    mcp_env: Literal["dev", "prod"] = "dev"
    mcp_token_verifier: Literal["local", "jwks"] = "local"
    mcp_jwks_url: str = ""
    mcp_jwt_issuer: str = ""
    mcp_jwt_audience: str = ""
    mcp_dev_jwt_secret: str = ""
    mcp_access_matrix_path: str = "access_matrix.yaml"
    mcp_http_timeout_s: float = 10.0

    rag_backend: Literal["http", "stub"] = "stub"
    rag_base_url: str = ""
    text2sql_backend: Literal["http", "stub"] = "stub"
    text2sql_base_url: str = ""
    sqlapi_backend: Literal["http", "stub"] = "stub"
    sqlapi_base_url: str = ""

    def access_matrix_file(self) -> Path:
        """Chemin absolu de la matrice, relatif à la racine du projet si besoin."""
        chemin = Path(self.mcp_access_matrix_path)
        return chemin if chemin.is_absolute() else _PROJECT_ROOT / chemin


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Écrire `app/domain/ports.py`**

```python
from collections.abc import Sequence
from typing import Any, Protocol

from app.domain.models import AuditEntry, Identity


class TokenVerifierPort(Protocol):
    def verify(self, token: str) -> Identity:
        """Vérifie un JWT et retourne l'identité. Lève InvalidTokenError sinon."""
        ...


class AuditLogPort(Protocol):
    def record(self, entry: AuditEntry) -> None:
        """Journalise un appel, autorisé ou refusé. Ne lève jamais."""
        ...


class RagPort(Protocol):
    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...


class Text2SqlPort(Protocol):
    async def generate_sql(
        self, question: str, profile: str, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...


class SqlExecutionPort(Protocol):
    async def run_sql(
        self,
        sql: str,
        profile: str,
        tables: Sequence[str],
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]: ...

    async def stock(
        self, product_ref: str, profile: str, correlation_id: str
    ) -> dict[str, Any]: ...

    async def order_status(
        self, order_id: str, profile: str, correlation_id: str
    ) -> dict[str, Any]: ...

    async def customer_orders(
        self,
        customer_id: str,
        limit: int,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]: ...

    async def schema_info(
        self, profile: str, keyword: str | None, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]: ...

    async def query_history(
        self, profile: str, limit: int, correlation_id: str
    ) -> dict[str, Any]: ...
```

- [ ] **Step 5: Lancer le test**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/domain/ports.py tests/unit/test_config.py
git commit -m "feat(mcp): ajoute la configuration et les ports du domaine"
```

---

## Task 7: Vérification de token — adapter à clé locale et garde-fous de démarrage

**Files:**
- Create: `app/infrastructure/keycloak/__init__.py`
- Create: `app/infrastructure/keycloak/local_key_verifier.py`
- Test: `tests/integration/test_local_key_verifier.py`

**Interfaces:**
- Consumes: `Identity` (t2), `InvalidTokenError` (t2), `TokenVerifierPort` (t6), `Settings` (t6).
- Produces: `LocalKeyTokenVerifier(secret, issuer, audience)`, `build_local_verifier(settings) -> LocalKeyTokenVerifier`, `UnsafeVerifierConfiguration`.

- [ ] **Step 1: Écrire le test**

`tests/integration/test_local_key_verifier.py` — cryptographie réelle, tokens réellement signés :

```python
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import Settings
from app.domain.errors import InvalidTokenError
from app.infrastructure.keycloak.local_key_verifier import (
    LocalKeyTokenVerifier,
    UnsafeVerifierConfiguration,
    build_local_verifier,
)

SECRET = "secret-de-test-uniquement"
ISSUER = "https://idp.test/realms/sorabel-data-gate"
AUDIENCE = "sorabel-mcp"


def forge(**overrides: object) -> str:
    payload: dict[str, object] = {
        "sub": "poste-vente-42",
        "sorabel_profile": "sales",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture
def verifier() -> LocalKeyTokenVerifier:
    return LocalKeyTokenVerifier(secret=SECRET, issuer=ISSUER, audience=AUDIENCE)


def test_un_token_valide_donne_le_sujet_et_le_profil(verifier):
    # Act
    identity = verifier.verify(forge())

    # Assert
    assert identity.subject == "poste-vente-42"
    assert identity.profile == "sales"


def test_un_token_expire_est_refuse(verifier):
    expire = forge(exp=datetime.now(timezone.utc) - timedelta(seconds=1))
    with pytest.raises(InvalidTokenError):
        verifier.verify(expire)


def test_un_mauvais_emetteur_est_refuse(verifier):
    with pytest.raises(InvalidTokenError):
        verifier.verify(forge(iss="https://attaquant.test/realms/autre"))


def test_une_mauvaise_audience_est_refusee(verifier):
    with pytest.raises(InvalidTokenError):
        verifier.verify(forge(aud="autre-service"))


def test_une_signature_falsifiee_est_refusee(verifier):
    faux = jwt.encode({"sub": "x", "iss": ISSUER, "aud": AUDIENCE}, "mauvais-secret", "HS256")
    with pytest.raises(InvalidTokenError):
        verifier.verify(faux)


def test_un_claim_de_profil_absent_est_refuse(verifier):
    sans_profil = jwt.encode(
        {
            "sub": "x",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        verifier.verify(sans_profil)


def test_le_verificateur_local_est_interdit_hors_developpement():
    # Arrange
    settings = Settings(
        _env_file=None, mcp_env="prod", mcp_token_verifier="local", mcp_dev_jwt_secret=SECRET
    )

    # Act / Assert — un adapter de dev ne doit pas survivre à un déploiement
    with pytest.raises(UnsafeVerifierConfiguration):
        build_local_verifier(settings)


def test_un_secret_vide_empeche_le_demarrage():
    settings = Settings(_env_file=None, mcp_env="dev", mcp_dev_jwt_secret="")
    with pytest.raises(UnsafeVerifierConfiguration):
        build_local_verifier(settings)
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/integration/test_local_key_verifier.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/infrastructure/keycloak/local_key_verifier.py`**

```python
from datetime import datetime, timezone

import jwt

from app.config import Settings
from app.domain.errors import InvalidTokenError
from app.domain.models import Identity

PROFILE_CLAIM = "sorabel_profile"


class UnsafeVerifierConfiguration(Exception):
    """Configuration d'authentification refusée au démarrage."""


class LocalKeyTokenVerifier:
    """Vérificateur symétrique, réservé au développement.

    Permet de signer des tokens de test sans Keycloak. Interdit hors `dev`
    par `build_local_verifier`.
    """

    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> Identity:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                audience=self._audience,
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("token invalide") from exc

        profile = claims.get(PROFILE_CLAIM)
        subject = claims.get("sub")
        if not isinstance(profile, str) or not isinstance(subject, str):
            raise InvalidTokenError(f"claims `sub`/`{PROFILE_CLAIM}` manquants")
        return Identity(
            subject=subject,
            profile=profile,
            expires_at=datetime.fromtimestamp(float(claims["exp"]), tz=timezone.utc),
        )


def build_local_verifier(settings: Settings) -> LocalKeyTokenVerifier:
    """Construit le vérificateur de dev, ou refuse de démarrer."""
    if settings.mcp_env != "dev":
        raise UnsafeVerifierConfiguration(
            "MCP_TOKEN_VERIFIER=local est réservé à MCP_ENV=dev"
        )
    if not settings.mcp_dev_jwt_secret:
        raise UnsafeVerifierConfiguration("MCP_DEV_JWT_SECRET est vide")
    return LocalKeyTokenVerifier(
        secret=settings.mcp_dev_jwt_secret,
        issuer=settings.mcp_jwt_issuer,
        audience=settings.mcp_jwt_audience,
    )
```

- [ ] **Step 4: Lancer le test**

Run: `pytest tests/integration/test_local_key_verifier.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/keycloak tests/integration/test_local_key_verifier.py
git commit -m "feat(mcp): ajoute le vérificateur de token local et ses garde-fous"
```

---

## Task 8: Vérification de token — adapter JWKS

**Files:**
- Create: `app/infrastructure/keycloak/jwks_verifier.py`
- Test: `tests/integration/test_jwks_verifier.py`

**Interfaces:**
- Consumes: `Identity`, `InvalidTokenError`, `Settings`.
- Produces: `JwksTokenVerifier(jwks_url, issuer, audience, timeout_s)`, `build_token_verifier(settings) -> TokenVerifierPort`.

- [ ] **Step 1: Écrire le test d'intégration — JWKS réellement servi en HTTP**

`tests/integration/test_jwks_verifier.py` :

```python
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.domain.errors import InvalidTokenError
from app.infrastructure.keycloak.jwks_verifier import JwksTokenVerifier

ISSUER = "https://idp.test/realms/sorabel-data-gate"
AUDIENCE = "sorabel-mcp"


class JwksServer:
    """Sert un document JWKS réel sur un port éphémère, et compte ses appels."""

    def __init__(self, jwks: dict[str, object]) -> None:
        self.appels = 0
        serveur = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — imposé par BaseHTTPRequestHandler
                serveur.appels += 1
                corps = json.dumps(jwks).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *args: object) -> None:
                return

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_port}/certs"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> "JwksServer":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def paire_de_cles() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cle.public_key()))
    jwk.update({"kid": "cle-test", "use": "sig", "alg": "RS256"})
    return cle, {"keys": [jwk]}


def forge(cle: rsa.RSAPrivateKey, kid: str = "cle-test") -> str:
    return jwt.encode(
        {
            "sub": "bot-slack-support",
            "sorabel_profile": "support",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        cle,
        algorithm="RS256",
        headers={"kid": kid},
    )


def test_verifie_une_signature_contre_un_jwks_reellement_servi():
    # Arrange
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)

        # Act
        identity = verifier.verify(forge(cle))

    # Assert
    assert identity.profile == "support"
    assert identity.subject == "bot-slack-support"


def test_les_cles_sont_mises_en_cache_entre_deux_verifications():
    # Arrange
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)

        # Act
        verifier.verify(forge(cle))
        verifier.verify(forge(cle))

        # Assert — un seul aller-retour réseau pour deux tokens
        assert serveur.appels == 1


def test_une_cle_inconnue_est_refusee():
    # Arrange — le token est signé par une clé absente du JWKS servi
    _, jwks = paire_de_cles()
    autre_cle, _ = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(forge(autre_cle, kid="cle-inconnue"))


def test_un_jwks_injoignable_refuse_le_token():
    # Arrange — port fermé
    verifier = JwksTokenVerifier("http://127.0.0.1:1/certs", ISSUER, AUDIENCE, timeout_s=1.0)
    cle, _ = paire_de_cles()

    # Act / Assert — jamais d'acceptation par défaut quand l'IdP est muet
    with pytest.raises(InvalidTokenError):
        verifier.verify(forge(cle))
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/integration/test_jwks_verifier.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/infrastructure/keycloak/jwks_verifier.py`**

```python
from datetime import datetime, timezone

import jwt
from jwt import PyJWKClient

from app.config import Settings
from app.domain.errors import InvalidTokenError
from app.domain.models import Identity
from app.domain.ports import TokenVerifierPort
from app.infrastructure.keycloak.local_key_verifier import (
    PROFILE_CLAIM,
    UnsafeVerifierConfiguration,
    build_local_verifier,
)


class JwksTokenVerifier:
    """Vérifie un JWT Keycloak via le JWKS publié, clés mises en cache."""

    def __init__(self, jwks_url: str, issuer: str, audience: str, timeout_s: float) -> None:
        self._issuer = issuer
        self._audience = audience
        self._clients = PyJWKClient(jwks_url, cache_keys=True, timeout=int(timeout_s) or 1)

    def verify(self, token: str) -> Identity:
        try:
            cle = self._clients.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                cle.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
            )
        except Exception as exc:  # PyJWKClient lève des erreurs réseau hors PyJWTError
            raise InvalidTokenError("token invalide ou JWKS injoignable") from exc

        profile = claims.get(PROFILE_CLAIM)
        subject = claims.get("sub")
        if not isinstance(profile, str) or not isinstance(subject, str):
            raise InvalidTokenError(f"claims `sub`/`{PROFILE_CLAIM}` manquants")
        return Identity(
            subject=subject,
            profile=profile,
            expires_at=datetime.fromtimestamp(float(claims["exp"]), tz=timezone.utc),
        )


def build_token_verifier(settings: Settings) -> TokenVerifierPort:
    """Sélectionne l'adapter de vérification selon la configuration."""
    if settings.mcp_token_verifier == "local":
        return build_local_verifier(settings)
    if not settings.mcp_jwks_url:
        raise UnsafeVerifierConfiguration("MCP_JWKS_URL est vide")
    return JwksTokenVerifier(
        jwks_url=settings.mcp_jwks_url,
        issuer=settings.mcp_jwt_issuer,
        audience=settings.mcp_jwt_audience,
        timeout_s=settings.mcp_http_timeout_s,
    )
```

> `except Exception` est ici volontaire et circonscrit : `PyJWKClient` remonte des erreurs
> réseau qui ne dérivent pas de `PyJWTError`, et le comportement attendu est identique
> dans tous les cas — refuser le token. Toute autre couche du projet reste soumise à la
> règle « jamais d'`Exception` large ».

- [ ] **Step 4: Lancer le test**

Run: `pytest tests/integration/test_jwks_verifier.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/keycloak/jwks_verifier.py tests/integration/test_jwks_verifier.py
git commit -m "feat(mcp): ajoute la vérification JWT par JWKS avec cache des clés"
```

---

## Task 9: Journal d'audit

**Files:**
- Create: `app/infrastructure/audit/__init__.py`
- Create: `app/infrastructure/audit/stdout_audit_log.py`
- Test: `tests/unit/test_stdout_audit_log.py`

**Interfaces:**
- Consumes: `AuditEntry` (t2), `AuditLogPort` (t6).
- Produces: `StdoutAuditLog(stream=None)` implémentant `record`.

- [ ] **Step 1: Écrire le test**

`tests/unit/test_stdout_audit_log.py` :

```python
import io
import json
from datetime import datetime, timezone

from app.domain.models import AuditEntry
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog


def entree(**overrides: object) -> AuditEntry:
    valeurs: dict[str, object] = {
        "timestamp": datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
        "correlation_id": "corr-1",
        "subject": "poste-vente-42",
        "profile": "sales",
        "tool": "get_stock",
        "arguments": {"product_ref": "REF-8842"},
        "decision": "allow",
        "rule": "sales.tools",
        "backend": "stub",
        "row_count": 3,
        "latency_ms": 12,
    }
    valeurs.update(overrides)
    return AuditEntry(**valeurs)  # type: ignore[arg-type]


def test_ecrit_une_ligne_json_par_appel():
    # Arrange
    flux = io.StringIO()
    journal = StdoutAuditLog(stream=flux)

    # Act
    journal.record(entree())
    journal.record(entree(decision="deny", error_code="UNAUTHORIZED_TOOL"))

    # Assert
    lignes = flux.getvalue().strip().splitlines()
    assert len(lignes) == 2
    assert json.loads(lignes[0])["decision"] == "allow"
    assert json.loads(lignes[1])["error_code"] == "UNAUTHORIZED_TOOL"


def test_journalise_tous_les_champs_exiges_par_e5():
    # Arrange
    flux = io.StringIO()

    # Act
    StdoutAuditLog(stream=flux).record(entree())

    # Assert
    ligne = json.loads(flux.getvalue())
    assert set(ligne) >= {
        "timestamp",
        "correlation_id",
        "subject",
        "profile",
        "tool",
        "arguments",
        "decision",
        "rule",
        "backend",
        "row_count",
        "latency_ms",
    }


def test_ne_journalise_jamais_le_contenu_du_resultat():
    # Arrange — un résultat métier glissé dans les arguments ne doit pas être un prétexte
    flux = io.StringIO()

    # Act
    StdoutAuditLog(stream=flux).record(entree(row_count=42))

    # Assert — seul le volume décrit le résultat
    ligne = json.loads(flux.getvalue())
    assert ligne["row_count"] == 42
    assert "rows" not in ligne
    assert "result" not in ligne
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_stdout_audit_log.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/infrastructure/audit/stdout_audit_log.py`**

```python
import json
import sys
from dataclasses import asdict
from typing import TextIO

from app.domain.models import AuditEntry


class StdoutAuditLog:
    """Journal append-only : une ligne JSON par appel, sur un flux texte.

    Aucun contenu métier n'est écrit — l'entrée elle-même ne porte que des
    métadonnées de résultat (`row_count`, `latency_ms`), par construction.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def record(self, entry: AuditEntry) -> None:
        ligne = asdict(entry)
        ligne["timestamp"] = entry.timestamp.isoformat()
        self._stream.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        self._stream.flush()
```

- [ ] **Step 4: Lancer le test**

Run: `pytest tests/unit/test_stdout_audit_log.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/audit tests/unit/test_stdout_audit_log.py
git commit -m "feat(mcp): ajoute le journal d'audit append-only sur stdout"
```

---

## Task 10: Barrière 1 — middleware d'authentification et `GovernedFastMCP`

Cœur de la gouvernance : un tool non autorisé n'est ni listé, ni dispatché.

**Files:**
- Create: `app/api/context.py`
- Create: `app/api/governance.py`
- Create: `app/application/use_cases/list_available_tools.py`
- Create: `app/application/use_cases/authorize_tool_call.py`
- Test: `tests/unit/test_governance.py`

**Interfaces:**
- Consumes: `AccessMatrix` (t4), `Identity`/`Allowed`/`Denied`/`AuditEntry` (t2), erreurs (t2), `AuditLogPort`/`TokenVerifierPort` (t6).
- Produces:
  - `current_identity: ContextVar[Identity | None]`, `current_correlation_id: ContextVar[str]`, `current_scope: ContextVar[Scope | None]`
  - `AuthContextMiddleware(app, verifier)` (middleware ASGI pur)
  - `GovernedFastMCP(matrix, audit, *args, **kwargs)` surchargeant `list_tools()` et `call_tool()`
  - `list_available_tools(matrix, identity, tools, name_of) -> list`, `authorize_tool_call(matrix, identity, tool, correlation_id) -> Allowed`

- [ ] **Step 1: Écrire le test**

`tests/unit/test_governance.py` :

```python
import json

import pytest

from app.api.context import current_correlation_id, current_identity
from app.api.governance import GovernedFastMCP
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.models import Identity, Scope
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog

from datetime import datetime, timedelta, timezone
import io


@pytest.fixture
def matrix() -> AccessMatrix:
    return AccessMatrix(
        version=1,
        profiles={
            "support": ProfileEntry(
                tools=frozenset({"get_stock"}),
                scope=Scope(("manuel",), ("stock",), ("margin",)),
            )
        },
    )


@pytest.fixture
def journal() -> tuple[StdoutAuditLog, io.StringIO]:
    flux = io.StringIO()
    return StdoutAuditLog(stream=flux), flux


@pytest.fixture
def serveur(matrix, journal) -> GovernedFastMCP:
    audit, _ = journal
    server = GovernedFastMCP(matrix=matrix, audit=audit, name="test")
    appels: list[str] = []

    @server.tool()
    def get_stock(product_ref: str) -> dict[str, object]:
        """Stock d'une référence."""
        appels.append(product_ref)
        return {"product_ref": product_ref, "quantity": 7}

    @server.tool()
    def get_query_history(profile: str, limit: int = 20) -> dict[str, object]:
        """Historique des requêtes."""
        appels.append("history")
        return {"items": []}

    server.appels = appels  # type: ignore[attr-defined]
    return server


def connecte(profile: str | None) -> None:
    current_correlation_id.set("corr-test")
    current_identity.set(
        None
        if profile is None
        else Identity(
            subject="client-1",
            profile=profile,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )


async def test_list_tools_ne_renvoie_que_les_tools_du_profil(serveur):
    # Arrange
    connecte("support")

    # Act
    tools = await serveur.list_tools()

    # Assert
    assert [tool.name for tool in tools] == ["get_stock"]


async def test_list_tools_est_vide_sans_authentification(serveur):
    # Arrange
    connecte(None)

    # Act / Assert — un appelant anonyme n'apprend pas quels tools existent
    assert await serveur.list_tools() == []


async def test_un_tool_autorise_est_bien_dispatche(serveur):
    # Arrange
    connecte("support")

    # Act
    await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert
    assert serveur.appels == ["REF-8842"]


async def test_un_tool_interdit_est_refuse_avant_tout_dispatch(serveur):
    # Arrange
    connecte("support")

    # Act
    with pytest.raises(Exception) as capture:
        await serveur.call_tool("get_query_history", {"profile": "support"})

    # Assert — erreur typée, et la fonction du tool n'a jamais été exécutée
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHORIZED_TOOL"
    assert serveur.appels == []


async def test_un_appel_sans_token_est_refuse(serveur):
    # Arrange
    connecte(None)

    # Act
    with pytest.raises(Exception) as capture:
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHENTICATED"
    assert serveur.appels == []


async def test_chaque_appel_est_journalise_autorise_comme_refuse(serveur, journal):
    # Arrange
    _, flux = journal
    connecte("support")

    # Act
    await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})
    with pytest.raises(Exception):
        await serveur.call_tool("get_query_history", {"profile": "support"})

    # Assert
    lignes = [json.loads(ligne) for ligne in flux.getvalue().strip().splitlines()]
    assert [ligne["decision"] for ligne in lignes] == ["allow", "deny"]
    assert lignes[1]["error_code"] == "UNAUTHORIZED_TOOL"
    assert all(ligne["correlation_id"] == "corr-test" for ligne in lignes)
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_governance.py -v`
Expected: FAIL — modules absents.

- [ ] **Step 3: Écrire `app/api/context.py`**

```python
from contextvars import ContextVar

from app.domain.models import Identity, Scope

# Renseignés par AuthContextMiddleware à chaque requête HTTP, lus par la
# gouvernance et par les tools. Un ContextVar plutôt qu'un accès au Request
# du SDK : indépendant de la version du SDK et sûr en concurrence asyncio.
current_identity: ContextVar[Identity | None] = ContextVar("current_identity", default=None)
current_correlation_id: ContextVar[str] = ContextVar("current_correlation_id", default="")
current_scope: ContextVar[Scope | None] = ContextVar("current_scope", default=None)
```

- [ ] **Step 4: Écrire les deux use cases**

`app/application/use_cases/authorize_tool_call.py` :

```python
from app.domain.access_matrix import AccessMatrix
from app.domain.errors import UnauthenticatedError, UnauthorizedToolError
from app.domain.models import Allowed, Identity


def authorize_tool_call(
    matrix: AccessMatrix, identity: Identity | None, tool: str, correlation_id: str
) -> Allowed:
    """Barrière 1 : autorise l'appel ou lève une erreur typée.

    Levée avant tout dispatch — la fonction du tool n'est jamais atteinte
    quand la décision est un refus.
    """
    if identity is None:
        raise UnauthenticatedError(correlation_id)
    decision = matrix.decide(identity.profile, tool)
    if isinstance(decision, Allowed):
        return decision
    raise UnauthorizedToolError(correlation_id)
```

`app/application/use_cases/list_available_tools.py` :

```python
from collections.abc import Callable, Sequence
from typing import TypeVar

from app.domain.access_matrix import AccessMatrix
from app.domain.models import Identity

T = TypeVar("T")


def list_available_tools(
    matrix: AccessMatrix,
    identity: Identity | None,
    tools: Sequence[T],
    name_of: Callable[[T], str],
) -> list[T]:
    """Projection du catalogue : ne conserve que les tools du profil.

    Générique sur le type de tool pour que `domain`/`application` ignorent
    le type `Tool` du SDK MCP.
    """
    if identity is None:
        return []
    autorises = set(matrix.tools_for(identity.profile))
    return [tool for tool in tools if name_of(tool) in autorises]
```

- [ ] **Step 5: Écrire `app/api/governance.py`**

```python
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.api.context import current_correlation_id, current_identity, current_scope
from app.application.use_cases.authorize_tool_call import authorize_tool_call
from app.application.use_cases.list_available_tools import list_available_tools
from app.domain.access_matrix import AccessMatrix
from app.domain.errors import InvalidTokenError, ToolError
from app.domain.models import AuditEntry
from app.domain.ports import AuditLogPort, TokenVerifierPort


class GovernedFastMCP(FastMCP):
    """FastMCP appliquant la matrice d'accès avant tout dispatch (barrière 1)."""

    def __init__(self, matrix: AccessMatrix, audit: AuditLogPort, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._matrix = matrix
        self._audit = audit

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        return list_available_tools(
            self._matrix, current_identity.get(), tools, lambda tool: tool.name
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        identity = current_identity.get()
        correlation_id = current_correlation_id.get() or str(uuid.uuid4())
        debut = time.perf_counter()
        try:
            allowed = authorize_tool_call(self._matrix, identity, name, correlation_id)
        except ToolError as refus:
            self._journalise(name, arguments, identity, correlation_id, debut, error=refus)
            raise

        current_scope.set(allowed.scope)
        try:
            resultat = await super().call_tool(name, arguments)
        except ToolError as echec:
            self._journalise(
                name, arguments, identity, correlation_id, debut, error=echec, rule=allowed.rule
            )
            raise
        self._journalise(
            name, arguments, identity, correlation_id, debut, rule=allowed.rule, allow=True
        )
        return resultat

    def _journalise(
        self,
        tool: str,
        arguments: dict[str, Any],
        identity: Any,
        correlation_id: str,
        debut: float,
        *,
        error: ToolError | None = None,
        rule: str = "",
        allow: bool = False,
    ) -> None:
        self._audit.record(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                correlation_id=correlation_id,
                subject=None if identity is None else identity.subject,
                profile=None if identity is None else identity.profile,
                tool=tool,
                arguments=arguments,
                decision="allow" if allow else "deny",
                rule=rule if rule else (error.error_code if error else ""),
                latency_ms=int((time.perf_counter() - debut) * 1000),
                error_code=None if error is None else error.error_code,
            )
        )


class AuthContextMiddleware:
    """Middleware ASGI pur : résout l'identité et la range dans les ContextVar.

    Lit `scope["headers"]` plutôt que l'objet Request du SDK — indépendant de
    la version du SDK, et fonctionne quel que soit le montage de l'app.
    """

    def __init__(self, app: Callable[..., Awaitable[None]], verifier: TokenVerifierPort):
        self._app = app
        self._verifier = verifier

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        entetes = {clef.lower(): valeur for clef, valeur in scope.get("headers", [])}
        brut = entetes.get(b"authorization", b"").decode()
        identity = None
        if brut.lower().startswith("bearer "):
            try:
                identity = self._verifier.verify(brut[7:].strip())
            except InvalidTokenError:
                identity = None

        correlation = entetes.get(b"x-correlation-id", b"").decode() or str(uuid.uuid4())
        jeton_identite = current_identity.set(identity)
        jeton_correlation = current_correlation_id.set(correlation)
        try:
            await self._app(scope, receive, send)
        finally:
            current_identity.reset(jeton_identite)
            current_correlation_id.reset(jeton_correlation)
```

- [ ] **Step 6: Lancer le test**

Run: `pytest tests/unit/test_governance.py -v`
Expected: PASS (6 tests).

Si `super().call_tool(...)` a une signature différente dans la version installée, l'adapter à la signature réelle vue en tâche 1 — sans changer le comportement testé.

> **Champs `backend` et `row_count`** : ils restent à `None` dans ce lot. Le SDK renvoie
> des blocs de contenu que la couche de gouvernance ne déballe pas, et parser ce format
> reviendrait à dépendre d'une structure interne au SDK. Les champs existent dans
> `AuditEntry` (spec §8) et sont renseignés par les adapters le jour où le résultat
> structuré est disponible — la décision, l'identité, le tool, la règle et la latence,
> eux, sont journalisés dès maintenant pour chaque appel, ce qu'exige E5.

- [ ] **Step 7: Commit**

```bash
git add app/api/context.py app/api/governance.py app/application/use_cases tests/unit/test_governance.py
git commit -m "feat(mcp): applique la matrice d'accès avant tout dispatch de tool"
```

---

## Task 11: Barrière 2 — résolution du périmètre

**Files:**
- Create: `app/application/use_cases/forward_to_backend.py`
- Test: `tests/unit/test_forward_to_backend.py`

**Interfaces:**
- Consumes: `Scope` (t2), `UnauthorizedCollectionError`/`UnauthorizedTableError` (t2), `current_scope`/`current_correlation_id` (t10).
- Produces: `resolve_collections(requested, scope, correlation_id) -> tuple[str, ...]`, `resolve_tables(requested, scope, correlation_id) -> tuple[str, ...]`, `require_scope() -> Scope`.

- [ ] **Step 1: Écrire le test**

`tests/unit/test_forward_to_backend.py` :

```python
import pytest

from app.application.use_cases.forward_to_backend import resolve_collections, resolve_tables
from app.domain.errors import UnauthorizedCollectionError, UnauthorizedTableError
from app.domain.models import Scope

PERIMETRE = Scope(("procedure_sav", "manuel"), ("products", "stock"), ("margin",))


def test_sans_demande_le_perimetre_du_profil_s_applique():
    assert resolve_collections(None, PERIMETRE, "corr") == ("procedure_sav", "manuel")


def test_une_demande_incluse_dans_le_perimetre_le_restreint():
    assert resolve_collections(["manuel"], PERIMETRE, "corr") == ("manuel",)


def test_une_demande_hors_perimetre_est_refusee():
    with pytest.raises(UnauthorizedCollectionError):
        resolve_collections(["datasheet"], PERIMETRE, "corr")


def test_une_demande_ne_peut_pas_elargir_par_melange():
    # Arrange — une collection autorisée mêlée à une interdite reste un refus
    with pytest.raises(UnauthorizedCollectionError):
        resolve_collections(["manuel", "datasheet"], PERIMETRE, "corr")


def test_les_tables_suivent_la_meme_regle():
    assert resolve_tables(["stock"], PERIMETRE, "corr") == ("stock",)
    with pytest.raises(UnauthorizedTableError):
        resolve_tables(["orders"], PERIMETRE, "corr")
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_forward_to_backend.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/application/use_cases/forward_to_backend.py`**

```python
from collections.abc import Sequence

from app.domain.errors import (
    UnauthorizedCollectionError,
    UnauthorizedTableError,
)
from app.domain.models import Scope


def _restreindre(
    demande: Sequence[str] | None, autorise: tuple[str, ...]
) -> tuple[str, ...] | None:
    """Retourne le périmètre effectif, ou None si la demande déborde."""
    if demande is None:
        return autorise
    if not set(demande) <= set(autorise):
        return None
    return tuple(demande)


def resolve_collections(
    demande: Sequence[str] | None, scope: Scope, correlation_id: str
) -> tuple[str, ...]:
    """Barrière 2 côté RAG : une demande ne peut qu'affiner, jamais élargir."""
    effectif = _restreindre(demande, scope.rag_collections)
    if effectif is None:
        raise UnauthorizedCollectionError(correlation_id)
    return effectif


def resolve_tables(
    demande: Sequence[str] | None, scope: Scope, correlation_id: str
) -> tuple[str, ...]:
    """Barrière 2 côté SQL : même règle sur les tables."""
    effectif = _restreindre(demande, scope.sql_tables)
    if effectif is None:
        raise UnauthorizedTableError(correlation_id)
    return effectif
```

- [ ] **Step 4: Lancer le test**

Run: `pytest tests/unit/test_forward_to_backend.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/application/use_cases/forward_to_backend.py tests/unit/test_forward_to_backend.py
git commit -m "feat(mcp): restreint le périmètre demandé au périmètre du profil"
```

---

## Task 12: Adapters stub des trois backends

**Files:**
- Create: `app/infrastructure/stub/__init__.py`
- Create: `app/infrastructure/stub/rag_stub.py`
- Create: `app/infrastructure/stub/text2sql_stub.py`
- Create: `app/infrastructure/stub/sqlapi_stub.py`
- Test: `tests/unit/test_stubs.py`

**Interfaces:**
- Consumes: `RagPort`, `Text2SqlPort`, `SqlExecutionPort` (t6), `NotFoundInCorpusError` (t2).
- Produces: `RagStub()`, `Text2SqlStub()`, `SqlApiStub()` — toutes les méthodes des ports, chaque payload portant `source: "stub"`.

- [ ] **Step 1: Écrire le test**

`tests/unit/test_stubs.py` :

```python
import pytest

from app.domain.errors import NotFoundInCorpusError
from app.infrastructure.stub.rag_stub import RagStub
from app.infrastructure.stub.sqlapi_stub import SqlApiStub
from app.infrastructure.stub.text2sql_stub import Text2SqlStub


async def test_chaque_reponse_stub_annonce_sa_provenance():
    # Act
    resultats = [
        await RagStub().search("tension", 5, ("manuel",), "corr"),
        await Text2SqlStub().generate_sql("stock ?", "sales", ("stock",), "corr"),
        await SqlApiStub().stock("REF-8842", "sales", "corr"),
    ]

    # Assert — une donnée fictive ne peut pas passer pour une donnée réelle
    assert all(resultat["source"] == "stub" for resultat in resultats)


async def test_le_stub_rag_refuse_explicitement_une_question_hors_corpus():
    # Act / Assert — E1 reste exerçable sans backend réel
    with pytest.raises(NotFoundInCorpusError):
        await RagStub().answer("question absente du corpus", ("manuel",), "corr")


async def test_le_stub_text2sql_ne_retourne_que_du_sql_jamais_un_resultat():
    # Act
    resultat = await Text2SqlStub().generate_sql("stock de REF-8842 ?", "sales", ("stock",), "c")

    # Assert
    assert resultat["sql"].lower().startswith("select")
    assert "rows" not in resultat
```

Note : le stub RAG refuse toute question contenant `absente` — convention explicite qui rend E1 testable de bout en bout sans backend.

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_stubs.py -v`
Expected: FAIL — modules absents.

- [ ] **Step 3: Écrire `app/infrastructure/stub/rag_stub.py`**

```python
from collections.abc import Sequence
from typing import Any

from app.domain.errors import NotFoundInCorpusError

CITATION = {
    "doc_id": "REF-8842:datasheet:1",
    "title": "Fiche produit REF-8842",
    "product_ref": "REF-8842",
    "published_date": "2026-01-15",
    "document_type": "datasheet",
}


class RagStub:
    """Doublure du service RAG, en attendant les endpoints de briques.

    Convention de test : une requête contenant « absente » simule un hors-corpus.
    """

    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if "absente" in query.lower():
            raise NotFoundInCorpusError(correlation_id)
        return {
            "source": "stub",
            "citations": [CITATION],
            "confidence": "high",
            "collections": list(collections),
        }

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if "absente" in query.lower():
            raise NotFoundInCorpusError(correlation_id)
        return {
            "source": "stub",
            "passages": [
                {"content": "Tension nominale : 230V.", "citation": CITATION} for _ in range(1)
            ][:top_k],
            "collections": list(collections),
        }

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return {"source": "stub", "product_ref": product_ref, "citation": CITATION}

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "doc_id": doc_id,
            "title": CITATION["title"],
            "version": "1",
            "published_date": CITATION["published_date"],
            "status": "active",
        }

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return {"source": "stub", "score": 0.0 if "absente" in query.lower() else 0.82}

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return {"source": "stub", "document_types": list(collections)}
```

- [ ] **Step 4: Écrire `app/infrastructure/stub/text2sql_stub.py`**

```python
from collections.abc import Sequence
from typing import Any


class Text2SqlStub:
    """Doublure de l'agent Text-to-SQL : génère, n'exécute jamais."""

    async def generate_sql(
        self, question: str, profile: str, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        table = tables[0] if tables else "products"
        return {
            "source": "stub",
            "sql": f"SELECT * FROM {table} LIMIT 100",
            "tables": list(tables),
            "question": question,
        }
```

- [ ] **Step 5: Écrire `app/infrastructure/stub/sqlapi_stub.py`**

```python
from collections.abc import Sequence
from typing import Any


class SqlApiStub:
    """Doublure de sorabelsql-api : exécute, ne génère jamais."""

    async def run_sql(
        self,
        sql: str,
        profile: str,
        tables: Sequence[str],
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "sql": sql,
            "rows": [],
            "row_count": 0,
            "masked_columns": list(masked_columns),
        }

    async def stock(
        self, product_ref: str, profile: str, correlation_id: str
    ) -> dict[str, Any]:
        return {"source": "stub", "product_ref": product_ref, "quantity": 12, "row_count": 1}

    async def order_status(
        self, order_id: str, profile: str, correlation_id: str
    ) -> dict[str, Any]:
        return {"source": "stub", "order_id": order_id, "status": "shipped", "row_count": 1}

    async def customer_orders(
        self,
        customer_id: str,
        limit: int,
        profile: str,
        masked_columns: Sequence[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "customer_id": customer_id,
            "orders": [],
            "row_count": 0,
            "masked_columns": list(masked_columns),
        }

    async def schema_info(
        self, profile: str, keyword: str | None, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return {
            "source": "stub",
            "tables": [{"name": nom, "columns": ["id"]} for nom in tables],
            "keyword": keyword,
        }

    async def query_history(
        self, profile: str, limit: int, correlation_id: str
    ) -> dict[str, Any]:
        return {"source": "stub", "items": [], "row_count": 0}
```

- [ ] **Step 6: Lancer le test**

Run: `pytest tests/unit/test_stubs.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add app/infrastructure/stub tests/unit/test_stubs.py
git commit -m "feat(mcp): ajoute les adapters stub des trois backends"
```

---

## Task 13: Les 13 fonctions de tool et l'assemblage du serveur

**Files:**
- Create: `app/api/tools/__init__.py`
- Create: `app/application/use_cases/answer_question.py`
- Create: `app/api/tools/rag.py`
- Create: `app/api/tools/sql.py`
- Create: `app/dependencies.py`
- Create: `app/api/server.py`
- Test: `tests/unit/test_tool_registration.py`

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces: `answer_question(rag, query, collections, correlation_id) -> dict`, `register_rag_tools(server, rag)`, `register_sql_tools(server, text2sql, sqlapi)`, `build_server() -> GovernedFastMCP`, `build_app()` (app ASGI enveloppée par `AuthContextMiddleware`).

- [ ] **Step 1: Écrire le test**

`tests/unit/test_tool_registration.py` :

```python
from app.api.server import build_server
from app.domain.catalog import CATALOG_BY_NAME


async def test_les_treize_tools_du_catalogue_sont_enregistres():
    # Arrange
    server = build_server()

    # Act — sans identité, la barrière 1 filtre : on interroge le registre brut
    noms = {tool.name for tool in await server.list_all_tools()}

    # Assert
    assert noms == set(CATALOG_BY_NAME)


async def test_chaque_tool_expose_une_docstring_non_vide():
    # Arrange
    server = build_server()

    # Act
    tools = await server.list_all_tools()

    # Assert — la description est ce que lit le LLM client
    assert all(tool.description and tool.description.strip() for tool in tools)
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_tool_registration.py -v`
Expected: FAIL — modules absents.

- [ ] **Step 3: Ajouter `list_all_tools()` à `GovernedFastMCP`**

Dans `app/api/governance.py`, ajouter à la classe :

```python
    async def list_all_tools(self) -> list[Any]:
        """Catalogue complet, sans filtrage — usage interne et tests d'exhaustivité."""
        return await super().list_tools()
```

- [ ] **Step 4a: Écrire `app/application/use_cases/answer_question.py`**

La seule orchestration réelle du projet vit dans `application/`, jamais dans `api/` — `python-hexagonal.md` : « `api/` ne contient aucune logique métier ».

```python
from collections.abc import Sequence
from typing import Any

from app.domain.ports import RagPort


async def answer_question(
    rag: RagPort, query: str, collections: Sequence[str], correlation_id: str
) -> dict[str, Any]:
    """Composite de MCP.md §1 : agrège trois briques, ne rédige rien.

    Le texte éventuellement généré par le backend n'est pas propagé : la
    rédaction appartient au LLM du client, à partir des sources retournées.
    """
    sources = await rag.answer(query, collections, correlation_id)
    metadonnees = [
        await rag.document_metadata(citation["doc_id"], collections, correlation_id)
        for citation in sources.get("citations", [])
        if citation.get("doc_id")
    ]
    types = await rag.document_types(collections, correlation_id)
    return {"sources": sources, "metadata": metadonnees, "document_types": types}
```

- [ ] **Step 4b: Écrire `app/api/tools/rag.py`**

```python
from typing import Any

from app.api.context import current_correlation_id, current_scope
from app.application.use_cases.answer_question import (
    answer_question as answer_question_use_case,
)
from app.application.use_cases.forward_to_backend import resolve_collections
from app.domain.models import Scope
from app.domain.ports import RagPort


def _contexte() -> tuple[Scope, str]:
    scope = current_scope.get()
    assert scope is not None  # garanti par la barrière 1, qui l'a posé
    return scope, current_correlation_id.get()


def register_rag_tools(server: Any, rag: RagPort) -> None:
    """Enregistre les 6 tools documentaires. Aucune logique métier ici."""

    @server.tool()
    async def answer_question(query: str) -> dict[str, Any]:
        """Agrège les sources documentaires nécessaires pour répondre à une question : passages pertinents, métadonnées des documents cités et catalogue des types de documents. NE RÉDIGE AUCUNE RÉPONSE — c'est au modèle appelant de formuler la réponse à partir des sources retournées, en citant systématiquement titre, référence et date. Si le corpus ne contient pas la réponse, le résultat est une erreur NOT_FOUND_IN_CORPUS : ne jamais la reformuler en réponse plausible. Args: query: Question métier en langage naturel."""
        scope, correlation_id = _contexte()
        collections = resolve_collections(None, scope, correlation_id)
        return await answer_question_use_case(rag, query, collections, correlation_id)

    @server.tool()
    async def search_documents(
        query: str, top_k: int = 5, collections: list[str] | None = None
    ) -> dict[str, Any]:
        """Recherche hybride (dense + BM25 + reranking) dans le corpus documentaire et retourne les passages les plus pertinents avec leurs métadonnées. À utiliser pour une question formulée en langage naturel. Pour une référence produit exacte (ex: 'REF-8842'), préférer lookup_by_reference, plus fiable sur les identifiants. Args: query: Requête en langage naturel. top_k: Nombre maximal de passages retournés (défaut 5). collections: Restriction optionnelle aux collections nommées — ne peut qu'affiner le périmètre du profil, jamais l'élargir."""
        scope, correlation_id = _contexte()
        effectif = resolve_collections(collections, scope, correlation_id)
        return await rag.search(query, top_k, effectif, correlation_id)

    @server.tool()
    async def lookup_by_reference(
        product_ref: str, collections: list[str] | None = None
    ) -> dict[str, Any]:
        """Retourne la fiche documentaire correspondant à une référence produit exacte, par correspondance littérale et sans scoring sémantique. À utiliser EN PRIORITÉ dès qu'une référence produit (ex: 'REF-8842') est connue — search_documents peut confondre deux références proches. Args: product_ref: Référence produit exacte. collections: Restriction optionnelle aux collections nommées."""
        scope, correlation_id = _contexte()
        effectif = resolve_collections(collections, scope, correlation_id)
        return await rag.lookup(product_ref, effectif, correlation_id)

    @server.tool()
    async def get_document_metadata(doc_id: str) -> dict[str, Any]:
        """Retourne les métadonnées d'un document (titre, version, date de publication, statut) sans son contenu. À utiliser pour vérifier qu'un document cité est toujours actif, ou pour dater une information. Args: doc_id: Identifiant du document."""
        scope, correlation_id = _contexte()
        collections = resolve_collections(None, scope, correlation_id)
        return await rag.document_metadata(doc_id, collections, correlation_id)

    @server.tool()
    async def check_answer_confidence(query: str) -> dict[str, Any]:
        """Retourne le score de pertinence du meilleur passage du corpus pour une question, sans retourner ni passage ni réponse. À utiliser pour décider s'il vaut la peine d'interroger le corpus avant d'appeler search_documents ou answer_question. Args: query: Question à évaluer."""
        scope, correlation_id = _contexte()
        collections = resolve_collections(None, scope, correlation_id)
        return await rag.confidence(query, collections, correlation_id)

    @server.tool()
    async def list_document_types() -> dict[str, Any]:
        """Retourne les catégories de documents présentes dans le corpus accessible au profil appelant (ex: 'datasheet', 'manuel', 'procedure_sav'). À appeler pour cadrer une recherche quand la nature du document recherché est incertaine."""
        scope, correlation_id = _contexte()
        collections = resolve_collections(None, scope, correlation_id)
        return await rag.document_types(collections, correlation_id)
```

- [ ] **Step 5: Écrire `app/api/tools/sql.py`**

Docstrings reprises verbatim de `MCP.md` §2 (tableau des signatures Python).

```python
from typing import Any

from app.api.context import current_correlation_id, current_identity, current_scope
from app.domain.models import Scope
from app.domain.ports import SqlExecutionPort, Text2SqlPort


def _contexte() -> tuple[Scope, str, str]:
    scope = current_scope.get()
    identity = current_identity.get()
    assert scope is not None and identity is not None  # garantis par la barrière 1
    return scope, identity.profile, current_correlation_id.get()


def register_sql_tools(server: Any, text2sql: Text2SqlPort, sqlapi: SqlExecutionPort) -> None:
    """Enregistre les 7 tools données. Aucune logique métier ici."""

    @server.tool()
    async def ask_database(question: str, profile: str) -> dict[str, Any]:
        """Génère une requête SQL en lecture seule à partir d'une question en langage naturel, via l'agent Text-to-SQL dédié. NE L'EXÉCUTE PAS — retourne uniquement le SQL généré ; appeler run_sql_query pour l'exécuter. À utiliser UNIQUEMENT si aucun des tools figés (get_stock, get_order_status, get_customer_order_history) ne couvre le besoin — dernier recours, plus coûteux et moins déterministe. CRITICAL: n'utilise que les noms de tables/colonnes retournés par get_schema_info, ne jamais en inventer. Args: question: Question métier en langage naturel. profile: Profil du client appelant, pour restreindre les tables/colonnes visibles dans le schéma injecté."""
        scope, profil_reel, correlation_id = _contexte()
        return await text2sql.generate_sql(
            question, profil_reel, scope.sql_tables, correlation_id
        )

    @server.tool()
    async def run_sql_query(sql: str, profile: str) -> dict[str, Any]:
        """Exécute une requête SQL déjà écrite (typiquement obtenue via ask_database) après validation par la chaîne de garde-fous en lecture seule (rôle DB, blocklist, AST, guardrail sémantique, LIMIT/timeout, réplica). NE GÉNÈRE AUCUN SQL — sql doit être une requête complète et syntaxiquement valide. Args: sql: Requête SQL à valider et exécuter. profile: Profil du client appelant, pour restreindre les tables/colonnes visibles et appliquer le masquage de colonnes."""
        scope, profil_reel, correlation_id = _contexte()
        return await sqlapi.run_sql(
            sql, profil_reel, scope.sql_tables, scope.masked_columns, correlation_id
        )

    @server.tool()
    async def get_stock(product_ref: str) -> dict[str, Any]:
        """Retourne le stock disponible pour une référence produit exacte. À utiliser EN PRIORITÉ dès qu'une référence produit (ex: 'REF-8842') est connue. Plus rapide et plus fiable que ask_database pour ce besoin précis — ne PAS utiliser ask_database si ce tool suffit. Args: product_ref: Référence produit exacte (ex: 'REF-8842')."""
        _, profil_reel, correlation_id = _contexte()
        return await sqlapi.stock(product_ref, profil_reel, correlation_id)

    @server.tool()
    async def get_order_status(order_id: str) -> dict[str, Any]:
        """Retourne le statut d'une commande à partir de son identifiant. À utiliser EN PRIORITÉ dès qu'un order_id est connu. Ne PAS utiliser ask_database pour ce besoin. Args: order_id: Identifiant de commande."""
        _, profil_reel, correlation_id = _contexte()
        return await sqlapi.order_status(order_id, profil_reel, correlation_id)

    @server.tool()
    async def get_customer_order_history(customer_id: str, limit: int = 20) -> dict[str, Any]:
        """Retourne l'historique des commandes d'un client identifié. À utiliser EN PRIORITÉ dès qu'un customer_id est connu. Ne PAS utiliser ask_database pour ce besoin. Args: customer_id: Identifiant client. limit: Nombre maximal de commandes retournées (défaut 20)."""
        scope, profil_reel, correlation_id = _contexte()
        return await sqlapi.customer_orders(
            customer_id, limit, profil_reel, scope.masked_columns, correlation_id
        )

    @server.tool()
    async def get_schema_info(profile: str, keyword: str | None = None) -> dict[str, Any]:
        """Retourne les tables et colonnes réellement accessibles au profil appelant. À appeler AVANT ask_database si le nom exact d'une table ou d'une colonne n'est pas certain — évite les erreurs de schéma et les hallucinations de noms de colonnes. Args: profile: Profil du client appelant (ex: 'support', 'sales'). keyword: Filtre optionnel sur le nom des tables/colonnes."""
        scope, profil_reel, correlation_id = _contexte()
        return await sqlapi.schema_info(
            profil_reel, keyword, scope.sql_tables, correlation_id
        )

    @server.tool()
    async def get_query_history(profile: str, limit: int = 20) -> dict[str, Any]:
        """Retourne les dernières requêtes exécutées ou rejetées pour ce profil. Outil d'audit et de debug côté client — jamais une source de données métier. Args: profile: Profil du client appelant. limit: Nombre maximal d'entrées retournées (défaut 20)."""
        _, profil_reel, correlation_id = _contexte()
        return await sqlapi.query_history(profil_reel, limit, correlation_id)
```

> Le paramètre `profile` reste dans la signature des tools qui le déclarent dans
> `MCP.md` §2 — c'est le contrat publié — mais il n'est **jamais** utilisé pour décider :
> le profil effectif vient du token (`identity.profile`). Un client qui ment sur ce
> paramètre n'obtient rien de plus.

- [ ] **Step 6: Écrire `app/dependencies.py`**

```python
from app.config import Settings, get_settings
from app.domain.ports import AuditLogPort, RagPort, SqlExecutionPort, Text2SqlPort
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from app.infrastructure.stub.rag_stub import RagStub
from app.infrastructure.stub.sqlapi_stub import SqlApiStub
from app.infrastructure.stub.text2sql_stub import Text2SqlStub


def build_rag_port(settings: Settings) -> RagPort:
    if settings.rag_backend == "stub":
        return RagStub()
    from app.infrastructure.http.rag_client import RagHttpClient

    return RagHttpClient(settings.rag_base_url, settings.mcp_http_timeout_s)


def build_text2sql_port(settings: Settings) -> Text2SqlPort:
    if settings.text2sql_backend == "stub":
        return Text2SqlStub()
    raise NotImplementedError("adapter HTTP text2sql-ai : le service n'existe pas encore")


def build_sqlapi_port(settings: Settings) -> SqlExecutionPort:
    if settings.sqlapi_backend == "stub":
        return SqlApiStub()
    raise NotImplementedError("adapter HTTP sorabelsql-api : le service n'existe pas encore")


def build_audit_log() -> AuditLogPort:
    return StdoutAuditLog()


def current_settings() -> Settings:
    return get_settings()
```

> Les deux `NotImplementedError` sont volontaires et explicites : `text2sql-ai` et
> `sorabelsql-api` n'ont pas une ligne de code. Configurer `TEXT2SQL_BACKEND=http`
> échoue au démarrage plutôt que de laisser croire à un câblage.

- [ ] **Step 7: Écrire `app/api/server.py`**

```python
from typing import Any

from app.api.governance import AuthContextMiddleware, GovernedFastMCP
from app.api.tools.rag import register_rag_tools
from app.api.tools.sql import register_sql_tools
from app.dependencies import (
    build_audit_log,
    build_rag_port,
    build_sqlapi_port,
    build_text2sql_port,
    current_settings,
)
from app.infrastructure.keycloak.jwks_verifier import build_token_verifier
from app.infrastructure.matrix.yaml_loader import load_access_matrix


def build_server() -> GovernedFastMCP:
    """Assemble le serveur : matrice, journal, tools, adapters."""
    settings = current_settings()
    server = GovernedFastMCP(
        matrix=load_access_matrix(settings.access_matrix_file()),
        audit=build_audit_log(),
        name="sorabel-data-gateway",
    )
    register_rag_tools(server, build_rag_port(settings))
    register_sql_tools(server, build_text2sql_port(settings), build_sqlapi_port(settings))
    return server


def build_app() -> Any:
    """App ASGI complète : transport HTTP streamable + résolution d'identité."""
    settings = current_settings()
    return AuthContextMiddleware(
        build_server().streamable_http_app(), build_token_verifier(settings)
    )


app = build_app()
```

- [ ] **Step 8: Lancer le test**

Run: `pytest tests/unit/test_tool_registration.py -v`
Expected: PASS (2 tests).

Ces tests instancient `build_server()`, qui lit le `.env` : s'assurer que `MCP_DEV_JWT_SECRET` y est renseigné localement (le `.env` est gitignored ; `.env.example` documente la variable).

- [ ] **Step 9: Écrire le test du composite**

`tests/unit/test_answer_question_composite.py` — la seule orchestration réelle du projet :

```python
from datetime import datetime, timedelta, timezone
from typing import Any

import io
import pytest

from app.api.context import current_correlation_id, current_identity
from app.api.governance import GovernedFastMCP
from app.api.tools.rag import register_rag_tools
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.models import Identity, Scope
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from app.infrastructure.stub.rag_stub import CITATION


class RagEspion:
    """Faux port qui compte ses appels et retient les correlation_id reçus."""

    def __init__(self) -> None:
        self.appels: list[str] = []
        self.correlations: list[str] = []

    async def answer(self, query: str, collections: Any, correlation_id: str) -> dict[str, Any]:
        self.appels.append("answer")
        self.correlations.append(correlation_id)
        return {"source": "stub", "citations": [CITATION], "confidence": "high"}

    async def document_metadata(
        self, doc_id: str, collections: Any, correlation_id: str
    ) -> dict[str, Any]:
        self.appels.append("document_metadata")
        self.correlations.append(correlation_id)
        return {"source": "stub", "doc_id": doc_id}

    async def document_types(self, collections: Any, correlation_id: str) -> dict[str, Any]:
        self.appels.append("document_types")
        self.correlations.append(correlation_id)
        return {"source": "stub", "document_types": list(collections)}

    async def search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("le composite ne doit pas appeler search")

    async def lookup(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("le composite ne doit pas appeler lookup")

    async def confidence(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("le composite ne doit pas appeler confidence")


@pytest.fixture
def espion_et_serveur() -> tuple[RagEspion, GovernedFastMCP]:
    espion = RagEspion()
    server = GovernedFastMCP(
        matrix=AccessMatrix(
            version=1,
            profiles={
                "sales": ProfileEntry(
                    tools=frozenset({"answer_question"}),
                    scope=Scope(("manuel",), (), ()),
                )
            },
        ),
        audit=StdoutAuditLog(stream=io.StringIO()),
        name="test",
    )
    register_rag_tools(server, espion)
    current_correlation_id.set("corr-composite")
    current_identity.set(
        Identity("client-1", "sales", datetime.now(timezone.utc) + timedelta(minutes=5))
    )
    return espion, server


async def test_le_composite_orchestre_les_trois_briques(espion_et_serveur):
    # Arrange
    espion, server = espion_et_serveur

    # Act
    await server.call_tool("answer_question", {"query": "tension de REF-8842 ?"})

    # Assert — les trois briques de MCP.md §1, une fois chacune
    assert espion.appels == ["answer", "document_metadata", "document_types"]


async def test_le_composite_propage_le_correlation_id_a_chaque_brique(espion_et_serveur):
    # Arrange
    espion, server = espion_et_serveur

    # Act
    await server.call_tool("answer_question", {"query": "tension ?"})

    # Assert
    assert espion.correlations == ["corr-composite"] * 3
```

- [ ] **Step 10: Lancer le test**

Run: `pytest tests/unit/test_answer_question_composite.py -v`
Expected: PASS (2 tests).

- [ ] **Step 11: Commit**

```bash
git add app/api/tools app/api/server.py app/dependencies.py app/api/governance.py app/application/use_cases/answer_question.py tests/unit/test_tool_registration.py tests/unit/test_answer_question_composite.py
git commit -m "feat(mcp): enregistre les 13 tools et assemble le serveur HTTP"
```

---

## Task 14: Adapter HTTP RAG et délégation au stub

**Files:**
- Create: `app/infrastructure/http/__init__.py`
- Create: `app/infrastructure/http/rag_client.py`
- Test: `tests/unit/test_rag_client.py`

**Interfaces:**
- Consumes: `RagPort` (t6), `RagStub` (t12), erreurs (t2).
- Produces: `RagHttpClient(base_url, timeout_s)`, attribut de classe `DELEGATED_TO_STUB: frozenset[str]`.

- [ ] **Step 1: Écrire le test**

`tests/unit/test_rag_client.py` :

```python
import httpx
import pytest

from app.domain.errors import BackendUnavailableError, NotFoundInCorpusError
from app.infrastructure.http.rag_client import RagHttpClient


def client_avec(handler) -> RagHttpClient:
    transport = httpx.MockTransport(handler)
    return RagHttpClient("http://rag.test", timeout_s=5.0, transport=transport)


async def test_une_reponse_200_donne_les_citations_sans_le_texte_genere():
    # Arrange — rag-hybride génère un texte que le serveur MCP ne doit pas propager
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer": "La tension nominale est de 230V.",
                "citations": [{"title": "Fiche REF-8842", "product_ref": "REF-8842"}],
                "confidence": "high",
                "refused": False,
            },
        )

    # Act
    resultat = await client_avec(handler).answer("tension ?", ("manuel",), "corr")

    # Assert
    assert resultat["citations"][0]["product_ref"] == "REF-8842"
    assert "answer" not in resultat
    assert "230V" not in str(resultat)


async def test_un_refus_de_corpus_devient_une_erreur_typee():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "", "citations": [], "refused": True})

    with pytest.raises(NotFoundInCorpusError):
        await client_avec(handler).answer("question absente", ("manuel",), "corr")


async def test_une_erreur_serveur_devient_backend_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error_code": "EMBEDDING_SERVICE_ERROR"})

    with pytest.raises(BackendUnavailableError):
        await client_avec(handler).answer("tension ?", ("manuel",), "corr")


async def test_le_correlation_id_est_propage_au_backend():
    recu: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recu["id"] = request.headers.get("x-correlation-id", "")
        return httpx.Response(200, json={"citations": [], "confidence": "low", "refused": False})

    await client_avec(handler).answer("tension ?", ("manuel",), "corr-42")
    assert recu["id"] == "corr-42"


async def test_les_briques_sans_endpoint_sont_deleguees_au_stub():
    # Arrange — aucune requête HTTP ne doit partir pour ces méthodes
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel réseau attendu")

    client = client_avec(handler)

    # Act
    resultat = await client.search("tension", 3, ("manuel",), "corr")

    # Assert — la provenance reste explicite
    assert resultat["source"] == "stub"
    assert RagHttpClient.DELEGATED_TO_STUB == frozenset(
        {"search", "lookup", "document_metadata", "confidence", "document_types"}
    )
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `pytest tests/unit/test_rag_client.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Écrire `app/infrastructure/http/rag_client.py`**

```python
from collections.abc import Sequence
from typing import Any

import httpx

from app.domain.errors import BackendUnavailableError, NotFoundInCorpusError
from app.infrastructure.stub.rag_stub import RagStub


class RagHttpClient:
    """Adapter réel vers `rag-hybride`, via l'URL configurée.

    `rag-hybride` n'expose aujourd'hui que `POST /api/v1/query`. Les briques
    sans endpoint sont déléguées au stub, chaque délégation restant visible
    dans `DELEGATED_TO_STUB` — un test verrouille cette liste, pour qu'une
    délégation ne survive pas à l'arrivée de son endpoint.
    """

    DELEGATED_TO_STUB = frozenset(
        {"search", "lookup", "document_metadata", "confidence", "document_types"}
    )

    def __init__(
        self,
        base_url: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport
        self._stub = RagStub()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_s, transport=self._transport
        )

    async def answer(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        try:
            async with self._client() as client:
                reponse = await client.post(
                    "/api/v1/query",
                    json={"query": query, "top_k": 5},
                    headers={"X-Correlation-Id": correlation_id},
                )
        except httpx.HTTPError as exc:
            raise BackendUnavailableError(correlation_id) from exc
        if reponse.status_code >= 500:
            raise BackendUnavailableError(correlation_id)
        if reponse.status_code >= 400:
            raise BackendUnavailableError(correlation_id)

        corps = reponse.json()
        if corps.get("refused"):
            raise NotFoundInCorpusError(correlation_id)
        # `answer` est délibérément écarté : le serveur MCP ne propage aucun
        # texte généré (spec §9, MCP.md §1).
        return {
            "source": "live",
            "citations": corps.get("citations", []),
            "confidence": corps.get("confidence"),
            "collections": list(collections),
        }

    async def search(
        self, query: str, top_k: int, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return await self._stub.search(query, top_k, collections, correlation_id)

    async def lookup(
        self, product_ref: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return await self._stub.lookup(product_ref, collections, correlation_id)

    async def document_metadata(
        self, doc_id: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return await self._stub.document_metadata(doc_id, collections, correlation_id)

    async def confidence(
        self, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return await self._stub.confidence(query, collections, correlation_id)

    async def document_types(
        self, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        return await self._stub.document_types(collections, correlation_id)
```

- [ ] **Step 4: Lancer le test**

Run: `pytest tests/unit/test_rag_client.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/http tests/unit/test_rag_client.py
git commit -m "feat(mcp): ajoute l'adapter HTTP vers rag-hybride"
```

---

## Task 15: Intégration — l'adapter RAG contre un vrai serveur HTTP

**Files:**
- Create: `tests/integration/conftest.py`
- Test: `tests/integration/test_rag_client_http.py`

**Interfaces:**
- Consumes: `RagHttpClient` (t14).
- Produces: fixture `serveur_rag` — un `uvicorn` sur port éphémère servant la doublure du contrat `rag-hybride`.

- [ ] **Step 1: Écrire la fixture de serveur réel**

`tests/integration/conftest.py` :

```python
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def _port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return int(prise.getsockname()[1])


def _application_double() -> FastAPI:
    """Doublure du contrat `rag-hybride`, servie par un vrai serveur.

    Les deux projets exposent chacun un paquet `app` : importer l'application
    réelle de `rag-hybride` ici entrerait en collision (cf. ../CLAUDE.md).
    """
    application = FastAPI()

    @application.post("/api/v1/query")
    async def query(request: Request) -> Any:
        corps = await request.json()
        requete = corps.get("query", "")
        if "absente" in requete:
            return {"answer": "", "citations": [], "confidence": "refused", "refused": True}
        if "panne" in requete:
            return JSONResponse(status_code=500, content={"error_code": "EMBEDDING_SERVICE_ERROR"})
        if "lent" in requete:
            time.sleep(2)
        return {
            "answer": "La tension nominale est de 230V.",
            "citations": [
                {
                    "title": "Fiche REF-8842",
                    "product_ref": "REF-8842",
                    "published_date": "2026-01-15",
                    "document_type": "datasheet",
                }
            ],
            "confidence": "high",
            "refused": False,
            "correlation_id_recu": request.headers.get("x-correlation-id", ""),
        }

    return application


@pytest.fixture(scope="session")
def serveur_rag() -> Iterator[str]:
    port = _port_libre()
    config = uvicorn.Config(
        _application_double(), host="127.0.0.1", port=port, log_level="warning"
    )
    serveur = uvicorn.Server(config)
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    while not serveur.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    serveur.should_exit = True
    fil.join(timeout=5)
```

- [ ] **Step 2: Écrire le test d'intégration**

`tests/integration/test_rag_client_http.py` :

```python
import httpx
import pytest

from app.domain.errors import BackendUnavailableError, NotFoundInCorpusError
from app.infrastructure.http.rag_client import RagHttpClient


async def test_appelle_reellement_le_serveur_et_renvoie_les_citations(serveur_rag):
    # Arrange
    client = RagHttpClient(serveur_rag, timeout_s=5.0)

    # Act
    resultat = await client.answer("tension nominale ?", ("manuel",), "corr-1")

    # Assert
    assert resultat["citations"][0]["product_ref"] == "REF-8842"
    assert resultat["source"] == "live"
    assert "answer" not in resultat


async def test_un_refus_de_corpus_traverse_le_reseau_en_erreur_typee(serveur_rag):
    client = RagHttpClient(serveur_rag, timeout_s=5.0)
    with pytest.raises(NotFoundInCorpusError):
        await client.answer("information absente", ("manuel",), "corr-2")


async def test_une_erreur_500_reelle_devient_backend_unavailable(serveur_rag):
    client = RagHttpClient(serveur_rag, timeout_s=5.0)
    with pytest.raises(BackendUnavailableError):
        await client.answer("panne du service", ("manuel",), "corr-3")


async def test_un_timeout_reel_devient_backend_unavailable(serveur_rag):
    # Arrange — le serveur met 2s, le client attend 0,2s
    client = RagHttpClient(serveur_rag, timeout_s=0.2)

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client.answer("réponse lente", ("manuel",), "corr-4")


async def test_une_connexion_refusee_devient_backend_unavailable():
    client = RagHttpClient("http://127.0.0.1:1", timeout_s=1.0)
    with pytest.raises(BackendUnavailableError):
        await client.answer("tension ?", ("manuel",), "corr-5")


async def test_le_correlation_id_arrive_reellement_chez_le_backend(serveur_rag):
    # Arrange — la doublure renvoie l'en-tête reçu
    async with httpx.AsyncClient(base_url=serveur_rag) as sonde:
        reponse = await sonde.post(
            "/api/v1/query", json={"query": "tension ?"}, headers={"X-Correlation-Id": "corr-9"}
        )

    # Assert
    assert reponse.json()["correlation_id_recu"] == "corr-9"


@pytest.mark.live
async def test_contre_le_vrai_rag_hybride_s_il_ecoute():
    """Vérification cross-projet, opt-in : `pytest -m live` avec rag-hybride démarré."""
    client = RagHttpClient("http://localhost:8001", timeout_s=10.0)
    resultat = await client.answer("tension nominale", ("manuel",), "corr-live")
    assert "citations" in resultat
```

- [ ] **Step 3: Lancer les tests**

Run: `pytest tests/integration/test_rag_client_http.py -v -m "not live"`
Expected: PASS (6 tests), le test `live` étant désélectionné.

- [ ] **Step 4: Vérifier que le marqueur `live` est bien exclu par défaut**

Run: `pytest tests/integration -v` puis vérifier qu'aucun avertissement `PytestUnknownMarkWarning` n'apparaît (le marqueur a été déclaré en tâche 1, step 3). Le test `live` échouera si aucun `rag-hybride` n'écoute : c'est attendu, il ne doit être lancé qu'avec `-m live`.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_rag_client_http.py
git commit -m "test(mcp): éprouve l'adapter RAG contre un vrai serveur HTTP"
```

---

## Task 16: Acceptance — les six scénarios de bout en bout

**Files:**
- Create: `tests/acceptance/conftest.py`
- Test: `tests/acceptance/test_personas.py`

**Interfaces:**
- Consumes: `build_server` (t13), `GovernedFastMCP`, `current_identity`, `current_correlation_id`.
- Produces: fixture `gateway(profile)` — serveur assemblé, identité posée comme le ferait le middleware.

- [ ] **Step 1: Écrire les fixtures**

`tests/acceptance/conftest.py` :

```python
import io
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone

import pytest

from app.api.context import current_correlation_id, current_identity, current_scope
from app.api.governance import GovernedFastMCP
from app.api.tools.rag import register_rag_tools
from app.api.tools.sql import register_sql_tools
from app.domain.models import Identity
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from app.infrastructure.matrix.yaml_loader import load_access_matrix
from app.infrastructure.stub.rag_stub import RagStub
from app.infrastructure.stub.sqlapi_stub import SqlApiStub
from app.infrastructure.stub.text2sql_stub import Text2SqlStub
from pathlib import Path

MATRICE = Path(__file__).resolve().parents[2] / "access_matrix.yaml"


@pytest.fixture
def journal() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def gateway(journal: io.StringIO) -> Callable[[str | None], GovernedFastMCP]:
    """Assemble le serveur comme en production, puis pose l'identité.

    L'identité est posée dans le ContextVar exactement comme le ferait
    AuthContextMiddleware après vérification du token.
    """

    def _construire(profile: str | None) -> GovernedFastMCP:
        server = GovernedFastMCP(
            matrix=load_access_matrix(MATRICE),
            audit=StdoutAuditLog(stream=journal),
            name="sorabel-data-gateway",
        )
        register_rag_tools(server, RagStub())
        register_sql_tools(server, Text2SqlStub(), SqlApiStub())
        current_correlation_id.set("corr-acceptance")
        current_scope.set(None)
        current_identity.set(
            None
            if profile is None
            else Identity(
                subject=f"client-{profile}",
                profile=profile,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
        return server

    return _construire


@pytest.fixture(autouse=True)
def contexte_propre() -> Iterator[None]:
    yield
    current_identity.set(None)
    current_scope.set(None)
    current_correlation_id.set("")
```

- [ ] **Step 2: Écrire les six scénarios**

`tests/acceptance/test_personas.py` :

```python
import json

import pytest


def lignes_journal(journal) -> list[dict]:
    return [json.loads(ligne) for ligne in journal.getvalue().strip().splitlines() if ligne]


async def test_bot_slack_support_ne_voit_que_ses_cinq_tools(gateway, journal):
    # Arrange
    serveur = gateway("support")

    # Act
    catalogue = {tool.name for tool in await serveur.list_tools()}
    with pytest.raises(Exception) as refus:
        await serveur.call_tool("get_customer_order_history", {"customer_id": "C-1"})
    await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert — E4 : le catalogue est la première défense ; E5 : tout est journalisé
    assert catalogue == {
        "search_documents",
        "lookup_by_reference",
        "ask_database",
        "get_stock",
        "get_order_status",
    }
    assert json.loads(str(refus.value))["error_code"] == "UNAUTHORIZED_TOOL"
    decisions = [ligne["decision"] for ligne in lignes_journal(journal)]
    assert decisions == ["deny", "allow"]


async def test_poste_de_vente_recoit_des_citations_sans_texte_redige(gateway):
    # Arrange
    serveur = gateway("sales")

    # Act
    resultat = await serveur.call_tool("answer_question", {"query": "tension de REF-8842 ?"})

    # Assert — E1 : des sources, jamais une réponse rédigée par le serveur
    rendu = json.dumps(resultat, default=str)
    assert "citations" in rendu
    assert "REF-8842" in rendu
    assert "La tension nominale est" not in rendu  # aucun texte rédigé ne transite


async def test_ide_dev_execute_du_sql_mais_ne_peut_pas_en_generer(gateway):
    # Arrange
    serveur = gateway("dev")

    # Act
    catalogue = {tool.name for tool in await serveur.list_tools()}
    await serveur.call_tool("run_sql_query", {"sql": "SELECT 1", "profile": "dev"})
    with pytest.raises(Exception) as refus:
        await serveur.call_tool("ask_database", {"question": "stock ?", "profile": "dev"})

    # Assert — l'invisibilité n'est pas la seule protection : l'appel forcé est refusé
    assert "run_sql_query" in catalogue
    assert "ask_database" not in catalogue
    assert json.loads(str(refus.value))["error_code"] == "UNAUTHORIZED_TOOL"


async def test_une_question_hors_corpus_est_une_erreur_typee(gateway):
    # Arrange
    serveur = gateway("sales")

    # Act
    with pytest.raises(Exception) as refus:
        await serveur.call_tool("answer_question", {"query": "information absente du corpus"})

    # Assert — E1 : jamais une réponse plausible de substitution
    assert json.loads(str(refus.value))["error_code"] == "NOT_FOUND_IN_CORPUS"


async def test_un_appel_sans_token_ne_voit_rien_et_ne_peut_rien(gateway, journal):
    # Arrange
    serveur = gateway(None)

    # Act
    catalogue = await serveur.list_tools()
    with pytest.raises(Exception) as refus:
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert
    assert catalogue == []
    assert json.loads(str(refus.value))["error_code"] == "UNAUTHENTICATED"
    assert lignes_journal(journal)[0]["decision"] == "deny"


async def test_un_backend_injoignable_donne_une_erreur_typee(gateway, monkeypatch):
    # Arrange — le port RAG tombe en panne réseau
    from app.domain.errors import BackendUnavailableError

    serveur = gateway("sales")

    async def tombe(*args: object, **kwargs: object) -> dict:
        raise BackendUnavailableError("corr-acceptance")

    monkeypatch.setattr("app.infrastructure.stub.rag_stub.RagStub.answer", tombe)

    # Act
    with pytest.raises(Exception) as refus:
        await serveur.call_tool("answer_question", {"query": "tension ?"})

    # Assert — le client reçoit un code stable, pas une trace d'exception
    charge = json.loads(str(refus.value))
    assert charge["error_code"] == "BACKEND_UNAVAILABLE"
    assert "Traceback" not in charge["message"]
```

- [ ] **Step 3: Lancer les tests**

Run: `pytest tests/acceptance -v`
Expected: PASS (6 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance
git commit -m "test(mcp): ajoute les scénarios d'acceptance par persona"
```

---

## Task 17: Test d'exhaustivité — le verrou de la gouvernance

Sans lui, la structure choisie (catalogue + fonctions) ne tient pas : un tool ajouté sans droit déclaré passerait inaperçu.

**Files:**
- Test: `tests/unit/test_exhaustivite.py`

**Interfaces:**
- Consumes: `CATALOG_BY_NAME` (t3), `load_access_matrix` (t5), `build_server` (t13), `RagHttpClient.DELEGATED_TO_STUB` (t14).

- [ ] **Step 1: Écrire le test**

`tests/unit/test_exhaustivite.py` :

```python
from pathlib import Path

from app.api.server import build_server
from app.domain.catalog import CATALOG_BY_NAME
from app.infrastructure.http.rag_client import RagHttpClient
from app.infrastructure.matrix.yaml_loader import load_access_matrix

MATRICE = Path(__file__).resolve().parents[2] / "access_matrix.yaml"


async def test_tools_enregistres_et_catalogue_coincident():
    # Act
    enregistres = {tool.name for tool in await build_server().list_all_tools()}

    # Assert
    assert enregistres == set(CATALOG_BY_NAME)


def test_tout_tool_de_la_matrice_existe_au_catalogue():
    # Arrange
    matrix = load_access_matrix(MATRICE)

    # Act
    cites = {tool for entree in matrix.profiles.values() for tool in entree.tools}

    # Assert — un droit accordé à un tool inexistant est une erreur de matrice
    assert cites <= set(CATALOG_BY_NAME)


def test_tout_tool_du_catalogue_est_arbitre_par_au_moins_un_profil():
    # Arrange
    matrix = load_access_matrix(MATRICE)
    cites = {tool for entree in matrix.profiles.values() for tool in entree.tools}

    # Assert — un tool que personne ne peut appeler est un oubli de matrice
    assert set(CATALOG_BY_NAME) - cites == set()


def test_les_delegations_au_stub_sont_exactement_celles_attendues():
    # Assert — une délégation oubliée après l'arrivée d'un endpoint casse ici
    assert RagHttpClient.DELEGATED_TO_STUB == frozenset(
        {"search", "lookup", "document_metadata", "confidence", "document_types"}
    )
```

- [ ] **Step 2: Lancer le test**

Run: `pytest tests/unit/test_exhaustivite.py -v`
Expected: PASS (4 tests).

Si `test_tout_tool_du_catalogue_est_arbitre_par_au_moins_un_profil` échoue, c'est que la matrice de `MCP.md` §6.4 laisse un tool sans aucun profil : le signaler plutôt que d'inventer un droit.

- [ ] **Step 3: Vérifier la suite complète et le typage**

```bash
pytest -m "not live"
mypy app
cd .. && ruff check . && ruff format --check .
```

Expected: tout vert. Corriger avant de continuer.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_exhaustivite.py
git commit -m "test(mcp): verrouille la cohérence catalogue, matrice et tools enregistrés"
```

---

## Task 18: Documentation du projet

**Files:**
- Modify: `README.md`
- Modify: `.claude/rules/mcp-primitives.md`
- Modify: `.claude/commands/new-tool.md`
- Create: `.claude/rules/testing-pytest.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces: une documentation à jour du serveur réellement construit.

- [ ] **Step 1: Corriger `README.md`**

Le README décrit 12 tools et un `run_sql_query` génératif — en retard sur `MCP.md`. Trois corrections :

1. §3 « Catalogue des tools » : passer à 13 lignes, ajouter `ask_database` (Génératif (SQL), `question`/`profile`, backend `text2sql-ai`), et corriger `run_sql_query` en « Exécution (SQL) », entrées `sql`/`profile`, backend `sorabelsql-api`.
2. §4 : remplacer le tableau des profils par celui de `access_matrix.yaml` (support 5, sales 10, dev 7) et ajouter une phrase : `ask_database` génère, `run_sql_query` exécute, le serveur ne les enchaîne jamais.
3. §2 : le diagramme dit « 12 tools » → « 13 tools ».

- [ ] **Step 2: Remplir `.claude/rules/mcp-primitives.md`**

Remplacer le TODO par : le format de `access_matrix.yaml` (les quatre clés par profil), la convention `@mcp.tool()` (la docstring **est** la description lue par le LLM ; consignes de priorité obligatoires sur les tools figés), les deux barrières et où elles vivent (`GovernedFastMCP` / `resolve_collections`), et la règle : tout nouveau tool doit apparaître dans `domain/catalog.py`, dans `access_matrix.yaml`, et passer `tests/unit/test_exhaustivite.py`.

- [ ] **Step 3: Écrire `.claude/commands/new-tool.md`**

Remplacer le squelette par la procédure réelle : ajouter le `ToolDescriptor` dans `app/domain/catalog.py`, la fonction `@server.tool()` avec sa docstring dans `app/api/tools/rag.py` ou `sql.py`, la méthode correspondante sur le port et sur le stub, l'entrée dans `access_matrix.yaml` pour chaque profil concerné, et lancer `pytest tests/unit/test_exhaustivite.py`.

- [ ] **Step 4: Écrire `.claude/rules/testing-pytest.md`**

Décrire les trois niveaux réellement en place :

```markdown
# Tests — mcp

## Organisation

​```
tests/
├── unit/          # domain/ + application/ + adapters isolés, aucun I/O réel
├── integration/    # adapters contre une vraie dépendance : serveur HTTP, JWKS, fichiers
├── acceptance/     # scénarios par persona, serveur assemblé, aucun monkeypatch interne
└── conftest.py
​```

## Règles

- Les tests unitaires ne mockent que des **ports**, jamais un détail d'infrastructure.
- Les tests d'intégration n'utilisent aucun mock de transport : un vrai serveur HTTP
  (`uvicorn` sur port éphémère) sert la doublure du contrat distant. Ne jamais importer
  l'application d'un autre projet de la solution : les paquets `app` entrent en collision.
- Les tests d'acceptance passent par le serveur assemblé et posent l'identité dans les
  `ContextVar`, comme le fait `AuthContextMiddleware` — jamais d'accès aux objets internes.
- Convention Arrange / Act / Assert, avec commentaires de section dès que le test dépasse
  quelques lignes.
- Le marqueur `live` désigne un test nécessitant un backend réellement en écoute ; il est
  sauté par défaut et lancé par `pytest -m live`.
```

- [ ] **Step 5: Référencer la règle depuis `CLAUDE.md`**

Ajouter sous `@.claude/rules/mcp-primitives.md` la ligne `@.claude/rules/testing-pytest.md`.

- [ ] **Step 6: Vérifier la suite complète une dernière fois**

```bash
pytest -m "not live"
mypy app
cd .. && ruff check . && ruff format --check .
```

- [ ] **Step 7: Commit**

```bash
git add README.md CLAUDE.md .claude
git commit -m "docs(mcp): aligne le README et les règles sur le serveur implémenté"
```

---

## Ce que ce plan ne fait pas

**Écart assumé avec l'arborescence de la spec §4** : `app/api/schemas/` n'est pas créé.
Ce répertoire existe, dans la règle hexagonale, pour empêcher qu'une entité de `domain/`
soit exposée telle quelle — or aucune ne franchit la frontière ici : les charges utiles
des tools sont des `dict` assemblés par les adapters, et le schéma d'entrée de chaque
tool est dérivé par le SDK depuis la signature typée de la fonction. Créer des DTO
Pydantic qui se contenteraient de recopier ces `dict` n'ajouterait aucune protection. Si
un tool en vient à renvoyer une entité de domaine, le répertoire redevient obligatoire.

Rappel du §14 de la spec, pour qu'aucune tâche ne dérive : ni `api-gateway`, ni realm
Keycloak dans `sorabel-idp`, ni endpoints de briques dans `rag-hybride`, ni masquage de
colonnes (porté par `sorabelsql-api`), ni Dockerfile. Les adapters HTTP `text2sql-ai` et
`sorabelsql-api` lèvent volontairement `NotImplementedError` : ces services n'ont pas une
ligne de code.
