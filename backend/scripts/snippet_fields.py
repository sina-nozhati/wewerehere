from pathlib import Path

s = Path(__file__).resolve().parents[2] / "ticket-a.svg"
text = s.read_text(encoding="utf-8")
out = []
for field in ("date", "time", "venue"):
    i = text.find(f'data-field="{field}"')
    out.append(field + ": " + text[i : i + 400])
Path(__file__).with_name("_snippets.txt").write_text("\n".join(out), encoding="utf-8")
