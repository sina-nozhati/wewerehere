#!/usr/bin/env bash
# We Were Here — VPS deploy helper (Ubuntu 24+). Use: sudo wwh-deploy update
set -euo pipefail

SCRIPT_NAME="${0##*/}"
DEFAULT_CONF="/etc/wewerehere/deploy.conf"

APP_DIR="${APP_DIR:-/opt/wewerehere}"
SERVICE="${SERVICE:-wewerehere}"
RUN_USER="${RUN_USER:-www-data}"
GIT_BRANCH="${GIT_BRANCH:-main}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/wewerehere}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5173/api/health}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"

NO_BACKUP=0
NO_GIT=0
DRY_RUN=0
CMD=""

log() { printf '[%s] %s\n' "$SCRIPT_NAME" "$*"; }
die() { log "ERROR: $*"; exit 1; }

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

need_root_for() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    die "subcommand '$1' needs root (sudo) for systemctl/chown"
  fi
}

load_config() {
  local conf="${WW_DEPLOY_CONF:-$DEFAULT_CONF}"
  if [[ -f "$conf" ]]; then
    # shellcheck source=/dev/null
    source "$conf"
    APP_DIR="${APP_DIR:-/opt/wewerehere}"
    SERVICE="${SERVICE:-wewerehere}"
    RUN_USER="${RUN_USER:-www-data}"
    GIT_BRANCH="${GIT_BRANCH:-main}"
    BACKUP_DIR="${BACKUP_DIR:-/var/backups/wewerehere}"
    HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5173/api/health}"
    SKIP_BACKUP="${SKIP_BACKUP:-0}"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-backup) NO_BACKUP=1; shift ;;
      --no-git) NO_GIT=1; shift ;;
      --dry-run) DRY_RUN=1; shift ;;
      install|update|migrate|smoke|status)
        if [[ -n "$CMD" ]]; then
          die "only one subcommand allowed (got '$CMD' and '$1')"
        fi
        CMD="$1"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1 (try --help)"
        ;;
    esac
  done
  CMD="${CMD:-update}"
}

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [options] <install|update|migrate|smoke|status>

  install   First-time venv, pip, dirs, permissions
  update    Backup, git pull, pip, migrate, restart, smoke (default)
  migrate   Run backend/scripts/migrate_legacy.py
  smoke     HTTP health and static asset checks
  status    systemd, git HEAD, data.sqlite size

Options:
  --no-backup   Skip tar backup before update
  --no-git      Skip git fetch/pull (manual/rsync deploy)
  --dry-run     Print commands without executing

Config: \$WW_DEPLOY_CONF or $DEFAULT_CONF
EOF
}

check_python() {
  command -v python3 >/dev/null 2>&1 || die "python3 not found"
  local ver
  ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  local major minor
  major="${ver%%.*}"
  minor="${ver#*.}"
  if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 11 ]]; then
    die "Python >= 3.11 required (found $ver)"
  fi
}

install_apt_runtime_deps() {
  if ! command -v apt-get >/dev/null 2>&1; then
    log "apt-get not found; skip Cairo/Pango/ffmpeg install"
    return 0
  fi
  local pkgs=(libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 fontconfig ffmpeg)
  local p need=0
  for p in "${pkgs[@]}"; do
    if ! dpkg -l "$p" 2>/dev/null | grep -q '^ii'; then
      need=1
      break
    fi
  done
  if [[ "$need" -eq 0 ]]; then
    log "Cairo/Pango/fontconfig/ffmpeg already installed"
    return 0
  fi
  log "apt install Cairo/Pango/fontconfig/ffmpeg (ticket PNG + memory video)"
  if ! run apt-get update -qq; then
    log "WARN: apt-get update failed (often a broken third-party source, e.g. Docker 403). Trying install anyway."
  fi
  if ! run apt-get install -y -qq "${pkgs[@]}"; then
    die "apt install failed for: ${pkgs[*]}. Fix broken apt repos (docs/DEPLOY_VPS.md) then: apt-get install -y ${pkgs[*]}"
  fi
}

install_ticket_font() {
  local font_src="$APP_DIR/assets/fonts/Vazirmatn-Regular.ttf"
  [[ -f "$font_src" ]] || die "missing ticket font: $font_src"
  run mkdir -p "$APP_DIR/storage/fonts"
  if command -v fc-cache >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
    local sys_font_dir="/usr/local/share/fonts/wwh"
    run mkdir -p "$sys_font_dir"
    run cp -f "$font_src" "$sys_font_dir/Vazirmatn-Regular.ttf"
    run fc-cache -f "$sys_font_dir" >/dev/null 2>&1 || true
    log "Vazirmatn registered with fontconfig ($sys_font_dir)"
  fi
}

pip_install() {
  [[ -d "$APP_DIR" ]] || die "APP_DIR does not exist: $APP_DIR"
  local venv="$APP_DIR/.venv"
  local req="$APP_DIR/backend/requirements.txt"
  [[ -f "$req" ]] || die "missing $req"

  if [[ ! -d "$venv" ]]; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
      log "creating venv at $venv"
      run python3 -m venv "$venv"
    else
      log "would create venv at $venv"
    fi
  fi

  log "pip install -r backend/requirements.txt"
  run "$venv/bin/pip" install -U pip
  run "$venv/bin/pip" install -r "$req"
}

ensure_data_dirs() {
  run mkdir -p "$APP_DIR/storage/receipts" "$APP_DIR/storage/public" "$APP_DIR/storage/archive" "$APP_DIR/storage/memories" "$APP_DIR/uploads"
}

fix_permissions() {
  need_root_for "install/update"
  local paths=(
    "$APP_DIR/storage"
    "$APP_DIR/uploads"
    "$APP_DIR/data.sqlite"
    "$APP_DIR/.venv"
  )
  for p in "${paths[@]}"; do
    if [[ -e "$p" ]]; then
      run chown -R "$RUN_USER:$RUN_USER" "$p"
    fi
  done
}

hint_systemd_unit() {
  local example="$APP_DIR/scripts/deploy/wewerehere.service.example"
  local unit="/etc/systemd/system/${SERVICE}.service"
  if [[ ! -f "$unit" && -f "$example" ]]; then
    log "systemd unit not found at $unit"
    log "  sudo cp $example $unit"
    log "  sudo systemctl daemon-reload && sudo systemctl enable --now $SERVICE"
  fi
}

ensure_wwh_deploy_cli() {
  # Delegate to ensure-wwh-deploy-cli.sh (writes /usr/local/bin/wwh-deploy +
  # enables wwh-deploy-cli.service so boot/restart always re-heals the CLI).
  local helper="$APP_DIR/scripts/deploy/ensure-wwh-deploy-cli.sh"
  [[ -f "$helper" ]] || return 0
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "would run $helper"
    return 0
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    return 0
  fi
  run chmod +x "$helper"
  APP_DIR="$APP_DIR" bash "$helper" || log "WARN: ensure-wwh-deploy-cli failed (non-fatal)"
}

cmd_install() {
  need_root_for install
  ensure_wwh_deploy_cli
  check_python
  install_apt_runtime_deps
  run cd "$APP_DIR"
  pip_install
  ensure_data_dirs
  install_ticket_font
  fix_permissions
  hint_systemd_unit
  log "install finished"
}

do_backup() {
  if [[ "$NO_BACKUP" -eq 1 || "$SKIP_BACKUP" == "1" ]]; then
    log "backup skipped"
    return 0
  fi
  need_root_for update
  local ts stamp archive items=()
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  stamp="${BACKUP_DIR}/wewerehere-${ts}.tar.gz"
  run mkdir -p "$BACKUP_DIR"

  [[ -f "$APP_DIR/data.sqlite" ]] && items+=("data.sqlite")
  [[ -d "$APP_DIR/storage" ]] && items+=("storage")
  [[ -d "$APP_DIR/uploads" ]] && items+=("uploads")

  if [[ ${#items[@]} -eq 0 ]]; then
    log "nothing to backup under $APP_DIR"
    return 0
  fi

  log "backup -> $stamp (${items[*]})"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    run tar -czf "$stamp" -C "$APP_DIR" "${items[@]}"
  else
    tar -czf "$stamp" -C "$APP_DIR" "${items[@]}"
  fi
}

do_git_pull() {
  if [[ "$NO_GIT" -eq 1 ]]; then
    log "git pull skipped (--no-git)"
    return 0
  fi
  [[ -d "$APP_DIR/.git" ]] || die "not a git repo: $APP_DIR"
  local deploy_script="scripts/deploy/wwh-deploy.sh"
  if ! git -C "$APP_DIR" diff --quiet HEAD -- "$deploy_script" 2>/dev/null; then
    log "discarding local edits to $deploy_script (use /etc/wewerehere/deploy.conf for overrides)"
    run git -C "$APP_DIR" checkout -- "$deploy_script"
  fi
  log "git fetch && pull $GIT_BRANCH"
  run git -C "$APP_DIR" fetch origin
  run git -C "$APP_DIR" checkout "$GIT_BRANCH"
  run git -C "$APP_DIR" pull --ff-only origin "$GIT_BRANCH"
}

do_migrate() {
  local py="$APP_DIR/.venv/bin/python"
  local script="$APP_DIR/backend/scripts/migrate_legacy.py"
  [[ -f "$script" ]] || die "missing $script"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    [[ -x "$py" ]] || die "venv python missing: $py"
  fi
  log "migrate_legacy.py"
  run "$py" "$script"
}

restart_service() {
  need_root_for update
  log "systemctl restart $SERVICE"
  run systemctl restart "$SERVICE"
}

wait_for_health() {
  local url="$HEALTH_URL"
  local attempt=1
  local max=45
  local health=""
  log "waiting for health (up to ${max}s) $url"
  while [[ "$attempt" -le "$max" ]]; do
    health="$(curl -fsS "$url" 2>/dev/null || true)"
    if [[ "$health" == *'"ok"'* && "$health" == *'true'* ]]; then
      if [[ "$health" != *'"backend":"fastapi"'* && "$health" != *'"backend": "fastapi"'* ]]; then
        log "WARN: health OK but backend is not FastAPI (legacy Node?)"
      fi
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  log "health never became ready; last response: ${health:-<empty>}"
  return 1
}

smoke_admin_ticket_png() {
  local base="${HEALTH_URL%/api/health}"
  local unit="/etc/systemd/system/${SERVICE}.service"
  local pw=""
  if [[ -f "$unit" ]]; then
    pw="$(sed -n 's/^Environment=ADMIN_PASSWORD=//p' "$unit" | head -1)"
  fi
  if [[ -z "$pw" ]]; then
    log "ticket PNG smoke skipped (no ADMIN_PASSWORD in $unit)"
    return 0
  fi
  local py="$APP_DIR/.venv/bin/python"
  if [[ ! -x "$py" ]]; then
    log "ticket PNG smoke skipped (venv python missing)"
    return 0
  fi
  log "smoke GET /api/admin/tickets/sample (expect PNG)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  if ! "$py" - "$base" "$pw" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base, pw = sys.argv[1], sys.argv[2]
login = urllib.request.Request(
    f"{base}/api/admin/login",
    data=json.dumps({"password": pw}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(login, timeout=20) as r:
        token = json.load(r)["token"]
except urllib.error.HTTPError as e:
    print(f"admin login failed: HTTP {e.code}", file=sys.stderr)
    sys.exit(1)
req = urllib.request.Request(
    f"{base}/api/admin/tickets/sample",
    headers={"Authorization": f"Bearer {token}"},
)
try:
    with urllib.request.urlopen(req, timeout=45) as r:
        ct = (r.headers.get("Content-Type") or "").lower()
        head = r.read(8)
except urllib.error.HTTPError as e:
    print(f"sample ticket failed: HTTP {e.code}", file=sys.stderr)
    sys.exit(1)
if "image/png" not in ct:
    print(f"unexpected content-type: {ct} (install libcairo2/libpango)", file=sys.stderr)
    sys.exit(1)
if head != b"\x89PNG\r\n\x1a\n":
    print("sample response is not PNG magic bytes", file=sys.stderr)
    sys.exit(1)
PY
  then
    log "ticket PNG smoke failed"
    return 1
  fi
  return 0
}

run_smoke_checks() {
  local base="${HEALTH_URL%/api/health}"
  log "smoke health $HEALTH_URL"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    run curl -fsS "$HEALTH_URL"
  elif ! wait_for_health; then
    log "health check failed: $HEALTH_URL"
    return 1
  fi

  local paths=(
    "/"
    "/track"
    "/admin"
    "/assets/wwh-theme.css"
    "/assets/wwh-shell.css"
    "/assets/wwh-chrome.js"
    "/assets/wwh-map.js"
    "/ticket-a.svg"
  )
  local p url code
  for p in "${paths[@]}"; do
    url="${base}${p}"
    log "smoke GET $url"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      run curl -fsS -o /dev/null "$url"
      continue
    fi
    code="$(curl -fsS -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")"
    if [[ "$code" != "200" ]]; then
      log "smoke failed: $url (HTTP $code)"
      return 1
    fi
  done
  smoke_admin_ticket_png || return 1
  log "smoke OK"
  return 0
}

cmd_smoke() {
  run_smoke_checks || die "smoke checks failed"
}

smoke_failure_hint() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  log "recent logs:"
  journalctl -u "$SERVICE" -n 40 --no-pager 2>/dev/null || true
}

cmd_update() {
  need_root_for update
  ensure_wwh_deploy_cli
  do_backup
  do_git_pull
  # Re-install CLI after pull (new APP_DIR / script path) and re-exec once so
  # the rest of update runs the freshly pulled wwh-deploy.sh when possible.
  ensure_wwh_deploy_cli
  if [[ "${WW_DEPLOY_REEXEC:-0}" != "1" ]]; then
    local fresh="$APP_DIR/scripts/deploy/wwh-deploy.sh"
    if [[ -f "$fresh" ]]; then
      log "re-exec update with pulled script (no-git, no-backup)"
      export WW_DEPLOY_REEXEC=1
      exec bash "$fresh" update --no-git --no-backup
    fi
  fi
  check_python
  install_apt_runtime_deps
  pip_install
  ensure_data_dirs
  install_ticket_font
  do_migrate || true
  fix_permissions
  restart_service
  if ! run_smoke_checks; then
    smoke_failure_hint
    ensure_wwh_deploy_cli
    exit 1
  fi
  ensure_wwh_deploy_cli
  log "update finished"
  log "NOTE: venue map on /track needs admin publish — set lat/lng + locationPublished for the event"
}

cmd_migrate() {
  do_migrate
}

cmd_status() {
  local active commit dbsize
  if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    active="active"
  else
    active="inactive"
  fi
  commit="n/a"
  if [[ -d "$APP_DIR/.git" ]]; then
    commit="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo n/a)"
  fi
  dbsize="missing"
  if [[ -f "$APP_DIR/data.sqlite" ]]; then
    dbsize="$(du -h "$APP_DIR/data.sqlite" | awk '{print $1}')"
  fi
  printf 'service=%s (%s)\n' "$SERVICE" "$active"
  printf 'git=%s branch=%s\n' "$commit" "$GIT_BRANCH"
  printf 'data.sqlite=%s\n' "$dbsize"
  printf 'app_dir=%s\n' "$APP_DIR"
  if [[ -x /usr/local/bin/wwh-deploy ]]; then
    printf 'cli=/usr/local/bin/wwh-deploy ok\n'
  else
    printf 'cli=MISSING — run: sudo bash %s/scripts/deploy/ensure-wwh-deploy-cli.sh\n' "$APP_DIR"
  fi
  if systemctl is-enabled --quiet wwh-deploy-cli.service 2>/dev/null; then
    printf 'cli_healer=enabled\n'
  else
    printf 'cli_healer=not-enabled\n'
  fi
  local font_path="$APP_DIR/assets/fonts/Vazirmatn-Regular.ttf"
  if [[ -f "$font_path" ]]; then
    printf 'vazirmatn_font=ok (%s)\n' "$font_path"
  else
    printf 'vazirmatn_font=MISSING\n'
  fi
  if command -v dpkg >/dev/null 2>&1; then
    if dpkg -l libcairo2 2>/dev/null | grep -q '^ii'; then
      printf 'libcairo2=installed\n'
    else
      printf 'libcairo2=missing (apt install libcairo2 libpango-1.0-0)\n'
    fi
  fi
  local unit="/etc/systemd/system/${SERVICE}.service"
  if [[ -f "$unit" ]]; then
    if grep -q uvicorn "$unit"; then
      printf 'runtime=uvicorn (FastAPI)\n'
    elif grep -qi node "$unit"; then
      printf 'runtime=node (legacy — switch to wewerehere.service.example)\n'
    fi
    grep -E '^WorkingDirectory=' "$unit" 2>/dev/null || true
    grep -E '^ExecStart=' "$unit" 2>/dev/null || true
  else
    printf 'systemd_unit=missing\n'
  fi
}

main() {
  parse_args "$@"
  load_config
  [[ "$NO_BACKUP" -eq 1 ]] && SKIP_BACKUP=1

  # Any root invocation re-heals /usr/local/bin/wwh-deploy (even status/smoke).
  if [[ "$(id -u)" -eq 0 ]]; then
    ensure_wwh_deploy_cli
  fi

  case "$CMD" in
    install) cmd_install ;;
    update) cmd_update ;;
    migrate) cmd_migrate ;;
    smoke) cmd_smoke ;;
    status) cmd_status ;;
    *) die "unknown command: $CMD" ;;
  esac
}

main "$@"
