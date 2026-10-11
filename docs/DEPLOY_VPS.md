# استقرار روی VPS (Ubuntu 24) — WE WERE HERE

راهنمای کوتاه برای سرور در `/opt/wewerehere` با **git pull** از GitHub و اسکریپت `wwh-deploy`.

---

## پیش‌نیاز (یک‌بار)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx curl
# در صورت خطای CairoSVG هنگام PNG بلیت:
sudo apt install -y libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0
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

```bash
sudo mkdir -p /etc/wewerehere
sudo cp /opt/wewerehere/scripts/deploy/wwh-deploy.conf.example /etc/wewerehere/deploy.conf
sudo chmod 600 /etc/wewerehere/deploy.conf
# مقادیر APP_DIR، GIT_BRANCH و غیره را در صورت نیاز ویرایش کنید
sudo ln -sf /opt/wewerehere/scripts/deploy/wwh-deploy.sh /usr/local/bin/wwh-deploy
sudo chmod +x /opt/wewerehere/scripts/deploy/wwh-deploy.sh
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
| smoke health شکست | سرویس down | `sudo systemctl status wewerehere`، `journalctl -u wewerehere -n 80` |
| health از localhost OK، دامنه نه | nginx/ssl | `nginx -t`، certbot، `proxy_pass` |
| آپلود رسید خطا | دسترسی فایل | `chown www-data` روی `storage/` و `ReadWritePaths` در unit |
| PNG بلیت خطا | Cairo | `apt install libcairo2 libpango-1.0-0` |

بعد از هر `update` ناموفق، اسکریپت آخرین خطوط journal را نشان می‌دهد.

---

## چک‌لیست دستی بعد از deploy

1. `curl -s http://127.0.0.1:5173/api/health` → `"ok":true`
2. باز کردن `/track` در مرورگر
3. ورود `/admin` با رمز systemd
4. دانلود/نمایش یک بلیت (SVG یا PNG)

---

## بکاپ دوره‌ای

علاوه بر بکاپ خودکار قبل از هر `update`، کرون شبانه توصیه می‌شود (جزئیات در [`DEPLOY.md`](../DEPLOY.md) بخش ۵).

**هرگز** `data.sqlite`، `storage/` و `uploads/` را با `git` یا `rsync --delete` بدون exclude بازنویسی نکنید.
