#!/usr/bin/env bash
# Offline test of scripts/deploy.sh: local git remotes, a fake `docker` and a
# fake `curl`. Needs only bash, git, flock. Run:  scripts/test-deploy.sh
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   $*"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $*"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1  [$2]"; fi; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$T/bin" "$T/remotes" "$T/work"

# fake docker / curl -----------------------------------------------------------
cat > "$T/bin/docker" <<'E'
#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_STATE/docker.log"
[ -e "$FAKE_STATE/build_fail" ] && [[ "$*" == *build* ]] && exit 1
exit 0
E
cat > "$T/bin/curl" <<'E'
#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_STATE/curl.log"
if [ -s "$FAKE_STATE/unhealthy" ] && [ "$(git -C "$FAKE_STATE/../install/opencpo-admin" rev-parse HEAD 2>/dev/null)" = "$(cat "$FAKE_STATE/unhealthy")" ]; then exit 22; fi
echo '{"status":"ok"}'
E
chmod +x "$T/bin/docker" "$T/bin/curl"
export FAKE_STATE="$T/state"; mkdir -p "$FAKE_STATE"
export PATH="$T/bin:$PATH" DEPLOY_HEALTH_TIMEOUT=2 DEPLOY_POLL_INTERVAL=1

# remotes ----------------------------------------------------------------------
mkrepo() {  # name branch  -> bare remote with one commit on that branch, plus main
  local n="$1" b="$2"
  git init -q --bare -b main "$T/remotes/$n.git"
  git clone -q "$T/remotes/$n.git" "$T/work/$n" 2>/dev/null
  ( cd "$T/work/$n" && git checkout -q -b main && echo v1 > file && git add . && git commit -q -m v1 && git push -q origin main \
    && git checkout -q -b "$b" && git push -q origin "$b" )
}
mkrepo orch deploybranch; mkrepo admin audit
( cd "$T/work/orch" && git checkout -q deploybranch && mkdir -p scripts && cp "$SRC/scripts/deploy.sh" scripts/ \
  && echo 'services: {}' > docker-compose.yml && git add . && git commit -q -m "add script" && git push -q origin deploybranch )

# install dir = clone of orch; admin component = clone of admin main
git clone -q "$T/remotes/orch.git" "$T/install" 2>&1 | grep -v "^$" ; ( cd "$T/install" && git checkout -q deploybranch )
git clone -q "$T/remotes/admin.git" "$T/install/opencpo-admin"
printf "OCPP_API_PORT='8000'\nCPO_ADMIN_PORT='8080'\n" > "$T/install/.env"
mkdir -p "$T/install/.deploy"
cat > "$T/install/.deploy/repos.conf" <<E
.|file://$T/remotes/orch.git|deploybranch|*
opencpo-admin|file://$T/remotes/admin.git|audit|cpo-admin
E
D="$T/install/scripts/deploy.sh"
dlog() { cat "$FAKE_STATE/docker.log" 2>/dev/null; }
rmlogs() { : > "$FAKE_STATE/docker.log"; rm -f "$FAKE_STATE/build_fail" "$FAKE_STATE/unhealthy"; }
push_admin() { ( cd "$T/work/admin" && git checkout -q audit && echo "$1" >> file && git add . && git commit -q -m "$1" && git push -q origin audit ); }
push_orch()  { ( cd "$T/work/orch" && git checkout -q deploybranch && echo "$1" >> "$2" && git add . && git commit -q -m "$1" && git push -q origin deploybranch ); }

push_admin v1b   # audit branch now differs from the checked-out main
echo "1. first run switches admin to the deploy branch and rebuilds only cpo-admin"
rmlogs; "$D"; rc=$?
check "exit 0" "[ $rc = 0 ]"
check "admin on audit branch" "[ \"\$(git -C $T/install/opencpo-admin branch --show-current)\" = audit ]"
check "built only cpo-admin" "dlog | grep -q 'compose build cpo-admin' && ! dlog | grep -q 'compose build charge-app'"
check "recreated with --no-deps" "dlog | grep -q 'compose up -d --no-deps cpo-admin'"
check "last_status ok" "grep -q '^ok' $T/install/.deploy/last_status"

echo "2. no change -> nothing happens"
rmlogs; "$D"; rc=$?
check "exit 0" "[ $rc = 0 ]"; check "no docker calls" "[ -z \"\$(dlog)\" ]"

echo "3. new commit deploys again"
push_admin v2; rmlogs; "$D"
check "rebuilt" "dlog | grep -q 'compose build cpo-admin'"
check "checkout matches remote" "[ \"\$(git -C $T/install/opencpo-admin rev-parse HEAD)\" = \"\$(git -C $T/remotes/admin.git rev-parse audit)\" ]"

echo "4. failing health check rolls back and does not retry the bad commit"
GOOD="$(git -C "$T/install/opencpo-admin" rev-parse HEAD)"
push_admin v3-broken; BADSHA="$(git -C "$T/remotes/admin.git" rev-parse audit)"
rmlogs; echo "$BADSHA" > "$FAKE_STATE/unhealthy"; "$D"; rc=$?
check "exit 1 (rolled back)" "[ $rc = 1 ]"
check "checkout restored to previous commit" "[ \"\$(git -C $T/install/opencpo-admin rev-parse HEAD)\" = $GOOD ]"
check "bad commit recorded" "[ \"\$(cat $T/install/.deploy/bad_opencpo-admin)\" = $BADSHA ]"
check "rebuilt twice (deploy + rollback)" "[ \"\$(dlog | grep -c 'compose build cpo-admin')\" = 2 ]"
rm -f "$FAKE_STATE/unhealthy"; rmlogs; "$D"
check "bad commit not retried" "[ -z \"\$(dlog)\" ]"
check "skip is logged once" "[ \"\$(grep -c 'failed its health check earlier' $T/install/deploy.log)\" = 1 ]"
"$D"; check "skip not logged again" "[ \"\$(grep -c 'failed its health check earlier' $T/install/deploy.log)\" = 1 ]"

echo "5. a newer commit after the bad one deploys"
push_admin v4-fixed; rmlogs; "$D"
check "deployed fix" "dlog | grep -q 'compose build cpo-admin'"
check "bad marker cleared" "[ ! -e $T/install/.deploy/bad_opencpo-admin ]"

echo "6. build failure also rolls back"
push_admin v5; rmlogs; touch "$FAKE_STATE/build_fail"; "$D"; rc=$?
check "exit nonzero" "[ $rc -ne 0 ]"
rm -f "$FAKE_STATE/build_fail"

echo "7. PAUSE file stops deployments"
push_admin v6; touch "$T/install/.deploy/PAUSE"; rmlogs; "$D"
check "no docker calls while paused" "[ -z \"\$(dlog)\" ]"
rm -f "$T/install/.deploy/PAUSE"

echo "8. local changes to tracked files are never overwritten"
echo dirty >> "$T/install/opencpo-admin/file"; rmlogs; "$D"; rc=$?
check "refused" "grep -q 'local changes, refusing' $T/install/deploy.log"
check "dirty file intact" "grep -q dirty $T/install/opencpo-admin/file"
git -C "$T/install/opencpo-admin" checkout -q -- file

echo "9. orchestrator docs-only change does not touch the stack"
rmlogs; "$D" >/dev/null   # catch up with v6
push_orch "docs" README.md; rmlogs; "$D"
check "pulled" "grep -q 'PULLED \\. ' $T/install/deploy.log"
check "no docker calls for docs-only change" "[ -z \"\$(dlog)\" ]"

echo "10. compose change recreates the whole stack"
push_orch "# changed" docker-compose.yml; rmlogs; "$D"
check "compose up -d (all)" "dlog | grep -qE 'compose up -d\$'"

echo "11. deploy.sh updating itself re-executes cleanly"
push_orch "# new version marker" scripts/deploy.sh; rmlogs; "$D"; rc=$?
check "re-exec logged" "grep -q 'deploy.sh updated, re-executing' $T/install/deploy.log"
check "exit 0" "[ $rc = 0 ]"

echo "12. --status works and unreachable remote is tolerated"
# shellcheck disable=SC2034  # used inside the eval in check()
out="$("$D" --status)"; check "status lists admin" "echo \"\$out\" | grep -q opencpo-admin"
mv "$T/remotes/admin.git" "$T/remotes/admin.gone"; rmlogs; "$D"; rc=$?
check "network failure is a warning, exit 0" "[ $rc = 0 ] && grep -q 'cannot read' $T/install/deploy.log"
mv "$T/remotes/admin.gone" "$T/remotes/admin.git"

echo "13. two runs at once: second exits immediately"
( exec 9>"$T/install/.deploy/lock"; flock -n 9; "$D"; echo "rc=$?" > "$T/second_rc" ) &  # placeholder, replaced below
wait
( flock -x "$T/install/.deploy/lock" sleep 3 ) & sleep 0.5
rmlogs; push_admin v7; "$D"; rc=$?
check "locked run exits 0 without deploying" "[ $rc = 0 ] && [ -z \"\$(dlog)\" ]"
wait

echo; echo "passed=$PASS failed=$FAIL"; [ "$FAIL" = 0 ]
