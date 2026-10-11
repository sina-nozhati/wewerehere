"""One-off: reposition meta fields, hide static sample values, adjust name Y."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OLD_META = (
    '<text class="cls-6" transform="matrix(0, -1, 1, 0, 17.757817, 117.920122)" style="white-space: pre;">'
    '<tspan data-field="date" x="0" y="0" style="font-family:\'Vazirmatn\',sans-serif;font-size:8px;word-spacing:0px;"></tspan>'
    '<tspan data-field="time" x="0" y="11" style="font-family:\'Vazirmatn\',sans-serif;font-size:8px;word-spacing:0px;"></tspan>'
    '<tspan data-field="venue" x="0" y="22" style="font-family:\'Vazirmatn\',sans-serif;font-size:8px;word-spacing:0px;"></tspan>'
    "</text>"
)

NEW_META = """<g id="wwh-ticket-dynamic-meta">
<text data-field="date" direction="rtl" x="128" y="61" text-anchor="start" style="font-family:'Vazirmatn',sans-serif;font-size:9.5px;fill:#231f20;"></text>
<text data-field="time" direction="ltr" x="128" y="71" text-anchor="start" style="font-family:'Vazirmatn',sans-serif;font-size:9.5px;fill:#231f20;unicode-bidi:embed;"></text>
<text data-field="venue" direction="rtl" x="128" y="81" text-anchor="start" style="font-family:'Vazirmatn',sans-serif;font-size:9px;fill:#231f20;"></text>
</g>"""

CITY_LINE = (
    '<text data-field="city_line" direction="ltr" transform="translate(20, 16) rotate(90)" '
    "text-anchor=\"start\" style=\"font-family:'Vazirmatn',sans-serif;font-size:8px;"
    'fill:#231f20;letter-spacing:0.02em;"></text>'
)

HIDE_STYLE = "<style>.wwh-ticket-static-meta-values{display:none}</style>"

STATIC_GROUP = '<g transform="matrix(1, 0, 0, 1, -17.301855, 0)">'
STATIC_GROUP_HIDDEN = (
    '<g transform="matrix(1, 0, 0, 1, -17.301855, 0)" class="wwh-ticket-static-meta-values">'
)

NAME_TRANSFORM_OLD = 'transform="translate(265,22) rotate(90)"'
NAME_TRANSFORM_NEW = 'transform="translate(265,-18) rotate(90)"'


def patch_common(text: str) -> str:
    if OLD_META in text:
        text = text.replace(OLD_META, NEW_META)
    if STATIC_GROUP in text:
        text = text.replace(STATIC_GROUP, STATIC_GROUP_HIDDEN, 1)
    if HIDE_STYLE not in text:
        text = text.replace("</style>", HIDE_STYLE + "</style>", 1)
    text = text.replace(NAME_TRANSFORM_OLD, NAME_TRANSFORM_NEW)
    return text


def main() -> None:
    for name in ("ticket-a.svg", "ticket-b.svg"):
        path = ROOT / name
        raw = path.read_text(encoding="utf-8")
        raw = re.sub(r"\bbx:", "", raw)
        out = patch_common(raw)
        path.write_text(out, encoding="utf-8")
        print("patched", name)


if __name__ == "__main__":
    main()
