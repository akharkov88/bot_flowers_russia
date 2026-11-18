import re
from datetime import date, time

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.handlers.admin import notify_order_chat
from bot.keyboards import get_main_keyboard
from bot.models import Order, OrderItem, Product, User, Cart
from bot.states import OrderForm
from bot.utils.logger import logger

order_router = Router()


async def abandon_cart(db_session, user_id):
    """Mark user's active cart as abandoned"""
    result = await db_session.execute(
        select(Cart).where(Cart.user_id == user_id, Cart.status == "active")
    )
    cart = result.scalar_one_or_none()
    if cart:
        cart.status = "abandoned"
        from datetime import datetime, timezone
        cart.abandoned_at = datetime.now(timezone.utc)
        await db_session.commit()


async def complete_cart(db_session, user_id):
    """Mark user's active cart as completed"""
    result = await db_session.execute(
        select(Cart).where(Cart.user_id == user_id, Cart.status == "active")
    )
    cart = result.scalar_one_or_none()
    if cart:
        cart.status = "completed"
        await db_session.commit()


@order_router.message(OrderForm.waiting_for_address)
async def process_address(message: Message, state: FSMContext, db_session, user):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await abandon_cart(db_session, user.id)
        await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
        return

    await state.update_data(address=message.text)
    await state.set_state(OrderForm.waiting_for_date)
    await message.answer(
        "📅 Введите дату доставки (необязательно):\n\n"
        "Формат: ДД.ММ.ГГГГ, ДД.ММ.ГГ или ДД.ММ, например: 15.11.2026, 15.11.26, 15.11"
    )


@order_router.message(OrderForm.waiting_for_date)
async def process_date(message: Message, state: FSMContext, db_session, user):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await abandon_cart(db_session, user.id)
        await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
        return

    if message.text and message.text.lower() == "пропустить":
        await state.update_data(date=None)
        await state.set_state(OrderForm.waiting_for_time)
        await message.answer(
            "🕐 Введите время доставки в формате ЧЧ:ММ:\n\n"
            "Например: 14:00"
        )
        return

    date_str = message.text.strip()
    if not re.match(r"^\d{2}\.\d{2}(\.\d{2,4})?$", date_str):
        await message.answer(
            "⚠️ Неверный формат даты.\n\n"
            "Формат: ДД.ММ.ГГГГ или ДД.ММ.ГГ или ДД.ММ, например: 15.11.2026, 15.11.26, 15.11"
        )
        return

    try:
        parts = date_str.split(".")
        day, month = int(parts[0]), int(parts[1])
        year = int(parts[2]) if len(parts) == 3 else None
        if year and year < 100:
            year += 2000
        validated_date = date(year or 2000, month, day)  # dummy year for validation
    except ValueError:
        await message.answer("⚠️ Такая дата не существует. Проверьте день и месяц.")
        return

    await state.update_data(date=date_str)
    await state.set_state(OrderForm.waiting_for_time)
    await message.answer(
        "🕐 Введите время доставки в формате ЧЧ:ММ:\n\n"
        "Например: 14:00"
    )


@order_router.message(OrderForm.waiting_for_time)
async def process_time(message: Message, state: FSMContext, db_session, user):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await abandon_cart(db_session, user.id)
        await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
        return

    time_str = message.text.strip()

    await state.update_data(time=time_str)
    await state.set_state(OrderForm.waiting_for_phone)
    await message.answer(
        "📞 Введите номер телефона для связи:\n\n"
        "Например: +7 (996) 041-22-27"
    )


@order_router.message(OrderForm.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext, db_session, user):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await abandon_cart(db_session, user.id)
        await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
        return

    phone = message.text.strip()
    if not re.match(r"^[\+]?[\d\s\-\(\)]{7,20}$", phone):
        await message.answer("⚠️ Неверный формат телефона. Введите номер ещё раз.")
        return

    await state.update_data(phone=phone)
    await state.set_state(OrderForm.waiting_for_comment)
    await message.answer(
        "💬 Добавьте комментарий к заказу (необязательно):\n\n"
        "Например: позвонить за час, код домофона 123"
    )


@order_router.message(OrderForm.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext, db_session, user, bot: Bot):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await abandon_cart(db_session, user.id)
        await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
        return

    data = await state.get_data()
    address = data.get("address")
    date_str = data.get("date")
    time_str = data.get("time")
    phone = data.get("phone")
    comment = message.text if message.text and message.text.lower() != "готово" else ""

    if date_str:
        parts = date_str.split(".")
        day, month = int(parts[0]), int(parts[1])
        year = int(parts[2]) if len(parts) == 3 else None
        if year and year < 100:
            year += 2000
        if year:
            delivery_date = date(year, month, day)
        else:
            current_year = date.today().year
            candidate = date(current_year, month, day)
            delivery_date = candidate if candidate >= date.today() else date(current_year + 1, month, day)
    else:
        delivery_date = None
    # Parse time: support both HH:MM and HH formats
    if ":" in time_str:
        hour, minute = map(int, time_str.split(":"))
        delivery_time = time(hour, minute)
    else:
        try:
            hour = int(time_str)
            delivery_time = time(hour, 0)
        except ValueError:
            delivery_time = None

    cart = data.get("cart", {})

    # Find internal user ID
    result = await db_session.execute(select(User).where(User.telegram_id == user.telegram_id))
    internal_user = result.scalar_one_or_none()
    user_id = internal_user.id if internal_user else 0

    total = 0
    order = Order(
        user_id=user_id,
        delivery_address=address,
        delivery_date=delivery_date,
        delivery_time=delivery_time,
        phone=phone,
        comment=comment,
    )
    db_session.add(order)
    await db_session.flush()

    order_items_text = []
    for prod_id_str, qty in cart.items():
        prod_id = int(prod_id_str)
        result = await db_session.execute(select(Product).where(Product.id == prod_id))
        product = result.scalar_one_or_none()
        if not product:
            continue
        if qty > product.quantity:
            await message.answer(
                f"❌ Товар «{product.name}» — в наличии только {product.quantity} шт. "
                f"Вы заказали {qty} шт.\n\n"
                f"Откорректируйте корзину или уменьшите количество."
            )
            return
        item = OrderItem(order_id=order.id, product_id=product.id, quantity=qty, price=product.price)
        db_session.add(item)
        total += product.price * qty
        order_items_text.append(f"  🌹 {product.name} x{qty} — {product.price * qty:.0f} ₽")

    # Уменьшаем количество на складе и деактивируем если 0
    for prod_id_str, qty in cart.items():
        prod_id = int(prod_id_str)
        result = await db_session.execute(select(Product).where(Product.id == prod_id))
        product = result.scalar_one_or_none()
        if product:
            product.quantity -= qty
            if product.quantity <= 0:
                product.quantity = 0
                product.is_active = False

    order.total_price = total
    await db_session.commit()
    await db_session.refresh(order)

    # Mark cart as completed
    await complete_cart(db_session, user.id)

    # Уведомление о заказе в чат
    try:
        await notify_order_chat(bot, order)
    except Exception as e:
        logger.error(f"Failed to notify about order #{order.id}: {e}")

    await state.clear()

    order_text = (
        f"✅ Заказ #{order.id} оформлен!\n\n"
        f"💰 Сумма: {total:.0f} ₽\n\n"
        f"📋 Состав:\n" + "\n".join(order_items_text) +
        f"\n\n📍 Доставка: {address}\n"
        f"📅 Дата: {date_str if date_str else 'не указана'}\n"
        f"🕐 Время: {time_str}\n"
        f"📞 Телефон: {phone}"
    )
    if comment:
        order_text += f"\n💬 Комментарий: {comment}"

    order_text += "\n\n🌸 Спасибо за заказ! Мы свяжемся с вами для подтверждения."

    await message.answer(order_text, reply_markup=get_main_keyboard())
