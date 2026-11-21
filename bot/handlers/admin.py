from aiogram import Router, F, Bot
from aiogram.types import Message as TgMessage, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select, func
import re

from bot.config import settings
from bot.keyboards import pack_cb, unpack_cb, get_admin_keyboard, get_admin_products_keyboard, get_admin_orders_keyboard, get_admin_order_status_keyboard, get_main_keyboard
from bot.models import Order, OrderItem, Product, Category, User, Message as UserModelMessage
from bot.utils.logger import logger

admin_router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids_list


@admin_router.message(F.command == "admin")
async def cmd_admin(message: TgMessage):
    if not is_admin(message.from_user.id):
        await message.answer("🔒 Доступ запрещён.")
        return

    await message.answer("⚙️ Админ-панель:", reply_markup=get_admin_keyboard())


@admin_router.callback_query(F.data.contains("admin"))
async def cb_admin_action(callback: CallbackQuery, bot: Bot, db_session):
    if not is_admin(callback.from_user.id):
        await callback.answer("🔒 Доступ запрещён")
        return

    data = unpack_cb(callback.data)
    action = data.get("action")

    if action == "products":
        result = await db_session.execute(select(Product).order_by(Product.id))
        products = result.scalars().all()
        await callback.message.edit_text("📦 Управление товарами:", reply_markup=get_admin_products_keyboard(products))
        await callback.answer()

    elif action == "orders":
        result = await db_session.execute(select(Order).order_by(Order.created_at.desc()).limit(20))
        orders = result.scalars().all()
        await callback.message.edit_text("📋 Управление заказами:", reply_markup=get_admin_orders_keyboard(orders))
        await callback.answer()

    elif action == "stats":
        result = await db_session.execute(select(func.count(Order.id)))
        total_orders = result.scalar() or 0

        result = await db_session.execute(select(func.sum(Order.total_price)).where(Order.status == "delivered"))
        revenue = result.scalar() or 0

        result = await db_session.execute(select(func.count(User.id)))
        total_users = result.scalar() or 0

        result = await db_session.execute(select(func.count(Product.id)).where(Product.is_active == True))
        active_products = result.scalar() or 0

        text = (
            f"📊 Статистика:\n\n"
            f"📦 Всего заказов: {total_orders}\n"
            f"💰 Выручка (доставленные): {revenue:.0f} ₽\n"
            f"👥 Зарегистрировано пользователей: {total_users}\n"
            f"🌹 Активных товаров: {active_products}"
        )
        await callback.message.edit_text(text)
        await callback.answer()

    elif action == "order_detail":
        order_id = int(data["id"])

        result = await db_session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()

        if not order:
            await callback.answer("Заказ не найден")
            return

        status_map = {
            "new": "🆕 Новый",
            "processing": "⏳ В обработке",
            "confirmed": "✅ Подтверждён",
            "delivered": "🚚 Доставлен",
            "cancelled": "❌ Отменён",
            "not_connected": "📵 Не дозвонились",
        }
        status = status_map.get(order.status, order.status)

        result = await db_session.execute(select(User).where(User.id == order.user_id))
        user = result.scalar_one_or_none()
        user_info = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"ID: {order.user_id}"

        text = (
            f"📦 Заказ #{order.id}\n"
            f"{status}\n"
            f"👤 {user_info}\n"
            f"💰 Сумма: {order.total_price:.0f} ₽\n"
            f"📅 {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"📋 Состав:\n"
        )

        result = await db_session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
        items = result.scalars().all()
        if order.is_custom:
            text += f"  ✨ Индивидуальный заказ\n"
            text += f"  📝 {order.custom_description}\n"
            if order.comment:
                text += f"  💬 {order.comment}\n"
        else:
            for item in items:
                result2 = await db_session.execute(select(Product).where(Product.id == item.product_id))
                product = result2.scalar_one_or_none()
                if product:
                    text += f"  🌹 {product.name} x{item.quantity} — {item.price * item.quantity:.0f} ₽\n"

        text += f"\n📍 {order.delivery_address}\n"
        text += f"📅 {order.delivery_date}\n🕐 {order.delivery_time or '—'}\n"
        text += f"📞 {order.phone}"
        if order.comment and not order.is_custom:
            text += f"\n💬 {order.comment}"

        await callback.message.answer(text, reply_markup=get_admin_order_status_keyboard(order))
        await callback.answer()

    elif action == "update_status":
        order_id = int(data["id"])
        new_status = data["page"]

        result = await db_session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()

        if not order:
            await callback.answer("Заказ не найден")
            return

        order.status = new_status
        await db_session.commit()

        status_map = {
            "new": "🆕 Новый",
            "processing": "⏳ В обработке",
            "confirmed": "✅ Подтверждён",
            "delivered": "🚚 Доставлен",
            "cancelled": "❌ Отменён",
            "not_connected": "📵 Не дозвонились",
        }
        new_status_text = status_map.get(new_status, new_status)
        await callback.answer(f"Статус изменён на {new_status_text}")
        await callback.message.answer(f"✅ Заказ #{order_id} → {new_status_text}")

        # Notify order chat
        await notify_chat(bot, settings.order_chat_id, order_id, new_status)

    elif action == "product_detail":
        prod_id = int(data["id"])

        result = await db_session.execute(select(Product).where(Product.id == prod_id))
        product = result.scalar_one_or_none()

        if not product:
            await callback.answer("Товар не найден")
            return

        text = (
            f"📦 Товар #{product.id}\n"
            f"Название: {product.name}\n"
            f"Цена: {product.price:.0f} ₽\n"
            f"Категория: {product.category.name if product.category else '—'}\n"
            f"Состав: {product.composition or '—'}\n"
            f"Описание: {product.description}\n"
            f"Статус: {'🟢 Активен' if product.is_active else '⚫ Неактивен'}"
        )
        await callback.message.answer(text)
        await callback.answer()

    elif action == "back":
        await callback.message.edit_text("⚙️ Админ-панель:", reply_markup=get_admin_keyboard())
        await callback.answer()


@admin_router.callback_query(F.data.contains("back"))
async def cb_back(callback: CallbackQuery):
    await callback.message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())
    await callback.answer()


# ==================== BAN / UNBAN ====================

@admin_router.message(F.command == "ban")
async def cmd_ban(message: TgMessage, bot: Bot, db_session):
    """Ban a user by telegram ID or reply."""
    if not is_admin(message.from_user.id):
        await message.answer("🔒 Доступ запрещён.")
        return

    target_id = None
    reason = ""

    # Parse from reply
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        user_name = message.reply_to_message.from_user.full_name or str(target_id)
    # Parse from command argument
    elif message.text and len(message.text.split()) > 1:
        target_id = message.text.split(None, 1)[1].strip()
        reason = message.text.split(None, 1)[1].strip()
        # Try to extract telegram ID (digits only)
        match = re.search(r'(\d+)', target_id)
        if match:
            target_id = int(match.group(1))
        user_name = target_id
    else:
        await message.answer(
            "🚫 Заблокировать пользователя:\n\n"
            "Варианты:\n"
            "• Ответьте сообщением пользователя\n"
            "• /ban TELEGRAM_ID\n\n"
            "Пример: /ban 123456789"
        )
        return

    if not target_id:
        await message.answer("❌ Не удалось определить ID пользователя.")
        return

    # Find user by telegram_id
    result = await db_session.execute(select(User).where(User.telegram_id == target_id))
    user = result.scalar_one_or_none()

    if not user:
        await message.answer(f"❌ Пользователь с telegram_id={target_id} не найден.")
        return

    user.is_blocked = True
    await db_session.commit()

    # Try to notify user
    try:
        await bot.send_message(
            target_id,
            f"⛔ Вы заблокированы в боте.\n\nПричина: {reason or 'не указана'}"
        )
    except Exception as e:
        logger.warning(f"Cannot notify blocked user {target_id}: {e}")

    user_display = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"ID: {user.telegram_id}"
    await message.answer(
        f"✅ Пользователь {user_display} (ID: {user.telegram_id}) заблокирован."
    )


@admin_router.message(F.command == "unban")
async def cmd_unban(message: TgMessage, db_session):
    """Unban a user by telegram ID."""
    if not is_admin(message.from_user.id):
        await message.answer("🔒 Доступ запрещён.")
        return

    if not message.text or len(message.text.split()) < 2:
        await message.answer(
            "♻️ Разблокировать пользователя:\n\n"
            "• /unban TELEGRAM_ID\n\n"
            "Пример: /unban 123456789"
        )
        return

    target_id_str = message.text.split(None, 1)[1].strip()
    match = re.search(r'(\d+)', target_id_str)
    if not match:
        await message.answer("❌ Неверный формат. Укажите числовой telegram ID.")
        return

    target_id = int(match.group(1))

    result = await db_session.execute(select(User).where(User.telegram_id == target_id))
    user = result.scalar_one_or_none()

    if not user:
        await message.answer(f"❌ Пользователь с telegram_id={target_id} не найден.")
        return

    if not user.is_blocked:
        await message.answer(f"ℹ️ Пользователь {user.first_name or user.username or target_id} уже разблокирован.")
        return

    user.is_blocked = False
    await db_session.commit()

    user_display = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"ID: {user.telegram_id}"
    await message.answer(
        f"✅ Пользователь {user_display} (ID: {user.telegram_id}) разблокирован."
    )


@admin_router.message(F.text.startswith("🚫 Заблокировать") | F.text.startswith("♻️ Разблокировать"))
async def admin_ban_from_list(message: TgMessage, bot: Bot, db_session):
    """Handle ban/unban from inline buttons in customers list."""
    if not is_admin(message.from_user.id):
        await message.answer("🔒 Доступ запрещён.")
        return

    # Extract user_id from text (format: "🚫 Заблокировать:123456789" or "♻️ Разблокировать:123456789")
    match = re.search(r'(\d+)', message.text)
    if not match:
        return

    target_id = int(match.group(1))

    result = await db_session.execute(select(User).where(User.telegram_id == target_id))
    user = result.scalar_one_or_none()

    if not user:
        await message.answer("❌ Пользователь не найден.")
        return

    is_ban = message.text.startswith("🚫")
    user.is_blocked = is_ban
    await db_session.commit()

    status_text = "заблокирован" if is_ban else "разблокирован"
    user_display = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"ID: {user.telegram_id}"
    await message.answer(
        f"✅ Пользователь {user_display} (ID: {user.telegram_id}) {status_text}."
    )

    # Notify user if banning
    if is_ban:
        try:
            await bot.send_message(target_id, "⛔ Вы заблокированы в боте. Обратитесь к администратору.")
        except Exception as e:
            logger.warning(f"Cannot notify blocked user {target_id}: {e}")


async def notify_order_chat(bot: Bot, order: Order, is_custom: bool = False):
    """Send order notification to order chat"""
    from bot.database import async_session_factory
    async with async_session_factory() as session:
        if is_custom:
            text = (
                f"🌸 Новый индивидуальный заказ #{order.id}!\n\n"
                f"📝 Описание:\n{order.custom_description or '—'}\n"
            )
            if order.comment:
                text += f"\n💰 {order.comment}"
            if order.delivery_date:
                text += f"\n📅 Желаемая дата: {order.delivery_date}"
            text += f"\n📍 {order.delivery_address}\n"
            text += f"📞 {order.phone}"
        else:
            result = await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
            items = result.scalars().all()

            items_text = []
            for item in items:
                result2 = await session.execute(select(Product).where(Product.id == item.product_id))
                product = result2.scalar_one_or_none()
                if product:
                    items_text.append(f"  🌹 {product.name} x{item.quantity} — {item.price * item.quantity:.0f} ₽")

            date_text = order.delivery_date.strftime("%d.%m") if order.delivery_date else "не указана"
            time_text = order.delivery_time.strftime("%H:%M") if order.delivery_time else "не указано"
            text = (
                f"📦 Новый заказ #{order.id}!\n\n"
                f"💰 Сумма: {order.total_price:.0f} ₽\n\n"
                f"📋 Состав:\n" + "\n".join(items_text) +
                f"\n\n📍 {order.delivery_address}\n"
                f"📅 {date_text}, {time_text}\n"
                f"📞 {order.phone}"
            )
            if order.comment:
                text += f"\n💬 {order.comment}"

        # Отправка в чат
        try:
            await bot.send_message(settings.order_chat_id, text)
        except Exception as e:
            logger.warning(f"Cannot send order notification to chat {settings.order_chat_id}: {e}")


STATUS_TEXTS = {
    "new": "🆕 Новый",
    "processing": "⏳ В обработке",
    "confirmed": "✅ Подтверждён",
    "delivered": "🚚 Доставлен",
    "cancelled": "❌ Отменён",
    "not_connected": "📵 Не дозвонились",
}


async def notify_user(bot: Bot, telegram_id: int, order_id: int, new_status: str):
    """Send order status change notification to user"""
    status_text = STATUS_TEXTS.get(new_status, new_status)
    text = (
        f"📦 Заказ #{order_id}\n\n"
        f"Ваш заказ теперь имеет статус: {status_text}\n\n"
        f"Спасибо за покупку! 🌸"
    )
    try:
        await bot.send_message(telegram_id, text)
        logger.info(f"Notification sent to user {telegram_id} for order #{order_id}")
    except Exception as e:
        logger.warning(f"Cannot notify user {telegram_id} about order #{order_id}: {e}")


async def notify_chat(bot: Bot, chat_id: int, order_id: int, new_status: str):
    """Send order status change notification to order chat"""
    status_text = STATUS_TEXTS.get(new_status, new_status)
    text = f"📦 Заказ #{order_id}\nСтатус: {status_text}"
    try:
        await bot.send_message(chat_id, text)
        logger.info(f"Notification sent to chat {chat_id} for order #{order_id}")
    except Exception as e:
        logger.warning(f"Cannot notify chat {chat_id} about order #{order_id}: {e}")


async def notify_admin(bot: Bot, order: Order, is_custom: bool = False):
    """Send order notification to admin chat (alias for notify_order_chat)"""
    return await notify_order_chat(bot, order, is_custom=is_custom)


