# Page Override — Admin Panel (`/admin`)

> Overrides `design-system/third-shahrivar/MASTER.md` for the admin panel.

**Updated:** 2026-08-21

## New: Orders & Receipts review

A new section between Tickets and Media:

### Filter tabs (`.filter`)
- Pill buttons: در انتظار / تایید شده / رد شده / همه (default is **همه** so approved orders stay visible after approving or pressing تازه‌سازی)
- `.active` → accent background + glow

### Order card (`.order-card`)
- Surface card, `--radius-md`; pending orders get a subtle warning border
- Head: names + phone (mono) + created/reviewed dates + status badge
- Receipt box: dashed border, shows text (pre-wrap) and/or image
- Rejected orders show admin note in danger-bordered box

### Actions (pending only)
- **تایید و صدور بلیط** (`.ok` = success green) → `POST /api/admin/orders/approve?id=`
  — server issues one ticket per name, links `order_id`, then refresh orders + tickets
- **رد** (`.danger`) → prompt for optional note → `POST /api/admin/orders/reject?id=`
- Reviewed orders show a static status badge instead of buttons

## New: Payment settings (مشخصات کارت)

A **پرداخت — مشخصات کارت** section lets the admin edit the card shown on the landing page without touching env vars:

- شماره کارت (card_number), نام دارنده کارت (card_holder), نام بانک (bank_name), قیمت هر بلیط (ticket_price)
- **ذخیره** → `PUT /api/admin/settings` (stored in the `settings` table; overrides env defaults)
- Landing page fetches via `/api/payment-info`

## Style notes
- Same Gothic+Cute system: near-black bg, white text, single accent `#D43F5A`
- Inputs/selects/textarea: `--surface-2` bg, `--radius-sm`, accent focus ring
- Buttons rounded `--radius-md`; serials in JetBrains Mono
- Status badges reuse the shared pending/approved/rejected palette
