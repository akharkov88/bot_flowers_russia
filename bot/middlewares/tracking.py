import asyncio
from typing import Any, Callable, Dict, List

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.types import Message as TgMessage, CallbackQuery
from sqlalchemy import select

from bot.database import async_session_factory
import json

from bot.models import Message, User
from bot.utils.logger import logger
from bot.utils.desktop_notifications import send_desktop_notification


class TrackingMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: List[int] = None):
        super().__init__()
        self.admin_ids = admin_ids or []
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Any],
        event: TgMessage | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        tg = None
        if isinstance(event, (TgMessage, CallbackQuery)):
            tg = event.from_user

        logger.info(f"DEBUG Middleware: event_type={type(event).__name__}, tg={tg.id if tg else None}")

        if tg:
            async with async_session_factory() as session:
                result = await session.execute(select(User).where(User.telegram_id == tg.id))
                user = result.scalar_one_or_none()

                if user is None:
                    user = User(
                        telegram_id=tg.id,
                        username=tg.username,
                        first_name=tg.first_name,
                        last_name=tg.last_name,
                    )
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                    logger.info(f"New user: {tg.id} ({tg.username or 'no username'})")
                else:
                    user.username = tg.username
                    user.first_name = tg.first_name
                    user.last_name = tg.last_name
                    await session.commit()

                # Check if user is blocked
                if user.is_blocked:
                    # Allow admins to use ban/unban commands
                    if tg.id in self.admin_ids and isinstance(event, TgMessage) and event.text:
                        if event.text in ['/ban', '/unban'] or event.text.startswith('/ban ') or event.text.startswith('/unban '):
                            pass  # Allow admin to use ban/unban
                        else:
                            if isinstance(event, CallbackQuery):
                                await event.answer("⛔ Вы заблокированы в боте. Обратитесь к администратору.")
                            return
                    else:
                        if isinstance(event, CallbackQuery):
                            await event.answer("⛔ Вы заблокированы в боте. Обратитесь к администратору.")
                        return

                data["user"] = user
                data["db_session"] = session

                # Save incoming text messages from users
                if isinstance(event, TgMessage) and event.text and event.chat.type == "private":
                    msg = Message(
                        user_id=user.id,
                        direction="incoming",
                        text=event.text,
                    )
                    session.add(msg)

                    await session.commit()
                    logger.info(f"Saved incoming message from user {tg.id}: {event.text[:50]}")

                    # Send desktop push notification (non-blocking)
                    user_name_display = user.first_name or user.username or str(tg.id)
                    asyncio.create_task(
                        send_desktop_notification(
                            f"📩 {user_name_display} (ID:{user.id} | TG:{tg.id})",
                            event.text
                        )
                    )

                # Save callback button clicks
                if isinstance(event, CallbackQuery) and event.data:
                    try:
                        cb_data = json.loads(event.data)
                        cb_type = cb_data.get("type", "unknown")
                        cb_action = cb_data.get("action", "unknown")
                    except (json.JSONDecodeError, AttributeError):
                        cb_data = None
                        cb_type = "unknown"
                        cb_action = "unknown"

                    msg = Message(
                        user_id=user.id,
                        direction="callback",
                        text=f"{cb_type}:{cb_action}",
                        callback_data=event.data,
                    )
                    session.add(msg)
                    await session.commit()
                    logger.info(f"Saved callback {cb_type}:{cb_action} from user {tg.id}")

                logger.info(f"User: {tg.id}, event: {type(event).__name__}")

                try:
                    result = await handler(event, data)
                    return result
                except Exception as e:
                    logger.error(f"Error in handler for user {tg.id}, event {type(event).__name__}: {e}", exc_info=True)
                    raise

        return await handler(event, data)
