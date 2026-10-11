# چیدمان بلیت (داده‌محور)

- **قالب:** `ticket-a.svg` / `ticket-b.svg` — `viewBox="0 0 362 128"` (¼ مقیاس رفرنس ۱۴۴۸×۵۱۲).
- **منبع مختصات:** `design-system/we-were-here/ticket-field-layout.json` (خروجی `backend/scripts/measure_ticket_fields.py`).
- **گروه داینامیک:** `<g id="wwh-dynamic">` — همهٔ `data-field`ها بدون transform والد گمراه‌کننده.
- **baseline رندر:** `storage/_ticket_test/baseline-guilanshah.svg` (از `seed_guilanshah_ticket.py`).

| فیلد | نقش |
|------|-----|
| `date`, `time`, `venue` | متا رویداد (جلالی / ساعت / محل) |
| `city_line` | `translate(11, 55) rotate(90)` |
| `date` | `x=176.5`, `y=65` |
| `time` | `x=112.5`, `y=77.25`, `font-size:8.5px` |
| `venue` | `x=199`, `y=88.75` |
| `no1` / `code1` | `73,117` (12px) / `180,117` |
| `no2` / `code2` (stub) | `317,56.5` / `317,71` |
| `name` | نام عمودی (واترمارک) |
| `no1`, `code1` | شماره و کد — بدنه اصلی |
| `no2`, `code2`, `name_stub` | همان مقادیر — stub ورود |
