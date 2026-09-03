# Conventions API — Solution Sorabel

Communes à toutes les API (FastAPI et ASP.NET), pour une cohérence de contrat côté clients.

## Format des réponses

- Succès : payload JSON direct, pas d'enveloppe superflue (`{ data: ... }` évité sauf pagination).
- Erreur : format uniforme

```json
{
  "error_code": "UNAUTHORIZED_TABLE",
  "message": "Accès non autorisé pour ce profil",
  "correlation_id": "..."
}
```

- `error_code` = code métier stable (PascalCase ou SCREAMING_SNAKE_CASE, cohérent par projet), jamais uniquement un code HTTP.
- `message` : jamais d'information confirmant l'existence d'une ressource non autorisée (pas de fuite d'info via l'erreur).

## Pagination

- Query params : `limit` (défaut raisonnable, max imposé), `offset` ou `cursor` selon le volume.
- Réponse paginée : `items`, `total` (si calculable sans coût), `next_cursor` le cas échéant.

## Versioning

- Préfixe de route : `/api/v1/...`
- Pas de breaking change sans incrément de version.

## Documentation

- FastAPI : Swagger/OpenAPI auto-généré (`/docs`) — docstrings des routes tenues à jour, c'est la doc de référence.
- ASP.NET : Swashbuckle/Swagger — mêmes exigences de description à jour.

## Nommage

- Routes en `snake_case` ou `kebab-case` selon la convention de chaque stack, mais cohérent à l'intérieur d'un même projet.
- Champs JSON : `snake_case` partout (y compris depuis les projets C#), pour une cohérence de contrat côté clients quel que soit le backend.
