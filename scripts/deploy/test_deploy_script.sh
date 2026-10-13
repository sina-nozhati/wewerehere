#!/usr/bin/env bash
# Local/CI checks for wwh-deploy.sh (no root required for most steps)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/deploy/wwh-deploy.sh"

ENSURE="$ROOT/scripts/deploy/ensure-wwh-deploy-cli.sh"

echo "== bash -n =="
bash -n "$SCRIPT"
bash -n "$ENSURE"

echo "== ensure script exists =="
[[ -f "$ENSURE" ]]
[[ -f "$ROOT/scripts/deploy/wwh-deploy-cli.service" ]]

echo "== safety greps (must not match) =="
if grep -E 'git clean|rm -rf storage|rsync.*--delete' "$SCRIPT" | grep -v '^[[:space:]]*#'; then
  echo "unsafe patterns found in deploy script" >&2
  exit 1
fi

echo "== dry-run update with temp config =="
TMP_CONF="$(mktemp)"
trap 'rm -f "$TMP_CONF"' EXIT
cat >"$TMP_CONF" <<EOF
APP_DIR=$ROOT
SERVICE=wewerehere
RUN_USER=$(whoami)
GIT_BRANCH=main
BACKUP_DIR=$ROOT/.deploy-test-backups
HEALTH_URL=http://127.0.0.1:5173/api/health
SKIP_BACKUP=1
EOF
mkdir -p "$ROOT/.deploy-test-backups"

WW_DEPLOY_CONF="$TMP_CONF" bash "$SCRIPT" --dry-run --no-git update

echo "== dry-run status =="
WW_DEPLOY_CONF="$TMP_CONF" bash "$SCRIPT" status

echo "All deploy script checks passed."
