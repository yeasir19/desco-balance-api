# DESCO Balance API

A small Flask service that fetches a [DESCO](https://prepaid.desco.org.bd)
prepaid account's **balance**, **meter information** and **current-month usage**,
and returns it as JSON. The response includes a ready-to-send `message` string
for Telegram notifications.

## Why this exists

DESCO runs two separate backends, and which one serves your account depends on
when your meter was installed:

| Endpoint | Used by | What it returns |
|---|---|---|
| `/api/tkdes/` | Older prepaid meters | Balance and current-month usage in one call |
| `/api/unified/` | Newer meters | Customer info; the balance endpoint often returns `null` |

There is no documented way to tell which backend an account belongs to, so this
service tries `tkdes` first and falls back to `unified`. Any field DESCO does
not provide is reported as `N/A` instead of failing the request.

## Setup

```bash
git clone <repo-url> desco-balance-api
cd desco-balance-api

pip install -r requirements.txt

cp .env.example .env
# Edit .env and set your ACCOUNT_NO
```

## Running

**Development:**
```bash
python3 app.py
```

**Production (gunicorn):**
```bash
gunicorn -w 2 -b 0.0.0.0:8080 app:app
```

**As a systemd service:**
```bash
sudo cp desco-balance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now desco-balance
```
Adjust the user and paths in the unit file if your setup differs.

## API

### `GET /check_balance`

```bash
curl http://localhost:8080/check_balance
```

```json
{
  "status": "success",
  "source": "tkdes",
  "accountNo": "12345678",
  "meterNo": "999900001111",
  "balance": 2822.85,
  "monthUsage": 32.96,
  "usageUnit": null,
  "readingTime": "2026-10-04 00:00:00",
  "message": "...Telegram-ready text..."
}
```

| Field | Description |
|---|---|
| `source` | Which backend answered: `tkdes` or `unified` |
| `balance` | Remaining balance in BDT, or `null` if DESCO does not provide it |
| `monthUsage` | Current-month consumption in BDT |
| `usageUnit` | Consumption in kWh (only available on `unified`) |
| `readingTime` | Timestamp of the last meter reading |
| `message` | Pre-formatted multi-line text for Telegram |

On failure the service returns HTTP 502 with a `message` explaining the problem.

## Telegram / n8n integration

The `message` field can be sent to Telegram as-is:

```
🔢 Account No: 12345678
🔌 Meter No: 999900001111
💡 Balance: 2,822.85 BDT
📊 This Month Usage: 32.96 BDT
🕑 Reading: 2026-10-04 00:00:00
```

A minimal n8n workflow:

1. **Schedule Trigger** - runs daily at a fixed time
2. **HTTP Request** - `GET http://<host>:8080/check_balance`
3. **Telegram** - message text: `📋 {{ date }}` followed by `{{ $json.message }}`

## Notes

- Never commit `.env`; it is already listed in `.gitignore`
- Not every account exposes balance or consumption data. An `N/A` means DESCO
  returned nothing for that field, not that the service failed
- Certificate verification is disabled for DESCO requests because their API
  serves an incomplete certificate chain
- This project is not affiliated with or endorsed by DESCO
