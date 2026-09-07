#!/usr/bin/env bash
# Repli documenté (spec §6) : applique les secrets après le boot, quand la
# substitution ${env.…} de l'export de realm n'est pas opérante.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] && { set -a; . ./.env; set +a; }
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?absent}" "${SORABEL_IDP_BOT_CLIENT_SECRET:?absent}" "${SORABEL_IDP_DEV_USER_PASSWORD:?absent}"
kc() { docker compose exec -T sorabel-idp /opt/keycloak/bin/kcadm.sh "$@"; }
kc config credentials --server http://localhost:8080 --realm master \
  --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"
kc update clients/11111111-1111-4111-8111-111111111111 -r sorabel-data-gate \
  -s "secret=$SORABEL_IDP_BOT_CLIENT_SECRET"
kc set-password -r sorabel-data-gate --username u-sales \
  --new-password "$SORABEL_IDP_DEV_USER_PASSWORD"
kc set-password -r sorabel-data-gate --username u-dev \
  --new-password "$SORABEL_IDP_DEV_USER_PASSWORD"
echo "secrets appliqués"
