import asyncio
import os

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile
from bot.config import settings
from bot.database import init_db, get_session, async_session_factory
from bot.handlers import register_handlers
from bot.proxy import SecureAiohttpSession

from bot.middlewares.tracking import TrackingMiddleware
from bot.models import Notification, Cart, Post, PostRecipient, PostStats
from bot.utils.logger import logger

from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
from admin_web.main import run_admin_web
from bot.models import User


async def main():
    # Create bot session with secure SSL context
    logger.info("Creating bot session with secure SSL context...")
    session = SecureAiohttpSession()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session
    )
    logger.info("Bot session created successfully")
    
    dp = Dispatcher()

    # Register handlers FIRST
    register_handlers(dp)

    # Register middleware AFTER routers
    dp.message.middleware(TrackingMiddleware(admin_ids=settings.admin_ids_list))
    dp.callback_query.middleware(TrackingMiddleware(admin_ids=settings.admin_ids_list))

    # Patch bot to intercept outgoing messages
    from bot.middlewares.tracking import OutgoingMessageMiddleware
    outgoing_mw = OutgoingMessageMiddleware(bot)
    outgoing_mw.patch_bot()

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Start web admin panel in background
    admin_task = asyncio.create_task(run_admin_web())

    # Notifications are handled by the web admin panel and desktop notifications only
    # No Telegram push notifications for user messages

    async def process_notifications():
        """Background task to send pending notifications from the database"""
        while True:
            try:
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(Notification)
                        .where(Notification.sent == False)
                        .order_by(Notification.created_at)
                        .limit(50)
                    )
                    pending = result.scalars().all()

                    for notif in pending:
                        try:
                            if notif.telegram_id:
                                # Send to user (personal chat)
                                if notif.image_url:
                                    logger.info(f"Processing photo notification {notif.id}: image_url={notif.image_url}, text={notif.text[:50]}")
                                    local_path = None
                                    if notif.image_url.startswith("/static/uploads/"):
                                        filename = notif.image_url.split("/")[-1]
                                        uploads_dir = os.path.join(
                                            os.path.dirname(os.path.dirname(__file__)),
                                            "admin_web", "static", "uploads"
                                        )
                                        local_path = os.path.join(uploads_dir, filename)
                                        logger.info(f"Photo local path: {local_path}, exists={os.path.exists(local_path)}")

                                    if local_path and os.path.exists(local_path):
                                        file_size = os.path.getsize(local_path)
                                        logger.info(f"Sending photo {local_path} (size={file_size} bytes)")
                                        await bot.send_photo(
                                            chat_id=notif.telegram_id,
                                            photo=FSInputFile(local_path),
                                            caption=notif.text or None,
                                        )
                                        logger.info(f"Photo notification sent to user {notif.telegram_id}")
                                    else:
                                        logger.warning(f"Photo file not found: {local_path} for notification {notif.id}")
                                        notif.sent = True
                                else:
                                    await bot.send_message(
                                        chat_id=notif.telegram_id,
                                        text=notif.text or "",
                                    )
                                    logger.info(f"Notification sent to user {notif.telegram_id}: {notif.text[:80]}")
                                notif.sent = True
                            elif notif.chat_id:
                                # Send to group/chat (e.g. order status updates)
                                if notif.image_url:
                                    local_path = None
                                    if notif.image_url.startswith("/static/uploads/"):
                                        filename = notif.image_url.split("/")[-1]
                                        uploads_dir = os.path.join(
                                            os.path.dirname(os.path.dirname(__file__)),
                                            "admin_web", "static", "uploads"
                                        )
                                        local_path = os.path.join(uploads_dir, filename)

                                    if local_path and os.path.exists(local_path):
                                        await bot.send_photo(
                                            chat_id=notif.chat_id,
                                            photo=FSInputFile(local_path),
                                            caption=notif.text or None,
                                        )
                                        logger.info(f"Photo notification sent to chat {notif.chat_id}")
                                    else:
                                        logger.warning(f"Photo file not found: {local_path} for notification {notif.id}")
                                        notif.sent = True
                                else:
                                    await bot.send_message(
                                        chat_id=notif.chat_id,
                                        text=notif.text or "",
                                    )
                                    logger.info(f"Notification sent to chat {notif.chat_id}: {notif.text[:80]}")
                                notif.sent = True
                            else:
                                notif.sent = True
                                logger.info(f"Notification skipped (no telegram_id or chat_id): {notif.text[:80]}")
                        except TelegramForbiddenError as e:
                            # Access denied to user or chat
                            if notif.telegram_id:
                                logger.warning(f"User blocked the bot or access denied: telegram_id={notif.telegram_id}: {e}")
                                if notif.user_id:
                                    result = await session.execute(select(User).where(User.id == notif.user_id))
                                    user = result.scalar_one_or_none()
                                    if user:
                                        user.user_blocked_bot = True
                                        logger.info(f"Marked user {user.id} (telegram_id={notif.telegram_id}) as blocked the bot")
                            else:
                                logger.warning(f"Cannot send to chat {notif.chat_id}: access denied or bot removed: {e}")
                            notif.sent = True
                        except TelegramAPIError as e:
                            if notif.telegram_id:
                                logger.warning(f"Failed to send notification to user {notif.telegram_id}: {e}")
                            elif notif.chat_id:
                                logger.warning(f"Failed to send notification to chat {notif.chat_id}: {e}")
                            else:
                                logger.warning(f"Failed to send notification (no target): {e}")

                    if pending:
                        await session.commit()
                        logger.info(f"Processed {len(pending)} notifications")
            except Exception as e:
                logger.warning(f"Error in notifications processor: {e}")

            await asyncio.sleep(5)  # Check every 5 seconds

    notifications_task = asyncio.create_task(process_notifications())

    async def process_abandoned_carts():
        """Background task to mark old active carts as abandoned"""
        while True:
            try:
                async with async_session_factory() as session:
                    cutoff = datetime.now() - timedelta(hours=24)
                    result = await session.execute(
                        select(Cart).where(
                            Cart.status == "active",
                            Cart.updated_at < cutoff
                        )
                    )
                    old_carts = result.scalars().all()
                    for cart in old_carts:
                        cart.status = "abandoned"
                        cart.abandoned_at = datetime.now()
                    if old_carts:
                        await session.commit()
                        logger.info(f"Marked {len(old_carts)} carts as abandoned")
            except Exception as e:
                logger.warning(f"Error in abandoned carts processor: {e}")

            await asyncio.sleep(1800)  # Check every 30 minutes

    abandoned_task = asyncio.create_task(process_abandoned_carts())

    async def _update_post_stats(session, post_id):
        """Recalculate post stats from recipients"""
        result = await session.execute(
            select(func.count(PostRecipient.id))
            .where(PostRecipient.post_id == post_id, PostRecipient.status == "sent")
        )
        total_sent = result.scalar() or 0

        result = await session.execute(
            select(func.count(PostRecipient.id))
            .where(PostRecipient.post_id == post_id, PostRecipient.status == "failed")
        )
        total_failed = result.scalar() or 0

        result = await session.execute(
            select(func.count(PostRecipient.id))
            .where(PostRecipient.post_id == post_id, PostRecipient.status == "pending")
        )
        total_pending = result.scalar() or 0

        result = await session.execute(
            select(PostStats).where(PostStats.post_id == post_id)
        )
        stats = result.scalar_one_or_none()
        if not stats:
            stats = PostStats(
                post_id=post_id,
                total_sent=total_sent,
                total_failed=total_failed,
                total_pending=total_pending,
            )
            session.add(stats)
        else:
            stats.total_sent = total_sent
            stats.total_failed = total_failed
            stats.total_pending = total_pending
        await session.commit()

    async def process_scheduled_posts():
        """Background task to send scheduled posts"""
        import json
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        while True:
            try:
                async with async_session_factory() as session:
                    # Get posts that need to be sent
                    now = datetime.now()
                    result = await session.execute(
                        select(Post)
                        .where(
                            Post.status.in_(["sending", "scheduled"]),
                            Post.scheduled_at <= now if Post.status == "scheduled" else True
                        )
                    )
                    posts_to_send = result.scalars().all()

                    for post in posts_to_send:
                        try:
                            # Get audience
                            audience = json.loads(post.audience) if post.audience else {"type": "all"}

                            # Get users
                            if audience.get("type") == "selected":
                                user_ids = audience.get("user_ids", [])
                                result = await session.execute(
                                    select(User).where(User.id.in_(user_ids))
                                )
                                users = result.scalars().all()
                            else:
                                result = await session.execute(select(User))
                                users = result.scalars().all()

                            # Check if recipients already exist (created by admin panel)
                            result = await session.execute(
                                select(func.count(PostRecipient.id))
                                .where(PostRecipient.post_id == post.id)
                            )
                            existing_count = result.scalar() or 0

                            if existing_count == 0:
                                # Create recipients only if not already created
                                for user in users:
                                    recipient = PostRecipient(
                                        post_id=post.id,
                                        user_id=user.id,
                                        telegram_id=user.telegram_id,
                                        status="pending",
                                    )
                                    session.add(recipient)
                                await session.commit()

                            # Send to each recipient
                            result = await session.execute(
                                select(PostRecipient)
                                .where(PostRecipient.post_id == post.id, PostRecipient.status == "pending")
                            )
                            pending_recipients = result.scalars().all()

                            # Initialize stats
                            result = await session.execute(
                                select(PostStats).where(PostStats.post_id == post.id)
                            )
                            stats = result.scalar_one_or_none()
                            if not stats:
                                stats = PostStats(
                                    post_id=post.id,
                                    total_sent=0,
                                    total_failed=0,
                                    total_pending=len(pending_recipients),
                                )
                                session.add(stats)
                            else:
                                stats.total_pending = len(pending_recipients)
                                stats.total_sent = 0
                                stats.total_failed = 0
                            await session.commit()

                            for recipient in pending_recipients:
                                try:
                                    # Send without inline buttons (button fields removed)
                                    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

                                    # Send photo
                                    images = json.loads(post.images) if post.images else []
                                    photo_filename = images[0] if images else None

                                    if photo_filename:
                                        # Handle both URLs and local file paths
                                        if photo_filename.startswith("http"):
                                            # URL may be local (inaccessible from Telegram), download first
                                            try:
                                                async with aiohttp.ClientSession() as session:
                                                    async with session.get(photo_filename) as resp:
                                                        if resp.status == 200:
                                                            photo_bytes = await resp.read()
                                                            import tempfile
                                                            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                                                                tmp.write(photo_bytes)
                                                                tmp_path = tmp.name
                                                            try:
                                                                await bot.send_photo(
                                                                    chat_id=recipient.telegram_id,
                                                                    photo=FSInputFile(tmp_path),
                                                                    caption=post.text,
                                                                    reply_markup=keyboard
                                                                )
                                                            finally:
                                                                os.unlink(tmp_path)
                                                            logger.info(f"Photo (downloaded URL) sent successfully to {recipient.telegram_id}")
                                                        else:
                                                            raise Exception(f"HTTP {resp.status}")
                                            except Exception as send_err:
                                                logger.error(f"Failed to send photo (downloaded URL) to {recipient.telegram_id}: {send_err}")
                                                await bot.send_message(
                                                    chat_id=recipient.telegram_id,
                                                    text=post.text,
                                                    reply_markup=keyboard
                                                )
                                        else:
                                            # Local file path - extract just the filename from URL
                                            filename = os.path.basename(photo_filename)
                                            local_path = os.path.join(
                                                os.path.dirname(os.path.dirname(__file__)),
                                                "admin_web", "static", "uploads",
                                                filename
                                            )
                                            if os.path.exists(local_path):
                                                try:
                                                    await bot.send_photo(
                                                        chat_id=recipient.telegram_id,
                                                        photo=FSInputFile(local_path),
                                                        caption=post.text,
                                                        reply_markup=keyboard
                                                    )
                                                    logger.info(f"Photo (file) sent successfully to {recipient.telegram_id}")
                                                except Exception as send_err:
                                                    logger.error(f"Failed to send photo (file) to {recipient.telegram_id}: {send_err}")
                                                    await bot.send_message(
                                                        chat_id=recipient.telegram_id,
                                                        text=post.text,
                                                        reply_markup=keyboard
                                                    )
                                            else:
                                                logger.warning(f"Photo file not found: {local_path}, sending text only")
                                                await bot.send_message(
                                                    chat_id=recipient.telegram_id,
                                                    text=post.text,
                                                    reply_markup=keyboard
                                                )
                                    else:
                                        logger.info(f"No photo for post {post.id}, sending text only")
                                        await bot.send_message(
                                            chat_id=recipient.telegram_id,
                                            text=post.text,
                                            reply_markup=keyboard
                                        )

                                    # Create Message record for admin chat view
                                    try:
                                        from bot.models import Message as BotMessage
                                        async with async_session_factory() as msg_session:
                                            msg = BotMessage(
                                                user_id=recipient.user_id,
                                                direction="outgoing",
                                                text=f"📢 Пост: {post.title}\n\n{post.text}",
                                            )
                                            msg_session.add(msg)
                                            await msg_session.commit()
                                            logger.info(f"Saved outgoing post message for user {recipient.user_id}: {post.title}")
                                    except Exception as e:
                                        logger.error(f"Error saving post message for user {recipient.user_id}: {e}")

                                    # Update recipient
                                    async with async_session_factory() as session:
                                        result = await session.execute(
                                            select(PostRecipient)
                                            .where(PostRecipient.id == recipient.id)
                                        )
                                        rec = result.scalar_one_or_none()
                                        if rec:
                                            rec.status = "sent"
                                            rec.sent_at = datetime.now()
                                            await session.commit()

                                    # Update stats (recalculate from recipients)
                                    await _update_post_stats(session, post.id)

                                except TelegramForbiddenError:
                                    # User blocked the bot
                                    logger.warning(f"User blocked the bot while sending post {post.id}: telegram_id={recipient.telegram_id}")
                                    async with async_session_factory() as session:
                                        result = await session.execute(
                                            select(PostRecipient)
                                            .where(PostRecipient.id == recipient.id)
                                        )
                                        rec = result.scalar_one_or_none()
                                        if rec:
                                            rec.status = "failed"
                                            rec.error_message = "User blocked the bot"
                                            await session.commit()

                                        # Mark user as blocked the bot
                                        result = await session.execute(select(User).where(User.id == recipient.user_id))
                                        user = result.scalar_one_or_none()
                                        if user:
                                            user.user_blocked_bot = True
                                            logger.info(f"Marked user {user.id} (telegram_id={recipient.telegram_id}) as blocked the bot")
                                        await session.commit()

                                    # Update stats (recalculate from recipients)
                                    await _update_post_stats(session, post.id)

                                except Exception as e:
                                    # Update recipient with error
                                    async with async_session_factory() as session:
                                        result = await session.execute(
                                            select(PostRecipient)
                                            .where(PostRecipient.id == recipient.id)
                                        )
                                        rec = result.scalar_one_or_none()
                                        if rec:
                                            rec.status = "failed"
                                            rec.error_message = str(e)[:500]
                                            await session.commit()

                                    # Update stats (recalculate from recipients)
                                    await _update_post_stats(session, post.id)

                            # Update post status
                            async with async_session_factory() as session:
                                result = await session.execute(select(Post).where(Post.id == post.id))
                                post = result.scalar_one_or_none()
                                if post:
                                    await _update_post_stats(session, post.id)
                                    result = await session.execute(
                                        select(func.count(PostRecipient.id))
                                        .where(PostRecipient.post_id == post.id, PostRecipient.status == "failed")
                                    )
                                    failed_count = result.scalar() or 0

                                    post.status = "failed" if failed_count > 0 else "sent"
                                    post.sent_at = datetime.now()
                                    await session.commit()

                        except Exception as e:
                            logger.warning(f"Failed to send post {post.id}: {e}")
                            await session.rollback()

            except Exception as e:
                logger.warning(f"Error in scheduled posts processor: {e}")

            await asyncio.sleep(60)  # Check every minute

    scheduled_posts_task = asyncio.create_task(process_scheduled_posts())

    # Don't let admin panel failure kill the bot
    async def safe_admin_task():
        try:
            await admin_task
        except asyncio.CancelledError:
            pass
        except (SystemExit, Exception) as e:
            logger.error(f"Admin panel crashed: {e}. Bot continues running.")

    admin_guard = asyncio.create_task(safe_admin_task())

    try:
        logger.info("Bot starting polling...")
        await dp.start_polling(bot)
    finally:
        admin_guard.cancel()
        try:
            await admin_guard
        except asyncio.CancelledError:
            pass
        notifications_task.cancel()
        try:
            await notifications_task
        except asyncio.CancelledError:
            pass
        abandoned_task.cancel()
        try:
            await abandoned_task
        except asyncio.CancelledError:
            pass
        scheduled_posts_task.cancel()
        try:
            await scheduled_posts_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
