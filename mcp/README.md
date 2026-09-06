# mcp — Sorabel Data Gateway (serveur MCP)

> Serveur MCP unifié exposant en **Tools** l'accès gouverné aux documents (RAG) et aux données (Text-to-SQL) de Sorabel, pour plusieurs clients (bot Slack Support, poste de vente, IDE développeur).

## 1. Rôle

Ce serveur est le **point d'orchestration unique** du système : il ne stocke ni n'indexe rien lui-même, il expose un catalogue de tools, vérifie l'identité et les droits (via [`sorabel-idp`](../sorabel-idp/README.md)), applique la matrice d'accès, puis délègue aux backends (`rag-hybride` pour la recherche documentaire, `text2sql-ai` pour la génération SQL, `sorabelsql-api` pour l'exécution SQL gouvernée) — jamais de logique métier ni de génération de texte ici.

> Analogie .NET : un contrôleur d'API qui n'implémente aucune logique métier — il valide l'`[Authorize]`, résout la policy, puis appelle les services applicatifs injectés.

## 2. Architecture

```mermaid
flowchart LR
    CLI["👥 Clients<br/>(Slack, Poste Vente, IDE)"] -->|"list_tools / call_tool<br/>Bearer JWT"| GW["🌐 API Gateway<br/>(routage seul)"]
    GW <--> IDP["🔑 sorabel-idp<br/>(Keycloak)"]
    GW <--> M

    subgraph M["🖥️ mcp — Serveur MCP"]
        Verif["✅ Vérif JWT (JWKS)"] --> RBAC{"🔀 Matrice d'accès<br/>profil × tool"}
        RBAC --> Tools["🛠️ 13 tools"]
        RBAC -->|Refusé| Err["🚫 isError typé"]
    end

    GW <-->|"REST interne"| SQL["🗄️ sorabelsql-api<br/>(exécution)"]
    GW <-->|"REST interne"| T2S["🤖 text2sql-ai<br/>(génération)"]
    GW <-->|"REST interne"| RAG["🧠 rag-hybride"]

    classDef client fill:#4B5563,stroke:#1F2937,color:#fff,font-weight:bold
    classDef mcp fill:#1D4ED8,stroke:#1E3A8A,color:#fff,font-weight:bold
    classDef risk fill:#FCA5A5,stroke:#B91C1C,color:#7F1D1D
    class CLI client
    class M,Verif,RBAC,Tools mcp
    class Err risk
```

*Convention couleurs reprise dans tous les docs Sorabel : gris = agents/clients, bleu = composants MCP, vert = flux légitime, rouge = friction/risque.*

## 3. Catalogue des tools

| Tool | Type | Entrées | Backend appelé |
|---|---|---|---|
| `answer_question` | Composite (RAG) | `query` | `rag-hybride` (via 3 briques) |
| `search_documents` | Brique (RAG) | `query`, `top_k`, `collections?` | `rag-hybride` |
| `lookup_by_reference` | Brique (RAG) | `product_ref`, `collections?` | `rag-hybride` |
| `get_document_metadata` | Brique (RAG) | `doc_id` | `rag-hybride` |
| `check_answer_confidence` | Brique (RAG) | `query` | `rag-hybride` |
| `list_document_types` | Brique (RAG) | — | `rag-hybride` |
| `ask_database` | Génératif (SQL) | `question`, `profile` | `text2sql-ai` |
| `run_sql_query` | Exécution (SQL) | `sql`, `profile` | `sorabelsql-api` |
| `get_stock` | Figé (SQL) | `product_ref` | `sorabelsql-api` |
| `get_order_status` | Figé (SQL) | `order_id` | `sorabelsql-api` |
| `get_customer_order_history` | Figé (SQL) | `customer_id`, `limit` | `sorabelsql-api` |
| `get_schema_info` | Introspection (SQL) | `profile`, `keyword?` | `sorabelsql-api` |
| `get_query_history` | Audit (SQL) | `profile`, `limit` | `sorabelsql-api` |

`answer_question` orchestre en interne 3 briques mais **ne génère aucun texte** : c'est le LLM du client qui rédige la réponse à partir du résultat agrégé (chunks + métadonnées + catalogue). `ask_database` génère du SQL sans jamais l'exécuter ; `run_sql_query` exécute un SQL déjà écrit sans jamais en générer — le serveur ne les enchaîne jamais lui-même.

> Le paramètre `profile` présent dans certaines signatures (`ask_database`, `run_sql_query`, `get_schema_info`, `get_query_history`) fait partie du contrat publié mais n'est jamais utilisé pour décider : le profil effectif est toujours celui du token vérifié (`Identity.profile`), jamais celui déclaré par l'appelant.

## 4. Sécurité — défense en profondeur

1. **Entrée du serveur** : `list_tools()` ne renvoie que les tools autorisés pour le profil du token (`sorabel_profile`) — un tool absent du catalogue ne peut pas être appelé, ni halluciné.
2. **Dans chaque tool** : contrôle fin (tables réellement interrogées, masquage de colonnes), délégué au backend concerné.

| Profil | Tools autorisés | Collections RAG | Tables SQL | Colonnes masquées |
|---|---|---|---|---|
| `support` (5 tools) | `search_documents`, `lookup_by_reference`, `ask_database`, `get_stock`, `get_order_status` | `procedure_sav`, `manuel` | `products`, `stock`, `orders` | `purchase_price`, `margin` |
| `sales` (10 tools) | `answer_question`, `search_documents`, `lookup_by_reference`, `get_document_metadata`, `check_answer_confidence`, `list_document_types`, `ask_database`, `get_stock`, `get_order_status`, `get_customer_order_history` | `datasheet`, `manuel`, `procedure_sav` | `products`, `stock`, `orders` | `purchase_price`, `margin` |
| `dev` (7 tools) | `search_documents`, `get_document_metadata`, `check_answer_confidence`, `list_document_types`, `get_schema_info`, `get_query_history`, `run_sql_query` | `datasheet`, `manuel`, `procedure_sav` | `products`, `stock`, `orders` | `purchase_price`, `margin` |

Tableau dérivé de `access_matrix.yaml`, seule autorité — ne pas le reparaphraser ailleurs. `ask_database` génère, `run_sql_query` exécute : le serveur ne les enchaîne jamais.

## 5. Primitives MCP utilisées

Seule la primitive **Tools** est exposée. Pas de **Resources** (toute lecture doit passer par la matrice d'accès + audit, que les Resources ne portent pas nativement) ni de **Prompts** (candidat futur : template guidant `run_sql_query` vs tools figés).

## 6. Gestion des erreurs

Chaque refus/échec renvoie un `CallToolResult` avec `isError: true` + un code stable (`UNAUTHENTICATED`, `UNAUTHORIZED_TOOL`, `UNAUTHORIZED_COLLECTION`, `UNAUTHORIZED_TABLE`, `NOT_FOUND_IN_CORPUS`, `SCHEMA_MISMATCH`, `BACKEND_UNAVAILABLE`) — jamais un texte que le LLM client pourrait paraphraser comme une réponse valide.

## 7. Dépendances

- [`sorabel-idp`](../sorabel-idp/README.md) — authentification et profil (claim `sorabel_profile`)
- [`rag-hybride`](../rag-hybride/README.md) — ingestion + hybrid retrieval documentaire. Seul `answer_question` lui parle réellement aujourd'hui (`POST /api/v1/query`) ; les autres briques RAG restent déléguées à un stub interne faute d'endpoint dédié exposé côté `rag-hybride` (voir `docs/superpowers/specs/2026-09-04-mcp-server-design.md` §12).
- [`text2sql-ai`](../text2sql-ai/README.md) — génération seule de SQL lecture seule, pour `ask_database`
- [`sorabelsql-api`](../sorabelsql-api/README.md) — exécution SQL gouvernée (garde-fous, masquage de colonnes), pour `run_sql_query` et les tools figés

## 8. Stack technique

- Python, convention `@mcp.tool()` (FastMCP)
- Vérification JWT via JWKS avec cache local (`sorabel-idp`/Keycloak) en production, ou via une clé locale partagée (HS256, dev uniquement) selon `MCP_TOKEN_VERIFIER`
- Matrice d'accès versionnée en YAML (`access_matrix.yaml`), résolue par profil

## 9. Glossaire

| Terme | Définition |
|---|---|
| Tool composite | Tool orchestrant plusieurs briques sans générer de texte lui-même |
| Brique | Tool élémentaire, appelable seul ou via un composite |
| Matrice d'accès | Table profil × tool × collections/tables, appliquée en deux points |
| `isError` | Champ du résultat de tool signalant un échec, à traiter avant toute rédaction LLM |

---
*Document généré à partir des fiches de cadrage `MCP.md`, `Advanced_RAG.md`, `Text2SQL_Sorabel.md`.*
