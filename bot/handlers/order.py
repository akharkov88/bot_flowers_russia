import re
from datetime import date, time, timedelta
from typing import List

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.calendar_keyboard import get_calendar_keyboard, format_date_display, get_time_keyboard
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


async def get_max_lead_days(db_session, cart: dict) -> int:
    """Возвращает максимальный min_delivery_days среди товаров в корзине."""
    if not cart:
        return 0
    max_days = 0
    for prod_id_str in cart:
        pid = int(prod_id_str)
        result = await db_session.execute(select(Product).where(Product.id == pid))
        product = result.scalar_one_or_none()
        if product and product.min_delivery_days and product.min_delivery_days > max_days:
            max_days = product.min_delivery_days
    return max_days


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

        # If user chose to enter new address via callback ("Другой адрес"), process their text input
        if data.get("chose_new_address"):
            await state.update_data(
                address=message.text,
                chose_new_address=False,
                _address_sent=False
            )
            await state.set_state(OrderForm.waiting_for_date)
            # Confirm selected address
            confirm_text = f"📍 Вы выбрали адрес доставки: {message.text}"
            await message.answer(confirm_text)
            await _save_outgoing(user.id, confirm_text)
            # Compute min_date from cart lead times
            cart = data.get("cart", {})
            max_lead_days = await get_max_lead_days(db_session, cart)
            min_date = date.today() + timedelta(days=max_lead_days)
            today = date.today()
            await state.update_data(cal_year=today.year, cal_month=today.month, min_delivery_days=max_lead_days)
            cal_kb = get_calendar_keyboard(year=today.year, month=today.month, min_date=min_date)
            info_msg = ""
            if max_lead_days > 0:
                lead_products = []
                for prod_id_str, qty in cart.items():
                    pid = int(prod_id_str)
                    result = await db_session.execute(select(Product).where(Product.id == pid))
                    p = result.scalar_one_or_none()
                    if p and p.min_delivery_days and p.min_delivery_days >= max_lead_days:
                        lead_products.append(f"«{p.name}» ({p.min_delivery_days} дн.)")
                if lead_products:
                    info_msg = f"⏰ Товары {', '.join(lead_products)} требуют доставки не ранее чем через {max_lead_days} дн.\n\n"
            text = info_msg + "📅 Укажите желаемую дату доставки (необязательно).\n\nВыберите дату на календаре."
            await message.answer(text, reply_markup=cal_kb)
            await _save_outgoing(user.id, text, cal_kb)
            return

        # If checkout already sent the prompt (_address_sent=True), this is the user's address
        if data.get("_address_sent") and not data.get("chose_new_address"):
            await state.update_data(
                address=message.text,
                _address_sent=False
            )
            await state.set_state(OrderForm.waiting_for_date)
            # Confirm selected address
            confirm_text = f"📍 Вы выбрали адрес доставки: {message.text}"
            await message.answer(confirm_text)
            await _save_outgoing(user.id, confirm_text)
            # Compute min_date from cart lead times
            cart = data.get("cart", {})
            max_lead_days = await get_max_lead_days(db_session, cart)
            min_date = date.today() + timedelta(days=max_lead_days)
            today = date.today()
            await state.update_data(cal_year=today.year, cal_month=today.month, min_delivery_days=max_lead_days)
            cal_kb = get_calendar_keyboard(year=today.year, month=today.month, min_date=min_date)
            info_msg = ""
            if max_lead_days > 0:
                lead_products = []
                for prod_id_str, qty in cart.items():
                    pid = int(prod_id_str)
                    result = await db_session.execute(select(Product).where(Product.id == pid))
                    p = result.scalar_one_or_none()
                    if p and p.min_delivery_days and p.min_delivery_days >= max_lead_days:
                        lead_products.append(f"«{p.name}» ({p.min_delivery_days} дн.)")
                if lead_products:
                    info_msg = f"⏰ Товары {', '.join(lead_products)} требуют доставки не ранее чем через {max_lead_days} дн.\n\n"
            text = info_msg + "📅 Укажите желаемую дату доставки (необязательно).\n\nВыберите дату на календаре."
            await message.answer(text, reply_markup=cal_kb)
            await _save_outgoing(user.id, text, cal_kb)
            return

        # First message after showing keyboard — show address history or ask for address
        # Check if callback already sent the calendar (race condition fix)
        fsm_data = await state.get_data()
        if fsm_data.get("_address_callback_sent"):
            # Callback already sent the calendar, don't send duplicate
            return

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
    # Only handle if user is in order flow
    current_state = await state.get_state()
    if current_state != OrderForm.waiting_for_address.state:
        return

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
            # Delete the address selection message (keyboard)
            await callback.message.delete()
            # Confirm selected address
            confirm_text = f"📍 Вы выбрали адрес доставки: {address}"
            await callback.message.answer(confirm_text)
            await _save_outgoing(user.id, confirm_text)
            # Compute min_date from cart lead times
            fsm_data = await state.get_data()
            cart = fsm_data.get("cart", {})
            max_lead_days = await get_max_lead_days(db_session, cart)
            min_date = date.today() + timedelta(days=max_lead_days)
            today = date.today()
            await state.update_data(cal_year=today.year, cal_month=today.month, min_delivery_days=max_lead_days)
            cal_kb = get_calendar_keyboard(year=today.year, month=today.month, min_date=min_date)
            info_msg = ""
            if max_lead_days > 0:
                lead_products = []
                for prod_id_str, qty in cart.items():
                    pid = int(prod_id_str)
                    result = await db_session.execute(select(Product).where(Product.id == pid))
                    p = result.scalar_one_or_none()
                    if p and p.min_delivery_days and p.min_delivery_days >= max_lead_days:
                        lead_products.append(f"«{p.name}» ({p.min_delivery_days} дн.)")
                if lead_products:
                    info_msg = f"⏰ Товары {', '.join(lead_products)} требуют доставки не ранее чем через {max_lead_days} дн.\n\n"
            text = info_msg + "📅 Укажите желаемую дату доставки (необязательно).\n\nВыберите дату на календаре."
            # Set flag to prevent duplicate calendar send from message handler (race condition fix)
            await state.update_data(_address_callback_sent=True)
            await callback.message.answer(text, reply_markup=cal_kb)
            await _save_outgoing(user.id, text, cal_kb)
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


@order_router.callback_query(lambda c: c.data and '"t":"cal"' in c.data)
async def cb_calendar(callback: CallbackQuery, state: FSMContext, db_session, user):
    # Only handle if user is in order flow
    current_state = await state.get_state()
    if current_state not in (OrderForm.waiting_for_date.state,):
        return

    data = unpack_cb(callback.data)
    action = data.get("action", "")

    if action == "select_date":
        fsm_data = await state.get_data()
        cal_year = fsm_data.get("cal_year", date.today().year)
        cal_month = fsm_data.get("cal_month", date.today().month)

        cal_year = int(data.get("y", cal_year))
        cal_month = int(data.get("m", cal_month))
        d = int(data.get("d", 1))
        selected_date = date(cal_year, cal_month, d)
        delivery_date_str = format_date_display(selected_date)
        await state.update_data(
            date=delivery_date_str,
            cal_year=cal_year,
            cal_month=cal_month
        )

        # Transition to time selection state
        await state.set_state(OrderForm.waiting_for_time)

        # Delete the old calendar message and show time keyboard
        await callback.message.delete()

        time_kb = get_time_keyboard()
        text = f"✅ Вы выбрали дату: {delivery_date_str}\n\n🕐 Выберите время доставки:"
        await callback.message.answer(text, reply_markup=time_kb)
        await _save_outgoing(user.id, text, time_kb)

    elif action == "skip":
        await state.update_data(date=None)
        await state.set_state(OrderForm.waiting_for_time)
        await callback.message.delete()
        time_kb = get_time_keyboard()
        text = "✅ Дата не выбрана.\n\n🕐 Выберите время доставки:"
        await callback.message.answer(text, reply_markup=time_kb)
        await _save_outgoing(user.id, text, time_kb)

    elif action in ("prev_month", "next_month"):
        fsm_data = await state.get_data()
        cal_year = fsm_data.get("cal_year", date.today().year)
        cal_month = fsm_data.get("cal_month", date.today().month)

        if action == "prev_month":
            cal_month -= 1
            if cal_month < 1:
                cal_month = 12
                cal_year -= 1
        elif action == "next_month":
            cal_month += 1
            if cal_month > 12:
                cal_month = 1
                cal_year += 1

        await state.update_data(cal_year=cal_year, cal_month=cal_month)
        # Compute min_date from cart lead times
        fsm_data = await state.get_data()
        cart = fsm_data.get("cart", {})
        max_lead_days = await get_max_lead_days(db_session, cart)
        min_date = date.today() + timedelta(days=max_lead_days)
        cal_kb = get_calendar_keyboard(year=cal_year, month=cal_month, min_date=min_date)
        text = "📅 Укажите желаемую дату доставки (необязательно).\n\nВыберите дату на календаре."
        await callback.message.edit_text(text=text, reply_markup=cal_kb)
        await _save_outgoing(user.id, text, cal_kb)

    elif action == "day_name":
        await callback.answer()
    else:
        await callback.answer()

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

        # Support skip via text
        if date_str.lower() == "пропустить":
            await state.update_data(date=None)
            await state.set_state(OrderForm.waiting_for_time)
            time_kb = get_time_keyboard()
            text = "🕐 Выберите время доставки:\n\nНажмите на удобное время."
            await message.answer(text, reply_markup=time_kb)
            await _save_outgoing(user.id, text, time_kb)
            return

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
            current_year = date.today().year
            validated_date = date(year or current_year, month, day)  # use current year as fallback
        except ValueError:
            text = "⚠️ Такая дата не существует. Проверьте день и месяц."
            await message.answer(text)
            await _save_outgoing(user.id, text)
            return

        # Validate date is not before min_date (lead time)
        data = await state.get_data()
        cart = data.get("cart", {})
        max_lead_days = await get_max_lead_days(db_session, cart)
        min_date = date.today() + timedelta(days=max_lead_days)
        if validated_date < min_date:
            text = f"⚠️ Дата {validated_date.strftime('%d.%m.%Y')} недоступна. Минимальная дата доставки: {min_date.strftime('%d.%m.%Y')}."
            await message.answer(text)
            await _save_outgoing(user.id, text)
            return

        await state.update_data(date=date_str)
        await state.set_state(OrderForm.waiting_for_time)
        # Confirm selected date and show time selection in one message
        text = f"✅ Вы выбрали дату: {date_str}\n\n🕐 Выберите время доставки:\n\nНажмите на удобное время."
        time_kb = get_time_keyboard()
        await message.answer(text, reply_markup=time_kb)
        await _save_outgoing(user.id, text, time_kb)
    except Exception as e:
        logger.error(f"Error in process_date: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или начните заново с /start")


@order_router.callback_query(lambda c: c.data and '"t":"time"' in c.data)
async def cb_time(callback: CallbackQuery, state: FSMContext, db_session, user):
    # Only handle if user is in order flow
    current_state = await state.get_state()
    if current_state not in (OrderForm.waiting_for_time.state,):
        return

    data = unpack_cb(callback.data)
    action = data.get("action", "")

    if action == "select":
        time_str = data.get("time")
        await state.update_data(time=time_str)
        await callback.message.delete()

        # Confirm selected time
        time_confirmation = f"✅ Вы выбрали время: {time_str}"
        await callback.message.answer(time_confirmation)
        await _save_outgoing(user.id, time_confirmation)

        # Get previous phones for user
        prev_phones = await get_previous_phones(db_session, user.id)
        if prev_phones:
            await state.update_data(prev_phones=prev_phones)
            await state.set_state(OrderForm.waiting_for_phone)
            text = "📞 Выберите номер или введите новый:"
            keyboard = get_phone_history_keyboard(prev_phones)
            # Set flag to prevent duplicate from message handler (race condition fix)
            await state.update_data(_time_callback_sent=True)
            await callback.message.answer(text, reply_markup=keyboard)
            await _save_outgoing(user.id, text, keyboard)
        else:
            await state.set_state(OrderForm.waiting_for_phone)
            text = "📞 Введите номер телефона для связи:\n\nНапример: +7 (996) 041-22-27"
            await callback.message.answer(text)
            await _save_outgoing(user.id, text)

    elif action == "skip":
        await state.update_data(time=None)
        await callback.message.delete()

        # Confirm time was skipped
        time_confirmation = "✅ Время не выбрано."
        await callback.message.answer(time_confirmation)
        await _save_outgoing(user.id, time_confirmation)

        # Get previous phones for user
        prev_phones = await get_previous_phones(db_session, user.id)
        if prev_phones:
            await state.update_data(prev_phones=prev_phones)
            await state.set_state(OrderForm.waiting_for_phone)
            text = "📞 Выберите номер или введите новый:"
            keyboard = get_phone_history_keyboard(prev_phones)
            # Set flag to prevent duplicate from message handler (race condition fix)
            await state.update_data(_time_callback_sent=True)
            await callback.message.answer(text, reply_markup=keyboard)
            await _save_outgoing(user.id, text, keyboard)
        else:
            await state.set_state(OrderForm.waiting_for_phone)
            text = "📞 Введите номер телефона для связи:\n\nНапример: +7 (996) 041-22-27"
            await callback.message.answer(text)
            await _save_outgoing(user.id, text)

    else:
        await callback.answer()

    await callback.answer()


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

        # Guard against duplicate messages
        data = await state.get_data()
        if data.get("_time_sent"):
            return
        await state.update_data(_time_sent=True)

        time_str = message.text.strip()

        # Validate time format if not skip
        if time_str.lower() == "пропустить":
            time_str = None
        elif time_str:
            if not re.match(r"^\d{2}:\d{2}$", time_str):
                await state.update_data(_time_sent=False)
                time_kb = get_time_keyboard()
                text = "⚠️ Неверный формат времени.\n\nФормат: ЧЧ:ММ, например: 14:00"
                await message.answer(text, reply_markup=time_kb)
                await _save_outgoing(user.id, text)
                return
            try:
                hour, minute = map(int, time_str.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except ValueError:
                await state.update_data(_time_sent=False)
                time_kb = get_time_keyboard()
                text = "⚠️ Такое время не существует. Проверьте часы и минуты."
                await message.answer(text, reply_markup=time_kb)
                await _save_outgoing(user.id, text)
                return

        await state.update_data(time=time_str)

        # Check if callback already sent the phone prompt (race condition fix)
        fsm_data = await state.get_data()
        if fsm_data.get("_time_callback_sent"):
            return

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
    # Only handle if user is in order flow
    current_state = await state.get_state()
    if current_state not in (OrderForm.waiting_for_phone.state,):
        return

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
            # Delete the phone selection message (keyboard)
            await callback.message.delete()
            # Confirm selected phone with date (time already shown)
            date_str = fsm_data.get("date") or "не указана"
            confirm_text = f"📞 Вы выбрали номер: {phone}\n\n📅 Дата доставки: {date_str}"
            await callback.message.answer(confirm_text)
            await _save_outgoing(user.id, confirm_text)
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
        # If time callback already sent the phone prompt, don't duplicate
        if data.get("_time_callback_sent"):
            return
        await state.update_data(_phone_sent=True)

        if data.get("chose_new_phone"):
            await state.update_data(
                phone=message.text.strip(),
                chose_new_phone=False,
            )
            await state.set_state(OrderForm.waiting_for_comment)
            # Confirm selected phone with date (time already shown)
            date_str = data.get("date") or "не указана"
            confirm_text = f"📞 Вы выбрали номер: {message.text.strip()}\n\n📅 Дата доставки: {date_str}"
            await message.answer(confirm_text)
            await _save_outgoing(user.id, confirm_text)
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
        # Confirm selected phone with date (time already shown)
        date_str = data.get("date") or "не указана"
        confirm_text = f"📞 Вы выбрали номер: {phone}\n\n📅 Дата доставки: {date_str}"
        await message.answer(confirm_text)
        await _save_outgoing(user.id, confirm_text)
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
        time_str = data.get("time") or ""
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

        # Lead time info
        max_lead_days = data.get("min_delivery_days", 0)
        if max_lead_days > 0:
            min_date = date.today() + timedelta(days=max_lead_days)
            lead_info = f"\n⏰ Минимальная дата доставки: {min_date.strftime('%d.%m.%Y')} ({max_lead_days} дн.)"
        else:
            lead_info = ""

        order_text = (
            f"✅ Заказ #{order.id} оформлен!\n\n"
            f"💰 Сумма: {total:.0f} ₽\n\n"
            f"📋 Состав:\n" + ("\n".join(order_items_text) if order_items_text else "  —") +
            f"\n\n📍 Доставка: {address if address else 'не указана'}\n"
            f"📅 Дата: {date_str if date_str else 'не указана'}\n"
            f"🕐 Время: {time_str if time_str else 'не указано'}\n"
            f"📞 Телефон: {phone}"
        )
        if comment:
            order_text += f"\n💬 Комментарий: {comment}"
        order_text += lead_info

        order_text += "\n\n🌸 Спасибо за заказ! Мы свяжемся с вами для подтверждения."

        await message.answer(order_text, reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, order_text, get_main_keyboard())
    except Exception as e:
        logger.error(f"Error in process_comment: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или начните заново с /start")
