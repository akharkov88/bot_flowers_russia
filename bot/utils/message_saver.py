"""Utility to save outgoing messages with keyboards to database."""
import json
from typing import List, Optional

from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Message as BotMessage
from bot.utils.logger import logger


async def save_outgoing_with_keyboard(
    session: AsyncSession,
    user_id: int,
    text: str,
    keyboard: Optional[ReplyKeyboardMarkup | InlineKeyboardMarkup] = None,
):
    """Save an outgoing message with its keyboard to the database."""
    try:
        keyboard_json = None
        if keyboard:
            keyboard_json = _serialize_keyboard(keyboard)

        msg = BotMessage(
            user_id=user_id,
            direction="outgoing",
            text=text,
            keyboard=keyboard_json,
        )
        session.add(msg)
        await session.commit()
        logger.info(f"Saved outgoing message with keyboard to user {user_id}: {text[:50]}")
    except Exception as e:
        logger.error(f"Error saving outgoing message with keyboard: {e}")
        await session.rollback()


def _serialize_keyboard(keyboard: ReplyKeyboardMarkup | InlineKeyboardMarkup) -> Optional[str]:
    """Serialize keyboard to JSON string for storage."""
    try:
        if isinstance(keyboard, ReplyKeyboardMarkup):
            return json.dumps({
                "type": "reply",
                "buttons": _serialize_reply_buttons(keyboard.keyboard),
            }, ensure_ascii=False)
        elif isinstance(keyboard, InlineKeyboardMarkup):
            return json.dumps({
                "type": "inline",
                "buttons": _serialize_inline_buttons(keyboard.inline_keyboard),
            }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error serializing keyboard: {e}")
    return None


def _serialize_reply_buttons(buttons: List[List]) -> List:
    """Serialize reply keyboard buttons."""
    result = []
    for row in buttons:
        row_data = []
        for btn in row:
            row_data.append({
                "text": btn.text,
                "request_contact": getattr(btn, 'request_contact', None),
                "request_location": getattr(btn, 'request_location', None),
            })
        result.append(row_data)
    return result


def _serialize_inline_buttons(buttons: List[List]) -> List:
    """Serialize inline keyboard buttons."""
    result = []
    for row in buttons:
        row_data = []
        for btn in row:
            row_data.append({
                "text": btn.text,
                "callback_data": getattr(btn, 'callback_data', None),
                "url": getattr(btn, 'url', None),
                "callback_game": getattr(btn, 'callback_game', None),
                "web_app": getattr(btn, 'web_app', None),
            })
        result.append(row_data)
    return result
