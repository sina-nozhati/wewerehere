import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "ticket-a.svg"
raw = path.read_text(encoding="utf-8")
# strip bx namespace for parse
raw = re.sub(r"\bbx:", "", raw)
root = ET.fromstring(raw)
out = []
for el in root.iter():
    if el.attrib.get("data-field") in ("date", "time", "venue"):
        attrs = {k: el.attrib.get(k) for k in el.attrib if k in (
            "data-field", "x", "y", "font-size", "class", "transform", "text-anchor"
        )}
        out.append(str(attrs) + " text=" + repr((el.text or "")[:40]))
Path(__file__).with_name("_ticket_styles.txt").write_text("\n".join(out), encoding="utf-8")
