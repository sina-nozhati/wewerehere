"""Apply ticket field anchors from design-system ticket-field-layout.json."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from app.config import ROOT

_LAYOUT_PATH = ROOT / "design-system" / "we-were-here" / "ticket-field-layout.json"
_XML_NS = "http://www.w3.org/XML/1998/namespace"


@lru_cache(maxsize=1)
def _layout_index() -> dict[str, dict[str, dict]]:
    raw = json.loads(_LAYOUT_PATH.read_text(encoding="utf-8"))
    return {entry["file"]: entry["fields"] for entry in raw}


def layout_fields_for_template(template_name: str) -> dict[str, dict]:
    fields = _layout_index().get(template_name)
    if fields is None:
        raise KeyError(f"no layout spec for template {template_name}")
    return fields


def _merge_style_font_size(style: str, font_size: str | None) -> str:
    if not font_size:
        return style
    if not style:
        return f"font-size:{font_size};"
    if re.search(r"font-size\s*:", style):
        style = re.sub(r"font-size\s*:[^;]+;?", f"font-size:{font_size};", style)
    else:
        style = style.rstrip(";") + f";font-size:{font_size};"
    return style


def _clear_position_attribs(el: ET.Element) -> None:
    for key in ("x", "y", "transform"):
        el.attrib.pop(key, None)


def apply_field_layout(root: ET.Element, template_name: str) -> None:
    """Set x/y/transform/text-anchor/direction from JSON on each data-field text node."""
    spec = layout_fields_for_template(template_name)
    for el in root.iter():
        field = el.attrib.get("data-field")
        if not field or field not in spec:
            continue
        cfg = spec[field]
        style = el.attrib.get("style", "")
        style = re.sub(r"display\s*:\s*none\s*;?", "", style, flags=re.I)
        style = _merge_style_font_size(style, cfg.get("font-size"))
        if style:
            el.attrib["style"] = style
        elif "style" in el.attrib and not el.attrib["style"].strip():
            del el.attrib["style"]

        _clear_position_attribs(el)
        transform = cfg.get("transform")
        if transform:
            el.set("transform", transform)
        else:
            if cfg.get("x") is not None:
                el.set("x", str(cfg["x"]))
            if cfg.get("y") is not None:
                el.set("y", str(cfg["y"]))

        anchor = cfg.get("text-anchor")
        if anchor:
            el.set("text-anchor", anchor)
        direction = cfg.get("direction")
        if direction:
            el.set("direction", direction)
            if direction == "rtl":
                el.set(f"{{{_XML_NS}}}lang", "fa")
            else:
                el.attrib.pop(f"{{{_XML_NS}}}lang", None)
