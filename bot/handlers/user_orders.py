from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from bot.keyboards import pack_cb, unpack_cb, get_main_keyboard
from bot.models import Order, OrderItem, Product
from bot.utils.logger import logger

user_orders_router = Router()


@user_orders_router.message(F.text == "📋 Мои заказы")
async def msg_my_orders(message: Message, db_session, user):
    result = await db_session.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(10)
    )
    orders = result.scalars().all()

    if not orders:
        await message.answer(
            "📋 У вас пока нет заказов.\n\n"
            "Оформите первый заказ в каталоге!",
            reply_markup=get_main_keyboard(),
        )
        return

    status_map = {
        "new": "🆕 Новый",
        "processing": "⏳ В обработке",
        "confirmed": "✅ Подтверждён",
        "delivered": "🚚 Доставлен",
        "cancelled": "❌ Отменён",
    }

    text = "📋 Ваши последние заказы:\n\n"
    for order in orders:
        status = status_map.get(order.status, order.status)
        text += (
            f"📦 Заказ #{order.id}\n"
            f"{status} — {order.total_price:.0f} ₽\n"
            f"📅 {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        )

    text += "Нажмите на заказ для просмотра деталей:"
    await message.answer(text)


@user_orders_router.callback_query(F.data.contains("order"))
async def cb_handle_orders(callback: CallbackQuery, bot: Bot, db_session, user):
    data = unpack_cb(callback.data)
    action = data.get("action")

    if action == "detail":
        order_id = int(data["id"])

        result = await db_session.execute(select(Order).where(Order.id == order_id, Order.user_id == user.id))
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
        }
        status = status_map.get(order.status, order.status)

        text = (
            f"📦 Заказ #{order.id}\n"
            f"{status}\n"
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

        text += f"\n📍 Доставка: {order.delivery_address}\n"
        text += f"📅 Дата: {order.delivery_date}\n"
        text += f"🕐 Время: {order.delivery_time}\n"
        text += f"📞 Телефон: {order.phone}"
        if order.comment and not order.is_custom:
            text += f"\n💬 Комментарий: {order.comment}"

        await callback.message.answer(text)
        await callback.answer()


@user_orders_router.callback_query(F.data.contains("back"))
async def cb_back(callback: CallbackQuery):
    await callback.message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())
    await callback.answer()
