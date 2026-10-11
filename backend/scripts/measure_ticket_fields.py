"""Print data-field layout attributes from ticket-a.svg / ticket-b.svg."""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def measure(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([^"]+)"', raw)
    root = ET.fromstring(raw)
    fields = {}
    for el in root.iter():
        field = el.attrib.get("data-field")
        if not field:
            continue
        style = el.attrib.get("style") or ""
        fields[field] = {
            "x": el.attrib.get("x"),
            "y": el.attrib.get("y"),
            "transform": el.attrib.get("transform"),
            "text-anchor": el.attrib.get("text-anchor"),
            "direction": el.attrib.get("direction"),
            "hidden": "display:none" in style or el.attrib.get("aria-hidden") == "true",
            "font-size": re.search(r"font-size:([^;]+)", style).group(1) if "font-size" in style else None,
        }
    return {"file": path.name, "viewBox": vb.group(1) if vb else None, "fields": fields}


def main() -> None:
    out = [measure(ROOT / n) for n in ("ticket-a.svg", "ticket-b.svg")]
    text = json.dumps(out, ensure_ascii=False, indent=2)
    dest = ROOT / "design-system" / "we-were-here" / "ticket-field-layout.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(text)
    if "--write-only" not in sys.argv:
        pass


if __name__ == "__main__":
    main()
