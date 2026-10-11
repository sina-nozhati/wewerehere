import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for name in ("ticket-a.svg", "ticket-b.svg"):
    s = (ROOT / name).read_text(encoding="utf-8")
    fields = re.findall(r'data-field="([^"]+)"', s)
    print(name, sorted(set(fields)))
