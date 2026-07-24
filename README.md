# 🚀 Telegram V2Ray Subscription Shop Bot

A powerful Telegram bot for selling and managing V2Ray subscriptions automatically.

This bot provides a complete subscription selling system with user management, payment receipt verification, admin panel, subscription expiration tracking, and configuration delivery.

---

## ✨ Features

### 👤 User Features

- 🛍 Buy V2Ray subscriptions
- 📦 View purchased subscriptions
- 💳 Automatic invoice generation
- 🧾 Upload payment receipt
- ⏳ Subscription expiration tracking
- 📚 Usage guide
- 👨‍💻 Support section

---

### 🛠 Admin Features

- 🔐 Secure admin login panel
- 🧾 Review payment receipts
- ✅ Approve or reject payments
- 📤 Send V2Ray configurations after approval
- 💳 Change payment card information
- 📢 Manage forced channel joining
- ⚙️ Manage subscription plans

---

## 🗄 Database

The project uses SQLite database.

Database file:
v2ray_shop.db


Tables:

- `settings`
  - Stores bot configurations
  - Payment card information
  - Subscription plans
  - Required channels

- `payments`
  - User payments
  - Subscription details
  - Receipt images
  - Payment status
  - V2Ray configurations
  - Expiration dates

---

## 🧩 Tech Stack

| Technology | Usage |
|---|---|
| Python | Main programming language |
| PyTelegramBotAPI | Telegram Bot Framework |
| SQLite | Database |
| JSON | Configuration management |

---

### 1. Clone Repository

```bash
git clone https://github.com/USERNAME/v2ray-shop-bot.git

cd v2ray-shop-bot
