"""Remove baked-in sample meta artwork (path letters) from ticket-a/b.svg."""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_BACKEND = ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.ticket_render import _strip_baked_sample_lettering, normalize_ticket_svg_xml  # noqa: E402


def patch_file(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"\bns\d+:", "", raw)
    root = ET.fromstring(raw)
    before = sum(1 for el in root.iter() if el.tag.endswith("path"))
    _strip_baked_sample_lettering(root)
    after = sum(1 for el in root.iter() if el.tag.endswith("path"))
    for el in root.iter():
        if el.tag.endswith("style") and el.text and "wwh-ticket-static-meta-values" in el.text:
            el.text = el.text.replace(".wwh-ticket-static-meta-values{display:none}", "").strip()
    out = normalize_ticket_svg_xml(ET.tostring(root, encoding="unicode", xml_declaration=True))
    path.write_text(out, encoding="utf-8")
    print(f"{path.name}: paths {before} -> {after}")


def main() -> None:
    for name in ("ticket-a.svg", "ticket-b.svg"):
        patch_file(ROOT / name)


if __name__ == "__main__":
    main()
