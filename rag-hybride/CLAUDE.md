# rag-hybride

@../CLAUDE.md
@../.claude/rules/python-hexagonal.md

## Contexte

Backend Python (FastAPI, archi hexagonale) exposant le **RAG documentaire hybride** de
la solution Sorabel : ingestion du corpus technique, retrieval hybride (dense + BM25),
reranking, génération de réponse citée. Consommé par `mcp` via REST interne — jamais
appelé directement par un client final.

Exigences servies : **E1** (citations systématiques, refus si non pertinent), **E2**
(lookup exact par référence + recherche en langage naturel), **E6** (évaluation du gain
hybride vs dense seul).

## Stack

- FastAPI + Pydantic
- PostgreSQL + pgvector (dense) + `tsvector` (sparse/BM25)
- Azure OpenAI (embeddings + génération)
- Pytest + Testcontainers
- Docker (déploiement local)

## Règles locales

@.claude/rules/rag-architecture.md
@.claude/rules/testing-pytest.md

## Commandes utiles

Voir `.claude/commands/` : `/eval-retrieval`, `/new-endpoint`.

## Point d'attention

`rag-hybride` ne fait **aucune** vérification de matrice d'accès (profil × collection) —
c'est la responsabilité d'`authorization-gateway` en amont. Ce projet suppose que tout
appel qu'il reçoit est déjà autorisé.
