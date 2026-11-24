import os
import re
from datetime import date, time, timedelta, datetime

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.handlers.admin import notify_admin
from bot.keyboards import get_main_keyboard, get_custom_bouquet_keyboard, get_address_history_keyboard, get_phone_history_keyboard, pack_cb, unpack_cb, _short_hash
from bot.models import Order, User
from bot.states import CustomBouquetForm, NavigationState
from bot.calendar_keyboard import get_calendar_keyboard, format_date_display, get_time_keyboard
from bot.utils.logger import logger
from bot.utils.message_saver import save_outgoing_with_keyboard
from bot.database import async_session_factory

# Menu button texts that should cancel any active FSM custom bouquet flow
_MENU_BUTTONS = {
    "🌸 Каталог",
    "🛒 Корзина",
    "📋 Мои заказы",
    "✨ Хочу букет которого нет в каталоге",
    "📍 Контакты",
}


custom_bouquet_router = Router()


async def _save_outgoing(user_id, text, keyboard=None):
    """Save an outgoing message sent by the bot."""
    try:
        async with async_session_factory() as session:
            await save_outgoing_with_keyboard(session, user_id, text, keyboard)
    except Exception as e:
        logger.error(f"Error saving outgoing message: {e}")


async def _get_prev_addresses(db_session, user_id):
    """Get unique delivery addresses from user's orders"""
    from bot.models import Order
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


async def _get_prev_phones(db_session, user_id):
    """Get unique phone numbers from user's orders"""
    from bot.models import Order
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


@custom_bouquet_router.message(lambda m: m.text and "Хочу букет" in m.text)
async def cmd_custom_bouquet(message: Message, state: FSMContext, db_session, user):
    # Если пользователь уже в процессе оформления, сбрасываем state
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    logger.info(f"DEBUG: Received text: {repr(message.text)}")
    # Сохраняем навигационный контекст
    back_context = "main"
    cat_id = 0

    # Проверяем FSM data для определения предыдущего экрана
    try:
        fsm_data = await state.get_data()
        screen = fsm_data.get("screen", "")
        cat_id = int(fsm_data.get("cat_id", 0))

        if screen in ("categories", "products", "product"):
            back_context = "catalog"
    except Exception:
        pass

    await state.set_state(CustomBouquetForm.waiting_for_description)
    await state.update_data(back_context=back_context, cat_id=cat_id)

    keyboard = get_custom_bouquet_keyboard(back_context=back_context, cat_id=cat_id)
    text = "🌸 Опишите желаемый букет:\n\nНапишите всё, что хотите: цвета, размеры, настроение, повод.\nНапример: 'Большой букет из розовых и белых пионов, нежный, для свадьбы'."
    await message.answer(text, reply_markup=keyboard)
    await _save_outgoing(user.id, text, keyboard)


@custom_bouquet_router.callback_query(F.data.startswith('{"t":"back"'))
async def cb_custom_back(callback: CallbackQuery, state: FSMContext, db_session, bot: Bot):
    data = unpack_cb(callback.data)
    back_context = data.get("back_context", "main")
    cat_id = int(data.get("cat_id", 0))

    # Очищаем FSM state
    await state.clear()

    if back_context == "catalog" and cat_id > 0:
        # Возвращаемся к продуктам категории
        from bot.handlers.catalog import _get_categories_with_available_products, get_image_path, UPLOAD_DIR
        from aiogram.types import FSInputFile
        from aiogram.exceptions import TelegramForbiddenError
        from sqlalchemy.orm import selectinload
        from bot.models import Product, Category
        from bot.keyboards import get_products_keyboard

        result = await db_session.execute(
            select(Product).options(selectinload(Product.images)).where(Product.category_id == cat_id, Product.is_active == True, Product.quantity > 0).order_by(Product.id)
        )
        products = result.scalars().all()
        if products:
            result = await db_session.execute(select(Category).where(Category.id == cat_id))
            category = result.scalar_one_or_none()
            if category:
                await callback.message.delete()
                if category.image_url:
                    cat_image_path = get_image_path(category.image_url)
                    if cat_image_path and os.path.exists(cat_image_path):
                        try:
                            await bot.send_photo(
                                callback.message.chat.id,
                                FSInputFile(cat_image_path),
                                caption=f"🌸 {category.name}\n\nВыберите букет:",
                                reply_markup=get_products_keyboard(products, cat_id=cat_id),
                            )
                        except (TelegramForbiddenError, Exception):
                            await bot.send_message(
                                callback.message.chat.id,
                                f"🌸 {category.name}\n\nВыберите букет:",
                                reply_markup=get_products_keyboard(products, cat_id=cat_id),
                            )
                    else:
                        await bot.send_message(
                            callback.message.chat.id,
                            f"🌸 {category.name}\n\nВыберите букет:",
                            reply_markup=get_products_keyboard(products, cat_id=cat_id),
                        )
                else:
                    await bot.send_message(
                        callback.message.chat.id,
                        f"🌸 {category.name}\n\nВыберите букет:",
                        reply_markup=get_products_keyboard(products, cat_id=cat_id),
                    )
                await callback.answer()
                return

    # Fallback — главное меню
    await callback.message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())
    await callback.answer()


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_description)
async def process_description(message: Message, state: FSMContext, db_session, user):
    # Cancel on menu buttons
    if message.text in _MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return

    description = message.text.strip()
    if len(description) < 10:
        text = "⚠️ Описание слишком короткое. Пожалуйста, опишите букет подробнее.\n\nМинимум 10 символов."
        await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
        await _save_outgoing(user.id, text)
        return

    await state.update_data(description=description)
    await state.set_state(CustomBouquetForm.waiting_for_budget)
    text = "💰 Укажите желаемый бюджет (необязательно).\n\nНапример: 1500-3000"
    await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
    await _save_outgoing(user.id, text)


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_budget)
async def process_budget(message: Message, state: FSMContext, db_session, user):
    # Cancel on menu buttons
    if message.text in _MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return

    if message.text and message.text.lower() == "пропустить":
        budget = None
    else:
        budget = message.text.strip()

    await state.update_data(budget=budget)
    await state.set_state(CustomBouquetForm.waiting_for_delivery_date)
    # Initialize calendar month/year if not set
    fsm_data = await state.get_data()
    cal_year = fsm_data.get("cal_year", date.today().year)
    cal_month = fsm_data.get("cal_month", date.today().month)
    await state.update_data(cal_year=cal_year, cal_month=cal_month)
    cal_kb = get_calendar_keyboard(year=cal_year, month=cal_month, hide_cancel=True)
    text = "📅 Укажите желаемую дату доставки (необязательно).\n\nВыберите дату на календаре или нажмите ⏩ Пропустить."
    await message.answer(text, reply_markup=cal_kb)
    await _save_outgoing(user.id, text)


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_delivery_date)
async def process_delivery_date(message: Message, state: FSMContext, db_session, user):
    # Cancel on menu buttons
    if message.text in _MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return

    # Also support manual text input as fallback
    if message.text and message.text.lower() == "пропустить":
        delivery_date = None
        delivery_date_str = None
    else:
        date_str = message.text.strip()
        if not re.match(r"^\d{2}\.\d{2}(\.\d{2,4})?$", date_str):
            text = "⚠️ Неверный формат даты.\n\nФормат: ДД.ММ.ГГГГ или ДД.ММ.ГГ или ДД.ММ, например: 20.11.2026, 20.11.26, 20.11"
            await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
            await _save_outgoing(user.id, text)
            return
        try:
            parts = date_str.split(".")
            day, month = int(parts[0]), int(parts[1])
            year = int(parts[2]) if len(parts) == 3 else None
            if year and year < 100:
                year += 2000
            current_year = date.today().year
            delivery_date = date(year or current_year, month, day)
            delivery_date_str = date_str
        except ValueError:
            text = "⚠️ Такая дата не существует. Проверьте день и месяц."
            await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
            await _save_outgoing(user.id, text)
            return

    await state.update_data(delivery_date=delivery_date, delivery_date_str=delivery_date_str)
    await state.set_state(CustomBouquetForm.waiting_for_time)
    time_kb = get_time_keyboard()
    text = "🕐 Выберите время доставки:\n\nНажмите на удобное время или введите своё (например: 14:00)."
    await message.answer(text, reply_markup=time_kb)
    await _save_outgoing(user.id, text)


@custom_bouquet_router.callback_query(F.data.startswith('{"t":"cal"'))
async def cb_custom_calendar(callback: CallbackQuery, state: FSMContext, db_session):
    data = unpack_cb(callback.data)
    action = data.get("action", "")

    if action in ("select_date", "prev_month", "next_month", "header"):
        # Calendar navigation / selection
        fsm_data = await state.get_data()
        cal_year = fsm_data.get("cal_year", date.today().year)
        cal_month = fsm_data.get("cal_month", date.today().month)
        selected_date = fsm_data.get("delivery_date")

        if action == "select_date":
            cal_year = data.get("y", cal_year)
            cal_month = data.get("m", cal_month)
            d = data.get("d", 1)
            selected_date = date(cal_year, cal_month, d)
            delivery_date_str = format_date_display(selected_date)
            await state.update_data(delivery_date=selected_date, delivery_date_str=delivery_date_str, cal_year=cal_year, cal_month=cal_month)

            # Transition to time selection state
            await state.set_state(CustomBouquetForm.waiting_for_time)

            # Delete the old calendar message and show time keyboard
            await callback.message.delete()

            text = f"✅ Выбрана дата: {delivery_date_str}\n\n🕐 Выберите время доставки:"
            time_kb = get_time_keyboard()
            await callback.message.answer(text, reply_markup=time_kb)
            await _save_outgoing(callback.from_user.id, text, time_kb)

        elif action == "skip":
            await state.update_data(delivery_date=None, delivery_date_str=None)
            await state.set_state(CustomBouquetForm.waiting_for_time)
            await callback.message.delete()
            text = "🕐 Выберите время доставки:"
            time_kb = get_time_keyboard()
            await callback.message.answer(text, reply_markup=time_kb)
            await _save_outgoing(callback.from_user.id, text, time_kb)

        else:
            # prev_month or next_month
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
            cal_kb = get_calendar_keyboard(year=cal_year, month=cal_month, hide_cancel=True)
            text = "📅 Укажите желаемую дату доставки (необязательно).\n\nВыберите дату на календаре или нажмите ⏩ Пропустить."
            await callback.message.edit_text(text=text, reply_markup=cal_kb)

    elif action == "day_name":
        await callback.answer()
    else:
        await callback.answer()

    await callback.answer()


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_time)
async def process_time(message: Message, state: FSMContext, db_session, user):
    # Cancel on menu buttons
    if message.text in _MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return

    # Guard against duplicate messages
    data = await state.get_data()
    if data.get("_time_sent"):
        return
    await state.update_data(_time_sent=True)

    if message.text and message.text.lower() == "пропустить":
        time_str = None
    else:
        time_str = message.text.strip()
        # Validate time format ЧЧ:ММ
        if not re.match(r"^\d{2}:\d{2}$", time_str):
            await state.update_data(_time_sent=False)
            text = "⚠️ Неверный формат времени.\n\nФормат: ЧЧ:ММ, например: 14:00"
            await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
            await _save_outgoing(user.id, text)
            return
        try:
            hour, minute = map(int, time_str.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            await state.update_data(_time_sent=False)
            text = "⚠️ Такое время не существует. Проверьте часы и минуты."
            await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
            await _save_outgoing(user.id, text)
            return

    await state.update_data(time=time_str)

    # Запрашиваем предыдущие адреса и показываем клавиатуру
    prev_addresses = await _get_prev_addresses(db_session, user.id)

    if prev_addresses:
        await state.update_data(prev_addresses=prev_addresses, _address_sent=True)
        await state.set_state(CustomBouquetForm.waiting_for_address)
        logger.info(f"DEBUG process_time: set state=waiting_for_address with prev_addresses, _address_sent=True")
        text = "📍 Выберите адрес или введите новый:"
        keyboard = get_address_history_keyboard(prev_addresses, prefix="custom_")
        await message.answer(text, reply_markup=keyboard)
        await _save_outgoing(user.id, text, keyboard)
    else:
        await state.update_data(_address_sent=True)
        await state.set_state(CustomBouquetForm.waiting_for_address)
        logger.info(f"DEBUG process_time: set state=waiting_for_address without prev_addresses, _address_sent=True")
        text = "📍 Введите адрес доставки:\n\nНапример: г. Нижний Новгород, ул. Белинского, д. 10, кв. 5"
        await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
        await _save_outgoing(user.id, text)


async def _send_address_prompt(callback, state, db_session, time_str=None):
    """Send time confirmation and prompt for address."""
    if time_str:
        text = "✅ Время: " + time_str + "\n\n📍 Выберите адрес или введите новый:"
    else:
        text = "📍 Выберите адрес или введите новый:"
    keyboard = get_custom_bouquet_keyboard()
    await callback.message.answer(text, reply_markup=keyboard)
    await _save_outgoing(callback.from_user.id, text)

    # Запрашиваем предыдущие адреса
    prev_addresses = await _get_prev_addresses(db_session, callback.from_user.id)
    if prev_addresses:
        await state.update_data(prev_addresses=prev_addresses, _address_sent=True)
        await state.set_state(CustomBouquetForm.waiting_for_address)
        text = "📍 Выберите адрес или введите новый:"
        keyboard = get_address_history_keyboard(prev_addresses, prefix="custom_")
        await callback.message.answer(text, reply_markup=keyboard)
        await _save_outgoing(callback.from_user.id, text, keyboard)
    else:
        await state.update_data(_address_sent=True)
        await state.set_state(CustomBouquetForm.waiting_for_address)
        text = "📍 Введите адрес доставки:\n\nНапример: г. Нижний Новгород, ул. Белинского, д. 10, кв. 5"
        await callback.message.answer(text, reply_markup=get_custom_bouquet_keyboard())
        await _save_outgoing(callback.from_user.id, text)


@custom_bouquet_router.callback_query(F.data.startswith('{"t":"time"'))
async def cb_custom_time(callback: CallbackQuery, state: FSMContext, db_session):
    data = unpack_cb(callback.data)
    action = data.get("action", "")

    if action == "select":
        time_str = data.get("tm")
        await state.update_data(time=time_str)
        await callback.message.delete()
        await _send_address_prompt(callback, state, db_session, time_str)

    elif action == "skip":
        await state.update_data(time=None)
        await callback.message.delete()
        await _send_address_prompt(callback, state, db_session)

    elif action == "custom":
        # User wants to enter custom time
        await callback.message.delete()
        text = "✏️ Введите своё время в формате ЧЧ:ММ:\n\nНапример: 14:00"
        await callback.message.answer(text, reply_markup=get_custom_bouquet_keyboard())
        await _save_outgoing(callback.from_user.id, text)

    else:
        await callback.answer()


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_address)
async def process_address(message: Message, state: FSMContext, db_session, user):
    _data = await state.get_data()
    logger.info(f"DEBUG process_address: user_id={user.id}, text={repr(message.text[:50])}, state={await state.get_state()}, _address_sent={_data.get('_address_sent')}")
    # Cancel on menu buttons
    if message.text in _MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return

    data = await state.get_data()

    # Check if user chose to enter new address via callback ("Другой адрес")
    if data.get("chose_new_address"):
        await state.update_data(
            address=message.text,
            chose_new_address=False
        )
        await state.set_state(CustomBouquetForm.waiting_for_phone)
        # Get previous phones for user
        internal_user = None
        result = await db_session.execute(select(User).where(User.telegram_id == user.telegram_id))
        internal_user = result.scalar_one_or_none()
        if internal_user:
            prev_phones = await _get_prev_phones(db_session, internal_user.id)
            if prev_phones:
                await state.update_data(prev_phones=prev_phones)
                text = "📞 Выберите номер или введите новый:"
                keyboard = get_phone_history_keyboard(prev_phones, prefix="custom_")
                await message.answer(text, reply_markup=keyboard)
                await _save_outgoing(user.id, text, keyboard)
            else:
                text = "📞 Введите номер телефона для связи:\n\nНапример: +7 (996) 041-22-27"
                await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
                await _save_outgoing(user.id, text)
        return

    # Check if already sent the prompt (_address_sent=True) — this is the user's address
    if data.get("_address_sent") and not data.get("chose_new_address"):
        await state.update_data(
            address=message.text,
            _address_sent=False
        )
        await state.set_state(CustomBouquetForm.waiting_for_phone)
        # Get previous phones for user
        internal_user = None
        result = await db_session.execute(select(User).where(User.telegram_id == user.telegram_id))
        internal_user = result.scalar_one_or_none()
        if internal_user:
            prev_phones = await _get_prev_phones(db_session, internal_user.id)
            if prev_phones:
                await state.update_data(prev_phones=prev_phones)
                text = "📞 Выберите номер или введите новый:"
                keyboard = get_phone_history_keyboard(prev_phones, prefix="custom_")
                await message.answer(text, reply_markup=keyboard)
                await _save_outgoing(user.id, text, keyboard)
            else:
                text = "📞 Введите номер телефона для связи:\n\nНапример: +7 (996) 041-22-27"
                await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
                await _save_outgoing(user.id, text)
        return

    # Should not reach here — _address_sent is always True when entering waiting_for_address
    # Fallback: treat as address input
    await state.update_data(
        address=message.text,
        _address_sent=False
    )
    await state.set_state(CustomBouquetForm.waiting_for_phone)
    internal_user = None
    result = await db_session.execute(select(User).where(User.telegram_id == user.telegram_id))
    internal_user = result.scalar_one_or_none()
    if internal_user:
        prev_phones = await _get_prev_phones(db_session, internal_user.id)
        if prev_phones:
            await state.update_data(prev_phones=prev_phones)
            text = "📞 Выберите номер или введите новый:"
            keyboard = get_phone_history_keyboard(prev_phones, prefix="custom_")
            await message.answer(text, reply_markup=keyboard)
            await _save_outgoing(user.id, text, keyboard)
        else:
            text = "📞 Введите номер телефона для связи:\n\nНапример: +7 (996) 041-22-27"
            await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
            await _save_outgoing(user.id, text)


@custom_bouquet_router.callback_query(F.data.contains('custom_addr'))
async def cb_custom_address(callback: CallbackQuery, state: FSMContext, db_session, user):
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
            await state.set_state(CustomBouquetForm.waiting_for_phone)
            # Get previous phones for user
            result = await db_session.execute(select(User).where(User.telegram_id == callback.from_user.id))
            internal_user = result.scalar_one_or_none()
            prev_phones = []
            if internal_user:
                prev_phones = await _get_prev_phones(db_session, internal_user.id)
            if prev_phones:
                await state.update_data(prev_phones=prev_phones)
                text = "📞 Выберите номер или введите новый:"
                keyboard = get_phone_history_keyboard(prev_phones, prefix="custom_")
                await callback.message.answer(text, reply_markup=keyboard)
                await _save_outgoing(user.id, text, keyboard)
            else:
                text = "📞 Введите номер телефона для связи:\n\nНапример: +7 (996) 041-22-27"
                await callback.message.answer(text, reply_markup=get_custom_bouquet_keyboard())
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


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext, db_session, user):
    # Cancel on menu buttons
    if message.text in _MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return

    data = await state.get_data()

    # Guard against duplicate messages
    if data.get("_phone_sent"):
        return
    await state.update_data(_phone_sent=True)

    # Check if user chose to enter new phone
    if data.get("chose_new_phone"):
        await state.update_data(
            phone=message.text.strip(),
            chose_new_phone=False,
        )
        await state.set_state(CustomBouquetForm.waiting_for_comment)
        text = "💬 Добавьте комментарий к заказу (необязательно):\n\nНапример: позвонить за час, код домофона 123"
        await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
        await _save_outgoing(user.id, text)
        return

    # User typed a phone number manually
    phone = message.text.strip()
    await state.update_data(phone=phone)
    await state.set_state(CustomBouquetForm.waiting_for_comment)
    text = "💬 Добавьте комментарий к заказу (необязательно):\n\nНапример: позвонить за час, код домофона 123"
    await message.answer(text, reply_markup=get_custom_bouquet_keyboard())
    await _save_outgoing(user.id, text)


@custom_bouquet_router.callback_query(F.data.contains('custom_phone'))
async def cb_custom_phone(callback: CallbackQuery, state: FSMContext, db_session, user):
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
            await state.set_state(CustomBouquetForm.waiting_for_comment)
            text = "💬 Добавьте комментарий к заказу (необязательно):\n\nНапример: позвонить за час, код домофона 123"
            await callback.message.answer(text, reply_markup=get_custom_bouquet_keyboard())
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


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext, db_session, user, bot: Bot):
    # Cancel on menu buttons
    if message.text in _MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        await _save_outgoing(user.id, "❌ Отменено.")
        return

    data = await state.get_data()
    description = data.get("description")
    budget = data.get("budget")
    delivery_date = data.get("delivery_date")
    time_str = data.get("time")
    address = data.get("address")
    phone = data.get("phone")
    comment = message.text if message.text and message.text.lower() != "готово" else ""

    # Find internal user ID
    result = await db_session.execute(select(User).where(User.telegram_id == user.telegram_id))
    internal_user = result.scalar_one_or_none()
    user_id = internal_user.id if internal_user else 0

    # Build comment with budget info
    budget_comment = f"Бюджет: {budget}" if budget else ""
    if comment and budget_comment:
        full_comment = f"{budget_comment}\n{comment}"
    elif comment:
        full_comment = comment
    elif budget_comment:
        full_comment = budget_comment
    else:
        full_comment = ""

    # Parse delivery time
    delivery_time = None
    if time_str:
        try:
            if ":" in time_str:
                hour, minute = map(int, time_str.split(":"))
                delivery_time = time(hour, minute)
        except (ValueError, IndexError):
            pass

    order = Order(
        user_id=user_id,
        status="new",
        total_price=0.0,
        delivery_address=address,
        delivery_date=delivery_date,
        delivery_time=delivery_time,
        phone=phone,
        comment=full_comment,
        is_custom=True,
        custom_description=description,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    await state.clear()

    # Notify admin
    try:
        await notify_admin(bot, order, is_custom=True)
    except Exception as e:
        logger.error(f"Failed to notify about custom order #{order.id}: {e}")

    delivery_date_str = data.get("delivery_date_str", "") or "не указана"
    time_str_display = time_str if time_str else "не указано"
    budget_str = budget if budget else "не указан"

    final_text = (
        f"✅ Ваша заявка на индивидуальный букет принята!\n\n"
        f"📝 Заказ #{order.id}\n\n"
        f"📝 Описание: {description}\n"
        f"💰 Бюджет: {budget_str}\n"
        f"📅 Желаемая дата: {delivery_date_str}\n"
        f"🕐 Время: {time_str_display}\n"
        f"📍 Адрес: {address}\n"
        f"📞 Телефон: {phone}\n"
        f"💬 Комментарий: {comment or '—'}\n\n"
        f"🌸 Мы свяжемся с вами для обсуждения деталей и подтверждения стоимости."
    )
    await message.answer(final_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    await _save_outgoing(user.id, final_text, get_main_keyboard())
