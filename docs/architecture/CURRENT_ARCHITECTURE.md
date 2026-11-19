# WE WERE HERE — Current Architecture & Runtime Map

> **Date:** 2026-11-08  
> **Repository:** `WE WERE HERE` (`wewerehere`)  
> **Status:** Audited & Verified Against Live Repository & Test Suite (135 passing tests)

---

## 1. High-Level Architectural Overview

The **WE WERE HERE** platform is a multi-event cultural/music ticketing, tracking, disposable camera memory sharing, and event management platform.

```
                          ┌──────────────────────────────────────────────┐
                          │         Client Browsers (Mobile/Desktop)     │
                          └──────┬──────────────┬──────────────┬─────────┘
                                 │              │              │
           Static HTML / Assets  │              │ JSON API     │ Ticket Media / Downloads
                                 ▼              ▼              ▼
                          ┌──────────────────────────────────────────────┐
                          │               Nginx Reverse Proxy            │
                          │   Port 80/443 -> 127.0.0.1:5173 (Uvicorn)   │
                          │   client_max_body_size 150m, 300s/600s timeouts
                          └──────────────────────┬───────────────────────┘
                                                 │
                                                 ▼
                          ┌──────────────────────────────────────────────┐
                          │            FastAPI Backend (Uvicorn)         │
                          │            backend/app/main.py:app           │
                          ├──────────────────────────────────────────────┤
                          │  Routers:                                    │
                          │   - public.py        (/api/events, /api/orders)
                          │   - admin.py         (/api/admin/*)          │
                          │   - support.py       (/api/support/*)        │
                          │   - memories.py      (/api/memories/*)       │
                          │   - storage_admin.py (/api/admin/storage/*)  │
                          │   - spa_static       (SPA & root static files)
                          ├──────────────────────────────────────────────┤
                          │  Domain Services:                            │
                          │   - orders.py, capacity.py, tickets.py       │
                          │   - ticket_render.py, ticket_layout.py       │
                          │   - sms_ir.py, notify.py                     │
                          │   - memory_gate.py, memory_media.py          │
                          │   - Storage Engine (Files.ir, S3, Local)     │
                          └──────────────┬──────────────────┬────────────┘
                                         │                  │
                    Database Access (ORM)│                  │ Cloud / Media I/O
                                         ▼                  ▼
                          ┌────────────────────────┐  ┌──────────────────┐
                          │      SQLite DB         │  │   Media Storage  │
                          │    (data.sqlite)       │  │ - Files.ir (API) │
                          │ 22 relational tables   │  │ - S3 (Object)    │
                          │ Events, Orders, etc.   │  │ - Local storage/ │
                          └────────────────────────┘  └──────────────────┘
```

---

## 2. Runtimes & Execution Truth

### 2.1 The Sole Production Backend: FastAPI (Python 3.11+)
- **Runtime entrypoint:** `uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 5173`
- **Configuration source:** `backend/app/config.py` (reads environment variables and `.env`).
- **Production process manager:** `systemd` (`wewerehere.service` at `/etc/systemd/system/wewerehere.service`).
- **Production updater CLI:** `scripts/deploy/wwh-deploy.sh` (`wwh-deploy update`).
- **Verification status:** 135 automated tests in `backend/tests/` passed cleanly on 2026-11-08.

### 2.2 The Legacy Implementation: Node.js (`server.js`)
- **Status:** **Inactive in production.**
- **Details:** Node.js HTTP server utilizing built-in `node:sqlite`. It was the prototype backend designed for a single event (`CAPACITY=50`, fixed event name).
- **Incompatibilities:** It does **not** know about multi-event structures (`events` table), lacks the disposable camera subsystem (`memory_items`, `memory_sessions`), lacks the multi-provider storage engine (Files.ir / S3), lacks SMS verification templates, and lacks support ticketing.
- **Migration bridge:** `backend/scripts/migrate_legacy.py` is invoked automatically by `backend/app/main.py:_maybe_migrate_legacy()` when migrating an old single-event SQLite database into the modern multi-event schema.
- **Role today:** Kept purely for historical reference and backward compatibility migration.

---

## 3. Storage Architecture

The media storage subsystem operates under a multi-provider strategy managed by `backend/app/services/storage/`:

| Storage Provider | Role | Configuration |
|---|---|---|
| **Files.ir** | Primary cloud storage for guest memories and event photography | REST API adapter (`files_ir_adapter.py`), quota monitor |
| **S3-Compatible** | Fallback / alternative cloud object storage (ArvanCloud, Liara, MinIO, AWS S3) | S3 adapter (`s3_adapter.py`) |
| **Local Disk** | Emergency fallback & local development storage | Stored under `storage/` (`storage/receipts`, `storage/memories`, `storage/archive`) |

Key operational rules:
- Payment receipts are uploaded by users and saved locally to `storage/receipts/` (or legacy `uploads/receipts/`).
- Guest memories (photos/videos) go through `memory_gate.py` token verification, chunked/direct upload reservations, and post-event moderation.
- `storage/` and `uploads/` are live server state and must never be deleted or tracked in Git.

---

## 4. Frontend Architecture & Design System Reality

### 4.1 Authoritative Design System
- **Identity:** "Gothic + Cute" (Dark, dramatic, playful, high-contrast, Persian RTL-first).
- **Core Document:** `design-system/third-shahrivar/MASTER.md`
- **Core Theme Stylesheet:** `assets/wwh-theme.css`
- **Color Tokens:**
  - Background: `#0A0A0B` (`--color-bg`)
  - Surface: `#141416` (`--color-surface`)
  - Primary Text: `#FFFFFF` (`--color-primary`)
  - Secondary Text: `#B8B8C0` (`--color-secondary`)
  - Cute Accent: `#D43F5A` (`--color-accent`, hearts, glowing accents)
  - Success / Approved: `#5EC98B`
  - Warning / Pending: `#F5C542`
  - Danger / Rejected: `#FF5A5A`
- **Typography:**
  - Primary Persian UI & Headings: `Vazirmatn` (variable font).
  - Serial numbers, codes, card digits: `JetBrains Mono`.

### 4.2 Spurious Generated Document
- `design-system/we-were-here/MASTER.md` was generated on 2026-10-11 by an automated survey generator tool with teal `#0D9488`, orange `#D97706`, and `Atkinson Hyperlegible` font. It has **no relation** to the real WE WERE HERE product.
- **CRITICAL NOTE:** `design-system/we-were-here/ticket-field-layout.json` is **not** documentation; it is an active runtime JSON configuration containing SVG coordinate definitions read by `backend/app/services/ticket_layout.py`.

---

## 5. Summary of Application Routes & Interfaces

| URL Path | Type | File / Handler | Purpose |
|---|---|---|---|
| `/` | HTML | `index.html` | Public landing page, event registration, countdown, setlist |
| `/episodes` | HTML | `episodes.html` | List of all past and current event episodes |
| `/track` | HTML | `track.html` | Order tracking by phone number, ticket preview and download |
| `/events/{slug}/memories` | HTML | `memories.html` | Disposable camera guest gallery & upload portal |
| `/support` | HTML | `support.html` | Customer support chat & session lookup |
| `/admin` | HTML | `admin.html` | Admin dashboard: orders, capacity, tickets, SMS, storage |
| `/api/events` | REST | `routers/public.py` | Event listing and featured event metadata |
| `/api/orders` | REST | `routers/public.py` | Order creation & receipt upload |
| `/api/tickets/*` | REST | `routers/public.py` | Ticket download (SVG/PNG/PDF), tracking |
| `/api/admin/*` | REST | `routers/admin.py` | Order approval/rejection, ticket exports, settings |
| `/api/memories/*` | REST | `routers/memories.py` | Guest camera uploads, likes, comments, moderation |
| `/api/support/*` | REST | `routers/support.py` | Real-time support messaging |
| `/api/admin/storage/*` | REST | `routers/storage_admin.py` | Storage provider management and monitoring |
