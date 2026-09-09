# Niveau 4 — acceptance / E2E (`mcp`)

**Ce dossier est vide : le niveau 4 n'est pas implémenté.** `make test-e2e`
échoue explicitement tant que c'est le cas, plutôt que de passer au vert sans
rien affirmer (cf. `../../../.claude/rules/testing-pyramid.md`, § « Ce que
Claude doit faire »).

## Ce qui appartient à ce dossier

Le niveau 4 démarre le service **tel qu'il sera déployé** et prouve qu'il se
configure, se connecte et répond. Ce que les niveaux 1‑3 ne prouvent pas :
`tests/contract/` assemble le serveur en mémoire avec ses trois ports backend
doublés — il ne dit rien du packaging ni de la configuration réelle.

Un scénario de ce dossier doit donc, au minimum :

- démarrer `mcp` avec sa vraie configuration (`.env` de la racine, matrice
  `access_matrix.yaml` réelle) ;
- obtenir un vrai JWT auprès de `sorabel-idp` (Keycloak), pas une doublure de
  `TokenVerifierPort` ;
- appeler `list_tools`/`call_tool` à travers `api-gateway`, jamais en direct
  (anti-pattern : aucun lien direct `mcp` ↔ backends) ;
- vérifier qu'un appel refusé est journalisé comme un appel normal (E5).

## Ce qui manque pour l'écrire

`mcp` n'a pas de Dockerfile propre (cf.
`../../../.claude/rules/makefile-conventions.md`, § « Exception — outillage
Python partagé »), et le `docker-compose.yml` de la racine ne contient
aujourd'hui que `postgres` — dont `mcp` ne se sert pas. La cible `test-e2e`
démarre ce compose parce que c'est ce que prescrit `testing-pyramid.md` pour les
projets Python à outillage partagé, mais **cela ne suffit pas** : tant que
`sorabel-idp`, `api-gateway` et les trois backends n'y sont pas déclarés, il n'y
a pas de dépendance réelle à laquelle se connecter.

Prérequis, dans l'ordre :

1. déclarer `sorabel-idp` et `api-gateway` dans le `docker-compose.yml` racine ;
2. décider comment `mcp` y est démarré (il n'a pas d'image à lui) ;
3. écrire les scénarios ici, puis retirer ce paragraphe.

En attendant, ne pas compenser en gonflant `tests/contract/` : un scénario qui
ne démarre pas le service tel qu'il sera déployé reste du niveau 3, quel que
soit le dossier qui le contient.
