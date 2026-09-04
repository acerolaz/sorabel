---
description: Scaffold un tool MCP + entrée matrice RBAC
---

# /new-tool

Procédure pour ajouter un tool au serveur MCP `mcp`, gouvernance comprise. Un
tool qui ne suit pas ces étapes dans l'ordre casse
`tests/unit/test_exhaustivite.py` (le verrou qui garantit que registre SDK,
catalogue et matrice coïncident) — voir `.claude/rules/mcp-primitives.md`.

1. **`app/domain/catalog.py`** — ajouter un `ToolDescriptor(name, family, backend)`
   au tuple `CATALOG` : `family` ∈ `"rag" | "sql"`, `backend` ∈
   `"rag" | "text2sql" | "sqlapi"`. C'est la source unique consommée par la
   matrice et par le filtrage de `list_tools` : un tool absent d'ici n'existe
   pour aucune des deux barrières.

2. **Le port** — si le tool a besoin d'une nouvelle opération backend, ajouter
   la méthode correspondante au `Protocol` concerné dans `app/domain/ports.py`
   (`RagPort`, `Text2SqlPort` ou `SqlExecutionPort`). Toute méthode qui rend
   des lignes métier SQL reçoit `masked_columns: Sequence[str]` ; toute
   méthode RAG/SQL qui rend une liste de ressources reçoit le périmètre résolu
   (`collections`/`tables`) — jamais choisi par l'appelant. `correlation_id`
   est systématique.

3. **Les doublures** — implémenter la méthode dans le(s) stub(s) concernés
   (`app/infrastructure/stub/rag_stub.py`, `text2sql_stub.py` ou
   `sqlapi_stub.py`), qui placent toujours `source: "stub"` dans leur retour.
   Aujourd'hui, seul `RagPort` a un adapter HTTP réel
   (`app/infrastructure/http/rag_client.py`, et seule sa méthode `answer()`
   parle vraiment à `rag-hybride` — le reste y est déjà délégué au stub, cf.
   `RagHttpClient.DELEGATED_TO_STUB`) ; `Text2SqlPort` et `SqlExecutionPort`
   n'ont pas d'adapter HTTP (`build_text2sql_port`/`build_sqlapi_port` lèvent
   `NotImplementedError` si `*_BACKEND=http`) — pas d'adapter réel à toucher
   pour un nouveau tool SQL tant que `text2sql-ai`/`sorabelsql-api` n'exposent
   pas l'endpoint correspondant.

4. **`app/api/tools/rag.py` ou `sql.py`** — ajouter la fonction `@server.tool()`
   dans `register_rag_tools` ou `register_sql_tools`. Aucune logique métier :
   `identity, scope, correlation_id = call_context()`, résoudre le périmètre
   via `resolve_collections`/`resolve_tables` si pertinent, puis déléguer au
   port. La **docstring est le contrat publié au LLM client** — voir
   `.claude/rules/mcp-primitives.md` § convention `@server.tool()` pour ce
   qu'elle doit obligatoirement porter (consignes de priorité en MAJUSCULES
   sur les tools figés, description de chaque `Args:`, une ligne).

5. **`access_matrix.yaml`** — ajouter le nom du tool à la clé `tools` de
   chaque profil qui doit pouvoir l'appeler. Un tool absent de tous les
   profils est un oubli détecté par l'étape suivante ; un tool cité par la
   matrice mais absent du catalogue l'est tout autant.

6. **Vérifier** :

   ```
   cd mcp
   ../.venv/Scripts/python.exe -m pytest tests/unit/test_exhaustivite.py -q
   ```

   Puis la suite complète (`../.venv/Scripts/python.exe -m pytest -q`) et
   `ruff check .` (depuis la racine du dépôt : `ruff check mcp/`) avant de
   proposer un commit.
