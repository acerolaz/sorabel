# Tests — rag-hybride

## Organisation

```
tests/
├── unit/          # domain/ + application/, tous les ports mockés
├── integration/    # infrastructure/, via Testcontainers (Postgres+pgvector réel)
└── conftest.py     # fixtures partagées
```

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
- **Integration tests** : utilisent **Testcontainers** pour lancer un Postgres/pgvector éphémère — jamais de mock sur la couche `infrastructure/postgres/`, sinon le test ne couvre rien de réel.
- Un cas de fusion RRF, un cas de chunking par section, un cas de refus (E1) sont couverts en priorité — ce sont les points les plus sensibles du pipeline.
- Nommage des tests : `test_<comportement>_<condition>` en français ou anglais, cohérent dans tout le fichier.

## Ce que Claude doit faire

- Ne jamais écrire un test d'intégration Postgres avec un mock à la place de Testcontainers.
- Toujours proposer un test pour toute nouvelle règle métier du domaine (fusion, seuil de refus, chunking).
- Signaler si un test unit dépend implicitement d'un état partagé entre tests (pas d'isolation).
