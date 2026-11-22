from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.keyboards import pack_cb, unpack_cb, get_categories_keyboard, get_products_keyboard, get_product_detail_keyboard, get_main_keyboard
from bot.models import Category, Product, Message as BotMessage, User
from bot.states import NavigationState, CustomBouquetForm
from bot.handlers.navigation import (
    push_navigation,
    pop_navigation,
    clear_navigation,
    get_navigation_stack,
    get_cart_back_context,
    SCREEN_MAIN_MENU,
    SCREEN_CATEGORIES,
    SCREEN_PRODUCTS,
    SCREEN_PRODUCT,
)
from bot.utils.logger import logger
from bot.database import async_session_factory
import os


async def save_outgoing(user_id, text, keyboard=None):
    """Save an outgoing message sent by the bot."""
    try:
        async with async_session_factory() as session:
            from bot.utils.message_saver import save_outgoing_with_keyboard
            await save_outgoing_with_keyboard(session, user_id, text, keyboard)
    except Exception as e:
        logger.error(f"Error saving outgoing message: {e}")


async def _get_categories_with_available_products(db_session):
    """Get active categories that have at least one active product with quantity > 0."""
    subquery = (
        select(Product)
        .where(
            Product.category_id == Category.id,
            Product.is_active == True,
            Product.quantity > 0,
        )
        .limit(1)
        .exists()
    )
    result = await db_session.execute(
        select(Category).where(Category.is_active == True, subquery).order_by(Category.sort_order, Category.id)
    )
    return result.scalars().all()

# Path to uploads directory
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "admin_web", "static", "uploads")


def get_image_path(image_url: str) -> str | None:
    """Convert image URL to local file path"""
    if not image_url:
        return None
    # Extract filename from URL like /static/uploads/filename.ext
    filename = image_url.split("/")[-1]
    return os.path.join(UPLOAD_DIR, filename)

catalog_router = Router()


@catalog_router.message(F.text == "🌸 Каталог")
async def msg_catalog(message: Message, state: FSMContext, db_session):
    try:
        # Get user from db_session (set by TrackingMiddleware)
        user_result = await db_session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id, first_name=message.from_user.first_name, username=message.from_user.username)
            db_session.add(user)
            await db_session.commit()

        categories = await _get_categories_with_available_products(db_session)

        if not categories:
            text = "🌸 Каталог пока пуст. Загляните позже!"
            await save_outgoing(user.id, text)
            await message.answer(text)
            return

        # Инициализируем стек навигации при первом входе в каталог
        stack = await get_navigation_stack(state)
        if not stack:
            await state.update_data(
                navigation_stack=[{
                    "screen": SCREEN_CATEGORIES,
                    "cat_id": 0,
                    "product_id": 0,
                }]
            )
            logger.info(f"DEBUG catalog: initialized stack with categories")
        await push_navigation(state, SCREEN_CATEGORIES)
        text2 = "🌸 Выберите категорию:"
        keyboard = get_categories_keyboard(categories)
        await save_outgoing(user.id, text2, keyboard)
        await message.answer(text2, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in msg_catalog: {e}")
        text_err = "❌ Произошла ошибка при загрузке каталога."
        await save_outgoing(user.id, text_err)
        await message.answer(text_err)


@catalog_router.callback_query(F.data.startswith('{"t":"cat"'))
async def cb_handle_catalog(callback: CallbackQuery, bot: Bot, db_session, state: FSMContext):
    data = unpack_cb(callback.data)
    action = data.get("action")

    if action == "view":
        cat_id = int(data["id"])
        result = await db_session.execute(select(Category).where(Category.id == cat_id))
        category = result.scalar_one_or_none()

        if not category:
            await callback.answer("Категория не найдена")
            return

        result = await db_session.execute(
            select(Product).options(selectinload(Product.images)).where(Product.category_id == cat_id, Product.is_active == True, Product.quantity > 0).order_by(Product.id)
        )
        products = result.scalars().all()

        if not products:
            await callback.answer("В этой категории пока нет товаров")
            await callback.message.answer("🌸 В этой категории пока нет товаров.")
            await save_outgoing(user.id, "🌸 В этой категории пока нет товаров.")
            return

        user = callback.from_user
        async with async_session_factory() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == user.id))
            internal_user = user_result.scalar_one_or_none()
            if internal_user:
                products_kb = get_products_keyboard(products, cat_id=cat_id)
                cat_text = f"🌸 {category.name}\n\nВыберите букет:"
                await save_outgoing(internal_user.id, cat_text, products_kb)

        await push_navigation(state, SCREEN_PRODUCTS, cat_id=cat_id)

        products_kb = get_products_keyboard(products, cat_id=cat_id)
        cat_text = f"🌸 {category.name}\n\nВыберите букет:"
        if category.image_url:
            cat_image_path = get_image_path(category.image_url)
            if cat_image_path and os.path.exists(cat_image_path):
                try:
                    await bot.send_photo(
                        callback.message.chat.id,
                        FSInputFile(cat_image_path),
                        caption=cat_text,
                        reply_markup=products_kb,
                    )
                except (TelegramForbiddenError, Exception):
                    await callback.message.edit_text(
                        cat_text,
                        reply_markup=products_kb,
                    )
            else:
                await callback.message.edit_text(
                    cat_text,
                    reply_markup=products_kb,
                )
        else:
            await callback.message.edit_text(
                cat_text,
                reply_markup=products_kb,
            )

        await callback.answer()



@catalog_router.callback_query(F.data.startswith('{"t":"back"'))
async def cb_handle_back(callback: CallbackQuery, bot: Bot, db_session, state: FSMContext):
    data = unpack_cb(callback.data)
    # pack_cb использует сокращённые ключи: "s" вместо "screen", "cid" вместо "cat_id"
    screen_type = data.get("s", data.get("screen", ""))

    # Если кнопка "Назад" из корзины — используем сохранённый контекст
    if screen_type == "cart":
        back_to = data.get("back_to", "main")
        if back_to == "catalog":
            cart_ctx = await get_cart_back_context(state)
            if cart_ctx["cat_id"] > 0:
                await restore_category_products(callback, bot, db_session, state, cart_ctx["cat_id"])
                await callback.answer()
                return
        # Fallback — главное меню
        await callback.message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())
        await callback.answer()
        return

    # Если пользователь в состоянии CustomBouquetForm — очищаем его
    fsm_data = await state.get_data()
    screen = fsm_data.get("screen", "")
    if screen in (CustomBouquetForm.waiting_for_description.state,
                  CustomBouquetForm.waiting_for_budget.state,
                  CustomBouquetForm.waiting_for_delivery_date.state,
                  CustomBouquetForm.waiting_for_address.state,
                  CustomBouquetForm.waiting_for_phone.state,
                  CustomBouquetForm.waiting_for_comment.state):
        await state.clear()
        back_context = data.get("back_context", "main")
        cat_id = int(data.get("cid", data.get("cat_id", 0)))
        if back_context == "catalog" and cat_id > 0:
            await restore_category_products(callback, bot, db_session, state, cat_id)
            await callback.answer()
            return
        await callback.message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())
        await callback.answer()
        return

    # Для каталога — используем стек навигации
    prev = await pop_navigation(state)

    if prev is None:
        # Стек пуст — в главное меню
        main_kb = get_main_keyboard()
        await callback.message.answer("🌸 Выберите раздел:", reply_markup=main_kb)
        await callback.answer()
        return

    prev_screen = prev.get("screen", SCREEN_MAIN_MENU)
    prev_cat_id = prev.get("cat_id", 0)

    if prev_screen == SCREEN_PRODUCTS and prev_cat_id > 0:
        await restore_category_products(callback, bot, db_session, state, prev_cat_id)
    elif prev_screen == SCREEN_CATEGORIES:
        categories = await _get_categories_with_available_products(db_session)
        if categories:
            cats_kb = get_categories_keyboard(categories)
            await callback.message.edit_text("🌸 Выберите категорию:", reply_markup=cats_kb)
        else:
            await callback.message.edit_text("🌸 Каталог пока пуст.")
    else:
        main_kb = get_main_keyboard()
        await callback.message.answer("🌸 Выберите раздел:", reply_markup=main_kb)

    await callback.answer()


async def restore_category_products(callback: CallbackQuery, bot: Bot, db_session, state: FSMContext, cat_id: int):
    """Restore the products list for a category (used by back navigation)."""
    result = await db_session.execute(
        select(Product).options(selectinload(Product.images)).where(
            Product.category_id == cat_id, Product.is_active == True, Product.quantity > 0
        ).order_by(Product.id)
    )
    products = result.scalars().all()
    if not products:
        await callback.answer("В этой категории пока нет товаров")
        return

    result = await db_session.execute(select(Category).where(Category.id == cat_id))
    category = result.scalar_one_or_none()
    if not category:
        await callback.answer("Категория не найдена")
        return

    await state.set_state(NavigationState.set)
    await state.update_data(screen=SCREEN_PRODUCTS, cat_id=cat_id)

    # Save message with keyboard
    user = callback.from_user
    async with async_session_factory() as session:
        user_result = await session.execute(select(User).where(User.telegram_id == user.id))
        internal_user = user_result.scalar_one_or_none()
        if internal_user:
            products_kb = get_products_keyboard(products, cat_id=cat_id)
            caption = f"🌸 {category.name}\n\nВыберите букет:"
            await save_outgoing(internal_user.id, caption, products_kb)

    await callback.message.delete()
    caption = f"🌸 {category.name}\n\nВыберите букет:"
    if category.image_url:
        cat_image_path = get_image_path(category.image_url)
        if cat_image_path and os.path.exists(cat_image_path):
            try:
                await bot.send_photo(
                    callback.message.chat.id,
                    FSInputFile(cat_image_path),
                    caption=caption,
                    reply_markup=get_products_keyboard(products, cat_id=cat_id),
                )
            except (TelegramForbiddenError, Exception):
                await bot.send_message(callback.message.chat.id, caption, reply_markup=get_products_keyboard(products, cat_id=cat_id))
        else:
            await bot.send_message(callback.message.chat.id, caption, reply_markup=get_products_keyboard(products, cat_id=cat_id))
    else:
        await bot.send_message(callback.message.chat.id, caption, reply_markup=get_products_keyboard(products, cat_id=cat_id))


@catalog_router.callback_query(F.data.startswith('{"t":"prod"'))
async def cb_handle_product(callback: CallbackQuery, bot: Bot, db_session, state: FSMContext):
    data = unpack_cb(callback.data)
    action = data.get("action")

    if action == "view":
        prod_id = int(data["id"])
        cat_id = int(data.get("cat_id", 0))
        result = await db_session.execute(select(Product).options(selectinload(Product.images)).where(Product.id == prod_id, Product.quantity > 0))
        product = result.scalar_one_or_none()

        if not product:
            await callback.answer("Товар не найден")
            return

        text = (
            f"🌹 {product.name}\n\n"
            f"💰 Цена: {product.price:.0f} ₽\n\n"
            f"📦 В наличии: {product.quantity} шт.\n\n"
            f"📝 {product.description}"
        )
        if product.composition:
            text += f"\n\n🌿 Состав:\n{product.composition}"

        keyboard = get_product_detail_keyboard(product, cat_id=cat_id)

        # Save message with keyboard
        user = callback.from_user
        async with async_session_factory() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == user.id))
            internal_user = user_result.scalar_one_or_none()
            if internal_user:
                await save_outgoing(internal_user.id, text, keyboard)

        await push_navigation(state, SCREEN_PRODUCT, cat_id=cat_id, product_id=prod_id)

        # Загружаем все фотографии товара
        if product.images:
            media_group = []
            seen_urls = set()
            for i, img in enumerate(product.images):
                # Skip duplicates
                if img.image_url in seen_urls:
                    continue
                seen_urls.add(img.image_url)
                
                img_path = get_image_path(img.image_url)
                if img_path and os.path.exists(img_path):
                    photo = FSInputFile(img_path)
                    # Все фото без caption, caption отправим отдельным сообщением с кнопками
                    media_group.append({
                        'type': 'photo',
                        'media': photo,
                    })
                    logger.info(f"Added product photo: {img_path}")
                else:
                    logger.warning(f"Photo file not found: {img_path} for URL: {img.image_url}")

            if media_group:
                try:
                    logger.info(f"Sending {len(media_group)} photos for product {product.name}")
                    await bot.send_media_group(
                        callback.message.chat.id,
                        media_group,
                    )
                    # Отправляем описание товара с кнопками "В корзину" и "Назад"
                    await callback.message.answer(text, reply_markup=keyboard)
                    await callback.answer()
                    return
                except Exception as e:
                    logger.error(f"send_media_group error: {e}")
                    pass
            else:
                logger.warning(f"No valid photos found for product {product.name}")

        # Если нет фото или ошибка - отправляем текстовое сообщение
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest:
            await callback.message.answer(text, reply_markup=keyboard)

        await callback.answer()


