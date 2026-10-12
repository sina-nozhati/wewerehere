# پلن استقرار (Deploy) — WE WERE HERE

بک‌اند اصلی **Python (FastAPI + uvicorn)** است. سرور Node (`server.js`) فقط برای سازگاری قدیمی نگه داشته شده؛ در production از `npm start` (uvicorn) استفاده کنید.

---

## ۱) نیازمندی‌های سرور (VPS / دبیان یا اوبونتو)

```
Python >= 3.11
Nginx
certbot (اختیاری ولی توصیه‌شده برای HTTPS)
```

نصب وابستگی‌ها روی سرور:

```bash
cd /opt/wewerehere
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

**خروجی PNG بلیت (CairoSVG):** روی لینوکس معمولاً با `pip install cairosvg` کافی است. روی ویندوز برای dev اگر دانلود بلیت SVG برمی‌گردد، [GTK3 runtime](https://github.com/nickvidal/gtk3-runtime/releases) یا نصب وابستگی‌های Cairo را بررسی کنید؛ فرانت `track.html` در صورت SVG سرور، PNG سمت مرورگر تولید می‌کند.

مهاجرت از دیتابیس Node (یک‌بار):

```bash
.venv/bin/python backend/scripts/migrate_legacy.py
```

کپی پروژه:

```bash
# از دستگاه خودتان (با rsync یا scp):
rsync -av --exclude 'data.sqlite' --exclude 'uploads' ./ user@SERVER:/opt/wewerehere/
```

> `data.sqlite`، `storage/` و `uploads/` (legacy) دادهی زنده هستند؛ اگر پروژه از قبل روی سرور داده دارد، آنها را **جابهجا نکنید/نسوزانید**.

---

## ۲) متغیرهای محیط (env) — در فایل `/opt/wewerehere/.env` نیست؛ در systemd unit تعریف میشوند

| متغیر | پیشفرض | توضیح |
|---|---|---|
| `PORT` | `5173` | پورت گوشدادن روی 127.0.0.1 (Nginx به همین رمزproxy میکند) |
| `HOST` | `127.0.0.1` | در دیپلوی پشت Nginx حتماً `127.0.0.1` بگذارید |
| `ADMIN_PASSWORD` | `wewerehere-admin` | **حتماً قبل از استقرار عوض کنید** |
| `CAPACITY` | `50` | کل ظرفیت بلیت |
| `TICKET_PRICE` | `0` | قیمت هر بلیت (تومان)؛ یا از پنل ادمین تنظیم کنید |
| `PAYMENT_CARD_NUMBER` / `PAYMENT_CARD_HOLDER` / `PAYMENT_BANK_NAME` | `''` | اطلاعات کارت برای نمایش در فرم پرداخت |

---

## ۳) سرویس systemd — فایل `/etc/systemd/system/wewerehere.service`

```ini
[Unit]
Description=We Were Here — ticket & event backend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/wewerehere
ExecStart=/opt/wewerehere/.venv/bin/python -m uvicorn app.main:app --app-dir /opt/wewerehere/backend --host 127.0.0.1 --port 5173
Restart=on-failure
RestartSec=2
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT=5173
Environment=ADMIN_PASSWORD=یک_رمز_قوی_عوض_کن
Environment=CAPACITY=50
# Environment=TICKET_PRICE=935000
# Environment=PAYMENT_CARD_NUMBER=0000-0000-0000-0000
# Environment=PAYMENT_CARD_HOLDER=نام
# Environment=PAYMENT_BANK_NAME=بانک
# برای آپلود مدیا، یوزر باید روی پوشه پروژه دسترسی نوشتن داشته باشد:
ReadWritePaths=/opt/wewerehere/storage /opt/wewerehere/uploads /opt/wewerehere/data.sqlite

[Install]
WantedBy=multi-user.target
```

فعالسازی و اجرا:

```bash
sudo chown -R www-data:www-data /opt/wewerehere
sudo chmod 700 /opt/wewerehere/uploads
sudo systemctl daemon-reload
sudo systemctl enable --now wewerehere
sudo systemctl status wewerehere
curl http://127.0.0.1:5173/api/health   # باید {"ok":true,...} بدهد
```

---

## ۴) Nginx — فایل `/etc/nginx/sites-available/wewerehere`

```nginx
server {
    listen 80;
    server_name example.com www.example.com;   # دامنهی خودتان

    client_max_body_size 150m;   # برای آپلود عکس رسید (پایه 40MB هر فایل)

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/wewerehere /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS (اختیاری اما توصیهشده):

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com -d www.example.com
```

---

## ۵) بکاپ (مهم) — `data.sqlite`، `storage/` و `uploads/`

یک کرون روی سرور (هر شب مثلاً):

```
30 3 * * *  tar -czf /backup/wewerehere-$(date +\%F).tgz -C /opt/wewerehere data.sqlite storage uploads && find /backup -name 'wewerehere-*.tgz' -mtime +14 -delete
```

بلیتها، سفارشها و رسیدها در دیتابیس و پوشه‌های `storage/` (و در صورت legacy، `uploads/`) هستند؛ بدون بکاپ، حذف سرور = حذف دادهها.

قبل از هر `wwh-deploy update` هم یک بکاپ timestamp‌شده در `BACKUP_DIR` (پیش‌فرض `/var/backups/wewerehere`) ساخته می‌شود.

---

## ۶) ارتقا (deploy جدید)

**روش توصیه‌شده روی VPS (git):**

```bash
sudo wwh-deploy update
```

نصب یک‌بار اسکریپت و پیکربندی: [`docs/DEPLOY_VPS.md`](docs/DEPLOY_VPS.md).

**rsync از دستگاه توسعه** (فقط اگر git روی سرور ندارید):

```bash
rsync -av --delete \
  --exclude data.sqlite --exclude storage --exclude uploads --exclude .venv --exclude .env \
  ./ user@server:/opt/wewerehere/
ssh user@server 'sudo wwh-deploy update --no-git'
```

دادهٔ زنده (`data.sqlite`, `storage/`, `uploads/`) را هرگز با `--delete` یا `git clean` روی سرور حذف نکنید.

---

## ۷) تست نهایی بعد از استقرار

```bash
curl https://example.com/api/health                    # {"ok":true,"tickets":N}
curl -I https://example.com/ticket-a.svg              # 200 image/svg+xml
curl -I https://example.com/tickets.js                # 200 text/javascript
curl -I https://example.com/admin                     # 200 (صفحهی ادمین)
```

- باز کردن `/` → بلیتهای نمونه A/B با شماره/کد/نام درست.
- باز کردن `/admin` با رمز جدید → ایجاد بلیت تست → بررسی در `/track`.
- باز کردن `/track` → ثبت سفارش تستی و پیگیری.

---

## نکات امنیتی

1. `ADMIN_PASSWORD` حتماً عوض شود و جایی جز systemd unit ذخیره نشود.
2. پورت 5173 را با firewall فقط روی localhost باز کنید (Nginx روی 80/443)؛
   `sudo ufw allow 80,443/tcp`.
3. sessions ادمین در حافظه است؛ بعد از ریاستارت سرور، لاگین مجدد لازم است (رفتار عمدی).
4. برای آپدیت Node حتماً پوشهی project را نسخهبرداری (بکاپ) کنید.