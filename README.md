# Flash Sale QA Harness

A production-minded, **authorized staging-only** harness for validating flash-sale monitoring, checkout workflows, concurrency limits, coupon selection, persistence, alerts, and graceful shutdown.

It is deliberately designed **not** to hide automation, bypass CAPTCHA/OTP, defeat anti-bot systems, manipulate affiliate attribution, or place orders on third-party production stores.

## Features

- Async product monitoring with configurable thresholds.
- Per-account session persistence and expiry recovery.
- Bounded concurrency and global request-rate limiting.
- Address setup, cart creation, coupon preview/apply, test COD, and idempotent order creation.
- Rolling 24-hour account order limits in SQLite.
- Structured JSONL logs.
- Telegram deal alerts and an authenticated Telegram command bot.
- Exponential-backoff retries.
- Ctrl+C/SIGTERM graceful shutdown.
- Built-in mock commerce API for end-to-end local testing.
- Dry-run by default, allowlisted hosts only, and explicit execution confirmation.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp config.example.json config.json
```

Terminal 1:

```bash
flash-sale-mock-store --host 127.0.0.1 --port 8080
```

Terminal 2:

```bash
flash-sale-qa --config config.json --run-seconds 15
```

The compatibility entry point also works:

```bash
python stealth_flash_qa.py --config config.json
```

## Telegram auto-order controller

Create a bot with BotFather, obtain your numeric Telegram chat ID, and enable the controller in `config.json`:

```json
{
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID",
    "command_bot_enabled": true,
    "poll_timeout_seconds": 20
  }
}
```

Only the configured chat ID can issue commands. Available commands:

- `/status` — show harness state, dry-run mode, account count, products, and active blitzes.
- `/products` — list configured staging products and thresholds.
- `/trigger sku-1` — immediately launch the existing bounded staging checkout workflow.
- `/stop` — request graceful shutdown.
- `/help` — show command help.

`/trigger` does not bypass any safety guard. It uses the same allowlisted staging API, test accounts, per-account limits, concurrency limits, SQLite tracking, and dry-run setting as automatic deal triggers.

## Execution mode

Dry-run remains enabled unless both controls are present:

```bash
export QA_EXECUTION_CONFIRMED=YES
flash-sale-qa --config config.json --execute
```

Execution mode still refuses known third-party live commerce hosts and only sends requests to hosts explicitly listed in `allowed_hosts`.

## Staging API contract

The harness expects these endpoints:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/test/login` | Authenticate a marked test account |
| GET | `/api/test/cart` | Verify session validity |
| GET | `/api/test/products/{id}` | Read price, discount, stock, sizes |
| POST | `/api/test/cart/items` | Add a staging product |
| GET | `/api/test/checkout` | Read totals and saved addresses |
| POST | `/api/test/checkout/address` | Save a test address |
| POST | `/api/test/checkout/coupon/preview` | Preview a coupon without mutation |
| POST | `/api/test/checkout/coupon/apply` | Apply the best coupon |
| POST | `/api/test/checkout/payment` | Select `TEST_COD` |
| POST | `/api/test/orders` | Create an idempotent dry-run/test order |

See `src/flash_sale_qa/mock_store.py` for a complete reference implementation.

## Configuration safety

- Every account must set `"test_account": true`.
- The target hostname must be in `allowed_hosts`.
- Known live Nykaa, Myntra, Tira, and Mamaearth hosts are blocked.
- Quantity is capped at 10 per workflow.
- Concurrency, requests per second, and account limits have hard upper bounds.
- Telegram commands are ignored unless they come from the configured chat ID.

## Tests and lint

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

## Docker

```bash
docker compose up --build
```

The compose stack starts the mock store and runs a bounded dry-run harness against it.

## Operational notes

Session files, logs, and SQLite databases are ignored by Git. Do not commit real customer data, real phone numbers, production credentials, or Telegram secrets.
