# Sécurité — Solution Sorabel

## Secrets

- **Jamais** de secret en clair dans le code, les commits, ou un `CLAUDE.md`.
- Développement local : `.env` (gitignored), chargé via `pydantic-settings` (Python) ou `IConfiguration` (C#).
- Un `.env.example` (sans valeurs réelles) est versionné pour documenter les variables attendues.
- Cible cible finale : Azure Key Vault — le `.env` local n'est qu'un fallback de dev.

## Authentification / Autorisation

- Toute API interne (sauf `sorabel-idp` lui-même) valide un JWT émis par Keycloak (claim `sorabel_profile`).
- La matrice d'accès (profil × tool/endpoint × données) est **centralisée**, jamais dupliquée en dur dans plusieurs projets — cf. `mcp` (`api-gateway` ne fait que router, sans logique d'autorisation).
- `api-gateway` est un pur relais sans inspection (passe le JWT tel quel) ; les services en aval (`mcp`, `sorabelsql-api`) valident le JWT et appliquent les contrôles d'accès selon le profil.

## Journalisation & audit

- Tout appel (autorisé ou refusé) est journalisé : horodatage, identité, ressource demandée, décision.
- Ne jamais logger un contenu métier complet en clair (résultats de requête, réponses générées) — logger des métadonnées (nombre de lignes, latence), pas le payload.

## Ce que Claude doit faire

- Refuser de générer du code avec un secret en dur, même à titre d'exemple — proposer une variable d'environnement à la place.
- Signaler si une route/tool censé être protégé ne vérifie pas le JWT/la matrice d'accès.
- Ne jamais désactiver une vérification de sécurité "pour tester rapidement" sans le signaler explicitement.
