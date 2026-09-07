# sorabel-idp — Solution Docker (Keycloak) | Design | 2026-09-07

## 1. Objet et périmètre

Ce document spécifie la stack Docker de `sorabel-idp` : un service Keycloak conteneurisé
émettant des JWT porteurs du claim `sorabel_profile`, et l'export de realm versionné qui
le configure.

`sorabel-idp` est de la **configuration**, pas du développement. Le livrable est donc
constitué de fichiers de configuration, d'un export de realm et d'un script de
vérification — aucun code applicatif, aucun `Dockerfile`, aucun `Makefile` (exclusions
posées par `.claude/rules/makefile-conventions.md` et `.claude/rules/testing-pyramid.md`).

**Dans le périmètre** : `docker-compose.yml`, `realm-export/sorabel-data-gate.json`,
`.env.example`, `scripts/smoke.sh`, mise à jour du `README.md` local.

**Hors périmètre** : le `docker-compose.yml` racine (scope transverse, cf. §8), la mise à
jour de `docs/architecture/MCP.md` (scope transverse, cf. §5.4), le durcissement de
production (cf. §7.2), toute logique d'autorisation fine — qui vit exclusivement dans
`mcp/`.

## 2. Décisions de design

| # | Décision | Alternative écartée | Raison |
|---|---|---|---|
| D1 | `start-dev` + `--import-realm`, base H2 éphémère, aucun volume de données | Keycloak + Postgres dédié et volume persistant | L'export JSON devient de fait la source de vérité : la dérive base/export du non-négociable est structurellement impossible, `down`/`up` restaure l'état nominal |
| D2 | Compose local dans `sorabel-idp/`, attaché à un réseau Docker externe partagé | Service ajouté au compose racine ; réseau isolé + port publié | Conserve le cycle de vie indépendant annoncé par le `README.md` et le `CLAUDE.md` local, tout en restant résolvable sous le nom d'hôte `sorabel-idp` que l'`api-gateway` attend déjà |
| D3 | Realm complet : 3 rôles, 3 clients, mappers, utilisateurs de dev | Squelette de realm ; un seul client | Un token réel est obtenable immédiatement pour les trois profils, ce qui rend la chaîne `mcp` testable de bout en bout dès cette itération |
| D4 | Claim `sorabel_profile` par `oidc-hardcoded-claim-mapper`, un par client | Attribut utilisateur → claim ; mapper de rôles + normalisation côté `mcp` | Seule option produisant une **chaîne** (`"sales"`) et fonctionnant identiquement en `client_credentials` et en `authorization_code`, sans modifier le contrat de lecture du token de `mcp` |
| D5 | Healthcheck Compose + `scripts/smoke.sh` | Healthcheck seul ; ajout d'une vérification de dérive de l'export | Le healthcheck ne prouve ni l'émission du token ni la présence du claim — précisément ce qui peut être mal configuré. La comparaison d'export exigerait de normaliser un JSON bruyant (ids, timestamps) |

## 3. Topologie

Un unique service, `sorabel-idp`, dans `sorabel-idp/docker-compose.yml`, avec un
`name:` de projet Compose explicite — sans lui, Compose dérive le nom de projet du
répertoire et les deux composes de la solution entrent en concurrence sur les noms de
ressources.

Le service est attaché à un réseau Docker externe partagé :

```yaml
networks:
  sorabel:
    external: true
    name: sorabel
```

Prérequis, à exécuter une seule fois et à documenter dans le `README.md` :

```bash
docker network create sorabel
```

Le nom de service `sorabel-idp` rend le service joignable à `http://sorabel-idp:8080/`,
soit exactement l'adresse déjà déclarée par le cluster `idp` de
`api-gateway/src/Sorabel.ApiGateway.Api/appsettings.Routes.json`. Aucune modification de
l'`api-gateway` n'est requise.

## 4. Service Keycloak

Image officielle `quay.io/keycloak/keycloak:26.7.3` — tag épinglé, jamais `latest`
(dernier tag stable publié sur quay.io au 2026-09-07, vérifié via l'API du registre).
Aucun build, aucun fork.

Cette famille de versions détermine plusieurs choix ci-dessous : variables
`KC_BOOTSTRAP_ADMIN_USERNAME`/`KC_BOOTSTRAP_ADMIN_PASSWORD` (et non les anciennes
`KEYCLOAK_ADMIN*`), port de management séparé `9000` pour les sondes de santé, et
`KC_HOSTNAME` acceptant une URL complète (§7).

| Élément | Valeur | Justification |
|---|---|---|
| Commande | `start-dev --import-realm` | Relit l'export à chaque démarrage (D1) |
| Volume | `./realm-export:/opt/keycloak/data/import:ro` | Le `:ro` matérialise que le conteneur ne réécrit jamais la source de vérité |
| Volume de données | aucun | État délibérément jetable (D1) |
| Port publié | `${KEYCLOAK_PORT:-8080}:8080` | Console d'admin et endpoints OIDC en dev |
| Port de management | `9000`, **non publié** | Sondes de santé accessibles au healthcheck seul |
| Santé | `KC_HEALTH_ENABLED=true`, sonde sur `:9000/health/ready` | Rend `docker compose up -d --wait` significatif et ouvre un `depends_on: service_healthy` aux autres services |

**Contrainte d'implémentation du healthcheck** : l'image Keycloak est distroless — ni
`curl`, ni `wget`. La sonde doit passer par le `/dev/tcp` de bash, qui est le mécanisme
retenu par la documentation Keycloak pour cette image.

## 5. Export de realm

### 5.1 Rôles et clients

Realm `sorabel-data-gate`, rôles de realm `role-support`, `role-sales`, `role-dev`.

| Client | Confidentialité | Flow | Claim `sorabel_profile` |
|---|---|---|---|
| `bot-slack-support` | confidentiel (secret) | `client_credentials` seul ; flow standard et direct access grants **désactivés** | `"support"` |
| `poste-vente` | public | `authorization_code` + PKCE `S256` | `"sales"` |
| `ide-dev` | public | `authorization_code` + PKCE `S256` | `"dev"` |

### 5.2 Protocol mappers (deux par client)

- `oidc-hardcoded-claim-mapper` — `claim.name: sorabel_profile`,
  `jsonType.label: String`, inclus dans l'access token. Garantit une chaîne, là où le
  mapper de rôles natif produirait un tableau (`["role-sales"]`) que `mcp` lirait comme
  une liste et non comme un profil.
- `oidc-audience-mapper` — `included.custom.audience: sorabel-mcp`, pour satisfaire le
  `MCP_JWT_AUDIENCE=sorabel-mcp` déjà déclaré dans le `.env.example` racine. L'audience
  *custom* est préférée à `included.client.audience` : elle évite de créer dans le realm
  un client `sorabel-mcp` fantôme dont le seul rôle serait d'être nommé dans un `aud`.

### 5.3 Deux pièges de l'import JSON

1. **Le rôle du service account ne se déclare pas dans le bloc du client.** Il passe par
   un utilisateur `service-account-bot-slack-support` dans la section `users`, avec
   `realmRoles: ["role-support"]`. Le lien vers le client se fait par le champ
   `serviceAccountClientId`, qui prend le **`clientId`** (`bot-slack-support`), pas
   l'`id` UUID interne du client. Omis, le client s'authentifie sans obtenir aucun rôle.
2. **Utilisateurs de dev** : `u-sales` et `u-dev`, chacun porteur du rôle de realm
   correspondant — les deux clients PKCE nécessitent un utilisateur pour se connecter.
   Mot de passe injecté par variable d'environnement (§6).

### 5.4 Contradiction documentaire à résoudre

`docs/architecture/MCP.md` §3 et `sorabel-idp/README.md` §2 écrivent tous deux que le
protocol mapper injecte le claim *« à partir du rôle Keycloak »*. La décision D4 dérive
le profil de **l'identité du client**, pas du rôle. Les rôles de realm restent présents
(conformes à la documentation de cadrage, et point d'extension futur) mais ne pilotent
plus le claim.

Le `CLAUDE.md` racine impose de **résoudre** toute contradiction entre niveaux avant de
merger, pas de la contourner :

**Résolue avant l'implémentation** (les deux documents affirment désormais que le profil
vient de l'identité du client OAuth, et que les rôles de realm ne pilotent rien) :

- `sorabel-idp/README.md` §2 — corrigé, même scope, commit `f5b51b8`.
- `docs/architecture/MCP.md` §3 et glossaire — corrigés dans un **commit isolé**
  (`d81eee4`), scope transverse : extractible de cette PR si la revue préfère le séparer
  (`git-conventions.md`, « une PR = un scope »).

## 6. Secrets

Trois secrets, aucun dans un fichier versionné : mot de passe admin bootstrap, secret
client de `bot-slack-support`, mot de passe des utilisateurs de dev. Le `.gitignore`
racine couvre déjà `.env*` avec l'exception `!.env.example`, sous-répertoires inclus —
rien à y ajouter.

`sorabel-idp/.env.example` est versionné **sans valeurs** :

```
KEYCLOAK_PORT=8080
KC_BOOTSTRAP_ADMIN_USERNAME=admin
KC_BOOTSTRAP_ADMIN_PASSWORD=
SORABEL_IDP_BOT_CLIENT_SECRET=
SORABEL_IDP_DEV_USER_PASSWORD=
```

Dans le compose, les secrets emploient la forme `${VAR:?message}`, **sans valeur par
défaut** — même comportement que `POSTGRES_PASSWORD` à la racine : l'absence de secret
fait échouer `docker compose up` avec un message actionnable, plutôt que de démarrer
silencieusement sur une valeur faible.

Dans l'export JSON, les emplacements de secret portent la syntaxe de substitution
d'environnement native de Keycloak (`${env.SORABEL_IDP_BOT_CLIENT_SECRET}`), pour garder
le fichier versionnable sans secret.

**Vérifié à l'implémentation : la substitution ne fonctionne pas sur le tag retenu
(Keycloak 26.7.3).** Le secret est importé tel quel — la chaîne littérale de 36 caractères
`${env.SORABEL_IDP_BOT_CLIENT_SECRET}` — plutôt que remplacé par sa valeur ; même
constat pour les mots de passe des utilisateurs de dev. Le mécanisme **livré** n'est donc
pas la substitution mais le repli prévu d'avance : `scripts/bootstrap-secrets.sh` applique
secret client et mots de passe via `kcadm.sh` après le boot. Conséquence opérationnelle :
la base étant éphémère, Keycloak régénère un secret client aléatoire à chaque import — ce
script doit être rejoué après **chaque** `docker compose down`/`up`, pas seulement au
premier démarrage.

**Risque résiduel assumé.** `kcadm.sh config credentials`/`update` reçoit le secret en
argument de ligne de commande (`-s secret=…`), brièvement visible dans la table des
processus de l'hôte le temps de l'appel. Acceptable pour un bootstrap de dev local sur un
conteneur éphémère, mais à ne pas taire.

## 7. Identité de l'issuer

### 7.1 Le problème

Keycloak calcule l'`iss` du token à partir de l'hôte de la requête. Le `.env.example`
racine fixe déjà le contrat côté `mcp` :

```
MCP_JWT_ISSUER=http://localhost:8080/realms/sorabel-data-gate
MCP_JWKS_URL=http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/certs
```

Un token demandé via `localhost:8080` porte `iss: http://localhost:8080/...` ; le même
token demandé de conteneur à conteneur via `sorabel-idp:8080` porte
`iss: http://sorabel-idp:8080/...`, et `mcp` le rejette — alors que la configuration a
toutes les apparences d'être correcte. C'est le mode de défaillance silencieux principal
de ce montage.

### 7.2 La décision

L'identité publique est fixée explicitement :

- `KC_HOSTNAME=http://localhost:8080` — issuer stable, aligné sur le contrat existant.
- `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` — les appels internes par nom de service (JWKS
  récupéré par un `mcp` conteneurisé) restent possibles sans déplacer l'issuer.

Le contrat côté `mcp` reste donc vrai quel que soit le chemin d'appel, sans modifier son
`.env.example`.

**Limite assumée.** En `start-dev`, la console d'admin partage le port 8080 publié :
l'anti-pattern « ne jamais exposer le port d'admin publiquement » du `CLAUDE.md` local
n'est **pas** satisfait par ce compose, et ne peut pas l'être dans ce mode. Le durcissement
(`KC_HOSTNAME_ADMIN`, écoute d'admin séparée, aucun port publié, mode `start` avec base
persistante) relève du déploiement réel et sort du périmètre de cette itération. Cette
limite est documentée plutôt que laissée implicite.

## 8. Dépendance transverse (hors périmètre)

Le `docker-compose.yml` racine (`name: sorabel`, service Postgres) n'attache rien au
réseau `sorabel` : son Postgres vit sur `sorabel_default`. Le jour où l'`api-gateway` sera
conteneurisé, les deux composes devront être rattachés au même réseau pour que la
résolution `sorabel-idp` fonctionne réellement entre conteneurs.

C'est un changement transverse : signalé ici, traité dans une PR distincte. Ce design ne
modifie pas le compose racine.

## 9. Vérification

`scripts/smoke.sh`, exécutable en une commande après `docker compose up -d --wait`,
vérifie ses prérequis (`curl`, `jq`) puis enchaîne :

1. `GET /realms/sorabel-data-gate/protocol/openid-connect/certs` → au moins une clé
   présente.
2. `POST /realms/sorabel-data-gate/protocol/openid-connect/token` en `client_credentials`
   avec `bot-slack-support` → obtention d'un access token.
3. Décodage du payload et assertions :
   - `sorabel_profile == "support"` (valide D4),
   - `sorabel-mcp` présent dans `aud` (valide l'audience mapper, §5.2),
   - `iss == http://localhost:8080/realms/sorabel-data-gate` (valide §7).

L'étape 3 est la seule qui prouve les trois décisions les plus fragiles du design. Le
script sort avec un code non nul en cas d'échec.

Ce script n'est pas un niveau de la pyramide de tests : `testing-pyramid.md` exclut
explicitement `sorabel-idp` de ses quatre niveaux. C'est un outil de vérification de
configuration, et il n'introduit aucun framework de test dans le projet.

## 10. Arborescence livrée

```
sorabel-idp/
├── README.md                          # mis à jour : réseau, .env, smoke, correction §2
├── CLAUDE.md                          # inchangé
├── docker-compose.yml                 # nouveau
├── .env.example                       # nouveau
├── realm-export/
│   └── sorabel-data-gate.json         # nouveau
├── scripts/
│   ├── smoke.sh                       # nouveau
│   └── bootstrap-secrets.sh           # nouveau — mécanisme livré, ${env.…} inopérant sur 26.7.3
└── .claude/
    └── settings.json                  # permissions docker à compléter
```

## 11. Critères d'acceptation

Reprennent les critères de succès du `CLAUDE.md` local, rendus vérifiables :

1. `docker network create sorabel` puis `docker compose up -d --wait` réussit depuis
   `sorabel-idp/`, sans erreur d'import de realm dans les logs.
2. `docker compose up` échoue avec un message actionnable si `.env` est absent ou si un
   secret est vide — jamais de démarrage sur une valeur par défaut faible.
3. `scripts/smoke.sh` sort avec le code 0 et affiche le claim `sorabel_profile` décodé.
4. Aucun secret, mot de passe ni identifiant admin en clair dans un fichier versionné —
   vérifiable par relecture du diff.
5. `realm-export/sorabel-data-gate.json` est la seule source de configuration du realm :
   aucune étape manuelle en console d'admin n'est requise pour atteindre les critères 1 à 3.
6. Aucun `Makefile`, aucun `Dockerfile`, aucune couche applicative ajoutée.
7. `sorabel-idp/README.md` ne contredit plus la dérivation réelle du claim (§5.4).
