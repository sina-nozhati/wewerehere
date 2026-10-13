# Admin panel — page overrides

> Overrides [`MASTER.md`](../MASTER.md) for the live admin shell in `admin.html`.
> The production admin UI is **dark** (WWH night tokens), not the light teal survey palette in Master.

## Surface

| Role | Token / value |
|------|----------------|
| Background | `--bg` `#0a0a0b` |
| Surface / card | `--surface` `#141416` |
| Border | `--border` `#2a2a2e` |
| Accent | `--accent` `#d43f5a` |
| Success | `--ok` `#5ec98b` |
| Danger | `--danger` `#ff5a5a` |
| Muted text | `--muted` `#7a7a85` |

Spacing follows Master rhythm (`--space-md` 16px gaps in form grids, 24px card padding).

## SMS compose section

- One card, one job: send a Verify-template SMS.
- Fields: phone (`data-wwh-phone`), preset select, param value (max 25).
- Failed submit: focusable error summary (`role="alert"`) + inline field `.error` borders.
- Submit feedback: loading → `.status.ok` / `.status.err` with `aria-live="polite"`.
- Touch targets ≥ 44px (existing admin buttons).

## Anti-patterns

- Do not introduce Master light teal cards into admin.
- Do not show full phone or API key in success toasts (masked only).
