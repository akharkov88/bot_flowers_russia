import os
import re
from datetime import date

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.handlers.admin import notify_admin
from bot.keyboards import get_main_keyboard, get_custom_bouquet_keyboard, pack_cb, unpack_cb
from bot.models import Order, User
from bot.states import CustomBouquetForm, NavigationState
from bot.utils.logger import logger

custom_bouquet_router = Router()


@custom_bouquet_router.message(F.text.contains("Хочу букет"))
async def cmd_custom_bouquet(message: Message, state: FSMContext, db_session):
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
    await message.answer(
        "🌸 Опишите желаемый букет:\n\n"
        "Напишите всё, что хотите: цвета, размеры, настроение, повод.\n"
        "Например: 'Большой букет из розовых и белых пионов, нежный, для свадьбы'.",
        reply_markup=keyboard
    )


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
async def process_description(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    description = message.text.strip()
    if len(description) < 10:
        await message.answer(
            "⚠️ Описание слишком короткое. Пожалуйста, опишите букет подробнее.\n\n"
            "Минимум 10 символов.",
            reply_markup=get_custom_bouquet_keyboard()
        )
        return

    await state.update_data(description=description)
    await state.set_state(CustomBouquetForm.waiting_for_budget)
    await message.answer(
        "💰 Укажите желаемый бюджет (необязательно).\n\n"
        "Например: 1500-3000",
        reply_markup=get_custom_bouquet_keyboard()
    )


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_budget)
async def process_budget(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    if message.text and message.text.lower() == "пропустить":
        budget = None
    else:
        budget = message.text.strip()

    await state.update_data(budget=budget)
    await state.set_state(CustomBouquetForm.waiting_for_delivery_date)
    await message.answer(
        "📅 Укажите желаемую дату доставки (необязательно).\n\n"
        "Формат: ДД.ММ.ГГГГ, ДД.ММ.ГГ или ДД.ММ, например: 20.11.2026, 20.11.26, 20.11",
        reply_markup=get_custom_bouquet_keyboard()
    )


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_delivery_date)
async def process_delivery_date(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    if message.text and message.text.lower() == "пропустить":
        delivery_date = None
        delivery_date_str = None
    else:
        date_str = message.text.strip()
        if not re.match(r"^\d{2}\.\d{2}(\.\d{2,4})?$", date_str):
            await message.answer(
                "⚠️ Неверный формат даты.\n\n"
                "Формат: ДД.ММ.ГГГГ или ДД.ММ.ГГ или ДД.ММ, например: 20.11.2026, 20.11.26, 20.11",
                reply_markup=get_custom_bouquet_keyboard()
            )
            return
        try:
            parts = date_str.split(".")
            day, month = int(parts[0]), int(parts[1])
            year = int(parts[2]) if len(parts) == 3 else None
            if year and year < 100:
                year += 2000
            delivery_date = date(year or 2000, month, day)  # dummy year for DB
            delivery_date_str = date_str
        except ValueError:
            await message.answer("⚠️ Такая дата не существует. Проверьте день и месяц.", reply_markup=get_custom_bouquet_keyboard())
            return

    await state.update_data(delivery_date=delivery_date, delivery_date_str=delivery_date_str)
    await state.set_state(CustomBouquetForm.waiting_for_time)
    await message.answer(
        "🕐 Введите время доставки в формате ЧЧ:ММ:\n\n"
        "Например: 14:00",
        reply_markup=get_custom_bouquet_keyboard()
    )


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    if message.text and message.text.lower() == "пропустить":
        time_str = None
    else:
        time_str = message.text.strip()

    await state.update_data(time=time_str)
    await state.set_state(CustomBouquetForm.waiting_for_address)
    await message.answer(
        "📍 Введите адрес доставки:\n\n"
        "Например: г. Нижний Новгород, ул. Белинского, д. 10, кв. 5",
        reply_markup=get_custom_bouquet_keyboard()
    )


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    await state.update_data(address=message.text)
    await state.set_state(CustomBouquetForm.waiting_for_phone)
    await message.answer(
        "📞 Введите номер телефона для связи:\n\n"
        "Например: +7 (996) 041-22-27",
        reply_markup=get_custom_bouquet_keyboard()
    )


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
        return

    phone = message.text.strip()
    if not re.match(r"^[\+]?[\d\s\-\(\)]{7,20}$", phone):
        await message.answer("⚠️ Неверный формат телефона. Введите номер ещё раз.", reply_markup=get_custom_bouquet_keyboard())
        return

    await state.update_data(phone=phone)
    await state.set_state(CustomBouquetForm.waiting_for_comment)
    await message.answer(
        "💬 Добавьте комментарий к заказу (необязательно):\n\n"
        "Например: позвонить за час, код домофона 123",
        reply_markup=get_custom_bouquet_keyboard()
    )


@custom_bouquet_router.message(CustomBouquetForm.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext, db_session, user, bot: Bot):
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard())
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

    order = Order(
        user_id=user_id,
        status="new",
        total_price=0.0,
        delivery_address=address,
        delivery_date=delivery_date,
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

    await message.answer(
        f"✅ Ваша заявка на индивидуальный букет принята!\n\n"
        f"📝 Заказ #{order.id}\n\n"
        f"📝 Описание: {description}\n"
        f"💰 Бюджет: {budget_str}\n"
        f"📅 Желаемая дата: {delivery_date_str}\n"
        f"🕐 Время: {time_str_display}\n"
        f"📍 Адрес: {address}\n"
        f"📞 Телефон: {phone}\n"
        f"💬 Комментарий: {comment or '—'}\n\n"
        f"🌸 Мы свяжемся с вами для обсуждения деталей и подтверждения стоимости.",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
