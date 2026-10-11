# ممیزی سشن و پشتیبانی — چک‌لیست

وضعیت: **اصلاح اولیه انجام شد** (۲۰۲۶-۱۰-۱۱). لاگ دیباگ: H1/H2 تأیید شد.

## علائم گزارش‌شده

- ورود خودکار به چت پشتیبانی از پیگیری بدون زدن «ادامه»
- در Network، `GET /api/support/session?phone=…` با شماره کامل
- در حالت ناشناس بعد از پیگیری، شماره از `localStorage` (`wwh_phone`) برمی‌گردد
- کلیک «ادامه» → خطای متد (۴۰۵ / Method Not Allowed)
- نگرانی از باقی‌ماندن APIهای legacy (Node `server.js` vs Python FastAPI)

## فرضیه‌های دیباگ

| ID | فرضیه | نشانه تأیید در لاگ |
|----|--------|---------------------|
| H1 | `support.html` با `?phone=` یا `localStorage` بلافاصله `verifyPhone()` را صدا می‌زند | `init branch: auto-verify-phone` |
| H2 | `GET /session` بدون Bearer متادیتای خریدار را لو می‌دهد | `GET session without bearer` |
| H3 | درخواست به سرور اشتباه (Node یا uvicorn قدیمی) → ۴۰۵ روی `POST /verify` | middleware `status: 405` |
| H4 | توکن منقضی/پاک‌شده + شماره در storage → UI نیمه‌کار | ۴۰۱ بعد از `resume-token+phone` |
| H5 | `track.html` هنوز `?phone=` در URL پشتیبانی می‌فرستد | `fromQuery: true` در init |

## رفتار سشن در همان تب (عمدی)

- توکن در **`sessionStorage`** است: رفرش یا رفتن به پیگیری و برگشت → همان گفتگو ادامه دارد.
- **تب جدید / ناشناس / بستن مرورگر** → باید دوباره «ادامه» بزند.
- روی دستگاه مشترک: نوار بالای صفحه **«تغییر شماره»** سشن را پاک می‌کند.

## چک‌لیست اصلاح (پس از تأیید لاگ)

### فرانت (`support.html`, `track.html`)

- [ ] حذف **auto-verify** در `init()` — فقط پیش‌پر کردن input؛ ورود فقط با دکمه «ادامه»
- [ ] حذف `GET /api/support/session?phone=` از جریان عادی؛ متادیتا فقط از پاسخ `POST /verify`
- [ ] لینک پیگیری → پشتیبانی **بدون** `?phone=` در URL
- [ ] جدا کردن کلید storage پیگیری (`wwh_track_phone`) از پشتیبانی یا پاک‌کردن `wwh_phone` هنگام «تغییر شماره»
- [ ] پیام خطای واضح اگر API ۴۰۴/۴۰۵ (سرور Node)

### بک‌اند (`backend/app/routers/support.py`)

- [ ] محافظت `GET /session` با Bearer یا حذف endpoint عمومی
- [ ] (اختیاری) OTP/SMS قبل از `issue_token`
- [ ] ذخیره توکن در DB/Redis به‌جای حافظه (ری‌استارت = logout)

### Legacy (`server.js`)

- [ ] مستندسازی: فقط `npm run dev` (uvicorn) — `dev:node` **بدون** `/api/support/*`
- [ ] یا proxy از Node به Python برای محیط‌هایی که هنوز Node دارند

### تست

- [ ] سناریو: پیگیری → پشتیبانی (ناشناس) → باید فرم تأیید بماند تا کلیک کاربر
- [ ] سناریو: `POST /verify` بدون شماره در query
- [ ] `pytest` + یک تست E2E دستی طبق `docs/QA_CHECKLIST.md`

## دستور اجرا

```bash
npm run dev
```

نه `npm run dev:node` برای تست پشتیبانی.
