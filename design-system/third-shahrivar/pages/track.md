# Page Override — Ticket Tracking (`/track`)

> Overrides `design-system/third-shahrivar/MASTER.md` for the tracking page.

**Updated:** 2026-10-11

## Support
- پشتیبانی در `/support` — لینک از فرم lookup و chrome مشترک

## Purpose
A separate page (`track.html`, served at `/track`) so buyers who close the browser
before admin approval can recover their order + tickets by **phone number**.

## Layout
- **Chrome** — shared topbar + footer (`wwh-chrome.js`); no setlist on this page (setlist only on landing `/#setlist`; backup JSON in `data/setlists/third-shahrivar-track-page-snapshot.json`)
- **Hero** — small accent heart eyebrow «پیگیری بلیط», title `بلیطت کجاست؟`, subtitle reassuring
  users that nothing is lost if they closed the browser
- **Lookup form** — phone input (JetBrains Mono, LTR, centered) + pill button
- **Results** — order cards + ticket cards

## Order card (`.order`)
- Surface card, `--radius-md`
- Names (bold) + created date (`fa-IR` locale)
- Status badge: pending (warning) / approved (success) / rejected (danger)
- Receipt block: dashed-border box showing receipt text (pre-wrap) and/or image
- Rejected orders show the admin's note in a danger-bordered `.notice`

## Tickets
- Shown **only when the order is approved** (tickets issued server-side)
- Each ticket renders the **real designed SVG ticket** (`/ticket-a.svg` for group A, `/ticket-b.svg` for group B) on a gothic backdrop (`gothic-frame` + corner ornaments)
- Placeholders are filled with the buyer's own data: `No.` ← sequential ticket number (rank among all tickets — dynamic, renumbers on delete, 1..50), `CODE:` ← 4-digit serial, and the buyer's name on both the main body and the stub
- Ticket `No.` + `CODE` appear on **both** the main ticket body and the Entry stub
- `دانلود / چاپ تیکت` per ticket (print CSS strips the frame, prints the SVG itself)
- Empty state: dashed box with link back to `/#register`

## State
- No tickets → `سفارشی پیدا نشد` empty state
- Pending order with no tickets → order card only, badge tells user to wait
- Approved → order badge + full tickets list
