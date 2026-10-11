import sys
import xml.etree.ElementTree as ET
from pathlib import Path

p = Path(sys.argv[1])
root = ET.parse(p).getroot()
out = Path(__file__).with_name("_ticket_fields.txt")
lines = []
for el in root.iter():
    field = el.attrib.get("data-field")
    if field:
        text = (el.text or "").strip()
        lines.append(f"{field}: {text}")
out.write_text("\n".join(lines), encoding="utf-8")
