# Telegram V2Ray Subscription Shop Bot

A Telegram bot for selling V2Ray subscriptions, reviewing payment receipts, and delivering configuration strings after manual approval.

Current bot version: `1.6.0`

## Features

### User side

- Forced membership check for up to 6 Telegram channels, with a 5-minute membership-result cache.
- Display available plans and prices in toman.
- Purchase flow: select a plan, choose a subscription name, receive payment details, and upload a receipt photo.
- Order status for the latest 5 orders.
- List of approved subscriptions with purchase date, expiration date, and V2Ray configuration.
- Usage guide with Android, iOS, and Windows client links.
- Configurable support username.

### Admin side

- Password-protected panel available through `/admin`.
- Payment queue with receipt photo review.
- Approve or reject payments.
- Send a V2Ray string after approval; the bot calculates the expiration date from the plan duration and sends the result to the user.
- View user and payment statistics.
- Update payment card number and account holder name.
- Add, remove, or clear forced-join channels.
- Add, remove, or clear subscription plans.
- Audit logging for logins, order changes, plan changes, channel changes, and card updates.

## Requirements

- Python 3.9 or newer
- A Telegram bot token from [BotFather](https://t.me/BotFather)
- `PyTelegramBotAPI`
- The bot should be an administrator in every forced-join channel so membership checks work reliably.

## Installation and configuration

1. Clone the repository and enter its directory:

  ```bash
  git clone <repository-url>
  cd vpn_selling_shopping_bot
  ```

2. Install the dependency:

  ```bash
  python -m pip install PyTelegramBotAPI
  ```

3. Set the required environment variables before starting the bot:

  | Variable | Required | Description |
  |---|---:|---|
  | `BOT_TOKEN` | Yes | Telegram bot token |
  | `ADMIN_PASSWORD` | Yes | Password used by `/admin` |
  | `DATABASE_PATH` | No | Custom SQLite path; defaults to `v2ray_shop.db` beside `AGHILE.py` |

  PowerShell example:

  ```powershell
  $env:BOT_TOKEN = "<bot-token>"
  $env:ADMIN_PASSWORD = "<strong-admin-password>"
  python AGHILE.py
  ```

  Linux/macOS example:

  ```bash
  export BOT_TOKEN="<bot-token>"
  export ADMIN_PASSWORD="<strong-admin-password>"
  python AGHILE.py
  ```

Do not commit tokens or passwords. The source currently contains fallback values for backward compatibility; always override them with environment variables and rotate any previously exposed bot token or password.

## Runtime behavior

- The bot uses threaded polling with up to 8 worker threads.
- SQLite connections use WAL mode, a 10-second busy timeout, and transaction rollback/close handling.
- Settings such as plans, card details, and forced-join channels are loaded into an in-memory cache and updated when changed by an admin.
- A background worker performs a passive WAL checkpoint every 10 minutes.
- Handler errors are logged without stopping the polling loop. Telegram-specific cases such as expired callbacks and blocked users are handled separately.
- Polling skips updates left over from downtime and retries critical polling failures with exponential backoff from 5 to 60 seconds.
- `SIGINT` and `SIGTERM` trigger a clean polling shutdown.

## Data and logs

The default database is `v2ray_shop.db`. It is created automatically on startup.

| Table | Stores |
|---|---|
| `settings` | Card details, support username, plans, and forced-join channels |
| `users` | Telegram user ID, username, first name, and registration time |
| `payments` | Plan, receipt, status, configuration, purchase date, and expiration date |

The `logs/` directory is created automatically:

- `logs/bot.log`: general bot activity
- `logs/errors.log`: errors and tracebacks
- `logs/audit.log`: administrative and order audit events

All log files use rotating handlers. Avoid sharing them because they may contain user IDs and operational details.

## Limits and input formats

- Maximum forced-join channels: `6`
- Maximum subscription plans: `12`
- New channel format: `@ChannelName`
- New plan format: `Plan name | price in toman | validity in days`

Example:

```text
30 GB one month | 50000 | 30
```

## Database initialization

No migration command is required for a fresh installation. On startup, the bot creates the tables and default settings when they do not already exist. Back up the SQLite database before moving or upgrading the deployment.

## License

This project is distributed under the Apache License 2.0. See [LICENSE](LICENSE).
