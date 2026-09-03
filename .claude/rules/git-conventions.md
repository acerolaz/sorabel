# Conventions Git — Solution Sorabel

## Commits (Conventional Commits)

```
<type>(<scope>): <description courte>

[corps optionnel]
```

| Type | Usage |
|---|---|
| `feat` | Nouvelle fonctionnalité |
| `fix` | Correction de bug |
| `refactor` | Changement sans impact fonctionnel |
| `test` | Ajout/modification de tests |
| `docs` | Documentation uniquement |
| `chore` | Tâches techniques (deps, config) |

`<scope>` = nom du projet concerné (`rag-hybride`, `mcp`, `sorabelsql-api`, ...).

Exemples :
```
feat(rag-hybride): ajoute la fusion RRF dense/sparse
fix(mcp): corrige le filtrage list_tools par profil
```

## Branches

```
<type>/<scope>/<description-courte>
```

Exemples : `feat/rag-hybride/hybrid-retrieval`, `fix/mcp/auth-token-refresh`.

## Pull Requests

- Une PR = un scope (un seul projet, sauf changement transverse `.claude/` racine).
- Titre = même format que le commit principal.
- Description : contexte, changements, comment tester.
- Squash merge par défaut — l'historique de la branche de travail n'est pas conservé sur `main`.

## Ce que Claude doit faire

- Ne jamais commit directement sur `main`.
- Toujours proposer un message de commit respectant ce format avant de committer.
- Ne jamais inclure de métadonnées d'IA dans les messages de commit.
