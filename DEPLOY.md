# 🚀 راهنمای استقرار Reze

این راهنما برای اجرای Reze روی **Render**، **Railway**، **Koyeb**، **Fly.io**، **Docker** و **VPS** تهیه شده است.

> 👤 سازنده: **UnchartedAli** — 📣 کانال رسمی: [@yamods](https://t.me/yamods)

---

## ۰) آماده‌سازی مشترک (قبل از هر پلتفرمی)

### ۱. گرفتن API ID و API HASH
به [my.telegram.org](https://my.telegram.org) بروید → `API development tools` → یک اپ بسازید.
مقادیر `api_id` و `api_hash` را بردارید.

### ۲. گرفتن شناسه عددی خودتان (OWNER ID)
به [@userinfobot](https://t.me/userinfobot) پیام بدهید و عدد `Id` را بردارید.

### ۳. ساخت رمز پنل
یکی از دو روش:

```bash
# روش ساده (پیشنهادی برای PaaS): یک رمز قوی در متغیر محیطی
REZE_PANEL_PASSWORD=MyStrongPassword123!

# روش امن‌تر: هش PBKDF2
python scripts/generate_hash.py
# خروجی را در REZE_PANEL_PASSWORD_HASH قرار دهید
```

### ۴. ساخت StringSession (مهم‌ترین قدم برای PaaS)

روی سرویس‌های ابری، فایل‌سیستم موقتی است؛ بنابراین باید سشن تلگرام را به‌صورت **رشته** بسازید و در متغیر محیطی بگذارید. این کار را **روی کامپیوتر خودتان** انجام دهید:

```bash
pip install -r requirements.txt
python scripts/generate_session.py
```

اسکریپت `API ID`، `API HASH`، شماره تلفن، کد تأیید و (در صورت وجود) رمز دو مرحله‌ای را می‌پرسد و در پایان یک خط چاپ می‌کند:

```
REZE_SESSION_STRING=1BVtsOK4Bu...
```

همان مقدار را در داشبورد سرویس (Environment Variables) با کلید `REZE_SESSION_STRING` ذخیره کنید.

اگر قبلاً روی VPS فایل `data/reze.session` ساخته‌اید، می‌توانید آن را تبدیل کنید:

```bash
python scripts/generate_session.py --from-file data/reze.session --api-id 123456 --api-hash abcdef...
```

> ⚠️ **امنیت:** رشته سشن مثل رمز کامل اکانت تلگرام است. آن را در گیت، چت یا اسکرین‌شات قرار ندهید. در صورت لو رفتن، از `Settings → Devices` در تلگرام آن سشن را terminate کنید.

---

## ۱) Render

### روش الف: Blueprint (خودکار)

1. ریپو را روی GitHub push کنید.
2. در Render: **New → Blueprint** → ریپو را انتخاب کنید. فایل `render.yaml` خودکار خوانده می‌شود.
3. مقادیر `sync: false` را پر کنید:
   - `REZE_API_ID`
   - `REZE_API_HASH`
   - `REZE_OWNER_ID`
   - `REZE_SESSION_STRING`
   - `REZE_PANEL_PASSWORD`
4. Deploy کنید. آدرس پنل بعد از پایان بیلد ساخته می‌شود.
5. Health Check روی `/healthz` تنظیم شده است.

### روش ب: دستی

- **New → Web Service** → Docker
- `Dockerfile Path`: `./Dockerfile`
- `Health Check Path`: `/healthz`
- متغیرها را از جدول [متغیرهای محیطی](#متغیرهای-محیطی) اضافه کنید.
- **حتماً `REZE_WEB_HOST=0.0.0.0` باشد** و `REZE_WEB_PORT` را تنظیم نکنید؛ Render خودش `PORT` را می‌دهد و برنامه از آن استفاده می‌کند.

### نکات مهم Render

- **پلن رایگان بعد از بی‌کاری خواب می‌رود** و یوزربات آفلاین می‌شود. برای ۲۴ ساعته بودن، پلن همیشه‌فعال لازم است.
- فقط **یک Instance** اجرا کنید (اتصال هم‌زمان دو نسخه به یک سشن مشکل ایجاد می‌کند).
- برای ماندگاری دیتابیس، پلن پرداختی و **Disk** لازم است:
  - `Mount Path`: `/app/data`
  - سپس `REZE_DATA_DIR=/app/data` (در `render.yaml` از قبل تنظیم شده است).
- بدون Disk، همیشه از `REZE_SESSION_STRING` استفاده کنید؛ دیتابیس با هر دیپلوی ریست می‌شود.

---

## ۲) Railway

1. **New Project → Deploy from GitHub repo**.
2. Railway به‌خاطر وجود `Dockerfile` و `railway.json`، خودکار با Docker بیلد می‌کند.
3. در تب **Variables** مقادیر را اضافه کنید:
   ```
   REZE_API_ID=...
   REZE_API_HASH=...
   REZE_OWNER_ID=...
   REZE_SESSION_STRING=...
   REZE_PANEL_PASSWORD=...
   REZE_WEB_HOST=0.0.0.0
   REZE_TIMEZONE=Asia/Tehran
   ```
4. در **Settings → Networking → Public Networking** دامنه بسازید و پورت `8080` را انتخاب کنید (اگر پورت را می‌پرسد).
5. **Volume** برای ماندگاری (اختیاری اما توصیه‌شده):
   - Mount Path: `/data`
   - متغیر `REZE_DATA_DIR=/data` را اضافه کنید.
6. Health Check: `/healthz` (در `railway.json` تنظیم شده است).

> اگر پلتفرم متغیر `PORT` را تنظیم کند، برنامه به‌صورت خودکار روی همان پورت گوش می‌دهد. `REZE_WEB_PORT` را دستی تنظیم نکنید.

---

## ۳) Koyeb

1. **Create Service → GitHub** و ریپو را انتخاب کنید.
2. Builder: **Dockerfile** (مسیر `Dockerfile`).
3. Port: `8080` (اگر Koyeb متغیر `PORT` بدهد، برنامه خودکار از آن استفاده می‌کند).
4. Health Check: نوع **HTTP**، مسیر `/healthz`، روی همان پورتی که سرویس به آن گوش می‌دهد (`8080` یا مقدار `PORT` که Koyeb می‌دهد).
5. Environment Variables:
   ```
   REZE_API_ID=...
   REZE_API_HASH=...
   REZE_OWNER_ID=...
   REZE_SESSION_STRING=...
   REZE_PANEL_PASSWORD=...
   REZE_WEB_HOST=0.0.0.0
   ```
6. برای ماندگاری: **Volumes → Create Volume** با mount path `/data` و سپس `REZE_DATA_DIR=/data`.
7. Instance: **1** (نه بیشتر).
8. Region: نزدیک‌ترین منطقه (مثلاً Frankfurt).

> Koyeb سرویس‌های رایگان را در صورت بی‌کاری scale-to-zero می‌کند؛ برای یوزربات ۲۴ ساعته یا پلن مناسب انتخاب کنید یا از VPS استفاده کنید.

---

## ۴) Fly.io (اختیاری)

```bash
fly launch --no-deploy --copy-config
fly volumes create reze_data --size 1
fly secrets set \
  REZE_API_ID=... \
  REZE_API_HASH=... \
  REZE_OWNER_ID=... \
  REZE_SESSION_STRING=... \
  REZE_PANEL_PASSWORD=...
fly deploy
fly logs
```

فایل `fly.toml` از قبل با health check روی `/healthz` و mount `/data` آماده شده است.

---

## ۵) VPS (Ubuntu 22.04 / 24.04)

### الف) اجرای مستقیم با systemd

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git sqlite3
sudo adduser --system --group --home /home/reze reze
sudo mkdir -p /home/reze && sudo chown reze:reze /home/reze
sudo -u reze -i

cd /home/reze
git clone <YOUR_REPO_URL> reze
cd reze
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env       # مقادیر را پر کنید
python scripts/generate_hash.py   # اگر از هش استفاده می‌کنید
python -m reze.app                # یک‌بار برای تست/لاگین
# با Ctrl+C خارج شوید
exit
```

سرویس systemd:

```bash
sudo cp deploy/reze.service /etc/systemd/system/reze.service
# مسیرها و نام کاربری را در فایل سرویس بررسی کنید
sudo systemctl daemon-reload
sudo systemctl enable --now reze
sudo systemctl status reze
sudo journalctl -u reze -f
```

Nginx + HTTPS (نمونه در `deploy/nginx_reze.conf`):

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx_reze.conf /etc/nginx/sites-available/reze
sudo ln -s /etc/nginx/sites-available/reze /etc/nginx/sites-enabled/reze
sudo certbot --nginx -d reze.yourdomain.com
```

در این حالت `REZE_WEB_HOST=127.0.0.1` کافی است و Nginx ترافیک را proxy می‌کند. برای کوکی امن، `REZE_PUBLIC_URL=https://reze.yourdomain.com` را تنظیم کنید.

### ب) اجرا با Docker Compose (ساده‌تر)

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f
```

- پنل روی `http://SERVER_IP:8080` در دسترس است.
- پوشه `./data` روی هاست mount می‌شود و دیتابیس/سشن بعد از ری‌استارت می‌ماند.
- برای امنیت بیشتر، پورت 8080 را از فایروال ببندید و از Nginx/HTTPS استفاده کنید.

---

## ۶) متغیرهای محیطی

| متغیر | الزامی | توضیح |
| :--- | :---: | :--- |
| `REZE_API_ID` | ✅ | از my.telegram.org |
| `REZE_API_HASH` | ✅ | از my.telegram.org |
| `REZE_PHONE` | خیر | شماره بین‌المللی؛ برای لاگین تعاملی روی VPS |
| `REZE_OWNER_ID` | ✅ | شناسه عددی خودتان |
| `REZE_SESSION_STRING` | ⭐ روی PaaS | سشن قابل حمل تلگرام |
| `REZE_SESSION_PATH` | خیر | فقط VPS، پیش‌فرض `<data_dir>/reze.session` |
| `REZE_PANEL_PASSWORD` | ✅ | رمز پنل (ساده‌ترین روش) |
| `REZE_PANEL_PASSWORD_HASH` | جایگزین | هش امن‌تر؛ اولویت دارد |
| `REZE_PANEL_USERNAME` | خیر | پیش‌فرض `admin` |
| `REZE_SECRET_KEY` | خیر | یک مقدار تصادفی امن |
| `REZE_WEB_HOST` | روی PaaS | `0.0.0.0` |
| `REZE_WEB_PORT` | خیر | روی PaaS تنظیم نکنید؛ `PORT` خودکار استفاده می‌شود |
| `REZE_PUBLIC_URL` | خیر | آدرس عمومی پنل (تشخیص خودکار در Render/Railway/Koyeb) |
| `REZE_DATA_DIR` | خیر | مسیر دیسک/ولوم، مثلاً `/data` |
| `REZE_DATABASE_URL` | خیر | پیش‌فرض `sqlite:///<data_dir>/reze.db` |
| `REZE_PROXY` | خیر | مثلاً `socks5://user:pass@host:port` |
| `REZE_TIMEZONE` | خیر | پیش‌فرض `Asia/Tehran` |
| `REZE_LOG_LEVEL` | خیر | `INFO` |
| `REZE_ALLOW_INSECURE_DEFAULT_LOGIN` | ❌ هرگز | فقط برای توسعه محلی |

> اگر رمز پنل تنظیم نشده باشد، ورود به پنل غیرفعال می‌شود تا پنل به‌صورت عمومی و بدون رمز باز نماند. برای فعال‌سازی، `REZE_PANEL_PASSWORD` (یا هش) را تنظیم کنید.

---

## ۷) سلامت سرویس (Health Check)

مسیر عمومی و بدون نیاز به ورود:

```
GET /healthz
```

نمونه پاسخ:

```json
{
  "status": "ok",
  "service": "reze-userbot",
  "version": "1.1.0",
  "author": "UnchartedAli",
  "channel": "@yamods",
  "telegram": { "configured": true, "connected": true, "session_backend": "string" },
  "uptime_seconds": 1234
}
```

این مسیر برای Render، Railway، Koyeb، Fly و Docker HEALTHCHECK استفاده می‌شود.

---

## ۸) ماندگاری داده‌ها

| چه چیزی | بدون دیسک | با دیسک/ولوم |
| :--- | :--- | :--- |
| سشن تلگرام | با `REZE_SESSION_STRING` کار می‌کند | فایل `data/reze.session` |
| دیتابیس (فیلترها، تنظیمات، اخطارها) | با هر دیپلوی ریست می‌شود | با `REZE_DATA_DIR` می‌ماند |

- Render → Disk با mount path `/app/data`
- Railway → Volume با mount path `/data` و `REZE_DATA_DIR=/data`
- Koyeb → Volume با mount path `/data` و `REZE_DATA_DIR=/data`
- Docker → volume `./data:/app/data`

---

## ۹) عیب‌یابی

| مشکل | راه‌حل |
| :--- | :--- |
| پنل باز نمی‌شود | `REZE_WEB_HOST=0.0.0.0` باشد؛ پورت را از `PORT`/`REZE_WEB_PORT` چک کنید؛ لاگ‌ها را ببینید |
| Health Check شکست می‌خورد | مسیر `/healthz` و پورت درست (8080 یا `PORT`) را تنظیم کنید |
| `Telegram session is not authorized` | `REZE_SESSION_STRING` را دوباره بسازید و در متغیرها بگذارید |
| پس از هر ری‌استارت لاگین می‌خواهد | حتماً `REZE_SESSION_STRING` بگذارید یا دیسک دائمی وصل کنید |
| `database is locked` | فقط یک Instance اجرا کنید؛ SQLite برای یک پروسه طراحی شده است |
| ورود پنل غیرفعال است | `REZE_PANEL_PASSWORD` را تنظیم کنید (در حالت ابری اجباری است) |
| ساعت/تاریخ اشتباه | `REZE_TIMEZONE=Asia/Tehran` و در صورت نیاز `TZ=Asia/Tehran` |
| کد تأیید در لاگ ماسک می‌شود | این رفتار امنیتی عمدی است؛ از اسکریپت session استفاده کنید |

---

## ۱۰) چک‌لیست امنیتی

- [ ] `REZE_SESSION_STRING` و `.env` را هرگز commit نکنید.
- [ ] رمز قوی برای پنل بگذارید و از `REZE_PANEL_PASSWORD_HASH` استفاده کنید.
- [ ] `REZE_ALLOW_INSECURE_DEFAULT_LOGIN` را روشن نکنید.
- [ ] `REZE_SECRET_KEY` را از مقدار پیش‌فرض تغییر دهید.
- [ ] فقط یک Instance اجرا کنید.
- [ ] پنل را در صورت امکان پشت HTTPS (Nginx/Cloudflare) قرار دهید.
- [ ] در صورت لو رفتن سشن، از Telegram → Settings → Devices آن را terminate کنید.

---

ساخته‌شده با ❤️ توسط **UnchartedAli** — کانال: [@yamods](https://t.me/yamods)
