# Génération SQL lecture seule — text2sql-ai

Génération à partir du schéma commenté filtré par profil, **jamais d'exécution**.

## Refus hors-schéma

Deux niveaux, et deux seulement :

1. **Déterministe, sans LLM** : si le schéma filtré par profil est vide, le use case
   refuse immédiatement (`refused_out_of_schema`).
2. **Signalé par le modèle** : si le schéma fourni ne contient pas la donnée demandée,
   le modèle pose `is_out_of_schema` dans son JSON structuré, et le use case en fait un
   refus terminal. Aucun contrôle lexical sur la question — un tel contrôle ne peut pas
   juger une couverture sémantique et refusait des questions françaises légitimes.

## Instructions système garanties

`app/domain/prompt.py` assemble le prompt et doit toujours y faire figurer :

- `READONLY_INSTRUCTION` — cadrage lecture seule, `SELECT` uniquement.
- `CRITICAL_INSTRUCTION` — interdiction d'inventer une table ou une colonne.
- `RESPONSE_FORMAT_INSTRUCTION` — quand poser `is_ambiguous`, quand poser
  `is_out_of_schema`, et ce que doit contenir `intent_reformulation`. Ces trois champs
  pilotent des branches entières du pipeline : le prompt doit les décrire, le
  `response_format` seul ne suffit pas.

> TODO : détailler le format du schéma statique commenté injecté au LLM et les règles de
> filtrage par profil.
