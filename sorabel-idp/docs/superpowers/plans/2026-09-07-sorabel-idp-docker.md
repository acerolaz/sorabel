# sorabel-idp — Solution Docker (Keycloak) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer une stack Docker Keycloak pour `sorabel-idp` qui émet des JWT porteurs du claim `sorabel_profile`, configurée intégralement par un export de realm versionné.

**Architecture :** Un unique service Keycloak `start-dev --import-realm` (base H2 éphémère, aucun volume de données), attaché à un réseau Docker externe partagé sous le nom d'hôte `sorabel-idp`. L'export JSON est la seule source de configuration du realm. Les secrets n'existent que dans un `.env` local, injectés dans l'export par substitution d'environnement. Un script de smoke prouve l'émission du token et le contenu du claim.

**Tech Stack :** Docker Compose, Keycloak 26.7.3 (image officielle quay.io), bash, curl, jq, python3.

**Spec :** `sorabel-idp/docs/superpowers/specs/2026-09-07-sorabel-idp-docker-design.md`

## Global Constraints

Ces contraintes s'appliquent à **toutes** les tâches.

- **Répertoire de travail** : toutes les commandes s'exécutent depuis `sorabel-idp/`, sauf mention contraire explicite.
- **Branche** : `feat/sorabel-idp/docker-keycloak`. Ne **jamais** committer sur `main` (`.claude/rules/git-conventions.md`).
- **Format de commit** : `<type>(sorabel-idp): <description courte>`. Aucune métadonnée d'IA dans les messages.
- **Image épinglée** : `quay.io/keycloak/keycloak:26.7.3`. Jamais `latest`, jamais de build, jamais de `Dockerfile`.
- **Interdits structurels** : aucun `Makefile`, aucun `Dockerfile`, aucun code applicatif, aucune couche hexagonale/clean archi (`.claude/rules/makefile-conventions.md`, `.claude/rules/testing-pyramid.md` excluent ce projet).
- **Aucun secret versionné** : ni mot de passe, ni secret client, ni identifiant admin dans un fichier commité. `.env*` est déjà ignoré à la racine avec l'exception `!.env.example`.
- **Aucune valeur par défaut de secret** : dans le compose, les secrets utilisent `${VAR:?message}` — l'absence de valeur doit faire échouer `docker compose up`.
- **Contrat d'issuer, non négociable** : `iss` = `http://localhost:8080/realms/sorabel-data-gate`, exactement la valeur de `MCP_JWT_ISSUER` dans le `.env.example` racine. Ne pas modifier le `.env.example` racine.
- **Contrat d'audience** : `aud` doit contenir `sorabel-mcp` (valeur de `MCP_JWT_AUDIENCE` à la racine).
- **Contrat de claim** : `sorabel_profile` est une **chaîne** (`"support"`, `"sales"`, `"dev"`), jamais un tableau.
- **Nom d'hôte réseau** : le service Compose doit s'appeler `sorabel-idp`, car `api-gateway/src/Sorabel.ApiGateway.Api/appsettings.Routes.json` déclare déjà `http://sorabel-idp:8080/`. Ne pas modifier l'`api-gateway`.
- **Hors périmètre** : le `docker-compose.yml` racine (dépendance transverse, spec §8). Ne pas le toucher.
- **Pourquoi il n'y a pas de tests unitaires ici** : `.claude/rules/testing-pyramid.md` exclut explicitement `sorabel-idp` de ses quatre niveaux. Le cycle « rouge → vert » de chaque tâche porte donc sur des **commandes de vérification** (`docker compose config`, `up -d --wait`, `scripts/smoke.sh`), pas sur un framework de test. N'introduire ni pytest, ni xUnit, ni aucune dépendance de test dans ce projet.

---

## File Structure

| Fichier | Responsabilité | Tâche |
|---|---|---|
| `docker-compose.yml` | Cycle de vie du service : image, commande, ports, santé, réseau, injection des variables | 1 |
| `.env.example` | Contrat documenté des variables attendues, sans valeurs | 1 |
| `realm-export/sorabel-data-gate.json` | Toute la configuration du realm : rôles, clients, mappers, utilisateurs | 2, 3, 4 |
| `scripts/smoke.sh` | Preuve exécutable : JWKS, émission de token, assertions sur le payload | 3 |
| `README.md` | Mode d'emploi : prérequis réseau, `.env`, démarrage, smoke, arborescence | 5 |
| `.claude/settings.json` | Permissions Docker locales | 5 |

`realm-export/sorabel-data-gate.json` est touché par trois tâches successives : c'est un fichier de configuration unique et indivisible côté Keycloak (un seul realm = un seul fichier d'import), qu'on construit par couches vérifiables. Il n'y a pas de découpage possible sans inventer un mécanisme de fusion qui n'existe pas.

---

### Task 1: Service Keycloak qui démarre et se déclare sain

**Files:**
- Create: `sorabel-idp/docker-compose.yml`
- Create: `sorabel-idp/.env.example`
- Create: `sorabel-idp/.env` (local, **non commité** — vérifier qu'il n'apparaît pas dans `git status`)

**Interfaces:**
- Consumes: rien (première tâche).
- Produces: un service Compose nommé `sorabel-idp`, joignable sur `http://localhost:${KEYCLOAK_PORT:-8080}`, sain au sens `docker compose up -d --wait`. Le répertoire `./realm-export` est monté sur `/opt/keycloak/data/import:ro`. Variables consommées par les tâches suivantes : `KEYCLOAK_PORT`, `KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_BOOTSTRAP_ADMIN_PASSWORD`, `SORABEL_IDP_BOT_CLIENT_SECRET`, `SORABEL_IDP_DEV_USER_PASSWORD`.

- [ ] **Step 1: Créer le réseau Docker partagé**

Ce réseau n'existe pas encore sur la machine (vérifié : `docker network ls` ne liste que `bridge`, `host`, `none`).

```bash
docker network create sorabel
docker network ls | grep sorabel
```

Attendu : une ligne `sorabel   bridge   local`. Si le réseau existe déjà, `docker network create` échoue avec « already exists » — c'est sans conséquence, passer à l'étape suivante.

- [ ] **Step 2: Écrire `.env.example` (versionné, sans valeurs)**

```bash
cat > .env.example <<'EOF'
# Configuration locale de sorabel-idp (Keycloak).
# Copier ce fichier vers .env et renseigner les valeurs — .env n'est jamais commité
# (cf. .gitignore racine et .claude/rules/security.md).

# Port publié de Keycloak sur l'hôte. Doit rester 8080 pour être cohérent avec
# MCP_JWT_ISSUER / MCP_JWKS_URL du .env.example racine.
KEYCLOAK_PORT=8080

# Compte admin bootstrap de la console Keycloak. Sans valeur, docker compose up échoue.
KC_BOOTSTRAP_ADMIN_USERNAME=admin
KC_BOOTSTRAP_ADMIN_PASSWORD=

# Secret du client confidentiel bot-slack-support (grant client_credentials).
SORABEL_IDP_BOT_CLIENT_SECRET=

# Mot de passe des utilisateurs de dev u-sales et u-dev (flows authorization_code + PKCE).
SORABEL_IDP_DEV_USER_PASSWORD=
EOF
```

- [ ] **Step 3: Écrire `docker-compose.yml`**

```bash
cat > docker-compose.yml <<'EOF'
# Stack Docker de sorabel-idp — Keycloak conteneurisé (authn + claim sorabel_profile).
#
# Ce projet est de la configuration, pas du développement : pas de Dockerfile,
# pas de Makefile, pas de code applicatif (cf. ../CLAUDE.md et
# ../.claude/rules/makefile-conventions.md).
#
# La base est volontairement éphémère (start-dev, H2 en mémoire, aucun volume de
# données) : realm-export/ est ainsi la seule source de vérité du realm, et la
# dérive base/export est structurellement impossible.
#
# `name` est explicite : sans lui, Compose dérive le nom de projet du répertoire
# et entre en concurrence avec le compose racine sur les noms de ressources.
name: sorabel-idp

services:
  sorabel-idp:
    # Nom de service = nom d'hôte réseau. api-gateway déclare déjà
    # http://sorabel-idp:8080/ dans appsettings.Routes.json — ne pas renommer.
    image: quay.io/keycloak/keycloak:26.7.3
    container_name: sorabel-idp
    command: ["start-dev", "--import-realm"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: ${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KC_BOOTSTRAP_ADMIN_PASSWORD:?KC_BOOTSTRAP_ADMIN_PASSWORD doit être défini — copier .env.example vers .env}
      # Consommés par la substitution ${env.…} de l'export de realm.
      SORABEL_IDP_BOT_CLIENT_SECRET: ${SORABEL_IDP_BOT_CLIENT_SECRET:?SORABEL_IDP_BOT_CLIENT_SECRET doit être défini — copier .env.example vers .env}
      SORABEL_IDP_DEV_USER_PASSWORD: ${SORABEL_IDP_DEV_USER_PASSWORD:?SORABEL_IDP_DEV_USER_PASSWORD doit être défini — copier .env.example vers .env}
      # Verrouille l'identité publique : sans cela, un token obtenu de conteneur à
      # conteneur porterait iss=http://sorabel-idp:8080/... et mcp le rejetterait,
      # alors que la configuration paraîtrait correcte.
      KC_HOSTNAME: http://localhost:${KEYCLOAK_PORT:-8080}
      KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"
      # Expose /health/* sur le port de management 9000 (non publié).
      KC_HEALTH_ENABLED: "true"
    ports:
      - "${KEYCLOAK_PORT:-8080}:8080"
    volumes:
      # :ro — le conteneur ne réécrit jamais la source de vérité du realm.
      - ./realm-export:/opt/keycloak/data/import:ro
    healthcheck:
      # L'image Keycloak est distroless : ni curl ni wget. On passe par le /dev/tcp
      # de bash, en l'invoquant explicitement (CMD-SHELL utiliserait /bin/sh).
      test:
        - CMD
        - /bin/bash
        - -c
        - 'exec 3<>/dev/tcp/127.0.0.1/9000; printf "GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n" >&3; grep -q "\"status\": \"UP\"" <&3'
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 20s
    networks:
      - sorabel

networks:
  # Réseau partagé entre les composes de la solution.
  # Prérequis, une seule fois : docker network create sorabel
  sorabel:
    external: true
    name: sorabel
EOF
```

- [ ] **Step 4: Vérifier l'échec bruyant en l'absence de secret (critère d'acceptation 2)**

C'est le « test rouge » de cette tâche : sans `.env`, le démarrage doit échouer avec un message actionnable, pas démarrer sur une valeur faible.

```bash
ls .env 2>/dev/null && echo "ATTENTION : .env existe déjà, le déplacer avant ce test"
docker compose config >/dev/null; echo "exit=$?"
```

Attendu : `exit=1`, avec sur stderr le message `KC_BOOTSTRAP_ADMIN_PASSWORD doit être défini — copier .env.example vers .env`. Si `exit=0`, la forme `${VAR:?...}` a été mal transcrite — corriger avant de continuer.

- [ ] **Step 5: Créer le `.env` local et vérifier qu'il n'est pas suivi par git**

```bash
cp .env.example .env
python3 - <<'PY'
import pathlib, secrets
p = pathlib.Path(".env")
s = p.read_text()
s = s.replace("KC_BOOTSTRAP_ADMIN_PASSWORD=", f"KC_BOOTSTRAP_ADMIN_PASSWORD={secrets.token_urlsafe(24)}")
s = s.replace("SORABEL_IDP_BOT_CLIENT_SECRET=", f"SORABEL_IDP_BOT_CLIENT_SECRET={secrets.token_urlsafe(32)}")
s = s.replace("SORABEL_IDP_DEV_USER_PASSWORD=", f"SORABEL_IDP_DEV_USER_PASSWORD={secrets.token_urlsafe(18)}")
p.write_text(s)
print("secrets locaux générés")
PY
git status --porcelain | grep -F ".env" || echo "OK : .env n'est pas suivi par git"
```

Attendu : `OK : .env n'est pas suivi par git`. Si `.env` apparaît, **arrêter** — ne rien committer et vérifier le `.gitignore` racine.

- [ ] **Step 6: Démarrer et vérifier la santé**

`realm-export/` n'existe pas encore : `--import-realm` n'importe alors rien et Keycloak démarre sur le realm `master` seul. C'est attendu à ce stade. Créer le répertoire vide pour que le montage ne crée pas un fichier :

```bash
mkdir -p realm-export
docker compose up -d --wait
docker compose ps
```

Attendu : le service `sorabel-idp` est `Up` et `(healthy)`. `up -d --wait` sort avec le code 0.

**Si le healthcheck ne passe jamais** (le conteneur reste `starting` puis `unhealthy`) alors que `curl -sf http://localhost:8080/realms/master/.well-known/openid-configuration` répond : le problème est la sonde, pas Keycloak. Diagnostiquer avec `docker compose logs sorabel-idp | tail -30` puis `docker exec sorabel-idp /bin/bash -c 'echo ok'`. Si bash est absent, remplacer la sonde par l'approche Java documentée par Keycloak :

```yaml
    healthcheck:
      test: ["CMD", "/opt/keycloak/bin/kcadm.sh", "config", "credentials", "--server", "http://localhost:8080", "--realm", "master", "--user", "$KC_BOOTSTRAP_ADMIN_USERNAME", "--password", "$KC_BOOTSTRAP_ADMIN_PASSWORD"]
```

- [ ] **Step 7: Vérifier l'issuer du realm master (pré-validation de la spec §7)**

```bash
curl -sf http://localhost:8080/realms/master/.well-known/openid-configuration | python3 -c "import json,sys; print(json.load(sys.stdin)['issuer'])"
```

Attendu exactement : `http://localhost:8080/realms/master`. Toute autre valeur (`http://sorabel-idp:8080/...`, un port différent) signifie que `KC_HOSTNAME` n'est pas pris en compte — corriger avant de continuer, sinon la tâche 3 échouera de manière déroutante.

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml .env.example
git status --porcelain   # doit être vide après le add : ni .env, ni realm-export/ (répertoire vide)
git commit -m "feat(sorabel-idp): ajoute la stack Docker Keycloak

Service Keycloak 26.7.3 en start-dev avec import de realm, base
éphémère et aucun volume de données : l'export JSON reste la seule
source de vérité du realm.

KC_HOSTNAME verrouille l'issuer sur http://localhost:8080 pour rester
aligné sur MCP_JWT_ISSUER, avec backchannel dynamique pour que les
appels entre conteneurs restent possibles. Les secrets sont exigés sans
valeur par défaut : un .env absent fait échouer le démarrage."
```

---

### Task 2: Realm importé et secret client injecté par l'environnement

Cette tâche est placée en deuxième parce qu'elle valide le **seul point du design non vérifiable sans exécution** (spec §6) : la substitution `${env.…}` à l'import. Tout le reste en dépend.

**Files:**
- Create: `sorabel-idp/realm-export/sorabel-data-gate.json`

**Interfaces:**
- Consumes: le service et les variables de la tâche 1.
- Produces: le realm `sorabel-data-gate` avec les rôles `role-support`, `role-sales`, `role-dev` et le client confidentiel `bot-slack-support` (id fixe `11111111-1111-4111-8111-111111111111`, `client_credentials` seul), dont le service account porte `role-support`. Endpoint token fonctionnel avec le secret du `.env`.

- [ ] **Step 1: Écrire le « test rouge » — la commande qui doit échouer maintenant et passer ensuite**

```bash
source .env
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/certs
```

Attendu maintenant : `404` (le realm n'existe pas). Cette même commande devra renvoyer `200` à l'étape 4.

- [ ] **Step 2: Écrire l'export de realm (première couche : rôles + client bot)**

Les `id` des clients sont **fixés en dur** volontairement : la section `users` doit référencer le client par son id interne via `serviceAccountClientLink`, et un id fixe rend cette référence déterministe au lieu de dépendre d'un UUID généré à l'import.

```bash
cat > realm-export/sorabel-data-gate.json <<'EOF'
{
  "realm": "sorabel-data-gate",
  "enabled": true,
  "sslRequired": "none",
  "accessTokenLifespan": 300,
  "roles": {
    "realm": [
      { "name": "role-support", "description": "Profil support (bot Slack). Ne pilote pas le claim sorabel_profile." },
      { "name": "role-sales", "description": "Profil vente (poste de vente). Ne pilote pas le claim sorabel_profile." },
      { "name": "role-dev", "description": "Profil developpeur (IDE). Ne pilote pas le claim sorabel_profile." }
    ]
  },
  "clients": [
    {
      "id": "11111111-1111-4111-8111-111111111111",
      "clientId": "bot-slack-support",
      "name": "Bot Slack Support",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "secret": "${env.SORABEL_IDP_BOT_CLIENT_SECRET}",
      "serviceAccountsEnabled": true,
      "standardFlowEnabled": false,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "fullScopeAllowed": true
    }
  ],
  "users": [
    {
      "username": "service-account-bot-slack-support",
      "enabled": true,
      "serviceAccountClientLink": "11111111-1111-4111-8111-111111111111",
      "realmRoles": ["role-support"]
    }
  ]
}
EOF
python3 -c "import json;json.load(open('realm-export/sorabel-data-gate.json'));print('JSON valide')"
```

- [ ] **Step 3: Recréer le conteneur pour déclencher l'import**

`--import-realm` n'agit qu'au démarrage, et la base est éphémère : il faut détruire puis recréer, pas redémarrer.

```bash
docker compose down
docker compose up -d --wait
docker compose logs sorabel-idp | grep -iE "imported|import|error" | tail -20
```

Attendu : une ligne indiquant l'import du realm `sorabel-data-gate`, aucune erreur d'import.

- [ ] **Step 4: Vérifier que le « test rouge » passe au vert**

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/certs
```

Attendu : `200`.

- [ ] **Step 5: Valider la substitution `${env.…}` — le point de risque du design**

```bash
source .env
curl -s -X POST http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=bot-slack-support \
  --data-urlencode "client_secret=${SORABEL_IDP_BOT_CLIENT_SECRET}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('OK : access_token obtenu' if 'access_token' in d else f'ÉCHEC : {d}')
sys.exit(0 if 'access_token' in d else 1)"
```

Attendu : `OK : access_token obtenu`.

**Si l'échec est `invalid_client`** : la substitution d'environnement n'a pas eu lieu et le secret du client est littéralement la chaîne `${env.SORABEL_IDP_BOT_CLIENT_SECRET}`. Confirmer par `docker compose exec sorabel-idp /bin/bash -c 'echo $SORABEL_IDP_BOT_CLIENT_SECRET'` (la variable doit être présente dans le conteneur). Appliquer alors le **repli arrêté dans la spec §6** :

1. Retirer la ligne `"secret": "${env.…}"` de l'export (le client garde un secret généré à l'import).
2. Créer `scripts/bootstrap-secrets.sh` qui applique le secret après le boot :

```bash
cat > scripts/bootstrap-secrets.sh <<'EOS'
#!/usr/bin/env bash
# Repli documenté (spec §6) : applique les secrets après le boot, quand la
# substitution ${env.…} de l'export de realm n'est pas opérante.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] && { set -a; . ./.env; set +a; }
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?absent}" "${SORABEL_IDP_BOT_CLIENT_SECRET:?absent}"
kc() { docker compose exec -T sorabel-idp /opt/keycloak/bin/kcadm.sh "$@"; }
kc config credentials --server http://localhost:8080 --realm master \
  --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"
kc update clients/11111111-1111-4111-8111-111111111111 -r sorabel-data-gate \
  -s "secret=$SORABEL_IDP_BOT_CLIENT_SECRET"
echo "secrets appliqués"
EOS
chmod +x scripts/bootstrap-secrets.sh
mkdir -p scripts && ./scripts/bootstrap-secrets.sh
```

3. Reprendre l'étape 5. Ce repli devra être mentionné dans le README à la tâche 5.

- [ ] **Step 6: Vérifier le rôle du service account (spec §5.3, piège n°1)**

```bash
source .env
curl -s -X POST http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=bot-slack-support \
  --data-urlencode "client_secret=${SORABEL_IDP_BOT_CLIENT_SECRET}" \
  | python3 -c "
import base64,json,sys
t=json.load(sys.stdin)['access_token'].split('.')[1]
t+='='*(-len(t)%4)
c=json.loads(base64.urlsafe_b64decode(t))
roles=c.get('realm_access',{}).get('roles',[])
print('roles =',roles)
sys.exit(0 if 'role-support' in roles else 1)"
```

Attendu : la liste contient `role-support`. Si absent, le `serviceAccountClientLink` n'a pas été résolu — vérifier que l'`id` du client dans `clients` et la valeur du lien dans `users` sont **identiques** au caractère près.

- [ ] **Step 7: Commit**

```bash
git add realm-export/sorabel-data-gate.json
git commit -m "feat(sorabel-idp): importe le realm sorabel-data-gate avec le client bot-slack-support

Realm versionné : trois rôles de realm et le client confidentiel
bot-slack-support en client_credentials seul (flow standard et direct
access grants désactivés).

Le secret du client est injecté par substitution d'environnement, donc
absent du fichier versionné. L'id du client est fixé en dur pour que le
serviceAccountClientLink de la section users soit déterministe."
```

---

### Task 3: Claim `sorabel_profile`, audience, et script de smoke

**Files:**
- Modify: `sorabel-idp/realm-export/sorabel-data-gate.json` (ajout de `protocolMappers` au client `bot-slack-support`)
- Create: `sorabel-idp/scripts/smoke.sh`

**Interfaces:**
- Consumes: le realm et le client de la tâche 2.
- Produces: un access token portant `sorabel_profile: "support"` (chaîne) et `sorabel-mcp` dans `aud`. `scripts/smoke.sh` est exécutable, sort 0 en cas de succès et non-0 sinon ; la tâche 5 le documente dans le README.

- [ ] **Step 1: Écrire le script de smoke (le « test » de cette tâche, rouge avant les mappers)**

```bash
mkdir -p scripts
cat > scripts/smoke.sh <<'EOS'
#!/usr/bin/env bash
# Vérification de configuration de sorabel-idp (spec §9).
#
# Ce script n'est PAS un niveau de la pyramide de tests : .claude/rules/testing-pyramid.md
# exclut sorabel-idp de ses quatre niveaux. C'est un outil de vérification de
# configuration, et il n'introduit aucun framework de test dans le projet.
#
# Usage : docker compose up -d --wait && ./scripts/smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."

for bin in curl python3; do
  command -v "$bin" >/dev/null || { echo "prérequis manquant : $bin" >&2; exit 1; }
done

[[ -f .env ]] || { echo "prérequis manquant : .env (copier .env.example)" >&2; exit 1; }
set -a; . ./.env; set +a
: "${SORABEL_IDP_BOT_CLIENT_SECRET:?SORABEL_IDP_BOT_CLIENT_SECRET absent de .env}"

PORT="${KEYCLOAK_PORT:-8080}"
BASE="http://localhost:${PORT}/realms/sorabel-data-gate"

echo "1/3 JWKS"
keys=$(curl -sf "${BASE}/protocol/openid-connect/certs" \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('keys',[])))")
[[ "$keys" -ge 1 ]] || { echo "  ÉCHEC : aucune clé publiée" >&2; exit 1; }
echo "  OK : ${keys} clé(s) publiée(s)"

echo "2/3 token client_credentials (bot-slack-support)"
token=$(curl -sf -X POST "${BASE}/protocol/openid-connect/token" \
  -d grant_type=client_credentials \
  -d client_id=bot-slack-support \
  --data-urlencode "client_secret=${SORABEL_IDP_BOT_CLIENT_SECRET}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
[[ -n "$token" ]] || { echo "  ÉCHEC : aucun access_token émis" >&2; exit 1; }
echo "  OK : access_token émis"

echo "3/3 assertions sur le payload"
python3 - "$BASE" "$token" <<'PY'
import base64, json, sys

expected_iss, token = sys.argv[1], sys.argv[2]
payload = token.split(".")[1]
payload += "=" * (-len(payload) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))

errors = []

profile = claims.get("sorabel_profile")
if profile != "support":
    errors.append(f'sorabel_profile attendu "support" (chaîne), obtenu {profile!r}')

aud = claims.get("aud")
aud = aud if isinstance(aud, list) else [aud]
if "sorabel-mcp" not in aud:
    errors.append(f'aud doit contenir "sorabel-mcp", obtenu {aud!r}')

iss = claims.get("iss")
if iss != expected_iss:
    errors.append(f"iss attendu {expected_iss!r}, obtenu {iss!r} — vérifier KC_HOSTNAME")

roles = claims.get("realm_access", {}).get("roles", [])
if "role-support" not in roles:
    errors.append(f'realm_access.roles doit contenir "role-support", obtenu {roles!r}')

for e in errors:
    print("  ÉCHEC :", e, file=sys.stderr)
if errors:
    sys.exit(1)

print(f"  OK : sorabel_profile={profile!r} aud={aud} iss={iss}")
PY

echo "smoke OK"
EOS
chmod +x scripts/smoke.sh
```

L'assertion sur `realm_access.roles` va **au-delà** des trois assertions de la spec §9 : elle verrouille aussi le piège du service account (spec §5.3), qui est silencieux autrement.

- [ ] **Step 2: Exécuter le smoke et vérifier qu'il échoue pour la bonne raison**

```bash
./scripts/smoke.sh; echo "exit=$?"
```

Attendu : `exit=1`, avec `ÉCHEC : sorabel_profile attendu "support" (chaîne), obtenu None` et `ÉCHEC : aud doit contenir "sorabel-mcp"`. Les étapes 1/3 et 2/3 doivent, elles, passer. Si l'assertion `iss` échoue déjà ici, revenir à la tâche 1 étape 7.

- [ ] **Step 3: Ajouter les deux protocol mappers au client `bot-slack-support`**

```bash
python3 - <<'PY'
import json, pathlib

p = pathlib.Path("realm-export/sorabel-data-gate.json")
realm = json.loads(p.read_text())

def mappers(profile):
    return [
        {
            # Hardcodé, et non dérivé du rôle : le mapper de rôles natif produirait
            # ["role-sales"] (tableau préfixé) là où mcp attend une chaîne, et un
            # client en client_credentials n'a pas d'utilisateur dont lire un rôle.
            "name": "sorabel-profile",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-hardcoded-claim-mapper",
            "consentRequired": False,
            "config": {
                "claim.name": "sorabel_profile",
                "claim.value": profile,
                "jsonType.label": "String",
                "access.token.claim": "true",
                "id.token.claim": "false",
                "userinfo.token.claim": "false",
            },
        },
        {
            # Audience custom : évite de créer dans le realm un client sorabel-mcp
            # fantôme dont le seul rôle serait d'être nommé dans un aud.
            "name": "sorabel-mcp-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.custom.audience": "sorabel-mcp",
                "access.token.claim": "true",
                "id.token.claim": "false",
            },
        },
    ]

for client in realm["clients"]:
    if client["clientId"] == "bot-slack-support":
        client["protocolMappers"] = mappers("support")

p.write_text(json.dumps(realm, indent=2, ensure_ascii=False) + "\n")
print("mappers ajoutés à bot-slack-support")
PY
python3 -c "import json;json.load(open('realm-export/sorabel-data-gate.json'));print('JSON valide')"
```

- [ ] **Step 4: Recréer le conteneur et vérifier que le smoke passe au vert**

```bash
docker compose down && docker compose up -d --wait
./scripts/smoke.sh; echo "exit=$?"
```

Attendu : `exit=0`, avec `OK : sorabel_profile='support' aud=['sorabel-mcp'] iss=http://localhost:8080/realms/sorabel-data-gate` puis `smoke OK`.

Si `aud` ne contient pas `sorabel-mcp` : vérifier que la clé de config est bien `included.custom.audience` (et non `included.client.audience`, qui exigerait un client existant de ce nom).

- [ ] **Step 5: Commit**

```bash
git add realm-export/sorabel-data-gate.json scripts/smoke.sh
git commit -m "feat(sorabel-idp): émet le claim sorabel_profile et l'audience sorabel-mcp

Deux protocol mappers sur bot-slack-support : un hardcoded-claim qui
émet sorabel_profile en chaîne, et un audience mapper custom qui place
sorabel-mcp dans aud, conformément à MCP_JWT_AUDIENCE.

scripts/smoke.sh prouve la chaîne complète : JWKS, émission du token,
puis assertions sur sorabel_profile, aud, iss et le rôle du service
account — les quatre points silencieux en cas de mauvaise configuration."
```

---

### Task 4: Clients PKCE `poste-vente` et `ide-dev`, utilisateurs de dev

**Files:**
- Modify: `sorabel-idp/realm-export/sorabel-data-gate.json`

**Interfaces:**
- Consumes: le realm complet de la tâche 3.
- Produces: les clients publics `poste-vente` (profil `sales`) et `ide-dev` (profil `dev`) en `authorization_code` + PKCE `S256`, et les utilisateurs `u-sales` / `u-dev` avec leurs rôles de realm. Aucune modification du contrat produit par la tâche 3.

- [ ] **Step 1: Écrire le « test rouge »**

```bash
for c in poste-vente ide-dev; do
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    "http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/auth?client_id=${c}&response_type=code&redirect_uri=http://localhost:3000/callback&scope=openid&code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&code_challenge_method=S256")
  echo "$c -> $code"
done
```

Attendu maintenant : `400` pour les deux (client inconnu). Après l'étape 2, la même commande doit renvoyer `200` (page de connexion servie).

- [ ] **Step 2: Ajouter les deux clients publics et les utilisateurs de dev**

```bash
python3 - <<'PY'
import json, pathlib

p = pathlib.Path("realm-export/sorabel-data-gate.json")
realm = json.loads(p.read_text())

def mappers(profile):
    return [
        {
            "name": "sorabel-profile",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-hardcoded-claim-mapper",
            "consentRequired": False,
            "config": {
                "claim.name": "sorabel_profile",
                "claim.value": profile,
                "jsonType.label": "String",
                "access.token.claim": "true",
                "id.token.claim": "false",
                "userinfo.token.claim": "false",
            },
        },
        {
            "name": "sorabel-mcp-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.custom.audience": "sorabel-mcp",
                "access.token.claim": "true",
                "id.token.claim": "false",
            },
        },
    ]

def public_client(cid, name, uuid, profile):
    return {
        "id": uuid,
        "clientId": cid,
        "name": name,
        "enabled": True,
        "protocol": "openid-connect",
        # Client public : le code est distribué (poste de vente, IDE), aucun secret
        # ne peut y rester caché — PKCE remplace le secret.
        "publicClient": True,
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "redirectUris": ["http://localhost:3000/callback", "http://localhost:*"],
        "webOrigins": ["+"],
        "attributes": {"pkce.code.challenge.method": "S256"},
        "fullScopeAllowed": True,
        "protocolMappers": mappers(profile),
    }

realm["clients"].append(public_client(
    "poste-vente", "Poste de vente", "22222222-2222-4222-8222-222222222222", "sales"))
realm["clients"].append(public_client(
    "ide-dev", "IDE developpeur", "33333333-3333-4333-8333-333333333333", "dev"))

def dev_user(username, first, last, role):
    return {
        "username": username,
        "enabled": True,
        "emailVerified": True,
        "firstName": first,
        "lastName": last,
        "credentials": [{
            "type": "password",
            "value": "${env.SORABEL_IDP_DEV_USER_PASSWORD}",
            "temporary": False,
        }],
        "realmRoles": [role],
    }

realm["users"].append(dev_user("u-sales", "Utilisateur", "Vente", "role-sales"))
realm["users"].append(dev_user("u-dev", "Utilisateur", "Dev", "role-dev"))

p.write_text(json.dumps(realm, indent=2, ensure_ascii=False) + "\n")
print("clients PKCE et utilisateurs de dev ajoutés")
PY
python3 -c "import json;json.load(open('realm-export/sorabel-data-gate.json'));print('JSON valide')"
```

- [ ] **Step 3: Recréer le conteneur et vérifier le passage au vert**

```bash
docker compose down && docker compose up -d --wait
for c in poste-vente ide-dev; do
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    "http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/auth?client_id=${c}&response_type=code&redirect_uri=http://localhost:3000/callback&scope=openid&code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&code_challenge_method=S256")
  echo "$c -> $code"
done
```

Attendu : `poste-vente -> 200` et `ide-dev -> 200`.

- [ ] **Step 4: Vérifier que PKCE est bien exigé**

Sans `code_challenge`, un client configuré en `S256` doit refuser la requête :

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "http://localhost:8080/realms/sorabel-data-gate/protocol/openid-connect/auth?client_id=poste-vente&response_type=code&redirect_uri=http://localhost:3000/callback&scope=openid"
```

Attendu : `400`. Un `200` signifie que `pkce.code.challenge.method` n'a pas été appliqué — vérifier la clé dans `attributes`.

- [ ] **Step 5: Vérifier que la tâche 3 n'a pas régressé**

```bash
./scripts/smoke.sh; echo "exit=$?"
```

Attendu : `exit=0`.

- [ ] **Step 6: Vérifier l'existence des utilisateurs de dev**

```bash
source .env
docker compose exec -T sorabel-idp /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"
docker compose exec -T sorabel-idp /opt/keycloak/bin/kcadm.sh get users \
  -r sorabel-data-gate --fields username,enabled
```

Attendu : `u-sales` et `u-dev` présents et `enabled: true`. Si les mots de passe n'ont pas été substitués (même cause qu'à la tâche 2 étape 5), étendre `scripts/bootstrap-secrets.sh` avec `set-password` pour les deux utilisateurs.

- [ ] **Step 7: Commit**

```bash
git add realm-export/sorabel-data-gate.json
git commit -m "feat(sorabel-idp): ajoute les clients PKCE poste-vente et ide-dev

Deux clients publics en authorization_code + PKCE S256, chacun avec son
mapper de profil (sales, dev) et l'audience sorabel-mcp. Publics et non
confidentiels : leur code est distribué sur les postes, aucun secret ne
pourrait y rester caché.

Ajoute les utilisateurs de dev u-sales et u-dev, requis par ces flows,
avec mot de passe injecté par l'environnement."
```

---

### Task 5: Documentation, permissions locales, et vérification depuis zéro

**Files:**
- Modify: `sorabel-idp/README.md` (sections 3 « Démarrage » et 4 « Arborescence »)
- Modify: `sorabel-idp/.claude/settings.json`

**Interfaces:**
- Consumes: l'ensemble des livrables des tâches 1 à 4.
- Produces: rien que d'autres tâches consomment — tâche terminale.

- [ ] **Step 1: Réécrire la section « Démarrage » du README**

```bash
python3 - <<'PY'
import pathlib, re

p = pathlib.Path("README.md")
s = p.read_text()

start = s.index("## 3. Démarrage")
end = s.index("## 4. Arborescence")

new = """## 3. Démarrage

### Prérequis, une seule fois

Le service est attaché à un réseau Docker partagé entre les composes de la solution :

```bash
docker network create sorabel
```

### Configuration locale

```bash
cp .env.example .env
# puis renseigner KC_BOOTSTRAP_ADMIN_PASSWORD, SORABEL_IDP_BOT_CLIENT_SECRET
# et SORABEL_IDP_DEV_USER_PASSWORD
```

`.env` n'est jamais commité. Aucun secret n'a de valeur par défaut : un `.env` absent
ou incomplet fait échouer `docker compose up` avec un message explicite, plutôt que de
démarrer sur une valeur faible.

### Démarrage et vérification

```bash
docker compose up -d --wait   # attend que le healthcheck passe
./scripts/smoke.sh            # prouve JWKS, émission du token, claim, aud et iss
```

Pas de `Makefile`, pas de `make build`/`make test` : le cycle de vie est intégralement
piloté par `docker compose` (image officielle, aucun build custom).

La base est **éphémère** (`start-dev`, H2 en mémoire, aucun volume de données) : c'est
délibéré. `realm-export/sorabel-data-gate.json` est ainsi la seule source de vérité du
realm, et la dérive entre la base et l'export est structurellement impossible. En
contrepartie, **rien de ce qui est modifié dans la console d'admin ne survit à un
`docker compose down`** — tout changement doit passer par l'export.

Un changement dans l'export ne prend effet qu'au **démarrage** : `docker compose down &&
docker compose up -d --wait`, pas un simple `restart`.

Console d'admin : `http://localhost:8080` (identifiants issus du `.env`). En `start-dev`,
la console partage le port applicatif : ce compose est destiné au développement local,
pas à un déploiement exposé.

"""
p.write_text(s[:start] + new + s[end:])
print("section 3 réécrite")
PY
```

- [ ] **Step 2: Mettre à jour l'arborescence du README**

```bash
python3 - <<'PY'
import pathlib

p = pathlib.Path("README.md")
s = p.read_text()
old = """```
sorabel-idp/
├── README.md
├── CLAUDE.md
├── docker-compose.yml         # Image Keycloak officielle
├── realm-export/
│   └── sorabel-data-gate.json # Export versionné du realm (source de vérité)
└── .claude/
    └── settings.json          # Permissions/config docker uniquement
```"""
new = """```
sorabel-idp/
├── README.md
├── CLAUDE.md
├── docker-compose.yml          # Image Keycloak officielle 26.7.3, aucun build
├── .env.example                # Variables attendues (sans valeurs)
├── realm-export/
│   └── sorabel-data-gate.json  # Export versionné du realm (source de vérité)
├── scripts/
│   └── smoke.sh                # Vérification : JWKS, token, claim, aud, iss
├── docs/superpowers/
│   ├── specs/                  # Design de la solution Docker
│   └── plans/                  # Plan d'implémentation
└── .claude/
    └── settings.json           # Permissions/config docker uniquement
```

Ni `Makefile`, ni `Dockerfile`, ni code applicatif : ce projet est de la configuration."""
assert old in s, "bloc d'arborescence introuvable — vérifier le README"
p.write_text(s.replace(old, new))
print("arborescence mise à jour")
PY
```

- [ ] **Step 3: Si le repli `bootstrap-secrets.sh` a été activé, le documenter**

À faire **uniquement** si la tâche 2 étape 5 a conduit à créer `scripts/bootstrap-secrets.sh`. Sinon, passer à l'étape 4.

```bash
python3 - <<'PY'
import pathlib
p = pathlib.Path("README.md")
s = p.read_text()
anchor = "./scripts/smoke.sh            # prouve JWKS, émission du token, claim, aud et iss\n```\n"
addition = anchor + """
Sur cette version de Keycloak, la substitution `${env.…}` de l'export n'est pas opérante :
les secrets sont appliqués après le boot par `./scripts/bootstrap-secrets.sh`, à exécuter
entre `up` et `smoke.sh`.
"""
assert anchor in s
p.write_text(s.replace(anchor, addition))
print("repli documenté")
PY
```

- [ ] **Step 4: Renseigner les permissions Docker locales**

```bash
cat > .claude/settings.json <<'EOF'
{
  "permissions": {
    "allow": [
      "Bash(docker compose:*)",
      "Bash(docker network create sorabel)",
      "Bash(docker network ls:*)",
      "Bash(./scripts/smoke.sh)"
    ],
    "deny": []
  }
}
EOF
python3 -c "import json;json.load(open('.claude/settings.json'));print('JSON valide')"
```

- [ ] **Step 5: Vérification finale depuis zéro (critères d'acceptation 1, 3, 5)**

Le seul test qui prouve que l'export est bien la source unique de configuration : détruire complètement puis suivre le README à la lettre.

```bash
docker compose down -v
docker compose up -d --wait
./scripts/smoke.sh; echo "smoke exit=$?"
```

Attendu : `smoke exit=0`, sans aucune intervention manuelle dans la console d'admin.

- [ ] **Step 6: Vérifier qu'aucun secret n'a fui dans les fichiers versionnés (critère 4)**

```bash
source .env
git ls-files -z | xargs -0 grep -nF -e "$SORABEL_IDP_BOT_CLIENT_SECRET" \
  -e "$KC_BOOTSTRAP_ADMIN_PASSWORD" -e "$SORABEL_IDP_DEV_USER_PASSWORD" \
  && { echo "ÉCHEC : un secret apparaît dans un fichier versionné"; exit 1; } \
  || echo "OK : aucun secret dans les fichiers versionnés"
git ls-files | grep -x ".env" && echo "ÉCHEC : .env est suivi" || echo "OK : .env non suivi"
```

Attendu : `OK : aucun secret dans les fichiers versionnés` et `OK : .env non suivi`.

- [ ] **Step 7: Vérifier les interdits structurels (critère 6)**

```bash
ls Makefile Dockerfile 2>/dev/null && echo "ÉCHEC : fichier interdit présent" || echo "OK : ni Makefile ni Dockerfile"
```

- [ ] **Step 8: Commit**

```bash
git add README.md .claude/settings.json
git status --porcelain
git commit -m "docs(sorabel-idp): documente le démarrage de la stack Docker

Prérequis réseau, configuration du .env, démarrage avec --wait et
vérification par scripts/smoke.sh. Explicite deux conséquences du choix
d'une base éphémère : les changements en console d'admin ne survivent
pas, et un changement d'export ne prend effet qu'au redémarrage complet.

Renseigne les permissions Docker locales, laissées vides jusqu'ici."
```

---

## Self-Review

**1. Couverture de la spec**

| Section de la spec | Tâche |
|---|---|
| §3 Topologie (réseau externe, nom de service, `name:` de projet) | 1 (étapes 1, 3) |
| §4 Service Keycloak (image, commande, volume `:ro`, ports, santé) | 1 (étapes 3, 6) |
| §5.1 Rôles et clients | 2 (bot), 4 (PKCE) |
| §5.2 Protocol mappers | 3 (bot), 4 (PKCE) |
| §5.3 Pièges d'import (service account, utilisateurs de dev) | 2 (étape 6), 4 (étapes 2, 6) |
| §5.4 Contradiction documentaire | déjà résolue avant le plan (commits `f5b51b8`, `d81eee4`) — aucune tâche requise |
| §6 Secrets (`.env.example`, `${VAR:?}`, substitution, repli) | 1 (étapes 2, 4, 5), 2 (étape 5), 5 (étape 3) |
| §7 Issuer (`KC_HOSTNAME`, backchannel dynamique, limite admin) | 1 (étapes 3, 7), 3 (assertion `iss`), 5 (étape 1) |
| §8 Dépendance transverse | hors périmètre, aucune tâche — rappelé dans les contraintes globales |
| §9 Vérification (`smoke.sh`, 3 assertions + rôle) | 3 (étapes 1, 4) |
| §10 Arborescence livrée | 5 (étape 2) |
| §11 Critères d'acceptation 1–7 | 1 (crit. 2), 3 (crit. 3), 5 (crit. 1, 3, 4, 5, 6, 7) |

Aucune section de la spec n'est sans tâche.

**2. Placeholders** — aucun « TBD », aucun « implémenter plus tard », aucune étape sans contenu exécutable. Les deux branches conditionnelles (repli `bootstrap-secrets.sh` en tâche 2 étape 5, sa documentation en tâche 5 étape 3) contiennent leur code complet et leur condition de déclenchement explicite.

**3. Cohérence des identifiants** — vérifiés d'un bout à l'autre : `sorabel-data-gate`, `sorabel-idp` (service et hôte), `sorabel_profile`, `sorabel-mcp` (audience), `bot-slack-support` / `poste-vente` / `ide-dev`, `role-support` / `role-sales` / `role-dev`, `u-sales` / `u-dev`, les cinq variables du `.env`, et l'id `11111111-1111-4111-8111-111111111111` référencé identiquement dans `clients`, dans `serviceAccountClientLink` et dans le repli `kcadm`. La fonction `mappers(profile)` de la tâche 4 est répétée intégralement plutôt que référencée depuis la tâche 3, les tâches pouvant être lues dans un ordre quelconque.
