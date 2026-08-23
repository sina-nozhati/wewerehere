# پلن استقرار (Deploy) — «ما اینجا بودیم»

اپ یک سرور Node صفر-وابستگی است (فقط ماژول داخلی `node:sqlite`) — همان کدی که روی سیستم خودتان اجرا میشود، روی سرور هم اجرا میشود. زیر اسکریپت build یا نصب پکیج نیست؛ پوشهی پروژه را بردارید، محیط را ست کنید و Node را اجرا کنید.

---

## ۱) نیازمندی‌های سرور (VPS / دبیان یا اوبونتو)

```
Node.js >= 22.5   (ماژول node:sqlite داخلی؛ در Node 22.5+ بدون flag کار می‌کند)
Nginx
certbot (اختیاری ولی توصیه‌شده برای HTTPS)
```

نصب Node (با nvm روی یوزر غیر root):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v   # باید >= 22.5 باشد
```

چون وابستگیای وجود ندارد، از `npm install` صرف‌نظر میکنیم؛ فقط پوشهی پروژه را کپی کنید:

```bash
# از دستگاه خودتان (با rsync یا scp):
rsync -av --exclude 'data.sqlite' --exclude 'uploads' ./ user@SERVER:/opt/wewerehere/
```

> `data.sqlite` و `uploads/` دادهی زنده هستند؛ اگر پروژه از قبل روی سرور داده دارد، آنها را **جابهجا نکنید/نسوزانید**.

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
ExecStart=/usr/bin/node server.js
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
ReadWritePaths=/opt/wewerehere/uploads /opt/wewerehere/data.sqlite

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

## ۵) بکاپ (مهم) — `data.sqlite` و `uploads/`

یک کرون روی سرور (هر شب مثلاً):

```
30 3 * * *  tar -czf /backup/wewerehere-$(date +\%F).tgz -C /opt/wewerehere data.sqlite uploads && find /backup -name 'wewerehere-*.tgz' -mtime +14 -delete
```

بلیطها، سفارشها و رسیدها همه در این دو مسیر هستند؛ بدون بکاپ، حذف سرور = حذف دادهها.

---

## ۶) ارتقا (deploy جدید)

```bash
sudo rsync -av --delete --exclude data.sqlite --exclude uploads ./ user@server:/opt/wewerehere/
ssh user@server 'sudo systemctl restart wewerehere'
```

---

## ۷) تست نهایی بعد از استقرار

```bash
curl https://example.com/api/health                    # {"ok":true,"tickets":N}
curl -I https://example.com/ticket-a.svg              # 200 image/svg+xml
curl -I https://example.com/tickets.js                # 200 text/javascript
curl -I https://example.com/admin                     # 200 (صفحهی ادمین)
```

- باز کردن `/` → بلیطهای نمونه A/B با شماره/کد/نام درست.
- باز کردن `/admin` با رمز جدید → ایجاد بلیط تست → بررسی در `/track`.
- باز کردن `/track` → ثبت سفارش تستی و پیگیری.

---

## نکات امنیتی

1. `ADMIN_PASSWORD` حتماً عوض شود و جایی جز systemd unit ذخیره نشود.
2. پورت 5173 را با firewall فقط روی localhost باز کنید (Nginx روی 80/443)؛
   `sudo ufw allow 80,443/tcp`.
3. sessions ادمین در حافظه است؛ بعد از ریاستارت سرور، لاگین مجدد لازم است (رفتار عمدی).
4. برای آپدیت Node حتماً پوشهی project را نسخهبرداری (بکاپ) کنید.