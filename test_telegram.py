"""
Standalone test: can we send a Telegram message?

This has nothing to do with cricket yet -- it just proves the bot token
and chat ID in config.py are correct before we wire notifications into
the real notifier.
"""

import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=10,
    )

    # Telegram's API always returns JSON, even on failure. "ok": true means
    # it worked; "ok": false comes with a "description" explaining why not
    # (wrong token, wrong chat ID, bot blocked, etc).
    result = response.json()
    print("Raw response:", result)

    if result.get("ok"):
        print("\n Success! Message sent to telegram")
    else:
        print(f"\n Failed: {result.get('description')}")


if __name__ == "__main__":
    send_telegram("Test message from cricket_notifier setup 🏏")
