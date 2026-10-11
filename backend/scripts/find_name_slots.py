import re
from pathlib import Path

for name in ("ticket-a.svg", "ticket-b.svg"):
    s = (Path(__file__).resolve().parents[2] / name).read_text(encoding="utf-8")
    for m in re.finditer(r'<text[^>]*data-field="name"[^>]*>', s):
        print(name, m.group(0)[:500])
    for m in re.finditer(r'<tspan[^>]*data-field="name"[^>]*>', s):
        print(name, "tspan", m.group(0)[:500])
