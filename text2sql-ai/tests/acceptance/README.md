# Niveau 4 — acceptance / E2E (`text2sql-ai`)

**Ce dossier est vide : le niveau 4 n'est pas implémenté.** `make test-e2e`
échoue explicitement tant que c'est le cas, plutôt que de passer au vert sans
rien affirmer (cf. `../../../.claude/rules/testing-pyramid.md`, § « Ce que
Claude doit faire »).

## Ce qui appartient à ce dossier

`text2sql-ai` est le projet Python le mieux placé pour porter un vrai niveau 4 :
contrairement à `mcp` et `rag-hybride`, il a son **propre Dockerfile** et son
propre `docker-compose.yml` (cf. `../../../.claude/rules/makefile-conventions.md`,
§ « Exception — `text2sql-ai` »), parce qu'il doit être déployable et scalable
indépendamment. La cible `test-e2e` construit donc l'image et démarre le
conteneur — la preuve de packaging que `mcp` et `rag-hybride` ne peuvent pas
apporter.

Un scénario de ce dossier doit donc, au minimum :

- construire l'image et démarrer le conteneur, et vérifier qu'il passe son
  `healthcheck` — c'est déjà la moitié de ce que le niveau 4 doit prouver ;
- appeler `/api/v1/.../generate` sur le conteneur, avec la configuration réelle
  (`schema_context.md` chargé au démarrage, filtrage par profil actif) ;
- vérifier que le SQL renvoyé est strictement lecture seule (E3) et ne
  référence aucune table hors périmètre du profil ;
- vérifier qu'une question insoluble avec le schéma filtré produit une erreur
  structurée, pas une requête approximative.

## Ce qui manque pour l'écrire

La seule vraie question ouverte : **Azure OpenAI**. Le conteneur a besoin d'un
endpoint et d'une clé pour générer. Trois issues possibles, à trancher :

1. appeler le vrai Azure OpenAI (le niveau 4 prouve le plus, mais devient
   coûteux, lent et non déterministe) ;
2. pointer le conteneur vers un double d'API servi par le compose (déterministe,
   mais on ne teste plus la vraie intégration LLM) ;
3. limiter le niveau 4 au démarrage + healthcheck + rejet d'une requête
   invalide, sans génération réelle (le plus modeste, mais déjà plus que zéro —
   il prouve que l'image se construit et se configure).

Rappel E3 : aucun test de ce dossier n'exécute le SQL généré. `text2sql-ai`
génère, `sorabelsql-api` exécute.
