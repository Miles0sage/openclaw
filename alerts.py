import os
import httpx
from dotenv import load_dotenv

load_dotenv()


async def send_telegram(text: str) -> None:
    """Send a Telegram message to the owner. Silently no-ops if creds missing."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_USER_ID", "")
    if not token or not chat_id:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
    except Exception:
        pass  # Never let alerts crash the runner
