# 🎁 AADHAAR·GRAM — Advanced Aadhaar PDF Telegram Bot (v2.0)

A high-performance, enterprise-grade Telegram bot designed to fetch, auto-decrypt, and deliver official e-Aadhaar PDF documents directly from the UIDAI Tathya portal using OTP authentication. Fully integrated with automated AI Captcha solving, real-time Cloudflare UPI verification, MongoDB/SQLite hybrid persistence, and Telegram Bot API modern button styling.

---

## ✨ Features & Architecture

### 🧠 100% Automated AI Captcha Engine
- Powered by `ddddocr` neural classification engine.
- Zero manual captchas: Captchas are retrieved and solved in milliseconds in the background.
- Automatic retry mechanism with up to 3 attempts on temporary server glitches.

### ⚡ Cloudflare Real-Time UPI Auto-Verifier
- Direct integration with Cloudflare UPI Payment Gateway (`faisal786786@fam`).
- Dynamic QR code generation in memory using `qrcode`.
- Live API status checks (`PENDING`, `SUCCESS`) on button tap.
- 12-digit UTR replay attack protection to prevent double crediting.

### 🗄️ Hybrid Database Persistence
- **Cloud Scaling**: Native support for **MongoDB Atlas** (`MONGO_URI`).
- **Resilient Fallback**: Automatic local ACID-compliant **SQLite** database (`bot_database.db`).
- Tracks users, credits, lifetime VIP memberships, and verified transaction history.

### 🎨 Modern Typography & Telegram Bot API UX
- **Small Caps Typography**: Consistent `sᴍᴀʟʟ ᴄᴀᴘs` aesthetic across menus, alerts, and instructions.
- **Native Button Colors**: Semantic Telegram Bot API styles (`primary` blue, `success` green, `danger` red).
- **Verified Custom Emojis**: Custom emoji tags with `icon_custom_emoji_id` parameters on both Reply and Inline keyboards.
- **Interactive Reactions**: Native Telegram ⚡ and 🎉 reactions on incoming requests and successful payments.

### 🔓 Zero-Disk Leak PDF Processing & Cracker
- Memory-safe PDF handling: Decrypted PDFs are stored in sandboxed temporary files and cleaned up immediately after transmission.
- Multi-threaded parallel password recovery using UIDAI naming conventions.

---

## 🚀 Quick Setup & Installation

### 1. Prerequisites
- Python 3.10+
- `pip` package manager
- Git

### 2. Clone the Repository
```bash
git clone https://github.com/OGAbdulOfficial/Aadhaar_PdfBot.git
cd Aadhaar_PdfBot
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
nano .env
```

```env
BOT_NAME="🎁 AADHAAR·GRAM"
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
OWNER_ID=8267676849
ADMIN_IDS="8267676849,8901139503"
OWNER_USERNAME="@apifounder"

FORCE_CHECK=True
CHANNEL_USERNAME="@AbdulBotzOfficial"
CHANNEL_LINK="https://t.me/AbdulBotzOfficial"

UPI_BASE_URL="https://upi-email-verifier.abdulstoreapi.workers.dev"
MERCHANT_UPI_ID="faisal786786@fam"
PAYEE_NAME="Faisal Abdul Aziz Ansari"

MONGO_URI="your_mongodb_connection_string"
MONGO_DB_NAME="AadhaarBot"
```

### 5. Run the Bot
```bash
python bot.py
```

---

## 🐧 24/7 Deployment on Linux VPS

### Systemd Service Setup (Recommended)
Create a systemd service file:
```bash
sudo nano /etc/systemd/system/aadhaarbot.service
```

Paste the following configuration:
```ini
[Unit]
Description=Aadhaar Telegram Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/nagi/Aadhaar_PdfBot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable aadhaarbot
sudo systemctl start aadhaarbot
sudo systemctl status aadhaarbot
```

---

## 💳 Credit Recharge Plans

| Plan | Credits | Price | Mode |
|---|---|---|---|
| **⚡ Starter** | 25 Credits | ₹50 | Regular |
| **🔥 Popular** | 60 Credits | ₹100 | Regular |
| **💎 Pro** | 160 Credits | ₹250 | Regular |
| **👑 Lifetime VIP** | Unlimited | ₹500 | Lifetime |

---

## 👨‍💻 Admin Commands

- `/admin` — Open administrative control dashboard.
- `/stats` — Live statistics (total users, active lifetime, credits pool, banned users).
- `/send <user_id> <credits>` — Grant credits manually (`-1` for Lifetime VIP).
- `/balance <user_id>` — Lookup credit balance for a user.
- `/userinfo <user_id>` — Inspect full account profile and referral count.
- `/ban <user_id>` / `/unban <user_id>` — Manage blacklist.
- `/broadcast <message>` — Send announcement to all registered users.

---

## 📜 License
Proprietary & Private. Designed for official automated e-Aadhaar distribution.
