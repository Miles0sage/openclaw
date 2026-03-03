import os
import httpx
from dotenv import load_dotenv

load_dotenv()


async def send_telegram(text: str) -> None:
    """Send a Telegram message to the owner via Telegram Bot API.

    Sends a formatted Telegram message to the configured chat using the Telegram Bot API.
    The message is formatted with Markdown parsing enabled. Silently handles all failure
    cases to prevent alerts from crashing the runner.

    Args:
        text (str): The message text to send to the Telegram chat. Supports Markdown
            formatting as per Telegram Bot API specification.

    Returns:
        None: This function always returns None. It silently succeeds or fails without
            raising exceptions.

    Note:
        - Silently no-ops if TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID environment
          variables are not set.
        - Silently catches and ignores any HTTP errors or request timeouts to ensure
          the alerting system never crashes the runner.
    """
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
