'use strict';

/**
 * "ما اینجا بودیم" — micro event experience backend.
 *
 * Zero-dependency Node server using the built-in `node:sqlite` module
 * (Node >= 22.5). Serves the landing page, the admin panel, uploaded
 * media, and a small JSON API.
 *
 * Run:  npm run dev        (defaults to http://127.0.0.1:5173)
 * Env:  PORT, HOST, ADMIN_PASSWORD
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { DatabaseSync } = require('node:sqlite');

const ROOT = __dirname;
const UPLOAD_DIR = path.join(ROOT, 'uploads');
const RECEIPT_DIR = path.join(UPLOAD_DIR, 'receipts');
const DB_PATH = path.join(ROOT, 'data.sqlite');
// The harness sometimes sets PORT=0 (meaning "pick your own"). Treat 0/NaN
// as "use the default" so the server always lands on a known, reachable port.
const PORT = (() => {
  const p = Number(process.env.PORT);
  return p && p > 0 ? p : 5173;
})();
const HOST = process.env.HOST || '127.0.0.1';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'wewerehere-admin';
// Total tickets available for the event. Remaining = CAPACITY - sold tickets.
const CAPACITY = (() => {
  const n = Number(process.env.CAPACITY);
  return n > 0 ? n : 50;
})();
// Payment info shown on the registration form — set these env vars before going live.
const PAYMENT_CARD_NUMBER = process.env.PAYMENT_CARD_NUMBER || '';
const PAYMENT_CARD_HOLDER = process.env.PAYMENT_CARD_HOLDER || '';
const PAYMENT_BANK_NAME = process.env.PAYMENT_BANK_NAME || '';
const TICKET_PRICE = Number(process.env.TICKET_PRICE) || 0;

const MAX_BODY = 120 * 1024 * 1024; // 120MB (media uploads arrive as base64 JSON)
const MAX_MEDIA_BYTES = 40 * 1024 * 1024; // 40MB decoded per file

fs.mkdirSync(UPLOAD_DIR, { recursive: true });
fs.mkdirSync(RECEIPT_DIR, { recursive: true });

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------
const db = new DatabaseSync(DB_PATH);
db.exec(`
  CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    serial      TEXT    UNIQUE NOT NULL,
    name        TEXT    NOT NULL,
    phone       TEXT    NOT NULL,
    group_name  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
  );
  CREATE TABLE IF NOT EXISTS media (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT    NOT NULL,
    original_name TEXT    NOT NULL,
    mime          TEXT    NOT NULL,
    size          INTEGER NOT NULL,
    caption       TEXT    DEFAULT '',
    created_at    TEXT    NOT NULL
  );
  CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phone         TEXT    NOT NULL,
    names         TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending',
    receipt_text  TEXT    DEFAULT '',
    receipt_image TEXT    DEFAULT '',
    admin_note    TEXT    DEFAULT '',
    created_at    TEXT    NOT NULL,
    reviewed_at   TEXT
  );
  CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
  );
`);

// Migration: link tickets to the order that created them (older DBs won't have this column).
try { db.exec('ALTER TABLE tickets ADD COLUMN order_id INTEGER'); } catch (err) { /* column already exists */ }

// In-memory admin sessions (lost on restart — acceptable for this scope).
const sessions = new Set();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mov': 'video/quicktime',
  '.woff2': 'font/woff2'
};

const MIME_EXT = {
  'image/jpeg': '.jpg',
  'image/png': '.png',
  'image/webp': '.webp',
  'image/gif': '.gif',
  'image/svg+xml': '.svg',
  'video/mp4': '.mp4',
  'video/webm': '.webm',
  'video/quicktime': '.mov'
};

function send(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store'
  });
  res.end(body);
}

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) {
        reject(new Error('request body too large'));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

// Random 4-digit serial (0000-9999), unique within the tickets table.
function uniqueSerial() {
  for (let i = 0; i < 200; i++) {
    const serial = String(Math.floor(Math.random() * 10000)).padStart(4, '0');
    const exists = db.prepare('SELECT 1 AS x FROM tickets WHERE serial = ?').get(serial);
    if (!exists) return serial;
  }
  throw new Error('could not allocate a unique serial number');
}

function soldCount() {
  return db.prepare('SELECT COUNT(*) AS n FROM tickets').get().n;
}

function pendingNamesCount() {
  const rows = db.prepare("SELECT names FROM orders WHERE status = 'pending'").all();
  let n = 0;
  for (const r of rows) {
    try { n += JSON.parse(r.names).length; } catch (err) { /* ignore malformed row */ }
  }
  return n;
}

function remainingTickets() {
  return CAPACITY - soldCount() - pendingNamesCount();
}

function groupFor(serial) {
  return (parseInt(serial, 10) % 2) ? 'A' : 'B';
}

// Sequential ticket number: the ticket's rank among all tickets ordered by id.
// Deleting a ticket renumbers the rest (dynamic), issuing a ticket assigns the next rank.
function ticketNumber(id) {
  return db.prepare('SELECT COUNT(*) AS n FROM tickets WHERE id <= ?').get(id).n;
}

function getSetting(key) {
  const row = db.prepare('SELECT value FROM settings WHERE key = ?').get(key);
  return row ? row.value : '';
}

function setSetting(key, value) {
  db.prepare('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value')
    .run(key, String(value == null ? '' : value).slice(0, 500));
}

function requireAuth(req, res, next) {
  const header = req.headers['authorization'] || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : '';
  if (!token || !sessions.has(token)) return send(res, 401, { error: 'unauthorized' });
  next();
}

// ---------------------------------------------------------------------------
// API handlers
// ---------------------------------------------------------------------------
function handleRegister(req, res) {
  readBody(req, 1024 * 1024)
    .then((buf) => {
      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }

      const phone = String(body.phone || '').replace(/\s/g, '');
      const names = Array.isArray(body.names) ? body.names.map((n) => String(n).trim()).filter(Boolean) : [];

      if (!/^\d{10,11}$/.test(phone)) return send(res, 400, { error: 'invalid phone' });
      if (names.length < 1 || names.length > 6) return send(res, 400, { error: 'invalid names' });

      const remaining = remainingTickets();
      if (names.length > remaining) {
        return send(res, 409, {
          error: remaining <= 0 ? 'ظرفیت تکمیل شده است' : ('ظرفیت باقی‌مانده: ' + remaining + ' نفر')
        });
      }

      const tickets = [];
      for (const name of names) {
        const serial = uniqueSerial();
        const group = groupFor(serial);
        db.prepare('INSERT INTO tickets (serial, name, phone, group_name, created_at) VALUES (?, ?, ?, ?, ?)')
          .run(serial, name.slice(0, 200), phone, group, new Date().toISOString());
        tickets.push({ serial, name, group });
      }

      send(res, 201, { tickets });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleTicket(req, res, url) {
  const raw = String(url.searchParams.get('serial') || '').replace(/\D/g, '').padStart(4, '0').slice(-4);
  if (!/^\d{4}$/.test(raw)) return send(res, 400, { error: 'invalid serial' });

  const ticket = db.prepare('SELECT id, serial, name, group_name FROM tickets WHERE serial = ?').get(raw);
  if (!ticket) return send(res, 200, { found: false });

  const media = db
    .prepare('SELECT id, filename, original_name, mime, caption, created_at FROM media ORDER BY id DESC')
    .all()
    .map((m) => ({
      id: m.id,
      url: '/uploads/' + m.filename,
      mime: m.mime,
      caption: m.caption,
      original_name: m.original_name
    }));

  send(res, 200, {
    found: true,
    ticket: { number: ticketNumber(ticket.id), serial: ticket.serial, name: ticket.name, group: ticket.group_name },
    media
  });
}

function handleLogin(req, res) {
  readBody(req, 1024 * 1024)
    .then((buf) => {
      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }
      if (body.password !== ADMIN_PASSWORD) return send(res, 401, { error: 'رمز عبور اشتباه است' });

      const token = crypto.randomBytes(24).toString('hex');
      sessions.add(token);
      send(res, 200, { token });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleAdminTickets(res) {
  const tickets = db
    .prepare('SELECT id, serial, name, phone, group_name, created_at FROM tickets ORDER BY id DESC')
    .all();
  send(res, 200, { tickets });
}

function handleAdminTicketCreate(req, res) {
  readBody(req, 1024 * 1024)
    .then((buf) => {
      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }

      const name = String(body.name || '').trim();
      const phone = String(body.phone || '').replace(/\s/g, '');
      if (!name) return send(res, 400, { error: 'name required' });
      if (!/^\d{10,11}$/.test(phone)) return send(res, 400, { error: 'invalid phone' });

      // Optional explicit serial (must be 4 digits + unique); otherwise random.
      let serial;
      if (body.serial !== undefined && body.serial !== '') {
        serial = String(body.serial).replace(/\D/g, '').padStart(4, '0').slice(-4);
        if (!/^\d{4}$/.test(serial)) return send(res, 400, { error: 'invalid serial' });
        const clash = db.prepare('SELECT 1 AS x FROM tickets WHERE serial = ?').get(serial);
        if (clash) return send(res, 409, { error: 'serial already exists' });
      } else {
        serial = uniqueSerial();
      }

      const group = (body.group === 'A' || body.group === 'B') ? body.group : groupFor(serial);
      const info = db
        .prepare('INSERT INTO tickets (serial, name, phone, group_name, created_at) VALUES (?, ?, ?, ?, ?)')
        .run(serial, name.slice(0, 200), phone, group, new Date().toISOString());

      send(res, 201, { id: Number(info.lastInsertRowid), serial, name, phone, group_name: group });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleAdminTicketUpdate(req, res, url) {
  readBody(req, 1024 * 1024)
    .then((buf) => {
      const id = Number(url.searchParams.get('id'));
      if (!id) return send(res, 400, { error: 'missing id' });
      const existing = db.prepare('SELECT * FROM tickets WHERE id = ?').get(id);
      if (!existing) return send(res, 404, { error: 'not found' });

      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }

      const name = body.name !== undefined ? String(body.name).trim() : existing.name;
      const phone = body.phone !== undefined ? String(body.phone).replace(/\s/g, '') : existing.phone;
      if (!name) return send(res, 400, { error: 'name required' });
      if (!/^\d{10,11}$/.test(phone)) return send(res, 400, { error: 'invalid phone' });

      let serial = existing.serial;
      if (body.serial !== undefined && body.serial !== '') {
        const s = String(body.serial).replace(/\D/g, '').padStart(4, '0').slice(-4);
        if (!/^\d{4}$/.test(s)) return send(res, 400, { error: 'invalid serial' });
        const clash = db.prepare('SELECT 1 AS x FROM tickets WHERE serial = ? AND id != ?').get(s, id);
        if (clash) return send(res, 409, { error: 'serial already exists' });
        serial = s;
      }

      const group = (body.group === 'A' || body.group === 'B')
        ? body.group
        : (serial !== existing.serial ? groupFor(serial) : existing.group_name);

      db.prepare('UPDATE tickets SET serial = ?, name = ?, phone = ?, group_name = ? WHERE id = ?')
        .run(serial, name.slice(0, 200), phone, group, id);

      send(res, 200, { id, serial, name, phone, group_name: group });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleAdminTicketDelete(req, res, url) {
  const id = Number(url.searchParams.get('id'));
  if (!id) return send(res, 400, { error: 'missing id' });
  const row = db.prepare('SELECT * FROM tickets WHERE id = ?').get(id);
  if (!row) return send(res, 404, { error: 'not found' });
  db.prepare('DELETE FROM tickets WHERE id = ?').run(id);
  send(res, 200, { ok: true });
}

function handleAdminMediaUpdate(req, res, url) {
  readBody(req, 1024 * 1024)
    .then((buf) => {
      const id = Number(url.searchParams.get('id'));
      if (!id) return send(res, 400, { error: 'missing id' });
      const row = db.prepare('SELECT * FROM media WHERE id = ?').get(id);
      if (!row) return send(res, 404, { error: 'not found' });

      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }

      const caption = body.caption !== undefined ? String(body.caption).slice(0, 500) : row.caption;
      db.prepare('UPDATE media SET caption = ? WHERE id = ?').run(caption, id);
      send(res, 200, { id, caption });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleAdminMediaList(res) {
  const media = db
    .prepare('SELECT id, filename, original_name, mime, size, caption, created_at FROM media ORDER BY id DESC')
    .all()
    .map((m) => Object.assign({}, m, { url: '/uploads/' + m.filename }));
  send(res, 200, { media });
}

function handleAdminMediaUpload(req, res) {
  readBody(req, MAX_BODY)
    .then((buf) => {
      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }

      const { filename, mime, data, caption } = body;
      if (!filename || !mime || !data) return send(res, 400, { error: 'missing fields' });
      if (!/^(image|video)\//.test(mime)) return send(res, 400, { error: 'unsupported type' });

      const ext = MIME_EXT[mime];
      if (!ext) return send(res, 400, { error: 'unsupported mime type' });

      let raw;
      try { raw = Buffer.from(String(data), 'base64'); } catch { return send(res, 400, { error: 'bad base64' }); }
      if (raw.length === 0) return send(res, 400, { error: 'empty file' });
      if (raw.length > MAX_MEDIA_BYTES) return send(res, 413, { error: 'file too large' });

      const safeName = Date.now().toString(36) + '-' + crypto.randomBytes(4).toString('hex') + ext;
      fs.writeFileSync(path.join(UPLOAD_DIR, safeName), raw);

      const info = db
        .prepare('INSERT INTO media (filename, original_name, mime, size, caption, created_at) VALUES (?, ?, ?, ?, ?, ?)')
        .run(safeName, String(filename).slice(0, 200), mime, raw.length, String(caption || '').slice(0, 500), new Date().toISOString());

      send(res, 201, {
        id: Number(info.lastInsertRowid),
        url: '/uploads/' + safeName,
        mime,
        caption: caption || '',
        original_name: filename
      });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleAdminSettingsGet(res) {
  send(res, 200, {
    card_number: getSetting('card_number'),
    card_holder: getSetting('card_holder'),
    bank_name: getSetting('bank_name'),
    ticket_price: getSetting('ticket_price')
  });
}

function handleAdminSettingsPut(req, res) {
  readBody(req, 1024 * 1024)
    .then((buf) => {
      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }
      if (body.card_number !== undefined) setSetting('card_number', String(body.card_number));
      if (body.card_holder !== undefined) setSetting('card_holder', String(body.card_holder));
      if (body.bank_name !== undefined) setSetting('bank_name', String(body.bank_name));
      if (body.ticket_price !== undefined) setSetting('ticket_price', String(body.ticket_price).replace(/\D/g, ''));
      send(res, 200, { ok: true });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleAdminMediaDelete(req, res, url) {
  const id = Number(url.searchParams.get('id'));
  if (!id) return send(res, 400, { error: 'missing id' });

  const row = db.prepare('SELECT * FROM media WHERE id = ?').get(id);
  if (!row) return send(res, 404, { error: 'not found' });

  const filePath = path.join(UPLOAD_DIR, row.filename);
  try { if (fs.existsSync(filePath)) fs.unlinkSync(filePath); } catch (err) { /* ignore */ }

  db.prepare('DELETE FROM media WHERE id = ?').run(id);
  send(res, 200, { ok: true });
}

// ---------------------------------------------------------------------------
// Orders (payment + receipt review workflow)
// ---------------------------------------------------------------------------
function handlePaymentInfo(res) {
  // Settings stored from the admin panel override the env-var defaults.
  send(res, 200, {
    cardNumber: getSetting('card_number') || PAYMENT_CARD_NUMBER,
    cardHolder: getSetting('card_holder') || PAYMENT_CARD_HOLDER,
    bankName: getSetting('bank_name') || PAYMENT_BANK_NAME,
    price: Number(getSetting('ticket_price') || '') || TICKET_PRICE
  });
}

function handleCreateOrder(req, res) {
  readBody(req, MAX_BODY)
    .then((buf) => {
      let body;
      try { body = JSON.parse(buf.toString('utf8')); } catch { return send(res, 400, { error: 'invalid json' }); }

      const phone = String(body.phone || '').replace(/\s/g, '');
      const names = Array.isArray(body.names) ? body.names.map((n) => String(n).trim()).filter(Boolean) : [];
      const receiptText = String(body.receiptText || '').trim().slice(0, 500);
      const receiptImage = body.receiptImage;

      if (!/^\d{10,11}$/.test(phone)) return send(res, 400, { error: 'invalid phone' });
      if (names.length < 1 || names.length > 6) return send(res, 400, { error: 'invalid names' });
      if (!receiptText && !(receiptImage && receiptImage.data)) {
        return send(res, 400, { error: 'رسید پرداخت (متن یا عکس) لازم است' });
      }

      const remaining = remainingTickets();
      if (names.length > remaining) {
        return send(res, 409, {
          error: remaining <= 0 ? 'ظرفیت تکمیل شده است' : 'فقط ' + remaining + ' جای خالی باقی مانده است'
        });
      }

      let receiptImageFilename = '';
      if (receiptImage && receiptImage.mime && receiptImage.data) {
        if (!/^image\//.test(receiptImage.mime)) return send(res, 400, { error: 'فقط عکس برای رسید قابل قبول است' });
        const ext = MIME_EXT[receiptImage.mime];
        if (!ext) return send(res, 400, { error: 'unsupported mime type' });
        let raw;
        try { raw = Buffer.from(String(receiptImage.data), 'base64'); } catch { return send(res, 400, { error: 'bad base64' }); }
        if (raw.length === 0) return send(res, 400, { error: 'empty file' });
        if (raw.length > MAX_MEDIA_BYTES) return send(res, 413, { error: 'file too large' });
        receiptImageFilename = Date.now().toString(36) + '-' + crypto.randomBytes(4).toString('hex') + ext;
        fs.writeFileSync(path.join(RECEIPT_DIR, receiptImageFilename), raw);
      }

      const info = db
        .prepare('INSERT INTO orders (phone, names, status, receipt_text, receipt_image, created_at) VALUES (?, ?, ?, ?, ?, ?)')
        .run(phone, JSON.stringify(names), 'pending', receiptText, receiptImageFilename, new Date().toISOString());

      send(res, 201, { orderId: Number(info.lastInsertRowid), status: 'pending' });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

function handleTrackOrders(req, res, url) {
  const normalizeDigits = (value) => String(value || '')
    .replace(/[۰-۹]/g, (digit) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(digit))
    .replace(/[٠-٩]/g, (digit) => '٠١٢٣٤٥٦٧٨٩'.indexOf(digit));
  const serial = normalizeDigits(url.searchParams.get('serial')).replace(/\D/g, '');
  const phone = normalizeDigits(url.searchParams.get('phone')).replace(/\s/g, '');

  if (serial) {
    if (!/^\d{4}$/.test(serial)) return send(res, 400, { error: 'invalid serial' });
    const tickets = db
      .prepare('SELECT id, serial, name, group_name FROM tickets WHERE serial = ? ORDER BY id DESC')
      .all(serial)
      .map((t) => ({ number: ticketNumber(t.id), serial: t.serial, name: t.name, group: t.group_name }));
    return send(res, 200, { orders: [], tickets });
  }

  if (!/^\d{10,11}$/.test(phone)) return send(res, 400, { error: 'invalid phone' });

  const orders = db
    .prepare('SELECT id, names, status, admin_note, created_at, reviewed_at, receipt_text, receipt_image FROM orders WHERE phone = ? ORDER BY id DESC')
    .all(phone)
    .map((o) => ({
      id: o.id,
      names: (() => { try { return JSON.parse(o.names || '[]'); } catch { return []; } })(),
      status: o.status,
      adminNote: o.admin_note || '',
      createdAt: o.created_at,
      reviewedAt: o.reviewed_at,
      hasReceiptText: Boolean(o.receipt_text),
      hasReceiptImage: Boolean(o.receipt_image)
    }));

  const tickets = db
    .prepare('SELECT id, serial, name, group_name FROM tickets WHERE phone = ? ORDER BY id DESC')
    .all(phone)
    .map((t) => ({ number: ticketNumber(t.id), serial: t.serial, name: t.name, group: t.group_name }));

  send(res, 200, { orders, tickets });
}

function handleAdminOrdersList(res, url) {
  const status = String(url.searchParams.get('status') || 'all');
  const rows = status === 'all'
    ? db.prepare('SELECT * FROM orders ORDER BY id DESC').all()
    : db.prepare('SELECT * FROM orders WHERE status = ? ORDER BY id DESC').all(status);

  const orders = rows.map((o) => ({
    id: o.id,
    phone: o.phone,
    names: (() => { try { return JSON.parse(o.names || '[]'); } catch { return []; } })(),
    status: o.status,
    receiptText: o.receipt_text || '',
    receiptImageUrl: o.receipt_image ? '/uploads/receipts/' + o.receipt_image : '',
    adminNote: o.admin_note || '',
    createdAt: o.created_at,
    reviewedAt: o.reviewed_at
  }));

  send(res, 200, { orders });
}

function handleAdminOrderApprove(req, res, url) {
  const id = Number(url.searchParams.get('id'));
  if (!id) return send(res, 400, { error: 'missing id' });
  const order = db.prepare('SELECT * FROM orders WHERE id = ?').get(id);
  if (!order) return send(res, 404, { error: 'not found' });
  if (order.status !== 'pending') return send(res, 409, { error: 'این درخواست رزرو قبلاً بررسی شده است' });

  let names = [];
  try { names = JSON.parse(order.names); } catch { names = []; }
  if (!names.length) return send(res, 400, { error: 'no names on order' });

  const tickets = [];
  for (const name of names) {
    const serial = uniqueSerial();
    const group = groupFor(serial);
    db.prepare('INSERT INTO tickets (serial, name, phone, group_name, order_id, created_at) VALUES (?, ?, ?, ?, ?, ?)')
      .run(serial, name.slice(0, 200), order.phone, group, order.id, new Date().toISOString());
    tickets.push({ serial, name, group });
  }

  db.prepare("UPDATE orders SET status = 'approved', reviewed_at = ? WHERE id = ?").run(new Date().toISOString(), id);

  send(res, 200, { id, status: 'approved', tickets });
}

function handleAdminOrderReject(req, res, url) {
  readBody(req, 1024 * 1024)
    .then((buf) => {
      const id = Number(url.searchParams.get('id'));
      if (!id) return send(res, 400, { error: 'missing id' });
      const order = db.prepare('SELECT * FROM orders WHERE id = ?').get(id);
      if (!order) return send(res, 404, { error: 'not found' });
      if (order.status !== 'pending') return send(res, 409, { error: 'این درخواست رزرو قبلاً بررسی شده است' });

      let body = {};
      try { body = JSON.parse(buf.toString('utf8') || '{}'); } catch { body = {}; }
      const note = String(body.note || '').slice(0, 500);

      db.prepare("UPDATE orders SET status = 'rejected', admin_note = ?, reviewed_at = ? WHERE id = ?")
        .run(note, new Date().toISOString(), id);

      send(res, 200, { id, status: 'rejected' });
    })
    .catch(() => send(res, 400, { error: 'bad request' }));
}

// ---------------------------------------------------------------------------
// Static files
// ---------------------------------------------------------------------------
function serveStatic(req, res, pathname) {
  let rel = decodeURIComponent(pathname);
  if (rel === '/' || rel === '/index') rel = '/index.html';
  if (rel === '/admin') rel = '/admin.html';
  if (rel === '/track') rel = '/track.html';

  const filePath = path.normalize(path.join(ROOT, rel));
  if (filePath !== ROOT && !filePath.startsWith(ROOT + path.sep)) {
    return send(res, 403, { error: 'forbidden' });
  }
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return send(res, 404, { error: 'not found' });
  }

  const ext = path.extname(filePath).toLowerCase();
  res.writeHead(200, {
    'Content-Type': MIME[ext] || 'application/octet-stream',
    'Cache-Control': 'no-cache'
  });
  fs.createReadStream(filePath).pipe(res);
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------
const server = http.createServer((req, res) => {
  // Minimal CORS so the API is usable from any origin in dev.
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  const url = new URL(req.url, 'http://' + (req.headers.host || 'localhost'));
  const pathname = url.pathname;
  const method = req.method;

  try {
    if (method === 'GET' && pathname === '/api/health') {
      const count = db.prepare('SELECT COUNT(*) AS n FROM tickets').get().n;
      return send(res, 200, { ok: true, tickets: count });
    }
    if (method === 'GET' && pathname === '/api/capacity') {
      const sold = soldCount();
      const pending = pendingNamesCount();
      return send(res, 200, { capacity: CAPACITY, sold, pending, remaining: Math.max(0, CAPACITY - sold - pending) });
    }
    if (method === 'POST' && pathname === '/api/register') return handleRegister(req, res);
    if (method === 'GET' && pathname === '/api/ticket') return handleTicket(req, res, url);
    if (method === 'GET' && pathname === '/api/payment-info') return handlePaymentInfo(res);
    if (method === 'POST' && pathname === '/api/orders') return handleCreateOrder(req, res);
    if (method === 'GET' && pathname === '/api/orders/track') return handleTrackOrders(req, res, url);
    if (method === 'POST' && pathname === '/api/admin/login') return handleLogin(req, res);
    if (method === 'GET' && pathname === '/api/admin/tickets') return requireAuth(req, res, () => handleAdminTickets(res));
    if (method === 'POST' && pathname === '/api/admin/tickets') return requireAuth(req, res, () => handleAdminTicketCreate(req, res));
    if (method === 'PUT' && pathname === '/api/admin/tickets') return requireAuth(req, res, () => handleAdminTicketUpdate(req, res, url));
    if (method === 'DELETE' && pathname === '/api/admin/tickets') return requireAuth(req, res, () => handleAdminTicketDelete(req, res, url));
    if (method === 'GET' && pathname === '/api/admin/media') return requireAuth(req, res, () => handleAdminMediaList(res));
    if (method === 'POST' && pathname === '/api/admin/media') return requireAuth(req, res, () => handleAdminMediaUpload(req, res));
    if (method === 'PUT' && pathname === '/api/admin/media') return requireAuth(req, res, () => handleAdminMediaUpdate(req, res, url));
    if (method === 'DELETE' && pathname === '/api/admin/media') return requireAuth(req, res, () => handleAdminMediaDelete(req, res, url));
    if (method === 'GET' && pathname === '/api/admin/orders') return requireAuth(req, res, () => handleAdminOrdersList(res, url));
    if (method === 'POST' && pathname === '/api/admin/orders/approve') return requireAuth(req, res, () => handleAdminOrderApprove(req, res, url));
    if (method === 'POST' && pathname === '/api/admin/orders/reject') return requireAuth(req, res, () => handleAdminOrderReject(req, res, url));
    if (method === 'GET' && pathname === '/api/admin/settings') return requireAuth(req, res, () => handleAdminSettingsGet(res));
    if (method === 'PUT' && pathname === '/api/admin/settings') return requireAuth(req, res, () => handleAdminSettingsPut(req, res));

    return serveStatic(req, res, pathname);
  } catch (err) {
    console.error('[wwh] error:', err);
    return send(res, 500, { error: 'server error' });
  }
});

server.listen(PORT, HOST, () => {
  console.log('[wwh] listening on http://' + HOST + ':' + PORT);
  console.log('[wwh] db: ' + DB_PATH);
  console.log('[wwh] admin: http://' + HOST + ':' + PORT + '/admin');
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error('[wwh] port ' + PORT + ' is already in use — set PORT to a free port and retry.');
    process.exit(1);
  }
  throw err;
});
