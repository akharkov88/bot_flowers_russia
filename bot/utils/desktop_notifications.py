import asyncio
import os
from bot.utils.logger import logger


async def send_desktop_notification(title: str, message: str) -> None:
    """Send a desktop push notification using notify-send (Linux)."""
    try:
        # Truncate message for display (notify-send has length limits)
        display_msg = message[:200] + ("..." if len(message) > 200 else "")
        await asyncio.create_subprocess_exec(
            "notify-send",
            "-u", "normal",
            title,
            display_msg,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        logger.info(f"Desktop notification sent: {title}")
    except FileNotFoundError:
        logger.warning("notify-send not found. Install libnotify-bin.")
    except Exception as e:
        logger.warning(f"Failed to send desktop notification: {e}")
