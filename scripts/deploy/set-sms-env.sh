#!/usr/bin/env bash
# Write /etc/wewerehere/sms.env and restart wewerehere.
# Usage:
#   sudo bash scripts/deploy/set-sms-env.sh \
#     --api-key 'YOUR_KEY' \
#     --ticket-template 123456 \
#     --admin-template 123457
set -euo pipefail

OUT=/etc/wewerehere/sms.env
PROVIDER=smsir
API_KEY=""
TICKET_TID=""
ADMIN_TID=""
PARAM=CODE
TIMEOUT=10
RESTART=1

usage() {
  cat <<EOF
Usage: sudo bash $0 --api-key KEY --ticket-template ID [--admin-template ID]

Options:
  --api-key KEY           sms.ir X-API-KEY
  --ticket-template ID    TemplateId for ticket issued SMS
  --admin-template ID     TemplateId for admin compose presets
  --param NAME            Verify parameter name (default CODE)
  --provider NAME         console|smsir (default smsir)
  --no-restart            Do not systemctl restart wewerehere
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-key) API_KEY="$2"; shift 2 ;;
    --ticket-template) TICKET_TID="$2"; shift 2 ;;
    --admin-template) ADMIN_TID="$2"; shift 2 ;;
    --param) PARAM="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --no-restart) RESTART=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run as root" >&2
  exit 1
fi
if [[ -z "$API_KEY" || -z "$TICKET_TID" ]]; then
  echo "ERROR: --api-key and --ticket-template are required" >&2
  usage
  exit 1
fi

mkdir -p /etc/wewerehere
umask 077
cat >"$OUT" <<EOF
SMS_PROVIDER=$PROVIDER
SMS_IR_API_KEY=$API_KEY
SMS_IR_TEMPLATE_ID_TICKET_NOTIFY=$TICKET_TID
SMS_IR_TEMPLATE_ID_ADMIN=${ADMIN_TID:-$TICKET_TID}
SMS_IR_VERIFY_PARAMETER_NAME=$PARAM
SMS_IR_TIMEOUT=$TIMEOUT
EOF
chmod 600 "$OUT"
echo "wrote $OUT"

UNIT=/etc/systemd/system/wewerehere.service
if [[ -f "$UNIT" ]] && ! grep -q 'EnvironmentFile=-/etc/wewerehere/sms.env' "$UNIT"; then
  # Insert EnvironmentFile after [Service] if missing
  if grep -q '^\[Service\]' "$UNIT"; then
    tmp="$(mktemp)"
    awk '
      BEGIN{done=0}
      /^\[Service\]$/ && !done { print; print "EnvironmentFile=-/etc/wewerehere/sms.env"; done=1; next }
      { print }
    ' "$UNIT" >"$tmp"
    install -m 644 "$tmp" "$UNIT"
    rm -f "$tmp"
    systemctl daemon-reload
    echo "added EnvironmentFile to wewerehere.service"
  fi
fi

if [[ "$RESTART" -eq 1 ]]; then
  systemctl restart wewerehere
  echo "restarted wewerehere"
fi
echo "done — try admin SMS panel or approve an order"
