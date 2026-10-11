"""Apply canonical WWH ticket field layout (viewBox 362×128, scaled from 1448×512)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from app.services.ticket_render import normalize_ticket_svg_xml

ROOT = Path(__file__).resolve().parents[2]
SVG_NS = "http://www.w3.org/2000/svg"

SCALE_X = 362 / 1448
SCALE_Y = 128 / 512


def _s(x: float, y: float) -> tuple[str, str]:
    return (f"{x * SCALE_X:.3f}".rstrip("0").rstrip("."), f"{y * SCALE_Y:.3f}".rstrip("0").rstrip("."))


# Reference layout from design spec (1448×512 → SVG user units).
REF = {
    "date": (450, 264),
    "time": (450, 309),
    "venue": (450, 355),
    "no1": (202, 469),
    "code1": (600, 469),
    "name": (1090, 218),
    "city_line": (43, 390),
    "no2": (1184, 226),
    "code2": (1184, 282),
    "name_stub": (1275, 380),
}

FIELD_ORDER = (
    "date",
    "time",
    "venue",
    "city_line",
    "name",
    "no1",
    "code1",
    "no2",
    "code2",
    "name_stub",
)

# Visual tuning vs raw ref×scale (static artwork labels, rotate anchors).
LAYOUT_TUNING: dict[str, dict[str, str]] = {
    "date": {"x": "176.5", "y": "65"},
    "time": {
        "x": "112.5",
        "y": "77.25",
        "style": "font-family:'Vazirmatn',sans-serif;fill:#231f20;font-size:8.5px;unicode-bidi:embed;",
    },
    "venue": {"x": "199", "y": "88.75"},
    "city_line": {"transform": "translate(11, 55) rotate(90)"},
    "no1": {
        "x": "73",
        "y": "117",
        "style": "font-family:Consolas,'Courier New',monospace;font-weight:700;fill:#333;font-size:12px;",
    },
    "code1": {"x": "180", "y": "117"},
    "no2": {"x": "317", "y": "56.5"},
    "code2": {"x": "317", "y": "71"},
}


def _tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


def _remove_field_nodes(root: ET.Element) -> None:
    kill: list[ET.Element] = []
    for el in root.iter():
        if el.attrib.get("data-field"):
            kill.append(el)
    for el in kill:
        parent = None
        for p in root.iter():
            if el in list(p):
                parent = p
                break
        if parent is None:
            continue
        if el.tag.endswith("tspan"):
            # Drop whole <text> if it only held dynamic tspans (+ optional static prefix).
            text_parent = parent
            if text_parent.tag.endswith("text"):
                parent.remove(el)
                if not list(text_parent) and not (text_parent.text or "").strip():
                    gp = None
                    for g in root.iter():
                        if text_parent in list(g):
                            gp = g
                            break
                    if gp is not None:
                        gp.remove(text_parent)
                elif text_parent.attrib.get("data-field") is None:
                    # Leave static "No." / "Code:" label text without empty tspan.
                    pass
            else:
                parent.remove(el)
        else:
            parent.remove(el)

    # Remove empty meta group from older patches.
    for g in list(root.iter()):
        if g.attrib.get("id") == "wwh-ticket-dynamic-meta":
            gp = None
            for p in root.iter():
                if g in list(p):
                    gp = p
                    break
            if gp is not None:
                gp.remove(g)
        if g.attrib.get("id") == "wwh-dynamic":
            gp = None
            for p in root.iter():
                if g in list(p):
                    gp = p
                    break
            if gp is not None:
                gp.remove(g)


def _style_for(field: str) -> str:
    base = "font-family:'Vazirmatn',sans-serif;fill:#231f20;"
    mono = "font-family:Consolas,'Courier New',monospace;font-weight:700;fill:#333;"
    if field == "date":
        return base + "font-size:9.5px;"
    if field == "time":
        return base + "font-size:9.5px;unicode-bidi:embed;"
    if field == "venue":
        return base + "font-size:9px;"
    if field == "city_line":
        return base + "font-size:8px;letter-spacing:0.02em;"
    if field == "name":
        return "white-space:pre;fill:#1a1520;font-family:'Vazirmatn',sans-serif;font-size:12px;font-weight:500;opacity:0.24;"
    if field == "name_stub":
        return "font-family:'Vazirmatn',sans-serif;font-size:9px;fill:#231f20;"
    if field in ("no1", "no2", "code1", "code2"):
        return mono + "font-size:9px;"
    return base


def _append_dynamic_group(root: ET.Element) -> None:
    g = ET.Element(_tag("g"), {"id": "wwh-dynamic"})
    for field in FIELD_ORDER:
        rx, ry = REF[field]
        x, y = _s(rx, ry)
        attribs = {
            "data-field": field,
            "style": _style_for(field),
        }
        if field == "name":
            attribs["direction"] = "rtl"
            attribs["transform"] = f"translate({x}, {y}) rotate(90)"
            attribs["text-anchor"] = "start"
            attribs["xml:space"] = "preserve"
        elif field == "city_line":
            attribs["direction"] = "ltr"
            attribs["transform"] = f"translate({x}, {y}) rotate(90)"
            attribs["text-anchor"] = "start"
        elif field == "name_stub":
            attribs["direction"] = "rtl"
            attribs["x"] = x
            attribs["y"] = y
            attribs["text-anchor"] = "end"
        elif field == "time":
            attribs["direction"] = "ltr"
            attribs["x"] = x
            attribs["y"] = y
            attribs["text-anchor"] = "start"
        elif field == "date":
            attribs["direction"] = "rtl"
            attribs["x"] = x
            attribs["y"] = y
            attribs["text-anchor"] = "start"
        elif field == "venue":
            attribs["direction"] = "rtl"
            attribs["x"] = x
            attribs["y"] = y
            attribs["text-anchor"] = "start"
        else:
            attribs["direction"] = "ltr"
            attribs["x"] = x
            attribs["y"] = y
            attribs["text-anchor"] = "start"
        for key, val in LAYOUT_TUNING.get(field, {}).items():
            if key == "style":
                attribs["style"] = val
            elif key == "transform":
                attribs["transform"] = val
                attribs.pop("x", None)
                attribs.pop("y", None)
            else:
                attribs[key] = val
        g.append(ET.Element(_tag("text"), attribs))
    root.append(g)


def patch_file(path: Path) -> None:
    raw = normalize_ticket_svg_xml(path.read_text(encoding="utf-8"))
    raw = re.sub(r"\bbx:", "", raw)
    root = ET.fromstring(raw)
    _remove_field_nodes(root)
    _append_dynamic_group(root)
    out = ET.tostring(root, encoding="unicode")
    if not out.startswith("<?xml"):
        out = "<?xml version='1.0' encoding='utf-8'?>\n" + out
    path.write_text(normalize_ticket_svg_xml(out), encoding="utf-8")


def main() -> None:
    for name in ("ticket-a.svg", "ticket-b.svg"):
        patch_file(ROOT / name)
        print("patched", name)


if __name__ == "__main__":
    main()
