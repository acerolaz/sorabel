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
[[ -n "$token" ]] || { echo "  ÉCHEC : aucun access_token émis (secret désynchronisé après un docker compose down/up ? relancer ./scripts/bootstrap-secrets.sh)" >&2; exit 1; }
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
