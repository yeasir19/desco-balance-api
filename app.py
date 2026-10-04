"""DESCO Prepaid Balance API.

A small Flask service that fetches a DESCO prepaid account's balance, meter
information and current-month usage, and returns it as JSON along with a
ready-to-send `message` string for Telegram notifications.

DESCO runs two separate backends and which one works depends on the account:

    /api/tkdes/      Older prepaid meters. Returns balance and current-month
                     consumption in a single call.
    /api/unified/    Newer meters. Customer info is available, but the balance
                     endpoint often returns null.

The service tries `tkdes` first and falls back to `unified`. Any field DESCO
does not provide is reported as "N/A" rather than failing the request.
"""

import os
from datetime import date

import requests
import urllib3
from dotenv import load_dotenv
from flask import Flask, jsonify

# DESCO serves an incomplete certificate chain, so verification is disabled.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

app = Flask(__name__)

BASE_URL = "https://prepaid.desco.org.bd/api"
TIMEOUT = 25


def call_api(path, params):
    """Call a DESCO endpoint and return ``(ok, data)``.

    Never raises: network errors, bad JSON and non-200 API codes all come
    back as ``(False, None)`` so callers can fall through to the next source.
    """
    try:
        response = requests.get(f"{BASE_URL}/{path}", params=params,
                                verify=False, timeout=TIMEOUT)
        body = response.json() if response.status_code == 200 else {}
        if body.get("code") == 200:
            return True, body.get("data")
    except (requests.RequestException, ValueError):
        pass
    return False, None


def fetch_tkdes(account):
    """Fetch from the legacy prepaid backend.

    Returns balance and current-month usage in one call, or None if this
    account does not exist on that backend.
    """
    ok, data = call_api("tkdes/customer/getBalance", {"accountNo": account})
    if not (ok and data):
        return None
    return {
        "accountNo": data.get("accountNo") or account,
        "meterNo": data.get("meterNo"),
        "balance": data.get("balance"),
        "monthUsage": data.get("currentMonthConsumption"),
        "usageUnit": None,
        "readingTime": data.get("readingTime"),
        "source": "tkdes",
    }


def fetch_unified(account):
    """Fetch from the newer meter backend.

    Customer info gives the meter number, which the balance and consumption
    endpoints then need. Both of those may legitimately return nothing.
    """
    ok, info = call_api("unified/customer/getCustomerInfo", {"accountNo": account})
    if not (ok and info):
        return None

    meter = info.get("meterNo")
    result = {
        "accountNo": info.get("accountNo") or account,
        "meterNo": meter,
        "balance": None,
        "monthUsage": None,
        "usageUnit": None,
        "readingTime": None,
        "source": "unified",
    }

    ok, balance = call_api("unified/customer/getBalance",
                           {"accountNo": account, "meterNo": meter})
    if ok and balance:
        result["balance"] = balance.get("balance")
        result["readingTime"] = balance.get("readingTime")

    month = date.today().strftime("%Y-%m")
    ok, usage = call_api("unified/customer/getCustomerMonthlyConsumption",
                         {"accountNo": account, "meterNo": meter,
                          "monthFrom": month, "monthTo": month})
    if ok and usage:
        current = usage[-1]
        result["monthUsage"] = current.get("consumedTaka")
        result["usageUnit"] = current.get("consumedUnit")

    return result


def money(value):
    """Format a number as '1,234.56', or 'N/A' when it is missing."""
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def build_message(data):
    """Build the multi-line text sent to Telegram.

    The date line is added by the n8n Schedule Trigger, so it is not
    included here.
    """
    usage = f"{money(data['monthUsage'])} BDT"
    if data.get("usageUnit") is not None:
        usage += f" ({data['usageUnit']} kWh)"

    lines = [
        f"\U0001F522 Account No: {data['accountNo'] or 'N/A'}",
        f"\U0001F50C Meter No: {data['meterNo'] or 'N/A'}",
        f"\U0001F4A1 Balance: {money(data['balance'])} BDT",
        f"\U0001F4CA This Month Usage: {usage}",
    ]
    if data.get("readingTime"):
        lines.append(f"\U0001F551 Reading: {data['readingTime']}")
    return "\n".join(lines)


@app.route("/check_balance")
def check_balance():
    """Return account details for the account configured in ACCOUNT_NO."""
    account = (os.getenv("ACCOUNT_NO") or "").strip()
    if not account:
        return jsonify({"status": "error",
                        "message": "ACCOUNT_NO is not set in .env"}), 500

    data = fetch_tkdes(account) or fetch_unified(account)
    if not data:
        return jsonify({
            "status": "error",
            "message": (f"\U0001F522 Account No: {account}\n"
                        "\u26A0\uFE0F Could not retrieve data from the DESCO API"),
        }), 502

    data["message"] = build_message(data)
    data["status"] = "success"
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
