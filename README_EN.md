# Emby Manager - Emby Registration Management System

<p align="center">
  <img src="https://img.shields.io/badge/Docker-Supported-blue?style=for-the-badge&logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/Version-v1.0.0-orange?style=for-the-badge" alt="Version">
</p>

A secondary development based on [guowanghushifu/emby-register-service](https://github.com/guowanghushifu/emby-register-service), adding a dashboard, user management, multi-channel notifications, and Telegram Bot remote control while keeping all original features.

> 📖 [中文版本](README.md)

---

## ✨ Features

### Original Features (Fully Preserved)
- 🎟️ **Token Generation & HMAC Signature Verification** - Secure registration link mechanism
- 📝 **Self-Service User Registration** - Copy permissions from template user, no manual configuration needed
- 🔐 **Admin Login Dashboard** - Password supports plaintext or hash storage

### New Features
- 📊 **Dashboard** — Real-time streaming status, registration trend charts (auto-refresh every 30 seconds)
- 🎟️ **Enhanced Tokens** — Support expiration (7/30 days/permanent), batch generation (up to 50), and notes
- 👥 **User Management** — View all registered users, batch renewal, lock/unlock, one-click expired account handling
- 🔔 **Multi-Channel Notifications** — Telegram, WeCom (Enterprise WeChat), DingTalk, ServerChan, Feishu
- 📅 **Scheduled Reports** — Daily/weekly/monthly automatic push notifications
- 🤖 **Telegram Bot** — Remote status query, renewal, and user lock/unlock via Bot
- 🔒 **Security Enhancements** — CSRF protection, server-side sessions, password hashing, brute-force protection

---

## 📋 System Requirements

- Docker 20.10+
- Docker Compose 2.0+
- Emby Server 4.7.0+

---

## 🚀 Quick Start

### Method 1: Docker Compose (Recommended)

```bash
# 1. Clone the project
git clone https://github.com/jialin4567/emby-register-enhanced.git
cd emby-register-enhanced

# 2. Copy and edit the configuration file
cp docker-compose.example.yml docker-compose.yml
# Edit docker-compose.yml with your settings (see detailed guide below)

# 3. Start the service
docker compose up -d

# 4. View logs
docker compose logs -f
```

Open your browser and visit `http://your-ip:18080`, then log in with your admin password.

### Method 2: Docker Run (Quick Test)

```bash
docker run -d \
  --name emby-manager \
  -p 18080:5000 \
  -v $(pwd)/data:/app/data \
  -e FLASK_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  -e ADMIN_PASSWORD="your-admin-password" \
  -e EMBY_SERVER_URL="http://your-emby-server:8096" \
  -e EMBY_API_KEY="your-emby-api-key" \
  -e COPY_FROM_USER_ID="template-user-id" \
  -e PUBLIC_ACCESS_URL="http://your-domain:18080" \
  --restart unless-stopped \
  jialin4567/emby-register-enhanced:latest
```

### Method 3: Build from Source

```bash
git clone https://github.com/jialin4567/emby-register-enhanced.git
cd emby-register-enhanced
docker build -t emby-register-enhanced .
docker compose up -d
```

---

## ⚙️ Detailed Configuration Guide

### Step 1: Generate SECRET_KEY

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output and paste it into `FLASK_SECRET_KEY`.

### Step 2: (Recommended) Hash Your Admin Password

`ADMIN_PASSWORD` supports two formats: plaintext (simple but not recommended) or hashed value (recommended).

Generate a hash with this command:

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password'))"
```

Example output: `pbkdf2:sha256:260000$xxx...` — starts with `pbkdf2:`, and the code will automatically detect and use hash comparison. Even if environment variables are leaked, attackers cannot reverse-engineer the plaintext password.

### Step 3: Get Required Parameters

#### Getting EMBY_API_KEY

1. Log in to your Emby console (`http://your-emby-address:8096`)
2. Go to **Settings → Advanced → API Keys**
3. Click the **+** button to create a new key
4. Enter an app name (e.g., `EmbyManager`) and confirm
5. Copy the generated key (a long string of characters)

#### Getting COPY_FROM_USER_ID

1. Create a dedicated template user in Emby (**do NOT give admin privileges!**)
2. Configure media library permissions, transcoding permissions, etc.
3. Go to Emby Console → User Management
4. Click on the template user and check your browser's address bar
5. Copy the string after `userId=` (e.g., `a22935174ac24711aa54f84999999`)

**Example URL:**
```
https://emby.your-domain.com:8920/web/index.html#!/users/user?userId=a22935174ac24711aa54f84999999
```

The part `a22935174ac24711aa54f84999999` is your `COPY_FROM_USER_ID`.

### Step 4: Complete docker-compose.yml Example

```yaml
services:
  emby-manager:
    image: jialin4567/emby-register-enhanced:latest  # Use pre-built image
    # build: .  # Or build from source (choose one)
    container_name: emby-manager
    ports:
      - "18080:5000"  # Host port:Container port
    volumes:
      - ./data:/app/data  # Data persistence directory
    environment:
      # ========== Required ==========
      - FLASK_SECRET_KEY=your-32-char-secret-key-here-xxxx
      - ADMIN_PASSWORD=your-admin-password-or-hash
      - EMBY_SERVER_URL=http://192.168.1.100:8096
      - EMBY_API_KEY=your-emby-api-key-from-console
      - COPY_FROM_USER_ID=template-user-id-from-url
      - PUBLIC_ACCESS_URL=http://your-domain.com:18080
      
      # ========== Optional ==========
      
      # Cloudflare accelerated address (for users in China)
      # - EMBY_SERVER_URL_CLOUDFLARE=https://emby-cf.your-domain.com
      
      # Telegram Bot configuration
      # - TG_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxyz
      # - TG_ADMIN_CHAT_ID=123456789
      
      # WeCom (Enterprise WeChat) notifications
      # - WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
      
      # DingTalk notifications
      # - DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
      # - DINGTALK_SECRET=SECxxx  # If signature verification is enabled
      
      # ServerChan notifications
      # - SERVERCHAN_KEY=SCTxxx
      
      # Feishu notifications
      # - FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
      
      # Scheduled reports (daily, weekly, monthly - can be combined)
      # - REPORT_SCHEDULE=daily,weekly,monthly
      # - REPORT_HOUR=8  # What time to send, default is 8 AM
      
    restart: unless-stopped
```

---

## 🤖 Telegram Bot Setup

### Creating a Bot

1. Search for **@BotFather** in Telegram
2. Send `/newbot` to create a new bot
3. Follow the prompts:
   - Bot name (display name)
   - Bot username (must end with bot, e.g., `MyEmbyBot`)
4. Save the returned **Bot Token** (format: `123456789:ABCdefGHIjklMNOpqrSTUvwxyz`)

### Getting Chat ID

1. Search for **@userinfobot**
2. Click **Start**, the bot will return your Chat ID
3. Or add the bot to a group, send a message, then visit:
   ```
   https://api.telegram.org/bot<YourBotToken>/getUpdates
   ```
   Look for `chat.id` in the returned JSON

### Bot Commands

The bot only responds to the admin configured in `TG_ADMIN_CHAT_ID`. Commands from other users will be ignored.

| Command | Description |
|---------|-------------|
| `/start` or `/help` | Show help information |
| `/status` | Server overview (online users, total users, expired users, etc.) |
| `/online` | Current active streaming list |
| `/users` | All users list (last 30) |
| `/expiring` | Users expiring within 3 days |
| `/renew <username> <days>` | Renew user, e.g., `/renew alice 30` |
| `/lock <username>` | Lock user (disable Emby account) |
| `/unlock <username>` | Unlock user (enable Emby account) |
| `/lockexpired` | One-click lock all expired users |
| `/report` | Send daily report immediately |

---

## 📊 Interface Preview

After logging in, you'll automatically enter the **Dashboard**. Use the left sidebar to switch between pages:

- **📊 Dashboard** — Real-time streams, registration trends, media type distribution, online users list
- **🎟️ Token Management** — Generate/copy/delete registration links, support batch generation and notes
- **👥 User Management** — View all registered users, batch renewal, lock/unlock, one-click expired account handling
- **🔔 Notifications** — Channel status, manual trigger, Bot command reference

---

## 💾 Data Backup

All data is stored in the `./data` directory. Just back up this folder:

```bash
# Backup
tar czvf emby-manager-backup-$(date +%Y%m%d).tar.gz ./data

# Restore
tar xzvf emby-manager-backup-20240312.tar.gz
docker compose restart
```

---

## ❓ FAQ

### Q: Can't access the admin dashboard?

**A:** Check the following:
- Is port 18080 being used by another program?
- Is port 18080 allowed through the firewall? (`sudo ufw allow 18080`)
- Is the Docker container running? (`docker ps | grep emby-manager`)
- Check the logs (`docker compose logs -f`)

### Q: Token link shows "invalid, tampered with, or expired"?

**A:** 
- Check if `PUBLIC_ACCESS_URL` is configured correctly. It must match the browser access address exactly (including port)
- If using a reverse proxy (Nginx), make sure `PUBLIC_ACCESS_URL` is the public access address
- Check if the token has expired (view in Token Management page)

### Q: Telegram Bot not responding to commands?

**A:**
- Confirm `TG_BOT_TOKEN` and `TG_ADMIN_CHAT_ID` are configured correctly
- The bot only responds to the configured admin Chat ID. Commands from other users are ignored
- Restart the container to apply changes (`docker compose restart`)

### Q: Push notifications not working?

**A:**
- Manually test each channel in the "Notifications" page of the admin dashboard
- Check if the Webhook URL is correct
- Check the log output (`docker compose logs -f`)

### Q: How to update to the latest version?

**A:**
```bash
cd emby-register-enhanced
docker compose pull
docker compose up -d
```

### Q: Forgot admin password?

**A:** Edit `ADMIN_PASSWORD` in `docker-compose.yml`, then restart the container:
```bash
docker compose restart
```

---

## 📝 Changelog

### v1.0.0 (2024-03-12)

**✨ New Features**
- Dashboard - Real-time streaming status monitoring, registration trend charts
- User Management System - Batch renewal, lock/unlock, expiration handling
- Enhanced Tokens - Support expiration, batch generation, notes
- Multi-Channel Notifications - Telegram, WeCom, DingTalk, ServerChan, Feishu
- Scheduled Reports - Daily/weekly/monthly automatic push
- Telegram Bot - Remote management commands

**🔒 Security Enhancements**
- CSRF protection
- Server-side sessions (filesystem storage)
- Password hash support (pbkdf2/scrypt/bcrypt)
- Brute-force protection (IP rate limiting)
- Security response headers

**🎨 UI Improvements**
- Brand new dark theme design
- Responsive layout, mobile-friendly
- Bootstrap 5 + Bootstrap Icons

---

## 🙏 Credits

This project is based on [guowanghushifu/emby-register-service](https://github.com/guowanghushifu/emby-register-service). Thanks to the original author for the open-source contribution.

---

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details
