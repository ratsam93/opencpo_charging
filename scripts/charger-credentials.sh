#!/usr/bin/env bash
# Manage per-charger OCPP passwords (HTTP Basic auth: user = charge point id).
#
#   scripts/charger-credentials.sh create <id>    create or rotate; the password is printed ONCE
#   scripts/charger-credentials.sh revoke <id>    revoke and disconnect the charger
#   scripts/charger-credentials.sh list           which chargers have credentials (no secrets)
#
# Needs the stack running; reads MANAGEMENT_API_KEY and OCPP_API_PORT from .env.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$INSTALL_DIR/.env"
[ -f "$ENV_FILE" ] || { echo "no .env in $INSTALL_DIR: run configure.py first" >&2; exit 1; }

env_get() {  # KEY default
  local v
  v="$(grep -E "^$1=" "$ENV_FILE" | tail -1 | sed -E "s/^$1=//; s/^'(.*)'\$/\\1/")"
  echo "${v:-$2}"
}
KEY="$(env_get MANAGEMENT_API_KEY '')"
[ -n "$KEY" ] || { echo "MANAGEMENT_API_KEY is not set in .env" >&2; exit 1; }
BASE="${CORE_URL:-http://127.0.0.1:$(env_get OCPP_API_PORT 8000)}/api/v1/charger-credentials"

call() {  # method path  (the key goes in a header file so it never appears in the process list)
  local hdr; hdr="$(mktemp)"; chmod 600 "$hdr"
  printf 'X-API-Key: %s\n' "$KEY" > "$hdr"
  curl -fsS -X "$1" -H "@$hdr" "$BASE$2" || { rm -f "$hdr"; return 1; }
  rm -f "$hdr"; echo
}

case "${1:-}" in
  create) [ -n "${2:-}" ] || { echo "usage: $0 create <charge-point-id>" >&2; exit 2; }
          call POST "/$2" ;;
  revoke) [ -n "${2:-}" ] || { echo "usage: $0 revoke <charge-point-id>" >&2; exit 2; }
          call DELETE "/$2" ;;
  list)   call GET "" ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
