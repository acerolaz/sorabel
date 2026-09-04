# Primitives MCP — catalogue et matrice d'accès

Seule la primitive **Tools** est exposée par ce serveur (voir `README.md` §5) —
cette règle ne couvre donc que les tools, leur enregistrement et leur gouvernance.

## Format de `access_matrix.yaml`

La matrice (`mcp/access_matrix.yaml`) est la **seule autorité** sur les droits :
aucun droit n'est codé en dur ailleurs, aucun document ne fait que la
reparaphraser. Elle a un `version` entier puis un mapping `profiles`, chaque
profil déclarant exactement quatre clés (`app/infrastructure/matrix/yaml_loader.py`
les valide au démarrage — fail closed : matrice absente, illisible ou mal
formée → le serveur ne démarre pas) :

```yaml
profiles:
  <nom_profil>:
    tools: [...]           # noms exacts des tools de app/domain/catalog.py
    rag_collections: [...] # périmètre RAG accordé (peut être vide : [])
    sql_tables: [...]      # périmètre SQL accordé (peut être vide : [])
    masked_columns: [...]  # colonnes masquées, transmises au backend d'exécution
```

- `tools` : chaque nom doit exister dans `CATALOG_BY_NAME` (`app/domain/catalog.py`)
  — un tool inconnu du catalogue fait échouer le chargement.
- `rag_collections` / `sql_tables` : le périmètre par défaut appliqué à ce
  profil. Une demande explicite du client ne peut que le *restreindre*,
  jamais l'élargir (barrière 2, voir plus bas) ; une liste vide est un
  périmètre valide de zéro ressource, distinct de l'absence de demande.
- `masked_columns` : colonnes à masquer, transmises telles quelles au backend
  d'exécution (`sorabelsql-api`) — `mcp` ne les masque pas lui-même, il les
  relaie (E5).

Aujourd'hui, les trois profils (`support`, `sales`, `dev`) partagent
exactement les mêmes `sql_tables` et `masked_columns` ; seuls `tools` et
`rag_collections` les différencient (voir §12 de la spec de conception pour
la conséquence sur les tests).

## Convention `@server.tool()`

Chaque tool est une fonction async enregistrée via `@server.tool()` (FastMCP),
dans `app/api/tools/rag.py` (6 tools documentaires) ou `app/api/tools/sql.py`
(7 tools données). Aucune logique métier dans ces fonctions : chacune résout
son périmètre via la barrière 2 (`resolve_collections`/`resolve_tables`) puis
délègue au port (`RagPort`, `Text2SqlPort`, `SqlExecutionPort`).

**La docstring de chaque tool *est* la description lue par le LLM client**
lors de `list_tools` — ce n'est pas de la documentation interne. Elle porte
donc, obligatoirement :

- ce que fait le tool, en une phrase ;
- des consignes de priorité explicites sur les tools figés, en MAJUSCULES
  (`À utiliser EN PRIORITÉ...`, `NE PAS utiliser ask_database si ce tool
  suffit`, `CRITICAL: n'utilise que les noms...`) — c'est ce qui évite qu'un
  LLM appelle `ask_database` (lent, non déterministe) là où `get_stock` ou
  `get_order_status` suffisent ;
- pour `answer_question` : la consigne qu'il **ne rédige aucune réponse** et
  que le refus `NOT_FOUND_IN_CORPUS` ne doit jamais être reformulé en réponse
  plausible (E1) ;
- la description de chaque `Args:`.

Ces docstrings tiennent sur une seule ligne (mise en forme du texte lu par le
modèle) — d'où le `# noqa: E501` sur chacune plutôt qu'un retour à la ligne
qui la romprait.

## Les deux barrières (spec §4.2)

1. **Barrière 1 — catalogue** : `GovernedFastMCP` (`app/api/governance.py`)
   surcharge `list_tools()` (ne rend que le sous-ensemble autorisé du profil,
   catalogue vide sans token valide) et `call_tool()` (refuse en
   `UNAUTHENTICATED`/`UNAUTHORIZED_TOOL` **avant** d'atteindre la fonction du
   tool). Un tool absent du catalogue projeté ne peut être ni vu ni appelé.
2. **Barrière 2 — périmètre** : `resolve_collections`/`resolve_tables`
   (`app/application/use_cases/forward_to_backend.py`), appelées depuis
   chaque fonction tool. Le périmètre transmis au backend vient toujours de
   `Scope` (résolu par la matrice pour le profil authentifié) ; une demande
   explicite du client (`collections=...`) ne peut que le restreindre — une
   seule valeur hors périmètre invalide la demande entière
   (`UNAUTHORIZED_COLLECTION`/`UNAUTHORIZED_TABLE`), jamais une intersection
   silencieuse.

## Ajouter un nouveau tool

Tout nouveau tool doit :

1. apparaître dans `app/domain/catalog.py` (`CATALOG`) ;
2. être enregistré via `@server.tool()` dans `app/api/tools/rag.py` ou `sql.py` ;
3. avoir une entrée dans `access_matrix.yaml` pour chaque profil qui doit
   pouvoir l'appeler ;
4. faire passer `tests/unit/test_exhaustivite.py` — ce test verrouille que le
   registre SDK, `CATALOG_BY_NAME` et `access_matrix.yaml` coïncident
   exactement (aucun tool enregistré sans entrée de catalogue, aucune entrée
   de matrice pointant un tool inexistant, aucun tool du catalogue orphelin
   de toute autorisation).

Voir `.claude/commands/new-tool.md` pour la procédure complète, fichier par
fichier.
