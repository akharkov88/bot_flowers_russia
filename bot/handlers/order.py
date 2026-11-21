import re
from datetime import date, time
from typing import List

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.handlers.admin import notify_order_chat
from bot.keyboards import get_main_keyboard, get_address_history_keyboard, get_phone_history_keyboard, unpack_cb, _short_hash
from bot.models import Order, OrderItem, Product, User, Cart
from bot.states import OrderForm, CustomBouquetForm
from bot.utils.logger import logger
from bot.utils.message_saver import save_outgoing_with_keyboard
from bot.database import async_session_factory

# Menu button texts that should cancel any active FSM order flow
_MENU_BUTTONS = {
    "🌸 Каталог",
    "🛒 Корзина",
    "📋 Мои заказы",
    "✨ Хочу букет которого нет в каталоге",
    "📍 Контакты",
}


async def _save_outgoing(user_id, text, keyboard=None):
    """Save an outgoing message sent by the bot."""
    try:
        async with async_session_factory() as session:
            await save_outgoing_with_keyboard(session, user_id, text, keyboard)
    except Exception as e:
        logger.error(f"Error saving outgoing message: {e}")

order_router = Router()


async def abandon_cart(db_session, user_id):
    """Mark user's active cart as abandoned"""
    result = await db_session.execute(
        select(Cart).where(Cart.user_id == user_id, Cart.status == "active")
    )
    cart = result.scalar_one_or_none()
    if cart:
        cart.status = "abandoned"
        from datetime import datetime
        cart.abandoned_at = datetime.now()
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


async def get_previous_addresses(db_session, user_id) -> List[str]:
    """Get unique delivery addresses from user's orders"""
    result = await db_session.execute(
        select(Order.delivery_address)
        .where(Order.user_id == user_id, Order.delivery_address.isnot(None), Order.delivery_address != "")
        .order_by(Order.id.desc())
    )
    addresses = [row[0] for row in result.all() if row[0]]
    # Deduplicate preserving order (most recent first)
    seen = set()
    unique = []
    for addr in addresses:
        if addr not in seen:
            seen.add(addr)
            unique.append(addr)
    return unique[:5]


async def get_previous_phones(db_session, user_id) -> List[str]:
    """Get unique phone numbers from user's orders"""
    result = await db_session.execute(
        select(Order.phone)
        .where(Order.user_id == user_id, Order.phone.isnot(None), Order.phone != "")
        .order_by(Order.id.desc())
    )
    phones = [row[0] for row in result.all() if row[0]]
    # Deduplicate preserving order (most recent first)
    seen = set()
    unique = []
    for phone in phones:
        if phone not in seen:
            seen.add(phone)
            unique.append(phone)
    return unique[:5]


@order_router.message(OrderForm.waiting_for_address)
async def process_address(message: Message, state: FSMContext, db_session, user):
    try:
        # Cancel on menu buttons
        if message.text in _MENU_BUTTONS:
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return
        if message.text and message.text.lower() == "отмена":
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return

        # Check if user chose to enter new address
        data = await state.get_data()

        # If checkout already sent the prompt (_address_sent=True), this is the user's address
        if data.get("_address_sent") and not data.get("chose_new_address"):
            await state.update_data(
                address=message.text,
                _address_sent=False
            )
            await state.set_state(OrderForm.waiting_for_date)
            text = "📅 Введите дату доставки (необязательно):\n\nФормат: ДД.ММ.ГГГГ, ДД.ММ.ГГ или ДД.ММ, например: 15.11.2026, 15.11.26, 15.11"
            await message.answer(text)
            await _save_outgoing(user.id, text)
            return

        if data.get("chose_new_address"):
            await state.update_data(
                address=message.text,
                chose_new_address=False,
                _address_sent=False
            )
            await state.set_state(OrderForm.waiting_for_date)
            text = "📅 Введите дату доставки (необязательно):\n\nФормат: ДД.ММ.ГГГГ, ДД.ММ.ГГ или ДД.ММ, например: 15.11.2026, 15.11.26, 15.11"
            await message.answer(text)
            await _save_outgoing(user.id, text)
            return

        # First message after showing keyboard — show address history or ask for address
        prev_addresses = await get_previous_addresses(db_session, user.id)
        if prev_addresses:
            await state.update_data(prev_addresses=prev_addresses, _address_sent=True)
            text = "📍 Выберите адрес или введите новый:"
            keyboard = get_address_history_keyboard(prev_addresses)
            await message.answer(text, reply_markup=keyboard)
            await _save_outgoing(user.id, text, keyboard)
        else:
            await state.update_data(_address_sent=True)
            text = "📍 Введите адрес доставки:"
            await message.answer(text)
            await _save_outgoing(user.id, text)
    except Exception as e:
        logger.error(f"Error in process_address: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или начните заново с /start")


@order_router.callback_query(lambda c: c.data and '"t":"addr"' in c.data and 'custom_' not in c.data)
async def cb_address(callback: CallbackQuery, state: FSMContext, db_session, user):
    data = unpack_cb(callback.data)
    action = data.get("action", "")

    if action == "select":
        hash_id = data.get("hash", "")
        # Get prev_addresses from FSM state, not from callback data
        fsm_data = await state.get_data()
        prev_addresses = fsm_data.get("prev_addresses", [])
        address = None
        for addr in prev_addresses:
            if _short_hash(addr) == hash_id:
                address = addr
                break
        if address:
            await state.update_data(address=address, _address_sent=False)
            await state.set_state(OrderForm.waiting_for_date)
            text = "📅 Введите дату доставки (необязательно):\n\nФормат: ДД.ММ.ГГГГ, ДД.ММ.ГГ или ДД.ММ, например: 15.11.2026, 15.11.26, 15.11"
            await callback.message.answer(text)
            await _save_outgoing(user.id, text)
        else:
            await callback.answer("Ошибка", show_alert=True)
    elif action == "new":
        await state.update_data(chose_new_address=True, _address_sent=False)
        await callback.answer()
        text = "✏️ Введите новый адрес в чат:"
        await callback.message.answer(text)
        await _save_outgoing(user.id, text)
        return

    await callback.answer()


@order_router.message(OrderForm.waiting_for_date)
async def process_date(message: Message, state: FSMContext, db_session, user):
    try:
        # Cancel on menu buttons
        if message.text in _MENU_BUTTONS:
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return
        if message.text and message.text.lower() == "отмена":
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return

        date_str = message.text.strip()
        if not re.match(r"^\d{2}\.\d{2}(\.\d{2,4})?$", date_str):
            text = "⚠️ Неверный формат даты.\n\nФормат: ДД.ММ.ГГГГ или ДД.ММ.ГГ или ДД.ММ, например: 15.11.2026, 15.11.26, 15.11"
            await message.answer(text)
            await _save_outgoing(user.id, text)
            return

        try:
            parts = date_str.split(".")
            day, month = int(parts[0]), int(parts[1])
            year = int(parts[2]) if len(parts) == 3 else None
            if year and year < 100:
                year += 2000
            validated_date = date(year or 2000, month, day)  # dummy year for validation
        except ValueError:
            text = "⚠️ Такая дата не существует. Проверьте день и месяц."
            await message.answer(text)
            await _save_outgoing(user.id, text)
            return

        await state.update_data(date=date_str)
        await state.set_state(OrderForm.waiting_for_time)
        text = "🕐 Введите время доставки в формате ЧЧ:ММ:\n\nНапример: 14:00"
        await message.answer(text)
        await _save_outgoing(user.id, text)
    except Exception as e:
        logger.error(f"Error in process_date: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или начните заново с /start")


@order_router.message(OrderForm.waiting_for_time)
async def process_time(message: Message, state: FSMContext, db_session, user):
    try:
        # Cancel on menu buttons
        if message.text in _MENU_BUTTONS:
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return
        if message.text and message.text.lower() == "отмена":
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return

        time_str = message.text.strip()

        await state.update_data(time=time_str)

        # Запрашиваем предыдущие телефоны и показываем клавиатуру
        prev_phones = await get_previous_phones(db_session, user.id)

        if prev_phones:
            await state.update_data(prev_phones=prev_phones)
            await state.set_state(OrderForm.waiting_for_phone)
            text = "📞 Выберите номер или введите новый:"
            keyboard = get_phone_history_keyboard(prev_phones)
            await message.answer(text, reply_markup=keyboard)
            await _save_outgoing(user.id, text, keyboard)
        else:
            await state.set_state(OrderForm.waiting_for_phone)
            text = "📞 Введите номер телефона для связи:\n\nНапример: +7 (996) 041-22-27"
            await message.answer(text)
            await _save_outgoing(user.id, text)
    except Exception as e:
        logger.error(f"Error in process_time: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или начните заново с /start")


@order_router.callback_query(lambda c: c.data and '"t":"phone"' in c.data and 'custom_' not in c.data)
async def cb_phone(callback: CallbackQuery, state: FSMContext, db_session, user):
    data = unpack_cb(callback.data)
    action = data.get("action", "")

    if action == "select":
        hash_id = data.get("hash", "")
        # Get prev_phones from FSM state, not from callback data
        fsm_data = await state.get_data()
        prev_phones = fsm_data.get("prev_phones", [])
        phone = None
        for p in prev_phones:
            if _short_hash(p) == hash_id:
                phone = p
                break
        if phone:
            await state.update_data(phone=phone, _phone_sent=False)
            await state.set_state(OrderForm.waiting_for_comment)
            text = "💬 Добавьте комментарий к заказу (необязательно):\n\nНапример: позвонить за час, код домофона 123"
            await callback.message.answer(text)
            await _save_outgoing(user.id, text)
        else:
            await callback.answer("Ошибка", show_alert=True)
    elif action == "new":
        await state.update_data(chose_new_phone=True, _phone_sent=False)
        await callback.answer()
        text = "✏️ Введите новый номер в чат:"
        await callback.message.answer(text)
        await _save_outgoing(user.id, text)
        return

    await callback.answer()


@order_router.message(OrderForm.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext, db_session, user):
    try:
        # Cancel on menu buttons
        if message.text in _MENU_BUTTONS:
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return
        if message.text and message.text.lower() == "отмена":
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return

        data = await state.get_data()

        # Guard against duplicate messages
        if data.get("_phone_sent"):
            return
        await state.update_data(_phone_sent=True)

        if data.get("chose_new_phone"):
            await state.update_data(
                phone=message.text.strip(),
                chose_new_phone=False,
            )
            await state.set_state(OrderForm.waiting_for_comment)
            text = "💬 Добавьте комментарий к заказу (необязательно):\n\nНапример: позвонить за час, код домофона 123"
            await message.answer(text)
            await _save_outgoing(user.id, text)
            return

        # User typed a phone number manually
        phone = message.text.strip()
        if not re.match(r"^[\+]?[\d\s\-\(\)]{7,20}$", phone):
            prev_phones = await get_previous_phones(db_session, user.id)
            if prev_phones:
                await state.update_data(prev_phones=prev_phones)
                text = "⚠️ Неверный формат телефона.\n\nВыберите один из предыдущих или введите новый:"
                keyboard = get_phone_history_keyboard(prev_phones)
                await message.answer(text, reply_markup=keyboard)
                await _save_outgoing(user.id, text, keyboard)
            else:
                text = "⚠️ Неверный формат телефона. Введите номер ещё раз."
                await message.answer(text)
                await _save_outgoing(user.id, text)
            return

        await state.update_data(phone=phone)
        await state.set_state(OrderForm.waiting_for_comment)
        text = "💬 Добавьте комментарий к заказу (необязательно):\n\nНапример: позвонить за час, код домофона 123"
        await message.answer(text)
        await _save_outgoing(user.id, text)
    except Exception as e:
        logger.error(f"Error in process_phone: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или начните заново с /start")


@order_router.message(OrderForm.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext, db_session, user, bot: Bot):
    try:
        # Cancel on menu buttons
        if message.text in _MENU_BUTTONS:
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
            return
        if message.text and message.text.lower() == "отмена":
            await state.clear()
            await abandon_cart(db_session, user.id)
            await message.answer("❌ Заказ отменён.", reply_markup=get_main_keyboard())
            await _save_outgoing(user.id, "❌ Заказ отменён.")
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
                text = (f"❌ Товар «{product.name}» — в наличии только {product.quantity} шт. "
                        f"Вы заказали {qty} шт.\n\nОткорректируйте корзину или уменьшите количество.")
                await message.answer(text)
                await _save_outgoing(user.id, text)
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
        await _save_outgoing(user.id, order_text, get_main_keyboard())
    except Exception as e:
        logger.error(f"Error in process_comment: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или начните заново с /start")
