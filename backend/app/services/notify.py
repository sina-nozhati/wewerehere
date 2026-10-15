"""Ticket / admin SMS notifications (console sink or sms.ir)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import ROOT, settings
from app.services import sms_ir
from app.services.phone import normalize_phone, valid_phone

log = logging.getLogger("wwh.notify")

# SMS disabled until enamad / sms.ir template approval — set True to re-enable.
SMS_ENABLED = False

_CONSOLE_LOG = ROOT / "storage" / "sms-console.log"
_SMS_PARAM_MAX = 25
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _param_name() -> str:
    return (settings.sms_ir_verify_parameter_name or "CODE").strip() or "CODE"


def _to_fa_digits(n: int) -> str:
    return "".join(_FA_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(n))


def format_fa_name_list(names: list[str], *, max_len: int = _SMS_PARAM_MAX) -> str:
    """Join names for SMS: «آنا»، «آنا و هستی»، «آنا، هستی و امیرعلی». Cap at max_len."""
    cleaned = [str(n).strip() for n in (names or []) if n and str(n).strip()]
    if not cleaned:
        return ""

    def join_fa(parts: list[str]) -> str:
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]} و {parts[1]}"
        return "، ".join(parts[:-1]) + " و " + parts[-1]

    full = join_fa(cleaned)
    if len(full) <= max_len:
        return full

    # Smart shorten: «آنا و ۲ نفر دیگر» (fits sms.ir 25-char parameter limit)
    first = cleaned[0]
    others = len(cleaned) - 1
    if others <= 0:
        return first[:max_len]

    suffix = f" و {_to_fa_digits(others)} نفر دیگر"
    if len(first) + len(suffix) <= max_len:
        return first + suffix
    room = max_len - len(suffix)
    if room < 1:
        return first[:max_len]
    return first[:room] + suffix


def list_admin_presets() -> list[dict[str, Any]]:
    """Public preset list for admin UI (no secrets)."""
    raw = (settings.sms_ir_admin_presets or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            out = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("id") or "").strip()
                tid = int(item.get("templateId") or 0)
                if not pid or not tid:
                    continue
                out.append(
                    {
                        "id": pid,
                        "label": str(item.get("label") or pid),
                        "paramName": str(item.get("param") or _param_name()),
                        "templateId": tid,
                    }
                )
            if out:
                return out
        except (json.JSONDecodeError, TypeError, ValueError):
            log.warning("invalid SMS_IR_ADMIN_PRESETS json")

    presets = []
    ticket_tid = int(settings.sms_ir_template_id_ticket_notify or 0)
    admin_tid = int(settings.sms_ir_template_id_admin or 0)
    if ticket_tid:
        presets.append(
            {
                "id": "ticket",
                "label": "صدور بلیت",
                "paramName": _param_name(),
                "templateId": ticket_tid,
            }
        )
    if admin_tid:
        presets.append(
            {
                "id": "notice",
                "label": "اطلاع‌رسانی",
                "paramName": _param_name(),
                "templateId": admin_tid,
            }
        )
    if not presets:
        # Dev-friendly placeholders so UI still works with console provider.
        presets = [
            {
                "id": "ticket",
                "label": "صدور بلیت",
                "paramName": _param_name(),
                "templateId": ticket_tid or 0,
            },
            {
                "id": "notice",
                "label": "اطلاع‌رسانی",
                "paramName": _param_name(),
                "templateId": admin_tid or 0,
            },
        ]
    return presets


def _preset_by_id(preset_id: str) -> dict[str, Any] | None:
    for p in list_admin_presets():
        if p["id"] == preset_id:
            return p
    return None


def _console_send(mobile: str, template_id: int, parameters: list[dict[str, str]]) -> dict[str, Any]:
    line = {
        "at": datetime.now(timezone.utc).isoformat(),
        "provider": "console",
        "mobile_masked": _mask_phone(mobile),
        "templateId": template_id,
        "parameters": parameters,
    }
    try:
        _CONSOLE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _CONSOLE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("console sms sink write failed")
    log.info("console sms templateId=%s mobile=%s", template_id, _mask_phone(mobile))
    return {"ok": True, "message_id": "console", "provider": "console"}


def _mask_phone(phone: str) -> str:
    p = phone or ""
    if len(p) < 7:
        return "***"
    return p[:4] + "****" + p[-3:]


def send_verify_dispatch(
    *,
    mobile: str,
    template_id: int,
    parameters: list[dict[str, str]],
) -> dict[str, Any]:
    # --- SMS provider body (kept for later; enamad / template approval) ---
    if not SMS_ENABLED:
        return {"ok": False, "failure_kind": "sms_disabled", "provider": "disabled"}
    provider = (settings.sms_provider or "console").strip().lower()
    if provider == "smsir":
        result = sms_ir.send_verify(
            mobile=mobile,
            template_id=template_id,
            parameters=parameters,
            api_key=settings.sms_ir_api_key or "",
            timeout=float(settings.sms_ir_timeout or 10),
        )
        result["provider"] = "smsir"
        return result
    return _console_send(mobile, template_id, parameters)


def notify_tickets_issued(phone: str, tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """One verify SMS per order: #NAMES# + #PHONE# (track link built in sms.ir template)."""
    if not SMS_ENABLED:
        return {"sent": 0, "failed": 0, "failure_kind": "sms_disabled", "disabled": True}
    phone = normalize_phone(phone)
    if not valid_phone(phone):
        return {"sent": 0, "failed": 0, "failure_kind": "invalid_phone"}
    if not tickets:
        return {"sent": 0, "failed": 0, "failure_kind": "no_tickets"}

    template_id = int(settings.sms_ir_template_id_ticket_notify or 0)
    if (settings.sms_provider or "").lower() == "smsir" and not template_id:
        log.warning("ticket notify skipped: missing template id")
        return {"sent": 0, "failed": 1, "failure_kind": "missing_template"}

    names = [str(t.get("name") or "").strip() for t in tickets if t.get("name")]
    names_value = format_fa_name_list(names)
    if not names_value:
        return {"sent": 0, "failed": 1, "failure_kind": "missing_names"}

    result = send_verify_dispatch(
        mobile=phone,
        template_id=template_id,
        parameters=[
            {"name": "NAMES", "value": names_value[:_SMS_PARAM_MAX]},
            {"name": "PHONE", "value": phone[:_SMS_PARAM_MAX]},
        ],
    )
    if result.get("ok"):
        return {"sent": 1, "failed": 0}
    return {
        "sent": 0,
        "failed": 1,
        "failure_kind": result.get("failure_kind") or "send_failed",
    }


def send_admin_preset(phone: str, preset_id: str, value: str) -> dict[str, Any]:
    if not SMS_ENABLED:
        return {"ok": False, "failure_kind": "sms_disabled", "provider": "disabled"}
    phone = normalize_phone(phone)
    if not valid_phone(phone):
        return {"ok": False, "failure_kind": "invalid_phone"}
    preset = _preset_by_id(preset_id)
    if not preset:
        return {"ok": False, "failure_kind": "unknown_preset"}
    value = (value or "").strip()[:25]
    if not value:
        return {"ok": False, "failure_kind": "empty_value"}
    template_id = int(preset.get("templateId") or 0)
    if (settings.sms_provider or "").lower() == "smsir" and not template_id:
        return {"ok": False, "failure_kind": "missing_template"}
    result = send_verify_dispatch(
        mobile=phone,
        template_id=template_id,
        parameters=[{"name": str(preset.get("paramName") or _param_name()), "value": value}],
    )
    return {
        "ok": bool(result.get("ok")),
        "failure_kind": result.get("failure_kind"),
        "message_id": result.get("message_id"),
        "provider": result.get("provider"),
        "phone_masked": _mask_phone(phone),
    }
