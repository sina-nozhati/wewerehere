"""End-to-end: order + receipt → admin approve → download ticket → layout audit."""
from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:5173"
RECEIPT = ROOT / "storage" / "receipts" / "1a12b72cfa9-15.png"
OUT_DIR = ROOT / "storage" / "_ticket_test" / "e2e-last-run"
LAYOUT = ROOT / "design-system" / "we-were-here" / "ticket-field-layout.json"
ADMIN_CANDIDATES = ("wewerehere-admin", "test-admin-pass", "admin")


def _req(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict | bytes, dict]:
    data = None
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in ctype:
                return resp.status, json.loads(raw.decode("utf-8")), dict(resp.headers)
            return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8")), {}
        except Exception:
            return e.code, raw, {}


def admin_token() -> str:
    for pwd in ADMIN_CANDIDATES:
        code, data, _ = _req("POST", "/api/admin/login", {"password": pwd})
        if code == 200 and isinstance(data, dict) and data.get("token"):
            print("admin login ok")
            return data["token"]
    raise SystemExit("admin login failed — set ADMIN_PASSWORD for running uvicorn")


def parse_fields(svg_text: str) -> dict[str, dict]:
    root = ET.fromstring(svg_text)
    out: dict[str, dict] = {}
    for el in root.iter():
        field = el.attrib.get("data-field")
        if not field:
            continue
        style = el.attrib.get("style") or ""
        text = (el.text or "").strip()
        out[field] = {
            "x": el.attrib.get("x"),
            "y": el.attrib.get("y"),
            "transform": el.attrib.get("transform"),
            "text": text,
            "hidden": "display:none" in style,
        }
    return out


def main() -> None:
    import time

    phone = "0912" + str(int(time.time()) % 10000000).zfill(7)
    holder = "سینا نزهتی"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    code, events_payload, _ = _req("GET", "/api/events")
    if code != 200:
        raise SystemExit(f"events HTTP {code}")
    events = events_payload.get("events") if isinstance(events_payload, dict) else events_payload
    if not events:
        raise SystemExit("no events")
    ev = next((e for e in events if e.get("isFeatured")), events[0])
    event_id = ev["id"]
    print("event", event_id, ev.get("slug"))

    if not RECEIPT.is_file():
        raise SystemExit(f"receipt image missing: {RECEIPT}")
    b64 = base64.b64encode(RECEIPT.read_bytes()).decode("ascii")
    order_body = {
        "phone": phone,
        "names": [holder],
        "receiptText": "E2E test receipt — automated flow",
        "receiptImage": {"mime": "image/png", "data": b64},
        "eventId": event_id,
    }
    code, order_res, _ = _req("POST", "/api/orders", order_body)
    if code not in (200, 201):
        raise SystemExit(f"order failed {code}: {order_res}")
    order_id = order_res["orderId"]
    print("order created", order_id)

    token = admin_token()
    code, appr, _ = _req(
        "POST",
        f"/api/admin/orders/approve?id={order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if code != 200:
        raise SystemExit(f"approve failed {code}: {appr}")
    print("approved", appr.get("tickets"))

    code, track, _ = _req("GET", f"/api/orders/track?phone={phone}&eventId={event_id}")
    if code != 200:
        raise SystemExit(f"track failed {code}")
    tickets = track.get("tickets") or []
    if not tickets:
        raise SystemExit("no tickets after approve")
    ticket = tickets[-1]
    serial = ticket["serial"]
    print("ticket", serial, ticket.get("name"))

    print_url = ticket["printUrl"]
    code, body, hdrs = _req("GET", f"{print_url}?serial={serial}&phone={phone}")
    if code != 200:
        raise SystemExit(f"download failed {code}")
    ctype = hdrs.get("Content-Type", hdrs.get("content-type", ""))
    if isinstance(body, bytes):
        if "svg" in ctype:
            svg_text = body.decode("utf-8")
            (OUT_DIR / "downloaded-ticket.svg").write_text(svg_text, encoding="utf-8")
            png_path = OUT_DIR / "downloaded-ticket.png"
            print("downloaded SVG (PNG export unavailable on server)")
        else:
            png_path = OUT_DIR / "downloaded-ticket.png"
            png_path.write_bytes(body)
            svg_text = None
            print("downloaded PNG", len(body), "bytes")
    else:
        raise SystemExit("unexpected download body")

    spec = json.loads(LAYOUT.read_text(encoding="utf-8"))
    template = next(e for e in spec if e["file"] == f"ticket-{ticket.get('group', 'A').lower()}.svg")
    if svg_text:
        filled = parse_fields(svg_text)
        report = {"serial": serial, "holder": holder, "fields": filled, "layout_ok": True, "issues": []}
        for field, exp in template["fields"].items():
            live = filled.get(field)
            if not live:
                report["layout_ok"] = False
                report["issues"].append(f"missing field {field}")
                continue
            if live["hidden"]:
                report["layout_ok"] = False
                report["issues"].append(f"{field} hidden")
            for key in ("x", "y", "transform"):
                if exp[key] != live[key]:
                    report["layout_ok"] = False
                    report["issues"].append(f"{field} {key}: expected {exp[key]} got {live[key]}")
            if not live["text"]:
                report["issues"].append(f"{field} empty text")
        if holder not in (svg_text if svg_text else ""):
            report["layout_ok"] = False
            report["issues"].append("holder name not in SVG")
        if serial not in (svg_text if svg_text else ""):
            report["layout_ok"] = False
            report["issues"].append("serial not in SVG")
        (OUT_DIR / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("layout_ok", report["layout_ok"])
        for issue in report["issues"]:
            print(" -", issue)
    else:
        (OUT_DIR / "audit.json").write_text(
            json.dumps({"serial": serial, "png_bytes": png_path.stat().st_size, "note": "visual check PNG manually"}, indent=2),
            encoding="utf-8",
        )

    meta = {
        "phone": phone,
        "orderId": order_id,
        "serial": serial,
        "trackUrl": f"{BASE}/track.html",
        "printUrl": f"{BASE}{print_url}?serial={serial}&phone={phone}",
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("artifacts", OUT_DIR)
    print("open track with phone", phone)


if __name__ == "__main__":
    main()
