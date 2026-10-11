"""One-off patch: vertical watermark name on main ticket, clear stub name slot."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MAIN_NAME = (
    '<text data-field="name" direction="rtl" xml:space="preserve" '
    'style="white-space:pre;fill:#1a1520;font-family:\'Vazirmatn\',sans-serif;'
    "font-size:12px;font-weight:500;opacity:0.24;"
    '" transform="translate(265,22) rotate(90)" text-anchor="start">'
    "</text>"
)

STUB_PATTERN = re.compile(
    r'<text style="white-space: pre; fill: rgb\(51, 51, 51\);[^"]*" x="285" y="84\.507" '
    r'transform="matrix\(0\.28, 0, 0, 0\.28, [^"]+\)" data-field="name">\s*</text>',
    re.DOTALL,
)

OLD_MAIN = re.compile(
    r'<text data-field="name" direction="rtl" xml:space="preserve" style="white-space:pre;fill:#231f20;font-family:\'Vazirmatn\',sans-serif;font-size:10px;font-weight:500;" transform="matrix\(0\.93,0,0,0\.93,58,74\)" text-anchor="start">\s*</text>'
)

for fname in ("ticket-a.svg", "ticket-b.svg"):
    path = ROOT / fname
    s = path.read_text(encoding="utf-8")
    if not OLD_MAIN.search(s):
        print("skip main", fname)
    else:
        s = OLD_MAIN.sub(MAIN_NAME, s, count=1)
    s2, n = STUB_PATTERN.subn(
        '<text data-field="name_stub" style="display:none" aria-hidden="true"></text>', s
    )
    if n:
        s = s2
    else:
        print("stub not replaced", fname)
    path.write_text(s, encoding="utf-8")
    print("patched", fname)
