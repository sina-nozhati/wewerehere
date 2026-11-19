# WE WERE HERE — Complete File & Component Classification

> **Classification Scheme:**
> - **[A] ACTIVE PRODUCTION:** Mandatory for production application runtime, API, UI, or deployment.
> - **[B] ACTIVE DEVELOPMENT / QA:** Diagnostics, test suite, developer scripts, and fixtures.
> - **[C] LEGACY / BACKWARD COMPATIBILITY:** Preserved for migration, rollback, or schema compatibility.
> - **[D] DOCUMENTATION / ARCHIVE:** Technical docs, design history, historical data snapshots.
> - **[E] POTENTIALLY UNUSED:** No verified runtime, build, or test dependency.
> - **[F] REDUNDANT / DUPLICATED:** Conflicting generated templates, duplicate logic, or scratch logs.

---

## 1. Web Pages & Frontend Assets

| File Path | Classification | Role / Purpose | Dependencies / References | Recommendation |
|---|:---:|---|---|---|
| `index.html` | **[A]** | Main landing page & registration form | `wwh-*.css`, `wwh-*.js`, `mahi.svg` | Keep in root |
| `track.html` | **[A]** | Order tracking & ticket display page | `tickets.js`, `wwh-map.js`, `wwh-api.js` | Keep in root |
| `episodes.html` | **[A]** | Episode list & event history | `wwh-theme.css`, `wwh-shell.css` | Keep in root |
| `memories.html` | **[A]** | Disposable camera gallery & upload UI | `wwh-uploader.js`, `wwh-lightbox.js` | Keep in root |
| `support.html` | **[A]** | Support chat & phone lookup UI | `wwh-theme.css`, `wwh-phone.js` | Keep in root |
| `admin.html` | **[A]** | Event & order management panel | Flatpickr CDN, `wwh-uploader.js`, `wwh-api.js` | Keep in root |
| `tickets.js` | **[A]** | Client-side SVG ticket filling engine | `ticket-a.svg`, `ticket-b.svg` | Keep in root (or relocate with router update) |
| `ticket-a.svg` | **[A]** | Ticket template Group A | `tickets.js`, `ticket_render.py` | Keep in root (served by `spa_static`) |
| `ticket-b.svg` | **[A]** | Ticket template Group B | `tickets.js`, `ticket_render.py` | Keep in root (served by `spa_static`) |
| `mahi.svg` | **[A]** | Fish animation graphic | `assets/wwh-fish.js` | Keep in root (served by `spa_static`) |
| `assets/fonts/Vazirmatn-Regular.ttf` | **[A]** | Vazirmatn font for server-side ticket rendering | `ticket_render.py`, `test_deploy_assets.py` | Keep in `assets/fonts/` |
| `assets/apple-touch-icon.jpg` | **[A]** | iOS home screen icon | HTML page heads | Keep in `assets/` |
| `assets/wwh-favicon.jpg` | **[A]** | Browser favicon | HTML page heads | Keep in `assets/` |
| `assets/wwh-theme.css` | **[A]** | Core design system tokens (Gothic Cute) | All HTML pages | Keep in `assets/` |
| `assets/wwh-shell.css` | **[A]** | Topbar / Footer navigation frame | All HTML pages | Keep in `assets/` |
| `assets/wwh-hero.css` | **[A]** | Shutter disc hero styling | `index.html` | Keep in `assets/` |
| `assets/wwh-atmosphere.css` | **[A]** | Background ambient effects | `index.html` | Keep in `assets/` |
| `assets/wwh-loader.css` | **[A]** | Preloader animation styling | `index.html` | Keep in `assets/` |
| `assets/wwh-perf.css` | **[A]** | Responsive & perf baseline styles | `index.html` | Keep in `assets/` |
| `assets/wwh-uploader.css` | **[A]** | Chunked upload widget styling | `admin.html`, `memories.html` | Keep in `assets/` |
| `assets/wwh-lightbox.css` | **[A]** | Lightbox modal styling | `admin.html`, `memories.html` | Keep in `assets/` |
| `assets/wwh-perf.js` | **[A]** | Performance monitor & font loading | `index.html` | Keep in `assets/` |
| `assets/wwh-loader.js` | **[A]** | Preloader logic | `index.html` | Keep in `assets/` |
| `assets/wwh-chrome.js` | **[A]** | Dynamic topbar & footer injector | All HTML pages | Keep in `assets/` |
| `assets/wwh-landing.js` | **[A]** | Landing page registration & countdown logic | `index.html` | Keep in `assets/` |
| `assets/wwh-phone.js` | **[A]** | Persian mobile number normalizer | `index.html`, `track.html`, `admin.html` | Keep in `assets/` |
| `assets/wwh-datetime.js` | **[A]** | Jalali date/time formatters | `index.html`, `track.html`, `episodes.html` | Keep in `assets/` |
| `assets/wwh-api.js` | **[A]** | Fetch wrapper for API calls | `track.html`, `admin.html` | Keep in `assets/` |
| `assets/wwh-map.js` | **[A]** | Neshan/Leaflet map embedder | `track.html`, `admin.html` | Keep in `assets/` |
| `assets/wwh-scroll.js` | **[A]** | Smooth scroll coordinator | `index.html` | Keep in `assets/` |
| `assets/wwh-spotlight.js` | **[A]** | Cursor radial glow effect | `index.html` | Keep in `assets/` |
| `assets/wwh-atmosphere.js` | **[A]** | Canvas background particle stars | `index.html` | Keep in `assets/` |
| `assets/wwh-fish.js` | **[A]** | Canvas swimming fish animation | `index.html`, `mahi.svg` | Keep in `assets/` |
| `assets/wwh-uploader.js` | **[A]** | Direct/multipart upload engine | `admin.html`, `memories.html` | Keep in `assets/` |
| `assets/wwh-lightbox.js` | **[A]** | Media viewer modal | `admin.html`, `memories.html` | Keep in `assets/` |

---

## 2. Backend Application Core (`backend/app/`)

| File Path | Classification | Role / Purpose | Dependencies / References | Recommendation |
|---|:---:|---|---|---|
| `backend/app/main.py` | **[A]** | FastAPI application root & SPA server | Lifespan, Routers, Database | Active production core |
| `backend/app/config.py` | **[A]** | Pydantic Settings & ENV parsing | Pydantic, `.env` | Active production core |
| `backend/app/db.py` | **[A]** | SQLAlchemy engine & SessionLocal | SQLite `data.sqlite` | Active production core |
| `backend/app/models.py` | **[A]** | 22 ORM models (Events, Orders, Storage) | SQLAlchemy | Active production core |
| `backend/app/auth.py` | **[A]** | Admin password hashing & verification | Bcrypt / hashlib | Active production core |
| `backend/app/storage_paths.py` | **[A]** | Path resolvers for receipts and archives | `config.settings` | Active production core |
| `backend/app/routers/public.py` | **[A]** | Public endpoints (orders, events, tickets) | FastAPI router | Active production core |
| `backend/app/routers/admin.py` | **[A]** | Admin endpoints (orders, SMS, tickets) | FastAPI router | Active production core |
| `backend/app/routers/memories.py` | **[A]** | Memories API (upload, gate, likes, comments) | FastAPI router | Active production core |
| `backend/app/routers/support.py` | **[A]** | Support ticket & messaging API | FastAPI router | Active production core |
| `backend/app/routers/storage_admin.py` | **[A]** | Storage management & sync API | FastAPI router | Active production core |
| `backend/app/services/capacity.py` | **[A]** | Seat capacity calculation & locks | Orders & Events | Active production core |
| `backend/app/services/orders.py` | **[A]** | Order creation, approval, rejection | DB & Models | Active production core |
| `backend/app/services/tickets.py` | **[A]** | Ticket serial numbering & access tokens | DB & Models | Active production core |
| `backend/app/services/ticket_render.py` | **[A]** | SVG/PNG/PDF rendering (CairoSVG/Weasyprint) | CairoSVG, Pillow, Vazirmatn | Active production core |
| `backend/app/services/ticket_layout.py` | **[A]** | SVG field coordinate injector | Reads `ticket-field-layout.json` | Active production core |
| `backend/app/services/ticket_png_headless.py` | **[A]** | Fallback headless PNG renderer | Playwright / Headless | Active production core |
| `backend/app/services/events.py` | **[A]** | Event metadata & featured event selector | DB & Models | Active production core |
| `backend/app/services/event_display.py` | **[A]** | Formats event dates/venues for display | Jalali schedule | Active production core |
| `backend/app/services/event_location.py` | **[A]** | Geolocation & coordinate privacy gate | DB & Models | Active production core |
| `backend/app/services/jalali_schedule.py` | **[A]** | Persian calendar formatting | Python datetime | Active production core |
| `backend/app/services/notify.py` | **[A]** | Notification orchestrator | `sms_ir.py` | Active production core |
| `backend/app/services/sms_ir.py` | **[A]** | SMS.ir Verify API client | SMS.ir HTTP API | Active production core |
| `backend/app/services/phone.py` | **[A]** | Backend Iranian mobile number validation | Regex | Active production core |
| `backend/app/services/media_guard.py` | **[A]** | File magic bytes / mime inspection | python-magic / fallback | Active production core |
| `backend/app/services/memory_gate.py` | **[A]** | Ticket-based token auth & rate limit for upload | DB & Models | Active production core |
| `backend/app/services/memory_media.py` | **[A]** | Media validation, thumbnail generation, FFmpeg | Pillow, FFmpeg | Active production core |
| `backend/app/services/memory_audit.py` | **[A]** | Admin audit logging for memory review | DB & Models | Active production core |
| `backend/app/services/support_access.py` | **[A]** | Session token verification for support chat | DB & Models | Active production core |
| `backend/app/services/support_contacts.py` | **[A]** | Support agent directory & contact routing | DB & Models | Active production core |
| `backend/app/services/storage/*` (11 files) | **[A]** | Multi-provider storage engine (Files.ir, S3) | Storage adapters & routing | Active production core |

---

## 3. Deployment & Production Operations

| File Path | Classification | Role / Purpose | Dependencies / References | Recommendation |
|---|:---:|---|---|---|
| `scripts/deploy/wwh-deploy.sh` | **[A]** | Core production deployment CLI (`wwh-deploy`) | Bash, Git, Systemd | Keep in `scripts/deploy/` |
| `scripts/deploy/ensure-wwh-deploy-cli.sh` | **[A]** | Boot self-healer for CLI binary in `/usr/local/bin` | Systemd service pre-start | Keep in `scripts/deploy/` |
| `scripts/deploy/set-sms-env.sh` | **[A]** | Safe helper to configure SMS credentials on VPS | Environment files | Keep in `scripts/deploy/` |
| `scripts/deploy/wewerehere.service.example` | **[A]** | Systemd unit template for Uvicorn | Linux systemd | Keep in `scripts/deploy/` |
| `scripts/deploy/wwh-deploy-cli.service` | **[A]** | Systemd unit ensuring CLI availability on reboot | Linux systemd | Keep in `scripts/deploy/` |
| `scripts/deploy/wwh-deploy.conf.example` | **[A]** | Deployment config example | `wwh-deploy.sh` | Keep in `scripts/deploy/` |
| `scripts/deploy/test_deploy_script.sh` | **[B]** | Sanity test verifying deploy scripts syntax | Bash test | Keep in `scripts/deploy/` |
| `scripts/dev-local.ps1` | **[B]** | Local Windows dev launcher for FastAPI + Uvicorn | PowerShell | Keep in `scripts/` |
| `DEPLOY.md` | **[A]** | Authoritative deployment manual | VPS setup instructions | Keep in root |
| `docs/DEPLOY_VPS.md` | **[A]** | Detailed step-by-step VPS runbook | `wwh-deploy` commands | Keep in `docs/` |

---

## 4. Tests & Quality Assurance (`backend/tests/`)

| File Path | Classification | Role / Purpose | Current Status | Recommendation |
|---|:---:|---|---|---|
| `backend/tests/test_admin_panel.py` | **[B]** | Verifies admin auth, orders review, ticket stats | Passed (9/9) | Keep in `backend/tests/` |
| `backend/tests/test_api.py` | **[B]** | Verifies public health, event listing, tracking | Passed (6/6) | Keep in `backend/tests/` |
| `backend/tests/test_approve_capacity.py` | **[B]** | Verifies race condition safety & capacity cap | Passed (2/2) | Keep in `backend/tests/` |
| `backend/tests/test_deploy_assets.py` | **[B]** | Verifies critical assets exist (font, shell.css) | Passed (2/2) | Keep in `backend/tests/` |
| `backend/tests/test_event_location.py` | **[B]** | Verifies location publish gating & coordinates | Passed (7/7) | Keep in `backend/tests/` |
| `backend/tests/test_media_guard.py` | **[B]** | Verifies image/video file validation | Passed (14/14) | Keep in `backend/tests/` |
| `backend/tests/test_memories.py` | **[B]** | Verifies disposable camera gate, upload, gallery | Passed (23/23) | Keep in `backend/tests/` |
| `backend/tests/test_sms.py` | **[B]** | Verifies SMS.ir client and mock delivery | Passed (13/13) | Keep in `backend/tests/` |
| `backend/tests/test_storage_manager.py` | **[B]** | Verifies Files.ir / S3 / Local routing & fallback | Passed (18/18) | Keep in `backend/tests/` |
| `backend/tests/test_support_flow.py` | **[B]** | Verifies customer support chat & message security | Passed (9/9) | Keep in `backend/tests/` |
| `backend/tests/test_ticket_render_and_track.py` | **[B]** | Verifies SVG parsing, layout coordinates, export | Passed (28/28) | Keep in `backend/tests/` |
| `backend/tests/test_tickets_numbering.py` | **[B]** | Verifies serial generation, grouping (A/B) | Passed (4/4) | Keep in `backend/tests/` |

---

## 5. Development Diagnostics vs Historical Scripts (`backend/scripts/`)

| File Path | Classification | Purpose | Execution Context | Recommendation |
|---|:---:|---|---|---|
| `backend/scripts/migrate_legacy.py` | **[C]** | Migrates Node single-event DB to FastAPI multi-event | Subprocess in `main.py` & `wwh-deploy` | Keep in `backend/scripts/` |
| `backend/scripts/check_ticket_png.py` | **[B]** | Headless PNG rendering smoke test | `npm run check:png` in `package.json` | Move to `tools/diagnostics/` or keep |
| `backend/scripts/smoke_admin_ticket_png.py` | **[B]** | Admin ticket PNG rendering verification | Manual / CI QA | Move to `tools/diagnostics/` |
| `backend/scripts/measure_ticket_fields.py` | **[B]** | Measures SVG field coordinates to update layout JSON | Developer ticket design tooling | Move to `tools/ticket-layout/` |
| `backend/scripts/inspect_ticket_svg.py` | **[B]** | Inspects text nodes and classes in ticket SVGs | Developer diagnostic | Move to `tools/ticket-layout/` |
| `backend/scripts/seed_guilanshah_ticket.py` | **[B]** | Generates test ticket fixture for second episode | Test fixture generation | Move to `tools/fixtures/` |
| `backend/scripts/e2e_customer_ticket_flow.py` | **[B]** | End-to-end customer order-to-ticket test runner | Extended integration test | Move to `backend/tests/e2e/` |
| `backend/scripts/dump_ticket_fields.py` | **[D]** | Dumps fields to `_ticket_fields.txt` | One-off extraction | Relocate to `tools/archive/` |
| `backend/scripts/extract_ticket_text_styles.py` | **[D]** | Dumps styles to `_ticket_styles.txt` | One-off extraction | Relocate to `tools/archive/` |
| `backend/scripts/find_name_slots.py` | **[D]** | Searches SVG for `<text data-field="name">` | One-off inspection | Relocate to `tools/archive/` |
| `backend/scripts/snippet_fields.py` | **[D]** | Snippets fields to `_snippets.txt` | One-off extraction | Relocate to `tools/archive/` |
| `backend/scripts/_dedupe_city.py` | **[D]** | One-off patch to deduplicate city in SVG | One-time patch (already applied) | Relocate to `tools/archive/` |
| `backend/scripts/patch_ticket_meta_layout.py` | **[D]** | One-off patch for SVG meta coordinates | One-time patch (already applied) | Relocate to `tools/archive/` |
| `backend/scripts/patch_ticket_names.py` | **[D]** | One-off patch for vertical watermark names | One-time patch (already applied) | Relocate to `tools/archive/` |
| `backend/scripts/patch_ticket_wwh_layout.py` | **[D]** | One-off patch for SVG layout groups | One-time patch (already applied) | Relocate to `tools/archive/` |
| `backend/scripts/strip_ticket_static_meta.py` | **[D]** | One-off patch to remove baked vector letters | One-time patch (already applied) | Relocate to `tools/archive/` |
| `backend/scripts/_peek_ticket.py` | **[D]** | Scratch regex printer | Developer scratch | Relocate to `tools/archive/` |
| `backend/scripts/_names.txt` | **[D]** | Scratch name extraction dump | Scratch text file | Relocate to `tools/archive/` |
| `backend/scripts/_names2.txt` | **[D]** | Scratch name extraction dump | Scratch text file | Relocate to `tools/archive/` |
| `backend/scripts/_snippets.txt` | **[D]** | Scratch snippet dump | Scratch text file | Relocate to `tools/archive/` |
| `backend/scripts/_ticket_fields.txt` | **[D]** | Scratch ticket field dump | Scratch text file | Relocate to `tools/archive/` |
| `backend/scripts/_ticket_styles.txt` | **[D]** | Scratch ticket styles dump | Scratch text file | Relocate to `tools/archive/` |

---

## 6. Temporary Files, Dumps, Probes & Root Clutter

| File Path | Classification | File Size | Description | Recommendation |
|---|:---:|:---:|---|---|
| `admin-big.png` | **[F]** | **28.3 MB** | Full admin screenshot left in repo root | Add to `.gitignore`, delete or archive outside Git |
| `admin-test.png` | **[F]** | **12.5 MB** | Admin test screenshot left in repo root | Add to `.gitignore`, delete or archive outside Git |
| `admin-test-guilanshah-ticket.svg` | **[B]** | 233 KB | Generated test ticket from `seed_guilanshah_ticket.py` | Move to `tests/fixtures/` |
| `debug-b0d7b4.log` | **[F]** | 10 KB | Cursor debug log file | Delete or ignore |
| `_index-preview.html` | **[B]** | 287 B | Iframe preview helper | Move to `tools/dev/` |
| `_probe.html` | **[B]** | 2.4 KB | Ticket SVG coordinate probe tool | Move to `tools/dev/` |
| `_track_probe.json` | **[B]** | 390 B | API mock probe response (pending order) | Move to `backend/tests/fixtures/` |
| `_track_probe2.json` | **[B]** | 1.3 KB | API mock probe response (approved order) | Move to `backend/tests/fixtures/` |
| `backend/_events.json` | **[D]** | 3.5 KB | Raw database dump of `events` table | Move to `docs/archive/data/` |
| `data.sqlite.bak` | **[C]** | 32 KB | SQLite backup file | Keep on local/server disk, never commit |
| `data.sqlite.backup_pre_storage_manager` | **[C]** | 200 KB | Pre-storage migration SQLite backup | Keep on local/server disk, never commit |
| `data/setlists/third-shahrivar-track-page-snapshot.json` | **[D]** | 1.2 KB | Backup of episode 1 setlist items | Keep in `docs/archive/snapshots/` |
| `توافق.docx` / `~$توافق.docx` | **[D]** | ~31 KB | Artist agreement / contract draft | Move to `docs/archive/contracts/` |
| `گیلانشاه.pdf` | **[D]** | 107 KB | Event poster / flyer PDF | Move to `docs/archive/flyers/` |

---

## 7. Design System & Documentation

| File Path | Classification | Description / Reality | Recommendation |
|---|:---:|---|---|
| `design-system/third-shahrivar/MASTER.md` | **[A]** | The true, authoritative WWH Design System (Gothic Cute, #0A0A0B, #D43F5A, Vazirmatn) | Promote to `docs/design-system/MASTER.md` |
| `design-system/third-shahrivar/pages/*` | **[A]** | Page-specific design specifications (index, track, admin) | Promote to `docs/design-system/pages/` |
| `design-system/we-were-here/ticket-field-layout.json` | **[A]** | **ACTIVE RUNTIME CONFIGURATION** for ticket SVG layout | Keep or relocate with import update in `ticket_layout.py` |
| `design-system/we-were-here/pages/ticket-layout.md` | **[A]** | Documentation for `ticket-field-layout.json` | Keep with ticket layout specs |
| `design-system/we-were-here/pages/admin.md` | **[D]** | Admin overrides noting dark tokens | Consolidate into authoritative design system |
| `design-system/we-were-here/MASTER.md` | **[F]** | Spurious generated Survey template (teal #0D9488, Atkinson font) | Move to `docs/archive/old-designs/` |
| `design-system/we-were-here/pages/episodes.md` | **[F]** | Spurious generated conference template (speakers/sponsors) | Move to `docs/archive/old-designs/` |
| `design-system/we-were-here/pages/index.md` | **[F]** | Spurious generated generic survey page | Move to `docs/archive/old-designs/` |
| `design-system/we-were-here/pages/track.md` | **[F]** | Spurious generated generic page | Move to `docs/archive/old-designs/` |
