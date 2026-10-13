#!/usr/bin/env bash
# Install / repair durable `wwh-deploy` CLI outside the git tree + boot-time healer.
# Safe to run anytime: sudo bash /opt/wewerehere/scripts/deploy/ensure-wwh-deploy-cli.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/wewerehere}"
if [[ -f /etc/wewerehere/deploy.conf ]]; then
  # shellcheck disable=SC1091
  source /etc/wewerehere/deploy.conf
fi
APP_DIR="${APP_DIR:-/opt/wewerehere}"

SCRIPT="$APP_DIR/scripts/deploy/wwh-deploy.sh"
BIN="/usr/local/bin/wwh-deploy"
UNIT_SRC="$APP_DIR/scripts/deploy/wwh-deploy-cli.service"
UNIT_DST="/etc/systemd/system/wwh-deploy-cli.service"
MARKER="# wewerehere-wwh-deploy-wrapper"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run as root (sudo)" >&2
  exit 1
fi

if [[ ! -f "$SCRIPT" ]]; then
  echo "ERROR: deploy script missing: $SCRIPT" >&2
  exit 1
fi

chmod +x "$SCRIPT" "$0" 2>/dev/null || true

# Drop legacy symlink into the repo (git pull used to break it).
if [[ -L "$BIN" ]]; then
  rm -f "$BIN"
fi

need_write=1
if [[ -f "$BIN" ]] && grep -qF "$MARKER" "$BIN" 2>/dev/null; then
  if grep -qF 'scripts/deploy/wwh-deploy.sh' "$BIN" 2>/dev/null; then
    need_write=0
  fi
fi

if [[ "$need_write" -eq 1 ]]; then
  cat >"$BIN" <<EOF
#!/usr/bin/env bash
$MARKER
# Durable CLI outside git. Healer: $0
set -euo pipefail
APP_DIR=/opt/wewerehere
if [[ -f /etc/wewerehere/deploy.conf ]]; then
  # shellcheck disable=SC1091
  source /etc/wewerehere/deploy.conf
fi
APP_DIR="\${APP_DIR:-/opt/wewerehere}"
exec bash "\$APP_DIR/scripts/deploy/wwh-deploy.sh" "\$@"
EOF
  chmod 755 "$BIN"
  echo "[ensure-wwh-deploy-cli] installed $BIN"
else
  echo "[ensure-wwh-deploy-cli] ok $BIN"
fi

# Boot healer so the CLI comes back even if someone deletes the binary.
# Skip systemctl start when we are already inside a systemd ExecStart (avoids recurse).
if [[ -f "$UNIT_SRC" ]]; then
  install -m 644 "$UNIT_SRC" "$UNIT_DST"
  systemctl daemon-reload
  systemctl enable wwh-deploy-cli.service >/dev/null
  if [[ -z "${INVOCATION_ID:-}" ]]; then
    systemctl start wwh-deploy-cli.service >/dev/null || true
  fi
  echo "[ensure-wwh-deploy-cli] enabled wwh-deploy-cli.service"
fi

if command -v wwh-deploy >/dev/null 2>&1; then
  echo "[ensure-wwh-deploy-cli] ready — try: sudo wwh-deploy update"
else
  echo "[ensure-wwh-deploy-cli] WARNING: $BIN exists but not on PATH" >&2
  echo "  run: /usr/local/bin/wwh-deploy update" >&2
fi
