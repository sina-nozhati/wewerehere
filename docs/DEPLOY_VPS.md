# استقرار روی VPS (Ubuntu 24) — WE WERE HERE

راهنمای کوتاه برای سرور در `/opt/wewerehere` با **git pull** از GitHub و اسکریپت `wwh-deploy`.

---

## پیش‌نیاز (یک‌بار)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx curl
# برای PNG بلیت با متن فارسی (Cairo/Pango + فونت):
sudo apt install -y libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 fontconfig
# `wwh-deploy install` همین پکیج‌ها و ثبت Vazirmatn را انجام می‌دهد.
```

کلون روی سرور:

```bash
sudo mkdir -p /opt/wewerehere
sudo git clone https://github.com/YOUR_ORG/wewerehere.git /opt/wewerehere
cd /opt/wewerehere
```

### Git در ایران / SSH

- ترجیحاً **Deploy key** روی GitHub (فقط این ریپو، read-only).
- روی سرور:

```bash
sudo mkdir -p /root/.ssh
sudo chmod 700 /root/.ssh
# کلید deploy را در /root/.ssh/id_ed25519_wwh قرار دهید
sudo ssh-keyscan github.com >> /root/.ssh/known_hosts
```

در `/etc/wewerehere/deploy.conf` یا قبل از pull:

```bash
export GIT_SSH_COMMAND='ssh -i /root/.ssh/id_ed25519_wwh -o IdentitiesOnly=yes'
```

اگر pull با HTTPS و credential است، `git config credential.helper store` فقط برای کاربری که `wwh-deploy` را اجرا می‌کند.

---

## نصب اولیه `wwh-deploy`

CLI یک **فایل واقعی** در `/usr/local/bin/wwh-deploy` است (نه symlink داخل ریپو). سرویس `wwh-deploy-cli.service` هم روی هر بوت آن را دوباره ترمیم می‌کند.

```bash
sudo mkdir -p /etc/wewerehere
sudo cp /opt/wewerehere/scripts/deploy/wwh-deploy.conf.example /etc/wewerehere/deploy.conf
sudo chmod 600 /etc/wewerehere/deploy.conf
```

### اگر `sudo: wwh-deploy: command not found` دیدی

اول CLI را نصب کن (یک‌بار کافی است؛ بعدش بوت و `update` خودش نگهش می‌دارد):

```bash
sudo git -C /opt/wewerehere pull --ff-only
sudo bash /opt/wewerehere/scripts/deploy/ensure-wwh-deploy-cli.sh
sudo wwh-deploy update
```

از این به بعد فقط:

```bash
sudo wwh-deploy update
```

واحد systemd (رمز ادمین را عوض کنید):

```bash
sudo cp /opt/wewerehere/scripts/deploy/wewerehere.service.example /etc/systemd/system/wewerehere.service
sudo systemctl daemon-reload
sudo systemctl enable --now wewerehere
```

نصب وابستگی‌های پایتون و پوشه‌های داده:

```bash
sudo wwh-deploy install
```

اگر از نسخهٔ Node مهاجرت می‌کنید (یک‌بار):

```bash
sudo wwh-deploy migrate
sudo wwh-deploy update
```

Nginx و SSL را طبق [`DEPLOY.md`](../DEPLOY.md) تنظیم کنید؛ `wwh-deploy` nginx را تغییر نمی‌دهد.

---

## پیامک sms.ir (بعد از تأیید بلیت + پنل ادمین)

کلید را در گیت نگذارید. روی سرور:

```bash
sudo bash /opt/wewerehere/scripts/deploy/set-sms-env.sh \
  --api-key 'YOUR_SMS_IR_KEY' \
  --ticket-template TEMPLATE_ID_TICKET \
  --admin-template TEMPLATE_ID_ADMIN
```

این فایل `/etc/wewerehere/sms.env` را می‌نویسد، در صورت نیاز `EnvironmentFile` را به unit اضافه می‌کند و سرویس را ری‌استارت می‌کند. تا قبل از ست کردن کلید، `SMS_PROVIDER=console` بماند.

---

## آپدیت روزمره

```bash
cd /opt/wewerehere
sudo wwh-deploy update
```

این کار به ترتیب: بکاپ `data.sqlite` + `storage/` + `uploads/` → `git pull --ff-only` → `pip install` → `migrate_legacy` → `systemctl restart` → تست smoke.

فلگ‌های مفید:

| فلگ | کاربرد |
|-----|--------|
| `--no-backup` | بدون tar قبل از آپدیت |
| `--no-git` | فقط pip + restart + smoke (کد با rsync آمده) |
| `--dry-run` | فقط نمایش دستورات |

```bash
sudo wwh-deploy status
sudo wwh-deploy smoke
```

---

## عیب‌یابی

| علامت | احتمال | اقدام |
|--------|--------|--------|
| `git pull` شکست | شبکه / احراز هویت | SSH key، `GIT_SSH_COMMAND`، `known_hosts` |
| `would be overwritten by merge` روی `wwh-deploy.sh` | ویرایش دستی اسکریپت روی سرور | `sudo git -C /opt/wewerehere checkout -- scripts/deploy/wwh-deploy.sh` سپس `sudo wwh-deploy update` (از نسخهٔ جدید اسکریپت خودکار هم discard می‌کند) |
| `apt-get update` / Docker `403 Forbidden` | منبع apt خراب (مثلاً `download.docker.com`) | موقتاً غیرفعال کنید: `sudo mv /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/docker.list.disabled` سپس `sudo apt-get update` و `sudo apt-get install -y libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 fontconfig` |
| `curl` نمونه بلیت → `application/json` | توکن ادمین اشتباه/جایگزین `TOKEN` | `export PW` بعد از `PW=$(grep …)`؛ یا: `ADMIN_PASSWORD="$PW" python3 /opt/wewerehere/backend/scripts/smoke_admin_ticket_png.py` |
| smoke health شکست بلافاصله بعد از restart | uvicorn هنوز بالا نیامده | `curl -s http://127.0.0.1:5173/api/health` — اگر `{"ok":true}` است deploy موفق بوده؛ `git pull` و دوباره `bash …/wwh-deploy.sh update` (نسخهٔ جدید health را retry می‌کند) |
| smoke health شکست | سرویس down | `sudo systemctl status wewerehere`، `journalctl -u wewerehere -n 80` |
| health از localhost OK، دامنه نه | nginx/ssl | `nginx -t`، certbot، `proxy_pass` |
| آپلود رسید خطا | دسترسی فایل | `chown www-data` روی `storage/` و `ReadWritePaths` در unit |
| PNG بلیت خطا یا مربع فارسی | Cairo / فونت | `sudo wwh-deploy install`؛ `wwh-deploy status` (font + libcairo2 + uvicorn) |
| بلیت بدون تاریخ | `event_at` خالی | در ادمین «تاریخ و ساعت اجرا» را پر کنید قبل از تأیید سفارش |

بعد از هر `update` ناموفق، اسکریپت آخرین خطوط journal را نشان می‌دهد.

---

## چک‌لیست دستی بعد از deploy

1. `curl -s http://127.0.0.1:5173/api/health` → `"ok":true`
2. باز کردن `/track` در مرورگر
3. ورود `/admin` با رمز systemd
4. `sudo wwh-deploy smoke` — شامل health و در صورت تنظیم `ADMIN_PASSWORD` در unit، نمونه PNG
5. دانلود بلیت نمونه از ادمین (باید PNG با متن فارسی باشد)

---

## بکاپ دوره‌ای

علاوه بر بکاپ خودکار قبل از هر `update`، کرون شبانه توصیه می‌شود (جزئیات در [`DEPLOY.md`](../DEPLOY.md) بخش ۵).

**هرگز** `data.sqlite`، `storage/` و `uploads/` را با `git` یا `rsync --delete` بدون exclude بازنویسی نکنید.
