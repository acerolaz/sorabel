#!/usr/bin/env bash
# Repli documenté (spec §6) : applique les secrets après le boot, quand la
# substitution ${env.…} de l'export de realm n'est pas opérante.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo "prérequis manquant : .env (copier .env.example vers .env et renseigner les valeurs)" >&2; exit 1; }
set -a; . ./.env; set +a

: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?KC_BOOTSTRAP_ADMIN_PASSWORD absent de .env}" \
  "${SORABEL_IDP_BOT_CLIENT_SECRET:?SORABEL_IDP_BOT_CLIENT_SECRET absent de .env}" \
  "${SORABEL_IDP_DEV_USER_PASSWORD:?SORABEL_IDP_DEV_USER_PASSWORD absent de .env}"

kc() { docker compose exec -T sorabel-idp /opt/keycloak/bin/kcadm.sh "$@"; }

kc config credentials --server http://localhost:8080 --realm master \
  --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"

# Résolution par clientId plutôt que par id UUID en dur : reste correct même si
# l'export venait à faire évoluer les id fixes des clients (cf. spec §5.3).
bot_client_uuid=$(kc get clients -r sorabel-data-gate -q clientId=bot-slack-support --fields id \
  | python3 -c 'import json,sys
clients = json.load(sys.stdin)
if not clients:
    print("ÉCHEC : client bot-slack-support introuvable (realm sorabel-data-gate importé ?)", file=sys.stderr)
    raise SystemExit(1)
print(clients[0]["id"])')
kc update "clients/${bot_client_uuid}" -r sorabel-data-gate \
  -s "secret=$SORABEL_IDP_BOT_CLIENT_SECRET"

kc set-password -r sorabel-data-gate --username u-sales \
  --new-password "$SORABEL_IDP_DEV_USER_PASSWORD"
kc set-password -r sorabel-data-gate --username u-dev \
  --new-password "$SORABEL_IDP_DEV_USER_PASSWORD"

echo "secrets appliqués"
