"""sms.ir Verify API client — no redirect follow, no secret logging."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("wwh.sms")

VERIFY_URL = "https://api.sms.ir/v1/send/verify"


def send_verify(
    *,
    mobile: str,
    template_id: int,
    parameters: list[dict[str, str]],
    api_key: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST /v1/send/verify. Returns {ok, message_id?, failure_kind?, cost?}."""
    if not api_key:
        return {"ok": False, "failure_kind": "missing_api_key"}
    if not template_id:
        return {"ok": False, "failure_kind": "missing_template"}
    if not mobile:
        return {"ok": False, "failure_kind": "invalid_mobile"}

    payload = {
        "mobile": mobile,
        "templateId": int(template_id),
        "parameters": [
            {"name": str(p.get("name") or ""), "value": str(p.get("value") or "")[:25]}
            for p in parameters
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        VERIFY_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-KEY": api_key,
        },
    )
    # Do not follow redirects with API key in headers.
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            http_status = getattr(resp, "status", None) or resp.getcode()
    except urllib.error.HTTPError as e:
        log.warning("smsir verify http_error status=%s", e.code)
        return {"ok": False, "failure_kind": f"http_{e.code}"}
    except urllib.error.URLError as e:
        log.warning("smsir verify network_error kind=%s", type(e.reason).__name__)
        return {"ok": False, "failure_kind": "network"}
    except TimeoutError:
        log.warning("smsir verify timeout")
        return {"ok": False, "failure_kind": "timeout"}
    except Exception:
        log.exception("smsir verify unexpected")
        return {"ok": False, "failure_kind": "unexpected"}

    if http_status != 200:
        log.warning("smsir verify bad_status status=%s", http_status)
        return {"ok": False, "failure_kind": f"http_{http_status}"}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("smsir verify invalid_json")
        return {"ok": False, "failure_kind": "invalid_json"}

    status = data.get("status")
    if status != 1:
        log.warning("smsir verify api_status=%s", status)
        return {"ok": False, "failure_kind": f"api_status_{status}"}

    inner = data.get("data") or {}
    message_id = inner.get("messageId")
    log.info("smsir verify ok message_id=%s", message_id)
    return {
        "ok": True,
        "message_id": message_id,
        "cost": inner.get("cost"),
    }
