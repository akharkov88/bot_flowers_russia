from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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
    peek_previous_navigation,
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


PRODUCTS_PER_PAGE = 3


async def _get_all_active_products(db_session):
    """Get all active products with quantity > 0, eager loading images."""
    result = await db_session.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.is_active == True, Product.quantity > 0)
        .order_by(Product.category_id, Product.id)
    )
    return result.scalars().all()


async def _send_product_photo(bot, chat_id, product, button_type="inline"):
    """Send a single product photo with appropriate button."""
    primary_image = None
    if product.images:
        primary_image = product.images[0]
    elif product.image_url:
        primary_image = type('Image', (), {'image_url': product.image_url})()

    caption = f"{product.name} — {product.price:.0f} ₽"

    if primary_image:
        img_path = get_image_path(primary_image.image_url)
        if img_path and os.path.exists(img_path):
            if button_type == "inline":
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔍 Подробнее",
                        callback_data=pack_cb(type="prod", action="view", id=product.id, cat_id=0)
                    )]
                ])
            else:
                keyboard = ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="🔍 Подробнее")]],
                    resize_keyboard=True,
                )
            try:
                await bot.send_photo(
                    chat_id,
                    FSInputFile(img_path),
                    caption=caption,
                    reply_markup=keyboard,
                )
                logger.info(f"Sent product photo: {product.name}")
                return True
            except Exception as e:
                logger.error(f"Error sending photo for {product.name}: {e}")

    # Fallback: send text message
    if button_type == "inline":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔍 Подробнее",
                callback_data=pack_cb(type="prod", action="view", id=product.id, cat_id=0)
            )]
        ])
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔍 Подробнее")]],
            resize_keyboard=True,
        )
    await bot.send_message(chat_id, caption, reply_markup=keyboard)
    return True


@catalog_router.message(F.text == "🌸 Все товары")
async def msg_all_products(message: Message, state: FSMContext, db_session, bot: Bot):
    try:
        # Get user from db_session
        user_result = await db_session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id, first_name=message.from_user.first_name, username=message.from_user.username)
            db_session.add(user)
            await db_session.commit()

        products = await _get_all_active_products(db_session)

        if not products:
            text = "🌸 Каталог пока пуст. Загляните позже!"
            await save_outgoing(user.id, text)
            await message.answer(text)
            return

        # Store total count in state for pagination
        await state.update_data(all_products_total=len(products))
        await state.update_data(all_products_page=0)

        # Send first 3 products
        await _send_products_page(bot, message.chat.id, products, page=0, state=state, has_back_button=True)

        logger.info(f"Sent products page 0: {min(PRODUCTS_PER_PAGE, len(products))}/{len(products)} products")

    except Exception as e:
        logger.error(f"Error in msg_all_products: {e}")
        text_err = "❌ Произошла ошибка при загрузке каталога."
        user_result = await db_session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = user_result.scalar_one_or_none()
        if user:
            await save_outgoing(user.id, text_err)
        await message.answer(text_err)


async def _send_products_page(bot, chat_id, products, page: int, state: FSMContext, has_back_button: bool = False):
    """Send a page of products (3 per page)."""
    start = page * PRODUCTS_PER_PAGE
    end = start + PRODUCTS_PER_PAGE
    page_products = products[start:end]
    total = len(products)
    total_pages = (total + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE
    current_page = page + 1

    for i, product in enumerate(page_products):
        is_last = (i == len(page_products) - 1)
        primary_image = None
        if product.images:
            primary_image = product.images[0]
        elif product.image_url:
            primary_image = type('Image', (), {'image_url': product.image_url})()

        caption = f"{product.name} — {product.price:.0f} ₽"

        if primary_image:
            img_path = get_image_path(primary_image.image_url)
            if img_path and os.path.exists(img_path):
                # Build inline keyboard
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                # First row: "Подробнее"
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(
                        text="🔍 Подробнее",
                        callback_data=pack_cb(type="prod", action="view", id=product.id, cat_id=0)
                    )
                ])
                # If last product, add navigation buttons
                if is_last and has_back_button:
                    nav_row = []
                    if current_page < total_pages:
                        nav_row.append(InlineKeyboardButton(
                            text="➡️ Ещё",
                            callback_data=pack_cb(type="all_products", action="next", page=page)
                        ))
                    nav_row.append(InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data=pack_cb(type="all_products", action="back")
                    ))
                    keyboard.inline_keyboard.append(nav_row)

                try:
                    await bot.send_photo(
                        chat_id,
                        FSInputFile(img_path),
                        caption=caption,
                        reply_markup=keyboard,
                    )
                    logger.info(f"Sent product photo with keyboard: {product.name}")
                    if is_last:
                        await state.update_data(all_products_page=page)
                    continue
                except Exception as e:
                    logger.error(f"Error sending photo for {product.name}: {e}")

        # Fallback: send text message
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔍 Подробнее",
                callback_data=pack_cb(type="prod", action="view", id=product.id, cat_id=0)
            )]
        ])
        if is_last and has_back_button:
            nav_row = []
            if current_page < total_pages:
                nav_row.append(InlineKeyboardButton(
                    text="➡️ Ещё",
                    callback_data=pack_cb(type="all_products", action="next", page=page)
                ))
            nav_row.append(InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=pack_cb(type="all_products", action="back")
            ))
            keyboard.inline_keyboard.append(nav_row)

        await bot.send_message(chat_id, caption, reply_markup=keyboard)
        if is_last:
            await state.update_data(all_products_page=page)


@catalog_router.message(F.text == "➡️ Ещё")
async def msg_more_products(message: Message, state: FSMContext, db_session, bot: Bot):
    try:
        data = await state.get_data()
        current_page = data.get("all_products_page", 0)
        total = data.get("all_products_total", 0)
        next_page = current_page + 1
        total_pages = (total + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE

        if next_page >= total_pages:
            await message.answer("Это последняя страница")
            return

        products = await _get_all_active_products(db_session)
        await _send_products_page(bot, message.chat.id, products, page=next_page, state=state, has_back_button=True)
    except Exception as e:
        logger.error(f"Error in msg_more_products: {e}")
        await message.answer("❌ Произошла ошибка при загрузке товаров.")


@catalog_router.message(F.text == "⬅️ Назад")
async def msg_back_from_products(message: Message, state: FSMContext):
    try:
        await state.clear()
        await message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Error in msg_back_from_products: {e}")
        await message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())


@catalog_router.callback_query(F.data.startswith('{"t":"all_products"'))
async def cb_all_products_pagination(callback: CallbackQuery, bot: Bot, db_session, state: FSMContext):
    data = unpack_cb(callback.data)
    action = data.get("action")

    if action == "next":
        current_page = data.get("page", 0)
        total = (await state.get_data()).get("all_products_total", 0)
        next_page = current_page + 1
        total_pages = (total + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE

        if next_page >= total_pages:
            await callback.answer("Это последняя страница")
            return

        products = await _get_all_active_products(db_session)
        await _send_products_page(bot, callback.message.chat.id, products, page=next_page, state=state, has_back_button=True)
        await callback.answer(f"📦 Страница {next_page + 1}/{total_pages}")
        await callback.message.delete()
    elif action == "back":
        await callback.answer()
        await callback.message.delete()
        # Return to main menu
        await callback.message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())


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
            stack.append({
                "screen": SCREEN_CATEGORIES,
                "cat_id": 0,
                "product_id": 0,
            })
            await state.update_data(navigation_stack=stack)
            await state.update_data(screen=SCREEN_CATEGORIES, cat_id=0, product_id=0)
            logger.info(f"DEBUG catalog: initialized stack with categories, stack={stack}")
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

        logger.info(f"DEBUG cb_handle_catalog: BEFORE push, stack={await get_navigation_stack(state)}")
        await push_navigation(state, SCREEN_PRODUCTS, cat_id=cat_id)
        logger.info(f"DEBUG cb_handle_catalog: AFTER push, stack={await get_navigation_stack(state)}")

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
    logger.info(f"DEBUG cb_handle_back: data={callback.data}")
    # pack_cb использует сокращённые ключи: "s" вместо "screen", "cid" вместо "cat_id"
    screen_type = data.get("s", data.get("screen", ""))
    logger.info(f"DEBUG cb_handle_back: screen_type={screen_type}")

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

    # Для каталога — используем pop_navigation (удаляем текущий экран из стека)
    prev = await pop_navigation(state)
    stack = await get_navigation_stack(state)
    logger.info(f"DEBUG cb_handle_back: pop result={prev}, stack_after={stack}, callback_data={callback.data}")

    if prev is None:
        # Стек пуст или один экран — в главное меню
        # Используем answer, так как get_main_keyboard возвращает ReplyKeyboardMarkup
        await callback.message.answer("🌸 Выберите раздел:", reply_markup=get_main_keyboard())
        await callback.answer()
        return

    prev_screen = prev.get("screen", SCREEN_MAIN_MENU)
    prev_cat_id = prev.get("cat_id", 0)
    prev_product_id = prev.get("product_id", 0)

    if prev_screen == SCREEN_PRODUCTS and prev_cat_id > 0:
        # Возвращаемся к списку продуктов категории
        await restore_category_products(callback, bot, db_session, state, prev_cat_id)
    elif prev_screen == SCREEN_CATEGORIES:
        # Возвращаемся к списку категорий
        categories = await _get_categories_with_available_products(db_session)
        if categories:
            cats_kb = get_categories_keyboard(categories)
            await callback.message.edit_text("🌸 Выберите категорию:", reply_markup=cats_kb)
        else:
            await callback.message.edit_text("🌸 Каталог пока пуст.")
    elif prev_screen == SCREEN_PRODUCT and prev_product_id > 0:
        # Возвращаемся к предыдущему товару
        await restore_product_detail(callback, bot, db_session, state, prev_product_id, prev_cat_id)
    else:
        main_kb = get_main_keyboard()
        await callback.message.edit_text("🌸 Выберите раздел:", reply_markup=main_kb)

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


async def restore_product_detail(callback: CallbackQuery, bot: Bot, db_session, state: FSMContext, prod_id: int, cat_id: int):
    """Restore the product detail screen (used by back navigation)."""
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

    # Не добавляем в стек при восстановлении — мы уже нажали "Назад"
    await state.set_state(NavigationState.set)
    await state.update_data(screen=SCREEN_PRODUCT, cat_id=cat_id, product_id=prod_id)

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
                await callback.message.edit_text(text, reply_markup=keyboard)
                await callback.answer()
                return
            except Exception as e:
                logger.error(f"send_media_group error: {e}")
                pass
        else:
            logger.warning(f"No valid photos found for product {product.name}")

    # Если нет фото или ошибка - редактируем текстовое сообщение
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard)

    await callback.answer()


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

        logger.info(f"DEBUG cb_handle_product: BEFORE push, stack={await get_navigation_stack(state)}")
        await push_navigation(state, SCREEN_PRODUCT, cat_id=cat_id, product_id=prod_id)
        logger.info(f"DEBUG cb_handle_product: AFTER push, stack={await get_navigation_stack(state)}")

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


