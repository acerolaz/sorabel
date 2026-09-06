# Pyramide de tests — Solution Sorabel

**Portée** : tous les projets développés en interne, C# comme Python (`api-gateway`,
`sorabelsql-api`, `mcp`, `rag-hybride`, `text2sql-ai`). **Exclus** : `sorabel-idp` (service
Keycloak configuré, pas développé) et `frontend` (stack non choisie).

Cette règle définit **quatre niveaux de test** et le critère d'appartenance à chacun. Elle
n'impose **pas** de proportions entre les niveaux : la forme de la pyramide dépend de la
nature du projet (voir « Forme attendue par projet »). Ce qui est exigé, c'est que les
quatre niveaux soient **couverts et outillés** dans chaque projet.

## Les quatre niveaux

| Niveau | Critère d'appartenance | Outillage C# | Outillage Python |
|---|---|---|---|
| **1 — Unitaire** | Aucune I/O, aucun framework, aucun conteneur. Teste le domaine pur. Durée : millisecondes. | xUnit | `pytest`, mocks des **ports** uniquement |
| **2 — Intégration technique** | Un adapter face à sa vraie dépendance ou à un double fidèle. Teste que l'implémentation d'un port fonctionne. | WireMock.Net (HTTP), Testcontainers (Postgres) | Postgres éphémère, `chromadb.EphemeralClient()`, `httpx.MockTransport` |
| **3 — Contrat / API** | L'application complète en mémoire, dépendances externes doublées. Vérifie le contrat HTTP exposé (routes, codes, format d'erreur). | `WebApplicationFactory` | `httpx.AsyncClient` contre `app` |
| **4 — Acceptance / E2E** | Le service réel avec ses vraies dépendances démarrées. Lent, exclu du cycle rapide. | `docker compose` + client HTTP | `docker compose` ou dépendances réelles de la racine |

### Ce qui distingue le niveau 1 du niveau 2

Un test qui touche un socket, un fichier, une base ou une horloge système **n'est pas
unitaire**, quel que soit le nom du fichier qui le contient. Le niveau 1 ne mocke que les
**ports** (`domain/ports.py` en Python, l'interface C# côté Domain/Application) — jamais un
détail d'implémentation d'infrastructure. Cette contrainte est déjà posée par
[[python-hexagonal]] et [[csharp-clean-architecture]] ; elle est ici la ligne de partage entre
les deux premiers niveaux.

### Ce qui distingue le niveau 3 du niveau 4

Le niveau 3 démarre l'application **en mémoire, dans le processus de test**, avec ses
backends doublés — il ne prouve rien sur le packaging ni sur la configuration réelle. Le
niveau 4 démarre le service **tel qu'il sera déployé** et prouve qu'il se configure, se
connecte et répond. Un projet dont seuls les niveaux 1–3 passent peut parfaitement être
incapable de démarrer.

## Cibles Makefile

Les niveaux 1 à 3 doivent tourner **sans Docker** et sur chaque commit ; le niveau 4 est
séparé car il démarre des conteneurs.

| Cible | Contenu |
|---|---|
| `make test` | Niveaux 1, 2 et 3 — rapide, sans Docker |
| `make test-e2e` | Niveau 4 uniquement — démarre les dépendances puis les arrête |

Voir [[makefile-conventions]] pour la liste complète des cibles standardisées.

### Cas des projets Python à outillage partagé

`mcp` et `rag-hybride` n'ont pas de Dockerfile propre (cf. [[makefile-conventions]],
§ « Exception — outillage Python partagé »). Leur niveau 4 ne containerise donc pas le
service : il démarre les **dépendances réelles** via le `docker compose` de la racine
(`docker compose up -d --wait postgres`) et exécute l'application depuis son répertoire de
travail contre celles-ci. La garantie visée reste la même — le service se connecte et répond
avec sa configuration réelle — mais la preuve de packaging n'est pas apportée à ce niveau
pour ces deux projets, par choix assumé.

## Forme attendue par projet

La répartition entre niveaux n'est pas normée, parce qu'elle dépend de la richesse du domaine.

| Projet | Forme attendue | Pourquoi |
|---|---|---|
| `sorabelsql-api` | Pyramide classique, base large | Chaîne de garde-fous, masquage de colonnes : beaucoup de logique isolable |
| `text2sql-ai` | Pyramide classique | Validation read-only, filtrage du schéma par profil |
| `rag-hybride` | Pyramide classique | Chunking, fusion RRF, reranking, scoring |
| `mcp` | Pyramide classique | Matrice d'accès, filtrage `list_tools`, journalisation |
| `api-gateway` | **Diamant** — base fine, niveau 3 dominant | Proxy pur : quasi aucune logique isolable par construction ; la valeur se prouve en intégration (bonne cible, bon en-tête, pas de rejeu) |

Un socle unitaire fin sur `api-gateway` n'est **pas** un défaut de couverture : c'est la
conséquence directe du non-négociable « aucune règle métier ne doit fuiter dans la couche de
routage ». Écrire des tests unitaires sur de la configuration de routage pour gonfler un
compteur est un anti-pattern, pas une mise en conformité.

## Couverture

- Seuil global de couverture de ligne : **80 %**, mesuré sur l'ensemble des niveaux 1 à 3.
- Aucun quota par niveau.
- La couverture est un garde-fou contre l'oubli, jamais un objectif en soi : un module à
  100 % dont les tests n'affirment rien de significatif est plus coûteux qu'un module non testé,
  parce qu'il donne une fausse assurance.

## Ce que Claude doit faire

- Avant d'écrire un test, identifier **explicitement son niveau** et vérifier qu'il en respecte
  le critère — en particulier : ne jamais ranger en niveau 1 un test qui touche une I/O.
- Quand un projet manque entièrement d'un niveau, le signaler plutôt que de compenser en
  gonflant un autre niveau.
- Ne jamais écrire de test dont la seule fonction est d'augmenter la couverture.
- Respecter la forme attendue du projet : ne pas réclamer un socle unitaire large sur
  `api-gateway`, ne pas se contenter de tests d'API sur `sorabelsql-api` ou `rag-hybride`.
- Ne jamais déclarer un travail terminé sur la foi des seuls niveaux 1–3 quand le changement
  touche le packaging, la configuration ou le démarrage — c'est le niveau 4 qui le prouve.
