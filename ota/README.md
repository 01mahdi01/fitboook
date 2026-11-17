# سرور OTA اپلیکیشن فیتبوک — راهنمای تحویل بک‌اند

> سرور به‌روزرسانی خودمیزبان (Self-hosted) با پیاده‌سازی پروتکل **Expo Updates v1** برای اپ اندروید/iOS فیتبوک؛ بدون EAS، بدون سرویس ابری و فقط با Django.
>
> این پوشه یک پروژهٔ Django کوچک و **کاملاً قابل اجرا و تست‌شده** است تا برنامه‌نویس بک‌اند فیتبوک بتواند آن را مستقیم اجرا کند یا فقط اپ (`ota`) را به بک‌اند اصلی منتقل کند.
>
> **محیط تست‌شده:** Python `3.14.9` — Django `5.2.19` (LTS) — تعداد تست‌های خودکار: **۲۰۶** (همه Pass) + ۴۰ بررسی End-to-End روی HTTP واقعی.

---

## فهرست

1. [این سرویس چیست و چه کاری می‌کند؟](#۱-این-سرویس-چیست-و-چه-کاری-میکند)
2. [قرارداد با کلاینت Expo — این‌ها نباید تغییر کنند](#۲-قرارداد-با-کلاینت-expo--اینها-نباید-تغییر-کنند)
3. [معماری و چرخهٔ کار](#۳-معماری-و-چرخهٔ-کار)
4. [ساختار ذخیره‌سازی (دیسک) و دیتابیس](#۴-ساختار-ذخیرهسازی-دیسک-و-دیتابیس)
5. [مرجع API](#۵-مرجع-api)
6. [نصب و ادغام در بک‌اند فیتبوک (گام‌به‌گام)](#۶-نصب-و-ادغام-در-بکاند-فیتبوک-گامبهگام)
7. [راه‌اندازی پروداکشن: gunicorn + systemd + nginx](#۷-راهاندازی-پروداکشن-gunicorn--systemd--nginx)
8. [گردش کار انتشار (Release Workflow)](#۸-گردش-کار-انتشار-release-workflow)
9. [برگشت (Rollback) و فعال‌سازی مجدد](#۹-برگشت-rollback-و-فعالسازی-مجدد)
10. [کلید قطع (Kill Switch)](#۱۰-کلید-قطع-kill-switch)
11. [نگهداشت (Retention)](#۱۱-نگهداشت-retention)
12. [امنیت (Security Checklist)](#۱۲-امنیت-security-checklist)
13. [عیب‌یابی (Troubleshooting)](#۱۳-عیبیابی-troubleshooting)
14. [تست‌ها و توسعه](#۱۴-تستها-و-توسعه)
15. [ساختار فایل‌ها](#۱۵-ساختار-فایلها)
16. [چک‌لیست تحویل به برنامه‌نویس بک‌اند](#۱۶-چکلیست-تحویل-به-برنامهنویس-بکاند)
17. [محدودیت‌ها و گام‌های بعدی](#۱۷-محدودیتها-و-گامهای-بعدی)

---

## ۱. این سرویس چیست و چه کاری می‌کند؟

اپ فیتبوک با `expo-updates` ساخته می‌شود. وقتی یک باگ جاوااسکریپتی یا تغییر UI داریم، لازم نیست نسخهٔ جدید را در گوگل‌پلی منتشر کنیم؛ کافی است بستهٔ JS جدید را از سرور خودمان (همین پروژه) سرو کنیم و اپ در اجرای بعدی آن را دانلود و اجرا کند. به این کار **OTA (Over-The-Air) Update** می‌گوییم.

این پروژه همان کاری را می‌کند که EAS Update انجام می‌داد، ولی روی زیرساخت خودمان:

- بستهٔ خروجی `npx expo export` را دریافت می‌کند، اعتبارسنجی می‌کند و روی دیسک سرور ذخیره می‌کند.
- در دیتابیس Django ثبت می‌کند که «چه نسخه‌ای برای چه `runtimeVersion` و چه پلتفرمی منتشر شده است».
- دو endpoint عمومی طبق پروتکل Expo Updates v1 ارائه می‌دهد: گرفتن manifest و دانلود فایل‌های بسته (JS bundle و asset‌ها).
- امکانات عملیاتی دارد: **برگشت (Rollback)**، **کلید قطع (Kill switch)**، **نگهداشت نسخه‌ها** و **انتشار از CI با HTTP**.

> کد هیچ وابستگی به EAS یا سرویس ابری ندارد. تنها وابستگی runtime: **Django**.

### جایگاه در معماری

```text
┌──────────────────────────┐        HTTPS         ┌────────────────────────────────────┐
│  Fitboook Expo app       │ ───────────────────► │  api.fitboook.ir (Django backend)   │
│  (expo-updates client)   │                      │                                    │
│                          │  GET /api/updates/   │  ota app:                          │
│  runtimeVersion=1.2.2    │      manifest        │    ├─ views.manifest               │
│  platform=android        │ ◄─────────────────── │    ├─ views.asset                  │
│                          │  multipart/mixed     │    ├─ publishing (copy+DB)         │
│                          │                      │    ├─ admin JSON API (CI)          │
│                          │  GET /api/updates/   │    └─ Django admin (rollback)      │
│                          │      assets?...      │                                    │
│                          │ ◄─────────────────── │  files: <OTA_UPDATES_DIR>/...      │
└──────────────────────────┘                      │  DB:    ota_release                │
                                                  └────────────────────────────────────┘
                                                              ▲
                                                   ota_publish / CI upload
```

---

## ۲. قرارداد با کلاینت Expo — این‌ها نباید تغییر کنند

کلاینت (`app.json`) توسط توسعه‌دهندهٔ موبایل این‌طور تنظیم می‌شود و **باید دقیقاً با این بک‌اند هم‌خوان باشد**:

```json
{
  "runtimeVersion": "1.2.2",
  "updates": {
    "enabled": true,
    "url": "https://api.fitboook.ir/api/updates/manifest",
    "checkAutomatically": "ON_LOAD",
    "fallbackToCacheTimeout": 0
  }
}
```

نکات الزامی:

| موضوع | مقدار مورد انتظار |
|---|---|
| آدرس manifest | دقیقاً `GET https://api.fitboook.ir/api/updates/manifest` (بدون اسلش انتهایی) |
| آدرس asset‌ها | در manifest به‌صورت مطلق ساخته می‌شود: `GET /api/updates/assets?asset=...&runtimeVersion=...&platform=...` |
| `runtimeVersion` اپ اصلی | برابر نسخهٔ اپ، مثل `1.2.2` |
| `runtimeVersion` نسخهٔ ادمین | مثل `1.2.2-admin` (جدا از اپ اصلی منتشر می‌شود) |
| پروتکل | `expo-protocol-version: 1` (کلاینت مدرن) — پروتکل `0` هم برای سازگاری پشتیبانی می‌شود |
| HTTPS | **الزامی**. کلاینت‌های release اندروید درخواست HTTP ساده را مسدود می‌کنند و Expo Updates روی HTTP ناامن کار نمی‌کند. |

> ⚠️ **قانون طلایی version/RuntimeVersion:** به‌روزرسانی OTA فقط روی باینری‌ای اعمال می‌شود که `runtimeVersion` آن **بایت‌به‌بایت** برابر `runtimeVersion` بستهٔ منتشرشده باشد. اگر نسخهٔ اپ را در استور بالا ببرید (`1.2.2` ← `1.2.3`)، باید یک بیلد جدید استور بسازید و از آن به بعد OTA نسخهٔ `1.2.3` جداگانه منتشر شود. بستهٔ `1.2.2` برای باینری `1.2.3` قابل استفاده نیست.

---

## ۳. معماری و چرخهٔ کار

```text
توسعه‌دهندهٔ موبایل                     سرور فیتبوک
─────────────────                     ────────────
npx expo export -p android
        │  dist-ota/
        ▼
  ota_publish (CLI)  ──یا──►  POST /api/admin/updates/publish/
        │                              │
        └──────────────┬───────────────┘
                       ▼
        ۱) اعتبارسنجی metadata.json و فایل‌ها
        ۲) کپی اتمیک به <OTA_UPDATES_DIR>/<runtimeVersion>/<timestampMillis>/
        ۳) ساخت/به‌روزرسانی ردیف در جدول ota_release
        ۴) هرس نسخه‌های قدیمی طبق OTA_MAX_RELEASES
                       │
                       ▼
        کلاینت: GET /api/updates/manifest
                       │
                       ├─ اگر نسخهٔ فعالی برای (runtimeVersion، platform) نیست → «به‌روزرسانی نداریم»
                       ├─ اگر کلاینت همین update-id را دارد → noUpdateAvailable
                       └─ وگرنه manifest با URL مطلق asset‌ها
                       │
                       ▼
        کلاینت: GET /api/updates/assets?...  (فایل‌ها immutable و cacheable)
```

چرا دیتابیس‌محور است و نه فقط دیسک؟

- **برگشت فوری:** با یک فیلد `is_active` می‌توان نسخهٔ قبلی را دوباره در دسترس همه گذاشت.
- **کلید قطع:** بدون دست‌زدن به فایل‌ها، سرو کردن نسخهٔ جدید متوقف می‌شود.
- **نگهداشت:** می‌توان نسخه‌های قدیمی را همراه فایل‌هایشان پاک کرد.
- **پلتفرم:** هر انتشار مربوط به یک پلتفرم ثبت می‌شود و فقط به کلاینت همان پلتفرم داده می‌شود.

---

## ۴. ساختار ذخیره‌سازی (دیسک) و دیتابیس

### دیسک

پوشهٔ ریشه با تنظیم `OTA_UPDATES_DIR` مشخص می‌شود. چیدمان (همان چیدمان مرجع اثبات‌شده در پروژهٔ nodoost):

```text
<OTA_UPDATES_DIR>/
├── 1.2.2/                          # runtimeVersion
│   ├── 1794600744639/              # timestampMillis انتشار
│   │   ├── metadata.json           # خروجی expo export
│   │   ├── expoConfig.json         # (اختیاری) در extra.expoClient برگردانده می‌شود
│   │   ├── _expo/static/js/android/entry-<hash>.hbc
│   │   └── assets/<hash>.png
│   └── 1794600999123/              # انتشار بعدی
│       └── ...
├── 1.2.2-admin/                    # نسخهٔ ادمین، کاملاً جدا
│   └── ...
└── .incoming/                      # فقط موقت هنگام آپلود zip (قابل حذف)
```

- فایل‌ها همیشه **کپی** می‌شوند؛ هرگز symlink ساخته نمی‌شود.
- کپی داخل پوشهٔ موقت `.staging-<uuid>` انجام و سپس با rename اتمیک به نام timestamp نهایی منتقل می‌شود؛ بنابراین کلاینتی وسط انتشار، فایل نیمه‌کاره نمی‌بیند.
- ردیف دیتابیس فقط **بعد از** آماده‌شدن کامل فایل‌ها ثبت می‌شود.

### دیتابیس

جدول `ota_release` — هر ردیف = یک انتشار:

| ستون | نوع | توضیح |
|---|---|---|
| `runtime_version` | CharField(128) | باید دقیقاً برابر runtimeVersion باینری باشد؛ `1.2.2` یا `1.2.2-admin` |
| `platform` | CharField | `android` یا `ios` |
| `update_id` | CharField(36) | UUID مشتق‌شده از `sha256(metadata.json)` (همان id پروتکل Expo) |
| `published_at` | DateTimeField | زمان انتشار (مبنای انتخاب «جدیدترین») |
| `created_at` | DateTimeField | زمان ثبت ردیف |
| `metadata` | JSONField | محتوای کامل `metadata.json` (fileMetadata هر پلتفرم) |
| `asset_metadata` | JSONField | `rel_path → {hash, key, content_type}` برای ساخت سریع manifest |
| `storage_path` | CharField | مسیر نسبی مثل `1.2.2/1794600744639` |
| `notes` | TextField | یادداشت انتشار |
| `is_active` | Boolean | برای برگشت؛ فقط ردیف‌های active نامزد سرو شدن هستند |
| `created_by` | FK (اختیاری) | کاربر/توکن منتشرکننده |

محدودیت یکتا: `(runtime_version, platform, update_id)` — انتشار تکراری همان محتوا ردیف تکراری نمی‌سازد (فایل‌های جدید جایگزین و ردیف به‌روزرسانی می‌شود).

جدول `ota_updatesettings` — یک ردیف singleton:

| ستون | توضیح |
|---|---|
| `enabled` | کلید قطع؛ پیش‌فرض `True` |
| `updated_at` | آخرین تغییر |

### قاعدهٔ انتخاب «جدیدترین نسخه»

هنگام درخواست manifest برای یک `(runtimeVersion, platform)`:

1. پرس‌وجو: ردیف‌های `is_active=True` با همان `runtime_version`، مرتب بر اساس `published_at` نزولی.
2. اولین ردیفی انتخاب می‌شود که **`metadata.fileMetadata` شامل آن پلتفرم** باشد و فایل bundle آن روی دیسک موجود باشد (ردیف خراب با هشدار skip می‌شود تا کانال به‌روزرسانی از کار نیفتد).
3. اگر هیچ ردیفی نباشد → «به‌روزرسانی موجود نیست» (پروتکل ۱: directive `noUpdateAvailable`؛ پروتکل ۰: HTTP 404).

> `platform` ردیف فقط نشان می‌دهد آن انتشار برای کدام پلتفرم منتشر شده است؛ معیار اصلی سرو شدن، وجود آن پلتفرم در `metadata.fileMetadata` است. چون `expo export -p android` فقط metadata اندروید را می‌آورد، عملاً هر انتشار فقط برای همان پلتفرم سرو می‌شود. برای iOS جداگانه publish کنید (با همان runtimeVersion).

> یک نکتهٔ مهم: asset‌ها بر اساس **همهٔ ردیف‌های آن runtimeVersion** (نه فقط جدیدترین) جست‌وجو می‌شوند تا کلاینتی که روی نسخهٔ قدیمی یا برگشت‌خورده است هم بتواند فایل‌هایش را دانلود کند؛ چون نام فایل‌های `expo export` هش‌محور است، فایل‌ها immutable هستند.

---

## ۵. مرجع API

### ۵.۱. `GET /api/updates/manifest` (عمومی، بدون auth)

هدرهای درخواست:

| هدر | الزامی | مقدار |
|---|---|---|
| `expo-protocol-version` | خیر | `1` (مدرن) یا `0` (legacy)؛ نبودنش = `0` |
| `expo-platform` | بله | `android` یا `ios` |
| `expo-runtime-version` | بله | مثل `1.2.2` |
| `expo-current-update-id` | خیر | id نسخه‌ای که کلاینت الان اجرا می‌کند |
| `expo-embedded-update-id` | خیر | id نسخهٔ embedded (فقط پذیرفته می‌شود) |

پاسخ پروتکل ۱ (کلاینت مدرن) — `200` با `multipart/mixed`:

```http
HTTP/1.1 200 OK
Content-Type: multipart/mixed; boundary=ota-...
expo-protocol-version: 1
expo-sfv-version: 0
Cache-Control: private, max-age=0

--ota-...
Content-Disposition: form-data; name="manifest"
Content-Type: application/json; charset=utf-8

{"id":"...","createdAt":"2026-11-13T20:12:24Z","runtimeVersion":"1.2.2", ...}
--ota-...
Content-Disposition: form-data; name="extensions"
Content-Type: application/json

{"assetRequestHeaders":{"<key>":{}, ...}}
--ota-...--
```

ساختار manifest:

```json
{
  "id": "8f14e45f-ceea-467f-a8f0-1b2c3d4e5f60",
  "createdAt": "2026-11-13T20:12:24Z",
  "runtimeVersion": "1.2.2",
  "launchAsset": {
    "hash": "<base64url sha256>",
    "key": "<md5 hex>",
    "fileExtension": ".bundle",
    "contentType": "application/javascript",
    "url": "https://api.fitboook.ir/api/updates/assets?asset=_expo%2Fstatic%2Fjs%2Fandroid%2Fentry.hbc&runtimeVersion=1.2.2&platform=android"
  },
  "assets": [
    {
      "hash": "<base64url sha256>",
      "key": "<md5 hex>",
      "fileExtension": ".png",
      "contentType": "image/png",
      "url": "https://api.fitboook.ir/api/updates/assets?asset=assets%2Flogo.png&runtimeVersion=1.2.2&platform=android"
    }
  ],
  "metadata": {},
  "extra": { "expoClient": { "...": "محتوای expoConfig.json" } }
}
```

پاسخ‌های دیگر:

| وضعیت | بدنه | معنی |
|---|---|---|
| `200` multipart با فقط `directive` | `{"type":"noUpdateAvailable"}` | نسخهٔ جدیدی نیست، یا کلاینت همین نسخه را دارد، یا کلید قطع فعال است |
| `200` JSON (پروتکل ۰) | manifest | کلاینت legacy |
| `400` | `{"error": "..."}` | هدر platform/runtimeVersion غایب یا نامعتبر |
| `404` | `{"error": "No update available"}` | پروتکل ۰ و نسخه‌ای موجود نیست |
| `406` | `{"error": "..."}` | `expo-protocol-version` ناشناخته |

نمونه تست دستی:

```bash
curl -i \
  -H "expo-platform: android" \
  -H "expo-runtime-version: 1.2.2" \
  -H "expo-protocol-version: 1" \
  https://api.fitboook.ir/api/updates/manifest
```

### ۵.۲. `GET /api/updates/assets` (عمومی، بدون auth)

| پارامتر query | الزامی | توضیح |
|---|---|---|
| `asset` | بله | مسیر نسبی داخل پوشهٔ انتشار (همان چیزی که در manifest آمده) |
| `runtimeVersion` | بله | مثل `1.2.2` |
| `platform` | بله | `android` یا `ios` |

پاسخ: بدنهٔ دقیق فایل با هدرهای:

```http
HTTP/1.1 200 OK
Content-Type: application/javascript
Content-Length: 1234567
Cache-Control: public, max-age=31536000, immutable
```

خطاها: `400` برای پارامتر نامعتبر/path traversal، `404` برای فایل یا runtimeVersion ناشناخته. فقط فایل‌هایی سرو می‌شوند که واقعاً در `metadata.json` همان انتشار ذکر شده باشند (`metadata.json` و `expoConfig.json` هرگز به‌عنوان asset سرو نمی‌شوند).

### ۵.۳. Admin/CI API — `/api/admin/updates/...`

احراز هویت: هدر `X-Admin-Key` برابر `OTA_ADMIN_TOKEN` (مقایسهٔ constant-time) **یا** کاربر staff لاگین‌شده در Django.

| متد و مسیر | کار |
|---|---|
| `GET /api/admin/updates/` | لیست release‌ها (JSON)، فیلترهای `?runtimeVersion=&platform=&active=` |
| `POST /api/admin/updates/publish/` | انتشار بسته؛ multipart: `bundle` (فایل zip خروجی export)، `runtimeVersion`، `platform`، `notes`، اختیاری `activate=false` |
| `POST /api/admin/updates/<id>/activate/` | فعال‌کردن مجدد یک release |
| `POST /api/admin/updates/<id>/deactivate/` | برگشت (rollback) به نسخهٔ قبلی |
| `GET /api/admin/updates/settings/` | وضعیت کلید قطع |
| `POST /api/admin/updates/settings/` | تغییر کلید قطع: JSON `{"enabled": false}` یا فرم `enabled=false` |

نمونهٔ انتشار از CI:

```bash
cd expo-repo
EXPO_PUBLIC_DATA_MODE=api npx expo export -p android --output-dir dist-ota
zip -r dist-ota.zip dist-ota

curl -X POST https://api.fitboook.ir/api/admin/updates/publish/ \
  -H "X-Admin-Key: $OTA_ADMIN_TOKEN" \
  -F "bundle=@dist-ota.zip" \
  -F "runtimeVersion=1.2.2" \
  -F "platform=android" \
  -F "notes=fix checkout crash"
```

> محدودیت‌های امنیتی zip (به‌صورت پیش‌فرض پیاده‌سازی شده‌اند): محافظت zip-slip، رد symlink/entry رمزگذاری‌شده، سقف حجم فشرده و بازشده (`OTA_MAX_UPLOAD_BYTES`، پیش‌فرض ۲۵۶ مگابایت)، سقف تعداد entry. اگر zip یک پوشهٔ تک‌سطحی داشته باشد (مثل `zip -r dist-ota.zip dist-ota`) خودکار تشخیص داده می‌شود.

---

## ۶. نصب و ادغام در بک‌اند فیتبوک (گام‌به‌گام)

این پروژه **self-contained** است: می‌توانید همین پوشه را deploy کنید، یا فقط اپ `ota/` را به بک‌اند اصلی فیتبوک منتقل کنید. حالت دوم رایج‌تر است.

### گام ۱ — کپی اپ

پوشهٔ `ota/` (همراه `migrations/`) را در ریشهٔ پروژهٔ Django خود کپی کنید:

```bash
cp -R backend/ota /srv/fitboook/backend/ota
```

### گام ۲ — وابستگی

Django از قبل در بک‌اند شما وجود دارد. `ota` هیچ پکیج اضافه‌ای لازم ندارد (نه DRF، نه celery، نه کتابخانهٔ آپلود). برای پروژهٔ standalone:

```bash
pip install -r requirements.txt
```

### گام ۳ — افزودن به `INSTALLED_APPS`

```python
INSTALLED_APPS = [
    # ...
    "django.contrib.admin",   # برای پنل مدیریت (اختیاری ولی توصیه‌شده)
    "ota",
]
```

### گام ۴ — URLها

در `urls.py` اصلی پروژه:

```python
from django.urls import include, path

urlpatterns = [
    # ... مسیرهای موجود پروژه
    path("api/updates/", include("ota.urls")),
    path("api/admin/updates/", include("ota.admin_urls")),
]
```

این دو include دقیقاً این مسیرها را می‌سازد:

- `GET /api/updates/manifest`
- `GET /api/updates/assets`
- مسیرهای `/api/admin/updates/...`

> اگر پروژهٔ شما زیرمسیر دیگری دارد (مثلاً همهٔ APIها زیر `/v1/`)، URL کلاینت و `OTA_ASSETS_PATH` را هم‌زمان تغییر دهید، ولی **پیش‌فرض پروژه همان چیزی است که در `app.json` قرار است بیاید**.

### گام ۵ — تنظیمات

این بلوک را به `settings.py` اضافه کنید (مقادیر را از environment بخوانید، نه hard-code):

```python
import os

# ریشه‌ای که بسته‌های OTA روی دیسک ذخیره می‌شوند؛ باید برای کاربر Django قابل نوشتن باشد
OTA_UPDATES_DIR = os.environ.get("OTA_UPDATES_DIR", str(BASE_DIR / "ota-updates"))

# دامنهٔ عمومی برای ساختن URL مطلق assetها (در پروداکشن الزامی)
OTA_PUBLIC_BASE_URL = os.environ.get("OTA_PUBLIC_BASE_URL", "https://api.fitboook.ir")

# توکن مشترک CI/ادمین برای X-Admin-Key (الزامی برای admin API)
OTA_ADMIN_TOKEN = os.environ.get("OTA_ADMIN_TOKEN", "")

# سقف حجم zip آپلودی (بایت) — پیش‌فرض 256 MiB
OTA_MAX_UPLOAD_BYTES = int(os.environ.get("OTA_MAX_UPLOAD_BYTES", 256 * 1024 * 1024))

# تعداد نسخه‌های نگهداری‌شده برای هر runtimeVersion
OTA_MAX_RELEASES = int(os.environ.get("OTA_MAX_RELEASES", 20))

# مسیر عمومی asset endpoint (باید با include در urls.py یکی باشد)
OTA_ASSETS_PATH = "/api/updates/assets"
```

توضیح هر تنظیم:

| تنظیم | پیش‌فرض | توضیح |
|---|---|---|
| `OTA_UPDATES_DIR` | — (الزامی) | مسیر مطلق پوشهٔ بسته‌ها؛ باید در backup باشد |
| `OTA_PUBLIC_BASE_URL` | `""` | اگر خالی باشد از Host درخواست ساخته می‌شود؛ در پروداکشن پشت nginx **حتماً** ست کنید |
| `OTA_ADMIN_TOKEN` | `""` | اگر خالی باشد admin API غیرفعال است (403) |
| `OTA_MAX_UPLOAD_BYTES` | 256 MiB | سقف zip در آپلود HTTP |
| `OTA_MAX_RELEASES` | 20 | نگهداشت نسخه‌ها برای هر runtimeVersion |
| `OTA_ASSETS_PATH` | `/api/updates/assets` | مسیر تولید URL asset |

### گام ۶ — مهاجرت دیتابیس

```bash
python manage.py migrate ota
```

جدول‌های `ota_release` و `ota_updatesettings` ساخته می‌شوند. ردیف تنظیمات در اولین درخواست manifest یا اولین بازدید از پنل ادمین **خودکار** ساخته می‌شود (`enabled=True`)؛ ولی می‌توانید صریح هم بسازید:

```bash
python manage.py shell -c "from ota.models import UpdateSettings; print(UpdateSettings.get_solo())"
```

### گام ۷ — پوشهٔ فایل‌ها و دسترسی‌ها

```bash
sudo mkdir -p /srv/fitboook/ota-updates
sudo chown -R fitboook:fitboook /srv/fitboook/ota-updates
# فقط کاربر اپ باید بتواند بنویسد؛ nginx (در حالت X-Accel) فقط خواندن لازم دارد
sudo chmod 750 /srv/fitboook/ota-updates
```

### گام ۸ — تست اجرای محلی

```bash
python manage.py runserver 127.0.0.1:8000
# در ترمینال دیگر، بعد از انتشار یک بسته (بخش ۸):
curl -i -H "expo-platform: android" \
     -H "expo-runtime-version: 1.2.2" \
     -H "expo-protocol-version: 1" \
     http://127.0.0.1:8000/api/updates/manifest
```

### گام ۹ — پنل ادمین

مدل‌های `OTA releases` و `OTA settings` در `/admin/` ثبت شده‌اند. از پنل ادمین می‌توانید:

- لیست انتشارها را ببینید (کدام نسخه «latest» است، مسیر فایل، یادداشت، منتشرکننده)،
- با اکشن **Deactivate** برگشت بزنید یا با **Activate** دوباره فعال کنید،
- کلید قطع را از صفحهٔ `OTA settings` روشن/خاموش کنید.

> برای دسترسی، یک کاربر staff/superuser بسازید:
> `python manage.py createsuperuser`

### گام ۱۰ — سیستم فایل و چند سرور

- **stateful است:** فایل‌ها روی دیسک همان سرور Django هستند. در حالت چند-worker همان دیسک مشترک است و مشکلی نیست.
- اگر **چند سرور** (load-balanced) دارید، `OTA_UPDATES_DIR` باید روی storage مشترک (NFS/EFS) باشد؛ در غیر این صورت publish روی یک سرور، روی بقیه دیده نمی‌شود.
- در خوشهٔ چندسروره، انتشار را از یک مسیر (یک CI job) انجام دهید تا timestamp و DB هماهنگ بمانند.

---

## ۷. راه‌اندازی پروداکشن: gunicorn + systemd + nginx

### gunicorn

```bash
gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers 3 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

> دانلود asset‌های بزرگ به‌صورت streaming با `FileResponse` انجام می‌شود؛ timeout را متناسب با حجم بسته و سرعت شبکه تنظیم کنید (پیش‌فرض ۱۲۰ ثانیه کافی است).

### systemd (نمونه)

```ini
# /etc/systemd/system/fitboook-ota.service
[Unit]
Description=Fitboook Django OTA backend (gunicorn)
After=network.target

[Service]
User=fitboook
Group=fitboook
WorkingDirectory=/srv/fitboook/backend
Environment="DJANGO_SETTINGS_MODULE=config.settings"
Environment="OTA_PUBLIC_BASE_URL=https://api.fitboook.ir"
Environment="OTA_UPDATES_DIR=/srv/fitboook/ota-updates"
EnvironmentFile=/etc/fitboook/ota.env
ExecStart=/srv/fitboook/backend/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fitboook-ota
```

### nginx

```nginx
# /etc/nginx/sites-available/api.fitboook.ir
server {
    listen 443 ssl http2;
    server_name api.fitboook.ir;

    ssl_certificate     /etc/letsencrypt/live/api.fitboook.ir/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.fitboook.ir/privkey.pem;

    # باید کمی بزرگ‌تر از OTA_MAX_UPLOAD_BYTES باشد (سرباری multipart)
    client_max_body_size 300m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 180s;
    }

    location /static/ {
        alias /srv/fitboook/staticfiles/;
        expires 30d;
    }

    # --- اختیاری: سرو فایل‌های OTA مستقیماً با nginx (X-Accel-Redirect) ---
    # با فعال‌کردن این بخش، Django فقط هدر X-Accel-Redirect می‌فرستد و nginx
    # فایل را با سرعت بالاتر و بدون اشغال worker های Python سرو می‌کند.
    location /__ota_internal/ {
        internal;
        alias /srv/fitboook/ota-updates/;
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header X-Content-Type-Options nosniff;
    }
}
```

اگر پروژهٔ Django را پشت nginx می‌گذارید، در تنظیمات Django این‌ها را هم داشته باشید:

```python
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = ["https://api.fitboook.ir"]
```

### سرو فایل‌ها: دو حالت (هر دو مستند شده‌اند)

- **حالت پیش‌فرض (پیاده‌سازی این پروژه):** Django خودش فایل را با `FileResponse` می‌فرستد. ساده‌ترین راه، بدون تنظیم اضافه؛ برای حجم‌های معمول OTA (چند مگابایت تا ~۲۰ مگابایت) کافی است.
- **حالت مقیاس‌پذیر (توصیه‌شده برای بسته‌های بزرگ یا ترافیک بالا):** `X-Accel-Redirect`. در این حالت در `ota/views.py` به‌جای `FileResponse` یک `HttpResponse` خالی با هدر `X-Accel-Redirect` برگردانید:

```python
# نمونهٔ تغییر برای حالت X-Accel-Redirect (در production)
response = HttpResponse(status=200)
response["X-Accel-Redirect"] = "/__ota_internal/" + str(file_path.relative_to(settings.OTA_UPDATES_DIR))
response["Content-Type"] = content_type
response["Cache-Control"] = "public, max-age=31536000, immutable"
return response
```

در این حالت `location /__ota_internal/` در nginx باید `internal` باشد تا کسی از بیرون نتواند مستقیم فایل‌ها را لیست/دانلود کند؛ فقط Django اجازهٔ redirect به آن را دارد. **اگر این حالت را فعال کردید، تست‌های `test_assets` باید مطابق آن به‌روزرسانی شوند** (بدنه دیگر از Django نمی‌آید).

### `collectstatic`

این اپ فایل static ندارد، ولی اگر پروژهٔ اصلی `django.contrib.staticfiles` دارد:

```bash
python manage.py collectstatic --noinput
```

---

## ۸. گردش کار انتشار (Release Workflow)

### ۸.۱. ساخت بسته — در ریپوی اکسپو

```bash
EXPO_PUBLIC_DATA_MODE=api npx expo export -p android --output-dir dist-ota
```

برای iOS (در صورت نیاز):

```bash
EXPO_PUBLIC_DATA_MODE=api npx expo export -p ios --output-dir dist-ota
```

خروجی `dist-ota/` شامل `metadata.json`، `expoConfig.json`، `_expo/static/...` و `assets/...` است.

### ۸.۲. انتشار — روی سرور (روش معمول)

```bash
python manage.py ota_publish \
  --export-dir dist-ota \
  --platform android \
  --runtime-version <app version> \
  --notes "fix checkout crash"
```

برای مثال با نسخهٔ فعلی اپ:

```bash
python manage.py ota_publish \
  --export-dir dist-ota \
  --platform android \
  --runtime-version 1.2.2 \
  --notes "fix checkout crash"
```

خروجی دستور یک JSON است که با آن می‌توانید برای CI گزارش بگیرید:

```json
{
  "ok": true,
  "release": {
    "id": 3,
    "runtimeVersion": "1.2.2",
    "platform": "android",
    "updateId": "8f14e45f-ceea-467f-a8f0-1b2c3d4e5f60",
    "publishedAt": "2026-11-13T20:12:24Z",
    "active": true,
    "storagePath": "1.2.2/1794600744639",
    "notes": "fix checkout crash",
    "createdBy": null
  },
  "created": true,
  "prunedReleaseIds": [],
  "activated": true
}
```

گزینه‌های دستور:

| گزینه | توضیح |
|---|---|
| `--export-dir` | پوشهٔ خروجی `expo export` (الزامی) |
| `--platform` | `android` یا `ios` (الزامی) |
| `--runtime-version` | دقیقاً برابر runtimeVersion باینری (الزامی) |
| `--notes` | یادداشت انتشار |
| `--no-activate` | ثبت بدون فعال‌کردن (stage کردن) |
| `--created-by USERNAME` | ثبت نام منتشرکننده |
| `--max-releases N` | override موقت `OTA_MAX_RELEASES` برای همین اجرا |

### ۸.۳. انتشار نسخهٔ ادمین

نسخهٔ ادمین (`FITBOOOK_APP_VARIANT=admin` / `EXPO_PUBLIC_APP_VARIANT=admin`) **runtimeVersion جداگانه** دارد و بستهٔ JS جداگانه می‌خواهد:

```bash
FITBOOOK_APP_VARIANT=admin EXPO_PUBLIC_APP_VARIANT=admin \
EXPO_PUBLIC_DATA_MODE=api npx expo export -p android --output-dir dist-ota-admin

python manage.py ota_publish \
  --export-dir dist-ota-admin \
  --platform android \
  --runtime-version 1.2.2-admin \
  --notes "admin panel fix"
```

> هرگز بستهٔ اپ اصلی را با runtimeVersion ادمین (یا برعکس) منتشر نکنید؛ id و فایل‌ها با هم قاطی می‌شوند. دو runtimeVersion دو کانال مستقل هستند.

### ۸.۴. انتشار از CI با HTTP

به‌جای اجرای `manage.py` روی سرور می‌توانید از CI به admin API آپلود کنید (بخش ۵.۳). نکته: `--export-dir` و zip باید محتوای **درون** پوشهٔ export باشند.

### ۸.۵. تأیید انتشار

```bash
curl -s -H "expo-platform: android" \
     -H "expo-runtime-version: 1.2.2" \
     -H "expo-protocol-version: 1" \
     https://api.fitboook.ir/api/updates/manifest | head -c 400
```

یا با admin API:

```bash
curl -s -H "X-Admin-Key: $OTA_ADMIN_TOKEN" \
     "https://api.fitboook.ir/api/admin/updates/?runtimeVersion=1.2.2&platform=android"
```

روی دستگاه واقعی، اپ باید یک‌بار کامل بسته شود و دوباره باز شود (چون `checkAutomatically: "ON_LOAD"` است). برای تست فوری از داخل اپ در development:

```js
import * as Updates from "expo-updates";
await Updates.checkForUpdateAsync();
await Updates.fetchUpdateAsync();
await Updates.reloadAsync();
```

### ۸.۶. افزایش نسخهٔ اپ

| اتفاق | نتیجه |
|---|---|
| تغییر JS/asset بدون تغییر native | فقط OTA با همان runtimeVersion |
| تغییر native (پکیج native، permission، SDK) یا افزایش نسخهٔ اپ | **بیلد جدید در استور** با runtimeVersion جدید؛ OTA از آن به بعد با runtimeVersion جدید |
| انتشار OTA برای runtimeVersion قدیمی | فقط باینری‌های قدیمی نصب‌شده آن را می‌گیرند |

نسخه‌های قدیمی runtimeVersion را تا زمانی که باینری‌هایش در دست کاربران هستند، از DB/دیسک حذف نکنید (پاک‌کردن ردیف‌ها = توقف OTA برای آن باینری‌ها).

---

## ۹. برگشت (Rollback) و فعال‌سازی مجدد

سه راه برای برگشت:

**۱) پنل ادمین:** `/admin/ota/release/` → انتخاب ردیف → اکشن «Deactivate selected releases (rollback)».

**۲) Admin API:**

```bash
# برگشت: نسخهٔ فعلی را غیرفعال کن؛ نسخهٔ فعال قبلی خودکار latest می‌شود
curl -X POST https://api.fitboook.ir/api/admin/updates/<release-id>/deactivate/ \
  -H "X-Admin-Key: $OTA_ADMIN_TOKEN"

# فعال‌سازی مجدد همان نسخه
curl -X POST https://api.fitboook.ir/api/admin/updates/<release-id>/activate/ \
  -H "X-Admin-Key: $OTA_ADMIN_TOKEN"
```

**۳) Django shell** (در شرایط اضطراری):

```bash
python manage.py shell -c "
from ota.models import Release
Release.objects.filter(id=<release-id>).update(is_active=False)
"
```

نکات مهم:

- برگشت فقط برای کلاینتی اثر دارد که هنوز نسخهٔ جدید را دانلود/اجرا نکرده یا بعد از باز شدن مجدد اپ درخواست manifest می‌کند؛ کلاینتی که update جدید را اجرا کرده، با noUpdateAvailable روی همان نسخه می‌ماند تا نسخهٔ بالاتر منتشر شود. اگر لازم است همه به نسخهٔ قبلی برگردند، معمولاً نسخهٔ قبلی را دوباره publish/activate کنید یا بیلد استور بدهید.
- asset‌های نسخهٔ غیرفعال‌شده هم‌چنان قابل دانلود می‌مانند (لازمهٔ پروتکل).
- `deactivate` روی نسخهٔ قدیمی‌تر از latest، تغییری در آنچه سرو می‌شود نمی‌دهد.
- برگشت فقط داخل پنجرهٔ نگهداشت (`OTA_MAX_RELEASES`) قابل انجام است؛ نسخه‌های هرس‌شده دیگر وجود ندارند.

---

## ۱۰. کلید قطع (Kill Switch)

اگر بستهٔ منتشرشده مشکل جدی داشت و نمی‌خواهید دستگاه‌های جدید آن را بگیرند:

```bash
# خاموش کردن OTA برای همهٔ کلاینت‌ها
curl -X POST https://api.fitboook.ir/api/admin/updates/settings/ \
  -H "X-Admin-Key: $OTA_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# روشن کردن مجدد
curl -X POST https://api.fitboook.ir/api/admin/updates/settings/ \
  -H "X-Admin-Key: $OTA_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

| کلاینت | رفتار وقتی `enabled=false` |
|---|---|
| پروتکل ۱ | `200` + directive `noUpdateAvailable` |
| پروتکل ۰ | `404` |
| دانلود assetها | همچنان `200` (کلاینت‌هایی که نسخه را گرفته‌اند از کار نمی‌افتند) |

معادل پنل ادمین: `/admin/ota/updatesettings/` → تیک `enabled` را بردارید و Save کنید.

> کلید قطع نسخه‌ها را حذف نمی‌کند؛ فقط سرو کردن آن‌ها را متوقف می‌کند. بعد از رفع مشکل می‌توانید نسخهٔ درست را publish و سپس کلید را روشن کنید.

---

## ۱۱. نگهداشت (Retention)

- با هر publish، برای همان `runtimeVersion` فقط `OTA_MAX_RELEASES` (پیش‌فرض ۲۰) نسخهٔ جدید نگه داشته می‌شود؛ ردیف‌ها و پوشه‌های قدیمی‌تر **حذف** می‌شوند تا دیسک بی‌نهایت رشد نکند.
- ردیفی که در حال حاضر سرو می‌شود همیشه در پنجرهٔ نگهداشت است و حذف نمی‌شود.
- اگر پوشهٔ فایل توسط ردیف دیگری (مثلاً ردیف iOS اشتراکی) استفاده شود، حذف فایل انجام نمی‌شود.
- برای نسخه‌های قدیمی runtimeVersion که باینری‌هایشان هنوز در دست کاربران است، باید `OTA_MAX_RELEASES` را کافی بگذارید یا ردیف‌های فعال را دستی نگه دارید.
- پاک‌کردن ردیف = پایان OTA برای آن نسخه؛ کلاینت‌های آن می‌توانند assetهای خود را تا وقتی فایل هست دریافت کنند، ولی نسخهٔ جدید نمی‌گیرند.
- پوشه‌های موقت به‌جامانده از publishهای نیمه‌کاره/کرش‌کرده (`.staging-*` و `.incoming/.zip-*`) در هر publish جدید، اگر بیشتر از یک ساعت عمر داشته باشند، خودکار پاک می‌شوند. با این حال برای پوشه‌های قدیمی‌تر بهتر است فقط پوشه‌های موقت بدون ردیف DB را با اسکریپت بررسی‌شده حذف کنید، نه `rm -rf` کورکورانه.

---

## ۱۲. امنیت (Security Checklist)

- [x] **HTTPS الزامی است.** کلاینت Expo Updates روی اندروید release اجازهٔ HTTP ساده نمی‌دهد؛ گواهی معتبر (Let's Encrypt) استفاده کنید و HTTP را به HTTPS redirect کنید.
- [x] **`OTA_ADMIN_TOKEN` را محیطی بدهید** (environment/secret manager)، هرگز در کد/git نگذارید. برای تولید:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

  توکن را از طریق `/etc/fitboook/ota.env` با مجوز `600` به سرویس بدهید و در صورت لو رفتن **rotate** کنید (تغییر env + restart؛ هیچ داده‌ای وابسته به توکن نیست).
- [x] **endpointهای manifest/assets عمداً عمومی‌اند** (پروتکل Expo auth ندارد). فقط کد JS و assetهای همان اپ را سرو می‌کنند که داخل باینری هم هست. اطلاعات حساس در یادداشت‌های Release یا expoConfig نگذارید.
- [x] **CSRF:** endpointهای admin با توکن `X-Admin-Key` و `csrf_exempt` هستند؛ مسیر session-user فقط در صورت نیاز است و امنیتش به `SESSION_COOKIE_SAMESITE='Lax'` (پیش‌فرض Django) و HTTPS وابسته است. این پیش‌فرض را تغییر ندهید.
- [x] **آپلود zip:** محافظت zip-slip، symlink، رمزگذاری، zip-bomb و سقف حجم/تعداد entry در کد پیاده‌سازی شده است. nginx هم `client_max_body_size` را متناسب تنظیم کند.
- [x] **مسیر asset:** هر مسیر از query با `safe_relative_path` + `resolve` بررسی می‌شود؛ خارج از پوشهٔ انتشار چیزی سرو نمی‌شود و فقط فایل‌های ذکرشده در metadata قابل دانلودند.
- [x] **دسترسی دیسک:** `OTA_UPDATES_DIR` فقط برای کاربر اپ قابل نوشتن باشد؛ اگر X-Accel فعال است، nginx فقط read و location `internal`.
- [x] **Backup:** دیتابیس و `OTA_UPDATES_DIR` را **با هم** بکاپ بگیرید (ردیف‌ها به فایل‌ها اشاره دارند). نمونه: یک cron شبانه با `pg_dump` + `tar` از پوشهٔ updateها.
- [ ] **Code signing (اختیاری، پیاده‌سازی نشده):** پروتکل Expo امکان امضای manifest با `expo-signature` و تأیید در کلاینت (`codeSigningCertificate` در app.json) را دارد. چون این سرویس روی HTTPS خودمان است و کلاینت فقط به همین دامنه وصل می‌شود، ریسک MITM با TLS پوشش داده می‌شود. اگر سیاست امنیتی سخت‌گیرانه‌تری لازم شد، گام بعدی: تولید کلید/گواهی با `npx expo-updates codesigning:generate`، جاسازی گواهی در بیلد، امضای manifest با `expo-signature` (SFV) در همین سرور. **در حال حاضر امضا انجام نمی‌شود** و در app.json نباید `codeSigningCertificate` تنظیم شود.
- [ ] **Rate limiting (اختیاری):** می‌توانید در nginx برای `/api/admin/updates/` محدودیت IP/rate بگذارید؛ manifest/assets باید برای همه باز باشند.
- [ ] **بازبینی لاگ:** لاگ‌های `ota` (logger name: `ota`) را در سیستم لاگ خود نگه دارید؛ انتشار، برگشت و کلید قطع در سطح warning/info لاگ می‌شوند.

---

## ۱۳. عیب‌یابی (Troubleshooting)

### ابزارهای بررسی

```bash
# پاسخ خام manifest
curl -i -H "expo-platform: android" -H "expo-runtime-version: 1.2.2" \
     -H "expo-protocol-version: 1" https://api.fitboook.ir/api/updates/manifest

# لیست نسخه‌های ثبت‌شده (نیاز به توکن)
curl -s -H "X-Admin-Key: $OTA_ADMIN_TOKEN" https://api.fitboook.ir/api/admin/updates/ | python -m json.tool

# لاگ‌های دستگاه (اندروید)
adb logcat | grep -i "expo-updates"

# وضعیت updates از داخل اپ در dev
import * as Updates from "expo-updates";
console.log(Updates.updateId, Updates.runtimeVersion, Updates.isEmbeddedLaunch);
```

### جدول مشکلات رایج

| نشانه | علت محتمل | راه‌حل |
|---|---|---|
| manifest همیشه `noUpdateAvailable` | هیچ ردیف active با آن `runtimeVersion` نیست؛ یا `expo-current-update-id` کلاینت با latest یکی است | لیست admin را با همان `runtimeVersion` چک کنید؛ مقدار runtimeVersion باینری را با `Updates.runtimeVersion` مقایسه کنید |
| manifest `404` (پروتکل ۰) | نسخه‌ای برای آن runtimeVersion/platform نیست یا کلید قطع خاموش است | publish بزنید؛ `GET .../settings/` را چک کنید |
| manifest `400` | هدر `expo-platform` یا `expo-runtime-version` غایب/نامعتبر است | درخواست کلاینت را با curl بازسازی کنید |
| manifest `406` | `expo-protocol-version` ناشناخته (کلاینت جدیدتر از سرور) | پروتکل کلاینت را بررسی کنید؛ سرور ۰ و ۱ را پشتیبانی می‌کند |
| admin API `401` | هدر `X-Admin-Key` ارسال نشده | هدر را اضافه کنید |
| admin API `403` | توکن اشتباه یا `OTA_ADMIN_TOKEN` در سرویس ست نشده | env سرویس را چک و restart کنید |
| `413` هنگام publish | zip از `OTA_MAX_UPLOAD_BYTES` بزرگ‌تر است (یا nginx `client_max_body_size`) | هر دو را افزایش دهید |
| `CommandError: metadata.json not found` | مسیر `--export-dir` اشتباه است یا zip محتوای پوشه را ندارد | از `dist-ota/` (نه والدش) publish کنید؛ zip را از محتوای پوشه بسازید |
| `metadata.json has no bundle for platform 'ios'` | export با `-p android` گرفته شده ولی با `--platform ios` منتشر می‌کنید | export درست + publish درست؛ برای iOS `npx expo export -p ios` بگیرید |
| اپ دانلود می‌کند ولی خطای hash/mismatch | فایل‌های پوشهٔ انتشار بعد از publish تغییر کرده‌اند (immutable violation) | هرگز فایل نسخهٔ منتشرشده را ویرایش نکنید؛ export جدید + publish جدید |
| asset `404` بعد از مدتی | نسخهٔ قدیمی هرس شده (`OTA_MAX_RELEASES`) | مقدار را زیاد کنید؛ نسخه‌های قدیمی runtimeVersionهای در دست کاربر را نگه دارید |
| asset برای کلاینت قدیمی `404` | ردیف آن نسخه حذف شده یا فایل‌ها دستکاری شده | backup را بررسی/بازگردانید |
| اپ بعد از انتشار همچنان نسخهٔ قبل را نشان می‌دهد | `checkAutomatically: ON_LOAD` فقط در اجرای بعدی چک می‌کند؛ اپ را کامل ببندید و باز کنید | رفتار طبیعی است؛ برای تست فوری `Updates.fetchUpdateAsync()` |
| کلاینت اصلاً به سرور وصل نمی‌شود | HTTP به‌جای HTTPS، DNS/SSL، یا آدرس `updates.url` اشتباه | `app.json` و گواهی SSL را چک کنید |
| بعد از restart سرور، تنظیمات کلید قطع برنمی‌گردد | تنظیمات در DB است نه فایل | مقدار row `ota_updatesettings` را چک کنید |
| انتشار با خطای `database is locked` در SQLite | هم‌زمانی publish/درخواست‌ها در SQLite | در پروداکشن از همان دیتابیس اصلی پروژه (Postgres/MySQL) استفاده کنید |

> لاگ‌ها: `logger` ماژول `ota` است. در Django LOGGING اگر level مشخص نکرده‌اید، هشدارها به‌طور پیش‌فرض دیده می‌شوند؛ برای debug سطح `INFO` فعال کنید.

---

## ۱۴. تست‌ها و توسعه

### راه‌اندازی محیط تست (دقیقاً همین دستورات استفاده شده)

```bash
cd backend

# venv داخل پوشهٔ backend تا سیستم دست‌نخورده بماند
python3 -m venv .venv
source .venv/bin/activate

# پوشهٔ موقت و کش pip داخل ورک‌اسپیس (محیط sandbox)
mkdir -p .tmp
export TMPDIR=$PWD/.tmp
export PIP_CACHE_DIR=$PWD/.pip-cache

pip install --upgrade pip
pip install "Django>=5.2,<6"     # نصب‌شده: Django 5.2.19
```

### اجرای تست‌ها

```bash
cd backend
source .venv/bin/activate
python manage.py test
```

خروجی نهایی (خلاصه):

```text
Found 206 test(s).
System check identified no issues (0 silenced).

Ran 206 tests in ~3s

OK
```

### چه چیزهایی تست می‌شوند؟

- `test_metadata.py` — اعتبارسنجی `metadata.json`، استخراج id از `sha256`، هش‌های asset، content-type‌ها، expoConfig
- `test_paths.py` — امنیت مسیرها، runtimeVersion، traversal
- `test_models.py` — مدل‌ها، یکتایی، انتخاب latest، برگشت، singleton
- `test_http.py` — ساختار bytes پاسخ multipart، هدرهای پروتکل
- `test_manifest.py` — manifest پروتکل ۱ و ۰، directiveها، کلید قطع، runtimeVersionهای جدا، `extra.expoClient`
- `test_assets.py` — سرو فایل، content-type/length/cache، traversal، assetهای نسخه‌های قدیمی
- `test_publish_command.py` — publish با CLI (happy path + ردها)، layout دیسک، republish
- `test_publishing_zip.py` — آپلود zip: zip-slip، symlink، zip-bomb، حجم، تعداد entry
- `test_admin_api.py` — auth (token/staff)، publish/list/activate/deactivate/settings
- `test_retention.py` — هرس نسخه‌ها (فایل + ردیف)، عدم حذف فایل مشترک
- `test_admin_site.py` — URL contract، ثبت در Django admin، هم‌خوانی migration با مدل‌ها

> تست‌ها از SQLite in-memory و پوشه‌های موقت استفاده می‌کنند؛ هیچ داده/فایلی روی محیط شما باقی نمی‌گذارند و لازم نیست `migrate` روی دیتابیس واقعی بزنید.

### کیفیت کد

```bash
# ابزارها در requirements نیستند؛ برای توسعه optionally نصب کنید
pip install black ruff
black .
ruff check .
```

کد با `black` فرمت شده و `ruff` بدون خطا پاس می‌شود (به‌جز قواعد مربوط به فایل migration خودکار و Meta مدل‌های Django).

---

## ۱۵. ساختار فایل‌ها

```text
backend/
├── manage.py
├── requirements.txt
├── .gitignore                           # .venv/ .data/ .tmp/ __pycache__/ *.sqlite3
├── README.md                            # همین سند
├── config/                              # فقط برای اجرای standalone و تست
│   ├── settings.py                      # env-based؛ بلوک OTA_* نمونه
│   ├── urls.py                          # includeهای قراردادی
│   ├── wsgi.py / asgi.py
├── ota/                                 # ← اپ تحویلی (این را به پروژهٔ اصلی ببرید)
│   ├── models.py                        # Release + UpdateSettings
│   ├── metadata.py                      # parse/validate metadata.json، هش‌ها، id
│   ├── publishing.py                    # publish از دیسک/zip، کپی اتمیک، retention
│   ├── services.py                      # انتخاب latest، ساخت manifest، پیدا کردن asset
│   ├── views.py                         # GET /manifest و GET /assets
│   ├── admin_views.py                   # JSON admin API (publish/list/rollback/settings)
│   ├── http.py                          # multipart encoder و پاسخ‌های استاندارد
│   ├── paths.py                         # امنیت مسیر/runtimeVersion
│   ├── conf.py                          # خواندن تنظیمات OTA_*
│   ├── exceptions.py                    # خطاهای typed با HTTP status
│   ├── urls.py / admin_urls.py          # مسیرهای عمومی و ادمین
│   ├── admin.py                         # پنل Django admin
│   ├── apps.py
│   ├── migrations/0001_initial.py       # جدول‌ها (این را commit/کپی کنید)
│   ├── management/commands/ota_publish.py
│   └── tests/                           # ۲۰۶ تست خودکار
└── .data/                               # فقط runtime محلی و gitignored (sqlite + updateها)
```

---

## ۱۶. چک‌لیست تحویل به برنامه‌نویس بک‌اند

### قبل از تحویل (انجام‌شده در این بسته)

- [x] اپ `ota` با مدل‌ها، migration، مدیریت، تست‌ها و مستندات کامل
- [x] پروتکل v1 دقیقاً مطابق اسپک Expo (manifest + extensions + directive)
- [x] پشتیبانی پروتکل ۰ برای کلاینت‌های قدیمی
- [x] CLI انتشار + admin API آپلود zip برای CI + Django admin
- [x] برگشت، کلید قطع، نگهداشت، امنیت مسیر/zip
- [x] ۲۰۶ تست خودکار Pass + ۴۰ بررسی End-to-End روی HTTP واقعی

### برنامه‌نویس بک‌اند فیتبوک باید انجام دهد

1. `ota/` + `migrations/` را به پروژهٔ اصلی Django کپی کند.
2. `ota` را به `INSTALLED_APPS` و URLها را طبق بخش ۶ اضافه کند.
3. تنظیمات `OTA_*` را (از env) در settings اصلی قرار دهد؛ `OTA_PUBLIC_BASE_URL=https://api.fitboook.ir` و `OTA_ADMIN_TOKEN` تصادفی قوی.
4. `python manage.py migrate ota` را روی دیتابیس اصلی بزند و از بکاپ گرفتن مطمئن شود.
5. پوشهٔ `OTA_UPDATES_DIR` را بسازد و مالکیت/مجوز درست بدهد.
6. nginx (TLS + `client_max_body_size`)، gunicorn/systemd را تنظیم کند و سرویس را restart کند.
7. `GET /api/updates/manifest` را با curl تست کند (بخش ۵.۱).
8. یک بستهٔ آزمایشی با `ota_publish` منتشر و با curl تأیید کند، سپس از اپ روی دستگاه واقعی OTA بگیرد.
9. یک **تمرین برگشت (rollback drill)** انجام دهد: publish نسخهٔ دوم → deactivate → تأیید سرو نسخهٔ اول → activate.
10. یک **تمرین کلید قطع** انجام دهد: settings `enabled=false` → تأیید noUpdateAvailable → روشن کردن مجدد.
11. ورودی‌های کلاینت را با تیم موبایل چک کند: `updates.url`، `runtimeVersion`، `enabled`، `checkAutomatically`، HTTPS.
12. فرایند انتشار و دسترسی به توکن/پنل ادمین را در runbook تیم ثبت کند (چه کسی publish می‌کند، از کجا، چطور rollback می‌زند).
13. بکاپ دیتابیس + پوشهٔ updateها و مانیتورینگ فضای دیسک/خطاهای 5xx را فعال کند.
14. (اختیاری، در صورت ترافیک بالا) X-Accel-Redirect را طبق بخش ۷ فعال کند.

---

## ۱۷. محدودیت‌ها و گام‌های بعدی

- **Code signing پیاده‌سازی نشده است.** امضای manifest (`expo-signature`) و تأیید گواهی در کلاینت، گام بعدی امنیتی در صورت نیاز است (بخش ۱۲).
- **فقط فایل‌سیستم محلی/مشترک.** آداپتور S3/CDN وجود ندارد. برای چندسروره باید storage مشترک (NFS/EFS) بدهید یا در آینده لایهٔ storage انتزاعی اضافه شود.
- **بدون targeting/channel.** همهٔ کلاینت‌های یک runtimeVersion/platform یک نسخه می‌گیرند. اگر لازم شد، می‌توان با `metadata` در manifest و `expo-manifest-filters` کانال/گروه اضافه کرد (نقطهٔ توسعه: فیلد `metadata` در Release و هدر فیلتر).
- **بدون فشرده‌سازی در Django.** فایل‌ها خام سرو می‌شوند؛ می‌توانید در nginx برای `application/javascript` و فونت‌ها `gzip`/`brotli` فعال کنید (کلاینت Expo هر دو را پشتیبانی می‌کند). توجه: تصاویر/ویدیو را دوباره فشرده نکنید.
- **single publisher.** هم‌زمانی چند publisher روی یک runtimeVersion به‌ندرت می‌تواند collision timestamp بدهد (کد retry دارد و DB یکتاست)، ولی بهتر است انتشار از یک job/مسیر واحد انجام شود.
- **پنل ادمین Django** برای عملیات کافی است؛ اگر UI اختصاصی لازم شد، همین JSON API پایهٔ آن است.
- **پروتکل ۱ جدیدتر از این سند:** اگر Expo در آینده نسخه‌های جدیدتر پروتکل را با ویژگی‌های اجباری منتشر کرد، `parse_protocol_version` و اسپک را بررسی کنید (فعلاً ۰ و ۱ پشتیبانی می‌شوند).

---

<div dir="ltr">

**Handoff summary (English, for the lead/employer):**
This Django app serves the Expo Updates v1 protocol from our own backend (no EAS). It exposes `GET /api/updates/manifest` and `GET /api/updates/assets`, plus a token-protected admin API to publish (`POST /api/admin/updates/publish/`), roll back (`POST .../<id>/deactivate/`), re-activate, list releases and toggle a global kill switch. Releases are stored on disk as `<OTA_UPDATES_DIR>/<runtimeVersion>/<timestampMillis>/` and tracked in `ota_release`; the newest active release whose `metadata.fileMetadata` contains the requested platform is served. Tests: **206 Django tests** pass (`python manage.py test`), plus **40 end-to-end checks** against a real `runserver` were run manually. Tested on **Django 5.2.19 / Python 3.14.9**. Only `backend/` was modified.

</div>
