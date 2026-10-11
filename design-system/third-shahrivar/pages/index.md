# Page Override — Landing + Registration (`index.html`)

> Overrides `design-system/third-shahrivar/MASTER.md` for the main landing page.

**Updated:** 2026-08-21

## Registration = 3-Step Payment Flow

The registration section is now a **3-step flow** (single page, no page reload):

1. **اطلاعات (Step 1)** — phone + quantity stepper + guest names
2. **پرداخت و رسید (Step 2)** — card info panel + receipt (text AND/OR image upload)
3. **تایید و دریافت (Step 3)** — pending confirmation → link to `/track`

### Step indicator
- `<ol class="steps">` with `<li class="step">` items, numbered `۱/۲/۳`
- `.step.is-active` → accent border + glow (`--glow-accent`)
- `.step.is-done` → success color
- RTL order (right-to-left), pill shaped (`--radius-full`)

### Card info panel (`.card-info`) — gothic SHETAB card
- Gothic framed card (`.gothic-frame` + `.gothic-card`): SHETAB brand, gold chip, big mono card number
- Bottom row: **مبلغ قابل پرداخت** (with ریال equivalent) on the **left**, **نام دارنده کارت** on the **right**
- Values come from `/api/payment-info` (admin-editable settings: card_number, card_holder, bank_name, ticket_price); env vars are the fallback
- Copy button on the card number

### Gothic atmosphere (whole page)
- Moon glow, drifting mist, vignette, floating embers, animated bats (appear/fly/vanish, random entry)
- **Fish (`mahi.svg`) — signature element**: rises from the deep ~1.5s after load, then periodically swims LEFT→RIGHT (random height, downward drift, `rotate(-90deg)` so the head faces right, lifelike wobble)
- All animations disabled under `prefers-reduced-motion`

### Sample tickets (`.ticket-stage`)
- Real ticket A/B designs (`ticket-a.svg` / `ticket-b.svg`) rendered on a gothic stage with `{{NO}}`/`{{CODE}}`/`{{NAME}}` filled with sample data (17 / 0427 / علی رضایی)

### Receipt upload (`.upload`)
- Dashed-border dropzone (`--radius-md`), accent border + glow on hover
- `.has-file` → solid success border + filename + inline preview image
- Receipt is **optional in either form**: text area OR image; at least one required
- Image sent to `/api/orders` as base64 (server stores to `uploads/receipts/`)

### Pending result (`.pending-result`)
- Clock icon in bordered square, "در انتظار تایید" + primary CTA → `/track`
- **No tickets are shown until admin approves** (server issues tickets on approve)

## Hero
- Accent heart SVG in the eyebrow (cute touch)
- Secondary CTA: `پیگیری بلیط` → `/track` (outline, small)

## Hero Re-UI (mobile-first)

- Scroll progress: `#scroll-progress` (accent red, RTL `scaleX`, [`assets/wwh-scroll.js`](assets/wwh-scroll.js))
- Column: `.hero__stack` `max-width: min(360px, …)` — ornament, date block, countdown grid, capacity pill, CTAs share one edge
- Typography: tagline ≥1.5rem; subline 1rem; countdown numbers `clamp(1.9rem, 9vw, 2.6rem)`; labels ≥0.8125rem; body ≥16px
- Schedule: [`assets/wwh-datetime.js`](assets/wwh-datetime.js) — tagline ordinal+month; subline `ساعت HH:MM · شهر`; episode chip only (no duplicate title)
- Countdown DOM order (RTL): روز → ساعت → دقیقه → ثانیه; past event → `#countdown-status` «رویداد برگزار شد»
- Capacity `.hero-capacity`: default accent border tint; `.is-low` (≤10) filled accent; `.sold-out` muted; `role="status"` atomic message
- CTAs: one primary `btn--filled` (56px); secondary pair in `.hero__cta-secondary` grid; mild `.btn--glow`
- Loader: `#wwh-loader` + [`assets/wwh-loader.js`](assets/wwh-loader.js); `wwh:loader-arm-spotlight` (~900ms) then fade; spotlight on first hero target before overlay lifts; `wwh:loader-done` after fade
- Stage spotlight: [`assets/wwh-spotlight.js`](assets/wwh-spotlight.js) — title → tagline → capacity+register; longer dwell on first two stops

## Dynamic landing (`assets/wwh-landing.js` + `GET /api/landing`)
- Hero date `#hero-date`, venue `#hero-venue`, capacity badge, footer `#footer-meta`
- Setlist rendered into `#setlist-list` from `event.setlist[]` (`title`, `artist`, `duration`)
- `salesStatus !== 'open'` → `#sales-closed-banner`, disabled registration CTAs
- Marquee text derived from featured event + remaining capacity

## Footer
- Shared chrome: [`assets/wwh-chrome.js`](assets/wwh-chrome.js) + [`assets/wwh-shell.css`](assets/wwh-shell.css) — mount `#wwh-footer-mount` on public pages
- `.footer__nav` links: اپیزودها / ثبت‌نام / ست لیست / پیگیری بلیط / پشتیبانی (`/support`) / دسترسی بعد از اجرا
- `#footer-meta` from `wwh-landing.js` on `/`; other pages via `/api/landing` in chrome
- Footer mark (mic icon) recolored to accent; mobile 2-column nav grid

## Gothic Atmosphere (added 2026-08-21)

- **Moon** — fixed pale circle behind the hero (low opacity, subtle pulse)
- **Mist** — two drifting fog layers across the viewport
- **Bats** — SVG bat silhouettes that fly across the screen (appear → swoop → disappear, random heights/directions, occasional accent-red tint)
- **Embers** — small glowing accent particles rising from the bottom (continuous, capped at ~14)
- **The fish (`/mahi.svg`)** — the site's main element: on load it rises from the deep through the hero (the "surprise"), then every ~45–75s it swims across the viewport at a random height/direction
- All ambience respects `prefers-reduced-motion` (disabled entirely)

## Gothic Payment Card

- `کارت به کارت به شماره زیر:` header, then a `gothic-frame` + `gothic-card`:
  - `SHETAB` brand (Cinzel, letterspaced) + gold chip, centered card number (JetBrains Mono, glow)
  - Bottom row: مبلغ قابل پرداخت (total = price × quantity, with ریال equivalent) / نام دارنده کارت
  - Meta row below: بانک + مبلغ هر بلیط

## Ticket Preview

- Shows **both designed tickets** (`/ticket-a.svg`, `/ticket-b.svg`) on a gothic backdrop (`gothic-frame` with corner ornaments), labeled گروه A / گروه B
- Sample placeholders: `No. 17` / `CODE: K7QM`; real tickets get the buyer's number + serial

## Notes
- No `letter-spacing` on Persian text; only on Latin/digits (mono serials & card numbers)
- All interactive elements use `--radius-md`; layout containers stay sharp
