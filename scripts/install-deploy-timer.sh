#!/usr/bin/env bash
# Install (or remove) the systemd timer that runs scripts/deploy.sh every minute.
# Run as root:   sudo scripts/install-deploy-timer.sh [--user opencpo] [--dir /home/opencpo/opencpo_charging]
#                sudo scripts/install-deploy-timer.sh --uninstall
set -euo pipefail

USER_NAME="opencpo"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --user) USER_NAME="$2"; shift 2 ;;
    --dir)  INSTALL_DIR="$2"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
UNIT_DIR=/etc/systemd/system

if [ "$UNINSTALL" = 1 ]; then
  systemctl disable --now opencpo-deploy.timer 2>/dev/null || true
  rm -f "$UNIT_DIR/opencpo-deploy.service" "$UNIT_DIR/opencpo-deploy.timer"
  systemctl daemon-reload
  echo "removed opencpo-deploy timer"; exit 0
fi

id "$USER_NAME" >/dev/null 2>&1 || { echo "user '$USER_NAME' does not exist" >&2; exit 1; }
id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx docker || { echo "user '$USER_NAME' is not in the docker group" >&2; exit 1; }
[ -x "$INSTALL_DIR/scripts/deploy.sh" ] || { echo "$INSTALL_DIR/scripts/deploy.sh not found or not executable" >&2; exit 1; }
[ -f "$INSTALL_DIR/.env" ] || { echo "$INSTALL_DIR/.env missing: run configure.py first" >&2; exit 1; }
for tool in git flock curl docker; do command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }; done

for f in opencpo-deploy.service opencpo-deploy.timer; do
  sed -e "s#@USER@#$USER_NAME#g" -e "s#@INSTALL_DIR@#$INSTALL_DIR#g" \
    "$INSTALL_DIR/deploy/systemd/$f" > "$UNIT_DIR/$f"
done
systemctl daemon-reload
systemctl enable --now opencpo-deploy.timer
echo "installed. Status:  systemctl list-timers opencpo-deploy.timer"
echo "Logs:    $INSTALL_DIR/deploy.log        Pause: touch $INSTALL_DIR/.deploy/PAUSE"
