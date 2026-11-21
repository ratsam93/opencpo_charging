#!/usr/bin/env bash
# deploy.sh — pull-based auto-deploy for the OpenCPO stack.
#
# Run every minute by a systemd timer (see deploy/systemd and docs/DEPLOY.md).
# For each configured repo it checks the remote branch; when it has changed it
# pulls it, rebuilds only the affected compose services, waits for their health
# check, and ROLLS BACK to the previous commit if the check fails.
#
# Safety properties:
#   * never touches .env, docker-compose.override.yml or any other compose project
#   * refuses to overwrite a checkout that has local changes to tracked files
#   * a remote commit that failed its health check is not retried until the
#     remote branch moves on
#   * touch .deploy/PAUSE to stop all deployments without disabling the timer
#   * only one run at a time (flock)
#
# Usage:  scripts/deploy.sh            # normal run (what the timer does)
#         scripts/deploy.sh --status   # show state and last result
#         scripts/deploy.sh --force    # ignore bad-commit markers and re-try
#
# Repo list: built-in defaults below, or override with .deploy/repos.conf,
# one line per repo:   dir|git-url|branch|services
#   dir       folder relative to the install dir ("." = this orchestrator repo)
#   services  space-separated compose services to rebuild, or
#             *     = the whole stack, only when docker-compose*.yml / .env.example changed
#             auto  = single-repo mode: decide from the changed folders (see service_for_path)

set -uo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$INSTALL_DIR/.deploy"
LOG_FILE="${DEPLOY_LOG:-$INSTALL_DIR/deploy.log}"
HEALTH_TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-240}"     # seconds per attempt
FORCE=0
MODE="run"

for arg in "$@"; do
  case "$arg" in
    --force)  FORCE=1 ;;
    --status) MODE="status" ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
  esac
done

mkdir -p "$STATE_DIR"

# ── Default: this repository contains every component (single-repo layout).
# Change the branch to "main" once the work is merged. For several separate
# repos, list them in .deploy/repos.conf instead (see the header).
DEFAULT_REPOS=(
  ".|https://github.com/ratsam93/opencpo_charging.git|claude/great-newton-0flk8g|auto"
)

log() {
  local msg
  msg="$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
  echo "$msg" >> "$LOG_FILE"
  [ -t 1 ] && echo "$msg"
  return 0
}

rotate_log() {
  if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 5000000 ]; then
    mv -f "$LOG_FILE" "$LOG_FILE.1"
  fi
}

# Read KEY from .env (single quotes stripped); fall back to default.
env_get() {
  local key="$1" def="$2" val
  val="$(grep -E "^${key}=" "$INSTALL_DIR/.env" 2>/dev/null | tail -1 | sed -E "s/^${key}=//; s/^'(.*)'\$/\\1/; s/^\"(.*)\"\$/\\1/")"
  echo "${val:-$def}"
}

compose() {
  local pre=()
  command -v nice >/dev/null 2>&1 && pre+=(nice -n 10)
  command -v ionice >/dev/null 2>&1 && pre+=(ionice -c 3)
  ( cd "$INSTALL_DIR" && "${pre[@]}" docker compose "$@" )
}

load_repos() {
  REPOS=()
  if [ -f "$STATE_DIR/repos.conf" ]; then
    while IFS= read -r line; do
      line="${line%%#*}"; line="$(echo "$line" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
      [ -n "$line" ] && REPOS+=("$line")
    done < "$STATE_DIR/repos.conf"
  else
    REPOS=("${DEFAULT_REPOS[@]}")
  fi
}

# ── Which compose service does a changed file belong to? ──────────────────
service_for_path() {  # prints a service name, "*" (whole stack) or nothing
  case "$1" in
    docker-compose*.yml|docker-compose*.yaml|.env.example) echo "*" ;;
    opencpo-core/*)         echo ocpp-core ;;
    opencpo-admin/*)        echo cpo-admin ;;
    opencpo-charge-app/*)   echo charge-app ;;
    opencpo-tester/*)       echo compliance-tester ;;
    opencpo-charger-farm/*) echo charger-farm ;;
    *) ;;                   # docs, scripts, bastion (not in compose), ...
  esac
}

services_for_changes() {  # path-to-checkout old-sha new-sha  -> space separated services or "*"
  local path="$1" old="$2" new="$3" f s out=() seen=" "
  while IFS= read -r f; do
    s="$(service_for_path "$f")"
    [ -n "$s" ] || continue
    if [ "$s" = "*" ]; then echo "*"; return; fi
    case "$seen" in *" $s "*) ;; *) out+=("$s"); seen="$seen$s " ;; esac
  done < <(git -C "$path" diff --name-only "$old" "$new" 2>/dev/null)
  echo "${out[*]:-}"
}

# ── Health checks ─────────────────────────────────────────────────────────
http_ok() {  # url [required-substring]
  local body
  body="$(curl -fsS -m 5 "$1" 2>/dev/null)" || return 1
  [ -z "${2:-}" ] || echo "$body" | grep -q "$2"
}

service_healthy() {
  case "$1" in
    ocpp-core)  http_ok "http://127.0.0.1:$(env_get OCPP_API_PORT 8000)/health/ready" '"status":"ok"' ;;
    cpo-admin)  http_ok "http://127.0.0.1:$(env_get CPO_ADMIN_PORT 8080)/health" '"status":"ok"' ;;
    charge-app) http_ok "http://127.0.0.1:$(env_get CHARGE_APP_PORT 8003)/health" '"status":"ok"' \
                  || http_ok "http://127.0.0.1:$(env_get CHARGE_APP_PORT 8003)/" ;;
    charger-farm) http_ok "http://127.0.0.1:$(env_get CHARGER_FARM_PORT 8087)/health" '"status":"ok"' \
                  || http_ok "http://127.0.0.1:$(env_get CHARGER_FARM_PORT 8087)/" ;;
    compliance-tester) return 0 ;;   # CLI: exits when no charger connects; build success is the check
    *) return 0 ;;
  esac
}

wait_healthy() {  # services...
  local deadline=$(( $(date +%s) + HEALTH_TIMEOUT )) s ok
  while :; do
    ok=1
    for s in "$@"; do service_healthy "$s" || { ok=0; break; }; done
    [ "$ok" = 1 ] && return 0
    [ "$(date +%s)" -ge "$deadline" ] && return 1
    sleep "${DEPLOY_POLL_INTERVAL:-5}"
  done
}

deploy_services() {  # services...   (build + recreate only these)
  if [ "$1" = "*" ]; then
    compose up -d
  else
    compose build "$@" && compose up -d --no-deps "$@"
  fi
}

# ── Status ────────────────────────────────────────────────────────────────
if [ "$MODE" = "status" ]; then
  echo "install dir : $INSTALL_DIR"
  echo "paused      : $([ -e "$STATE_DIR/PAUSE" ] && echo yes || echo no)"
  echo "last result : $(cat "$STATE_DIR/last_status" 2>/dev/null || echo 'never run')"
  load_repos
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r dir url branch services <<< "$entry"
    printf '  %-24s %-28s deployed=%s' "$dir" "$branch" "$(git -C "$INSTALL_DIR/$dir" rev-parse --short HEAD 2>/dev/null || echo none)"
    [ -f "$STATE_DIR/bad_${dir//\//_}" ] && printf '  BAD-COMMIT=%s' "$(cut -c1-7 "$STATE_DIR/bad_${dir//\//_}")"
    echo
  done
  exit 0
fi

# ── Single instance, pause switch ─────────────────────────────────────────
exec 9>"$STATE_DIR/lock"
flock -n 9 || exit 0
[ -e "$STATE_DIR/PAUSE" ] && exit 0
rotate_log

load_repos
SELF_BEFORE="$(sha256sum "$INSTALL_DIR/scripts/deploy.sh" 2>/dev/null | cut -d' ' -f1)"

declare -a CHANGED_DIRS=() CHANGED_PREV=() CHANGED_NEW=() CHANGED_SVCS=()
ANY_ERROR=0

# ── Phase 1: fetch and check out new commits ──────────────────────────────
for entry in "${REPOS[@]}"; do
  IFS='|' read -r dir url branch services <<< "$entry"
  [ -n "${dir:-}" ] && [ -n "${url:-}" ] && [ -n "${branch:-}" ] || { log "ERROR bad repos.conf line: $entry"; ANY_ERROR=1; continue; }
  path="$INSTALL_DIR/$dir"; key="${dir//\//_}"
  [ -d "$path/.git" ] || { log "ERROR $dir: not a git checkout ($path)"; ANY_ERROR=1; continue; }

  remote_sha="$(git -C "$path" ls-remote "$url" "refs/heads/$branch" 2>/dev/null | cut -f1)"
  [ -n "$remote_sha" ] || { log "WARN $dir: cannot read $url $branch (network or branch missing)"; continue; }
  local_sha="$(git -C "$path" rev-parse HEAD 2>/dev/null)"
  [ "$remote_sha" = "$local_sha" ] && continue

  if [ "$FORCE" = 0 ] && [ -f "$STATE_DIR/bad_$key" ] && [ "$(cat "$STATE_DIR/bad_$key")" = "$remote_sha" ]; then
    if [ ! -f "$STATE_DIR/bad_$key.noted" ]; then
      log "SKIP $dir: ${remote_sha:0:7} failed its health check earlier; waiting for a newer commit"
      touch "$STATE_DIR/bad_$key.noted"
    fi
    continue
  fi

  if [ -n "$(git -C "$path" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    log "ERROR $dir: tracked files have local changes, refusing to overwrite (resolve by hand)"
    ANY_ERROR=1; continue
  fi

  git -C "$path" remote set-url origin "$url" 2>/dev/null || true
  if ! git -C "$path" fetch -q --depth 1 origin "$branch" 2>>"$LOG_FILE"; then
    log "ERROR $dir: git fetch failed"; ANY_ERROR=1; continue
  fi
  new_sha="$(git -C "$path" rev-parse FETCH_HEAD)"
  git -C "$path" checkout -q -B "$branch" "$new_sha" 2>>"$LOG_FILE" || { log "ERROR $dir: checkout failed"; ANY_ERROR=1; continue; }
  rm -f "$STATE_DIR/bad_$key" "$STATE_DIR/bad_$key.noted"
  log "PULLED $dir ${local_sha:0:7} -> ${new_sha:0:7} ($branch)"

  # Which services need a rebuild?
  svcs="$services"
  if [ "$services" = "auto" ]; then
    svcs="$(services_for_changes "$path" "$local_sha" "$new_sha")"
    if [ -z "$svcs" ]; then
      log "INFO $dir: no service folders changed, stack not touched"
      continue
    fi
    log "INFO $dir: changed services: $svcs"
  elif [ "$services" = "*" ]; then
    if git -C "$path" diff --name-only "$local_sha" "$new_sha" 2>/dev/null | grep -qE '^(docker-compose[^/]*\.ya?ml|\.env\.example)$'; then
      svcs="*"
    else
      log "INFO $dir: no compose changes, stack not touched"
      continue
    fi
  fi
  CHANGED_DIRS+=("$dir"); CHANGED_PREV+=("$local_sha"); CHANGED_NEW+=("$new_sha"); CHANGED_SVCS+=("$svcs")
done

# If this script itself changed, re-run once with the new version.
SELF_AFTER="$(sha256sum "$INSTALL_DIR/scripts/deploy.sh" 2>/dev/null | cut -d' ' -f1)"
if [ "$SELF_BEFORE" != "$SELF_AFTER" ] && [ -z "${DEPLOY_REEXEC:-}" ]; then
  log "INFO deploy.sh updated, re-executing"
  export DEPLOY_REEXEC=1
  flock -u 9; exec 9>&-
  exec "$INSTALL_DIR/scripts/deploy.sh" "$@"
fi

if [ "${#CHANGED_DIRS[@]}" -eq 0 ]; then
  [ "$ANY_ERROR" = 0 ] || echo "error $(date -u +%FT%TZ)" > "$STATE_DIR/last_status"
  exit "$ANY_ERROR"
fi

# ── Phase 2: rebuild, health-check, roll back on failure ──────────────────
all_services=()
for s in "${CHANGED_SVCS[@]}"; do
  if [ "$s" = "*" ]; then all_services=("*"); break; fi
  for one in $s; do all_services+=("$one"); done
done
if [ "${all_services[0]}" != "*" ]; then
  mapfile -t all_services < <(printf '%s\n' "${all_services[@]}" | sort -u)
fi

if [ "${all_services[0]}" = "*" ]; then
  check_services=(ocpp-core cpo-admin charge-app charger-farm)
else
  check_services=("${all_services[@]}")
fi

log "DEPLOY services: ${all_services[*]}"
if deploy_services "${all_services[@]}" >>"$LOG_FILE" 2>&1 && \
   wait_healthy "${check_services[@]}"; then
  log "OK deployed: $(printf '%s ' "${CHANGED_DIRS[@]}")"
  echo "ok $(date -u +%FT%TZ) ${CHANGED_DIRS[*]}" > "$STATE_DIR/last_status"
  exit 0
fi

log "FAIL health check failed — rolling back"
for i in "${!CHANGED_DIRS[@]}"; do
  dir="${CHANGED_DIRS[$i]}"; key="${dir//\//_}"; path="$INSTALL_DIR/$dir"
  echo "${CHANGED_NEW[$i]}" > "$STATE_DIR/bad_$key"
  git -C "$path" reset -q --hard "${CHANGED_PREV[$i]}" >>"$LOG_FILE" 2>&1
  log "ROLLBACK $dir -> ${CHANGED_PREV[$i]:0:7} (bad commit ${CHANGED_NEW[$i]:0:7} recorded)"
done
if deploy_services "${all_services[@]}" >>"$LOG_FILE" 2>&1 && \
   wait_healthy "${check_services[@]}"; then
  log "ROLLED BACK ok: previous version is healthy again"
  echo "rolled-back $(date -u +%FT%TZ) ${CHANGED_DIRS[*]}" > "$STATE_DIR/last_status"
  exit 1
fi
log "CRITICAL rollback did not restore health; manual intervention needed"
echo "critical $(date -u +%FT%TZ)" > "$STATE_DIR/last_status"
exit 2
