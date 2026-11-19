# WE WERE HERE — Complete Dependency Map

> **Audit Date:** 2026-11-08  
> **Repository:** `WE WERE HERE` (`wewerehere`)

---

## 1. Frontend Pages to Asset Dependencies

Every frontend page runs directly in the browser and loads specific shared CSS and JS assets from the root or `/assets/` directory:

| Page | Stylesheets (.css) | Scripts (.js) | Static Assets (.svg/.jpg) |
|---|---|---|---|
| **`index.html`**<br>(Landing / Registration) | `wwh-theme.css`<br>`wwh-shell.css`<br>`wwh-hero.css`<br>`wwh-atmosphere.css`<br>`wwh-loader.css`<br>`wwh-perf.css` | `wwh-perf.js`<br>`wwh-loader.js`<br>`tickets.js`<br>`wwh-phone.js`<br>`wwh-datetime.js`<br>`wwh-chrome.js`<br>`wwh-landing.js`<br>`wwh-scroll.js`<br>`wwh-spotlight.js`<br>`wwh-atmosphere.js`<br>`wwh-fish.js` | `mahi.svg`<br>`wwh-favicon.jpg`<br>`apple-touch-icon.jpg`<br>`ticket-a.svg`<br>`ticket-b.svg` |
| **`track.html`**<br>(Ticket Tracking & View) | `wwh-theme.css`<br>`wwh-shell.css` | `wwh-map.js`<br>`wwh-datetime.js`<br>`wwh-chrome.js`<br>`wwh-api.js`<br>`wwh-phone.js`<br>`tickets.js` | `wwh-favicon.jpg`<br>`apple-touch-icon.jpg`<br>`ticket-a.svg`<br>`ticket-b.svg` |
| **`episodes.html`**<br>(Episode Directory) | `wwh-theme.css`<br>`wwh-shell.css` | `wwh-datetime.js`<br>`wwh-chrome.js` | `wwh-favicon.jpg`<br>`apple-touch-icon.jpg` |
| **`memories.html`**<br>(Disposable Camera Gallery) | `wwh-theme.css`<br>`wwh-shell.css`<br>`wwh-uploader.css`<br>`wwh-lightbox.css` | `wwh-chrome.js`<br>`wwh-uploader.js`<br>`wwh-lightbox.js` | `wwh-favicon.jpg`<br>`apple-touch-icon.jpg` |
| **`support.html`**<br>(Guest Support Chat) | `wwh-theme.css`<br>`wwh-shell.css` | `wwh-datetime.js`<br>`wwh-chrome.js`<br>`wwh-phone.js` | `wwh-favicon.jpg`<br>`apple-touch-icon.jpg` |
| **`admin.html`**<br>(Admin Operations Panel) | `wwh-theme.css`<br>`wwh-uploader.css`<br>`wwh-lightbox.css`<br>*(CDN flatpickr)* | `wwh-map.js`<br>`wwh-api.js`<br>`wwh-phone.js`<br>`wwh-uploader.js`<br>`wwh-lightbox.js`<br>*(CDN flatpickr, qrcodejs, chart.js)* | `wwh-favicon.jpg`<br>`apple-touch-icon.jpg` |

---

## 2. Frontend to Backend API Dependencies

```mermaid
flowchart LR
    subgraph Frontend Pages
        IDX[index.html]
        TRK[track.html]
        EPS[episodes.html]
        MEM[memories.html]
        SUP[support.html]
        ADM[admin.html]
    end

    subgraph API Routers
        PUB[routers/public.py]
        MEM_R[routers/memories.py]
        SUP_R[routers/support.py]
        ADM_R[routers/admin.py]
        STO_R[routers/storage_admin.py]
    end

    IDX -->|GET /api/events/featured, POST /api/orders| PUB
    TRK -->|POST /api/orders/track, GET /api/tickets/:token| PUB
    EPS -->|GET /api/events| PUB
    MEM -->|POST /api/memories/gate, GET /api/memories/items, POST /api/memories/upload| MEM_R
    SUP -->|POST /api/support/auth, GET /api/support/tickets, POST /api/support/messages| SUP_R
    ADM -->|POST /api/admin/auth, GET /api/admin/orders, POST /api/admin/orders/:id/approve| ADM_R
    ADM -->|POST /api/admin/sms/send, GET /api/admin/tickets/export| ADM_R
    ADM -->|GET /api/admin/storage/providers, POST /api/admin/storage/sync| STO_R
```

---

## 3. API Routers to Domain Services Mapping

| Router | File Path | Key Domain Services Invoked |
|---|---|---|
| **Public API** | `backend/app/routers/public.py` | `services.orders`<br>`services.capacity`<br>`services.tickets`<br>`services.ticket_render`<br>`services.events`<br>`services.phone` |
| **Admin API** | `backend/app/routers/admin.py` | `services.orders` (approval & rejection)<br>`services.capacity`<br>`services.tickets`<br>`services.ticket_render` (ZIP PNG/SVG export)<br>`services.notify` & `services.sms_ir`<br>`services.media_guard`<br>`services.events` |
| **Memories API** | `backend/app/routers/memories.py` | `services.memory_gate` (token check & rate limit)<br>`services.memory_media` (validation & dimensions)<br>`services.memory_audit`<br>`services.storage.upload_manager`<br>`services.storage.routing_manager` |
| **Support API** | `backend/app/routers/support.py` | `services.support_access`<br>`services.support_contacts`<br>`services.phone` |
| **Storage Admin API** | `backend/app/routers/storage_admin.py` | `services.storage.provider_manager`<br>`services.storage.routing_manager`<br>`services.storage.storage_monitor`<br>`services.storage.download_manager`<br>`services.storage.folder_manager` |

---

## 4. Domain Services to Infrastructure & Storage Mapping

```mermaid
flowchart TD
    subgraph Domain Services
        ORD[orders.py]
        TCK[tickets.py]
        TRND[ticket_render.py]
        TLYT[ticket_layout.py]
        MEMG[memory_gate.py]
        MEMM[memory_media.py]
        SMS[sms_ir.py]
        STOM[storage/*]
    end

    subgraph Data & Storage Models
        DB[(data.sqlite - SQLAlchemy)]
        LOC[storage/ - Local FS]
        FILES_IR[Files.ir API - Cloud]
        S3[S3 Bucket - Cloud]
        SMS_GW[sms.ir HTTP API]
    end

    subgraph Design & Layout Resources
        TPL_SVG[ticket-a.svg & ticket-b.svg]
        LYT_JSON[design-system/we-were-here/ticket-field-layout.json]
        FONT[assets/fonts/Vazirmatn-Regular.ttf]
    end

    ORD --> DB
    TCK --> DB
    TRND --> TCK
    TRND --> TLYT
    TLYT --> LYT_JSON
    TRND --> TPL_SVG
    TRND --> FONT
    MEMG --> DB
    MEMM --> STOM
    STOM --> DB
    STOM --> LOC
    STOM --> FILES_IR
    STOM --> S3
    SMS --> SMS_GW
```

---

## 5. Critical Files with Hidden or Non-Obvious Runtime Dependencies

1. **`design-system/we-were-here/ticket-field-layout.json`**:
   - Referenced in: `backend/app/services/ticket_layout.py:13`
   - Referenced in: `backend/tests/test_ticket_render_and_track.py:468`
   - Referenced in: `backend/scripts/measure_ticket_fields.py:36`
   - *Impact if moved or deleted:* **CRITICAL BREAKAGE** of ticket SVG and PNG rendering.

2. **`assets/fonts/Vazirmatn-Regular.ttf`**:
   - Referenced in: `backend/app/services/ticket_render.py:27`
   - Tested in: `backend/tests/test_deploy_assets.py:18`
   - *Impact if moved or deleted:* Broken ticket text rendering on server (CairoSVG / Pillow).

3. **`mahi.svg`**:
   - Referenced in: `assets/wwh-fish.js:26` and `line 38`
   - *Impact if moved or deleted:* Broken fish animation on landing page.

4. **`ticket-a.svg` & `ticket-b.svg`**:
   - Served directly from repository root via `backend/app/main.py:spa_static()`
   - Fetched by: `tickets.js:40`
   - Parsed by: `backend/app/services/ticket_render.py:65`
   - *Impact if moved or deleted:* Inability to display or download tickets.

5. **`backend/scripts/migrate_legacy.py`**:
   - Dynamically executed via subprocess by `backend/app/main.py:_maybe_migrate_legacy()`
   - Executed by: `scripts/deploy/wwh-deploy.sh:279`
   - *Impact if deleted prematurely:* Old deployments or databases lacking `events` table will fail startup or migration.
