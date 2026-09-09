# Niveau 4 — acceptance / E2E (`rag-hybride`)

**Ce dossier est vide : le niveau 4 n'est pas implémenté.** `make test-e2e`
échoue explicitement tant que c'est le cas, plutôt que de passer au vert sans
rien affirmer (cf. `../../../.claude/rules/testing-pyramid.md`, § « Ce que
Claude doit faire »).

## Ce qui appartient à ce dossier

Le niveau 4 démarre le service **tel qu'il sera déployé** et prouve qu'il se
configure, se connecte et répond. `tests/contract/` monte l'application en
mémoire avec ses adapters doublés : il ne dit rien du packaging, des migrations,
ni de la configuration réelle.

Un scénario de ce dossier doit donc, au minimum :

- démarrer l'application depuis son répertoire de travail avec le `.env` réel,
  contre le Postgres/pgvector du `docker-compose.yml` de la racine ;
- avoir joué les migrations Alembic sur cette base avant d'interroger quoi que
  ce soit ;
- ingérer un document, puis l'interroger, et vérifier que la réponse **cite ses
  sources** (E1) ;
- vérifier qu'une question hors corpus produit un refus structuré, pas une
  réponse fabriquée (E1).

## Ce qui manque pour l'écrire

C'est le projet où le niveau 4 est le plus proche : sa seule dépendance réelle,
Postgres/pgvector, est déjà déclarée dans le `docker-compose.yml` racine et la
cible `test-e2e` la démarre. Restent à décider :

1. comment l'application est lancée (uvicorn en sous-processus depuis la suite,
   ou démarrée hors pytest et jointe par URL) ;
2. quoi faire des dépendances externes réelles — embeddings et LLM (Azure
   OpenAI) : les appeler pour de vrai, ou pointer un double au niveau de la
   configuration, sachant qu'un double ici affaiblit ce que le niveau 4 prouve.

Point à ne pas confondre : `tests/integration/` utilise déjà Testcontainers et
donc Docker, mais ça reste du **niveau 2** — un adapter face à sa vraie
dépendance, pas le service tel qu'il sera déployé.
