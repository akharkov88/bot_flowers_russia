import json

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select

from bot.keyboards import pack_cb, unpack_cb, get_cart_keyboard, get_main_keyboard, get_address_history_keyboard
from bot.models import Product, Cart, User, Order
from bot.states import OrderForm
from bot.handlers.navigation import save_cart_back_context, get_cart_back_context
from bot.utils.logger import logger
from bot.utils.message_saver import save_outgoing_with_keyboard
from bot.database import async_session_factory


async def _save_outgoing(user_id, text, keyboard=None):
    """Save an outgoing message sent by the bot."""
    try:
        async with async_session_factory() as session:
            await save_outgoing_with_keyboard(session, user_id, text, keyboard)
    except Exception as e:
        logger.error(f"Error saving outgoing message: {e}")

cart_router = Router()


async def get_or_create_cart(session, user_id: int, telegram_id: int):
    """Get existing active cart or create new one"""
    result = await session.execute(
        select(Cart).where(
            Cart.user_id == user_id,
            Cart.status == "active"
        ).order_by(Cart.updated_at.desc())
    )
    carts = result.scalars().all()

    if not carts:
        cart = Cart(
            user_id=user_id,
            telegram_id=telegram_id,
            data="{}",
            total_price=0.0,
            status="active",
        )
        session.add(cart)
        await session.commit()
        await session.refresh(cart)
        return cart

    # Merge duplicate carts into the most recent one
    primary = carts[0]
    if len(carts) > 1:
        for duplicate in carts[1:]:
            dup_data = json.loads(duplicate.data) if duplicate.data else {}
            merged = {**(json.loads(primary.data) if primary.data else {}), **dup_data}
            primary.data = json.dumps(merged, ensure_ascii=False)
            duplicate.status = "merged"
            await session.commit()

    return primary


async def recalculate_cart(session, cart):
    """Recalculate total price from cart data"""
    cart_data = json.loads(cart.data) if cart.data else {}
    total = 0.0
    for prod_id_str, qty in cart_data.items():
        pid = int(prod_id_str)
        result = await session.execute(select(Product).where(Product.id == pid))
        product = result.scalar_one_or_none()
        if product:
            total += product.price * qty
    cart.total_price = total
    await session.commit()


async def refresh_cart_message(callback: CallbackQuery, db_session, cart: dict):
    """Update the cart message with current cart data"""
    if not cart:
        # Отправляем новое сообщение с reply-клавиатурой
        await callback.message.answer(
            "🛒 Ваша корзина пуста.\n\nДобавьте что-нибудь из каталога!",
            reply_markup=get_main_keyboard(),
        )
        return

    total = 0
    lines = ["🛒 Ваша корзина:\n"]
    cart_for_kb = []
    for prod_id_str, qty in cart.items():
        pid = int(prod_id_str)
        result = await db_session.execute(select(Product).where(Product.id == pid))
        p = result.scalar_one_or_none()
        if p:
            line_total = p.price * qty
            total += line_total
            lines.append(f"  🌹 {p.name} x{qty} — {line_total:.0f} ₽")
            cart_for_kb.append({"product": p, "qty": qty})

    lines.append(f"\n💰 Итого: {total:.0f} ₽\n\nВыберите действие:")
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=get_cart_keyboard(cart_for_kb, total))
    except TelegramBadRequest:
        pass


@cart_router.message(F.text == "🛒 Корзина")
async def msg_cart(message: Message, state: FSMContext, db_session):
    # Load cart from DB
    result = await db_session.execute(select(User).where(User.telegram_id == message.from_user.id))
    user = result.scalar_one_or_none()
    if not user:
        await message.answer("Пользователь не найден")
        return

    db_cart = await get_or_create_cart(db_session, user.id, message.from_user.id)
    cart = json.loads(db_cart.data) if db_cart.data else {}

    # Also sync FSM state
    await state.update_data(cart=cart)

    # Save navigation context for back button
    await save_cart_back_context(state)

    if not cart:
        await message.answer("🛒 Ваша корзина пуста.\n\nДобавьте что-нибудь из каталога!", reply_markup=get_main_keyboard())
        return

    total = 0
    lines = ["🛒 Ваша корзина:\n"]
    cart_for_kb = []
    for prod_id_str, qty in cart.items():
        prod_id = int(prod_id_str)
        result = await db_session.execute(select(Product).where(Product.id == prod_id))
        product = result.scalar_one_or_none()
        if product:
            line_total = product.price * qty
            total += line_total
            lines.append(f"  🌹 {product.name} x{qty} — {line_total:.0f} ₽")
            cart_for_kb.append({"product": product, "qty": qty})

    lines.append(f"\n💰 Итого: {total:.0f} ₽\n\nВыберите действие:")
    await message.answer("\n".join(lines), reply_markup=get_cart_keyboard(cart_for_kb, total))


@cart_router.callback_query(lambda c: c.data and '"t":"cart"' in c.data)
async def cb_cart_action(callback: CallbackQuery, bot: Bot, state: FSMContext, db_session):
    data = unpack_cb(callback.data)
    action = data.get("action")

    # Only handle cart-specific actions; let other handlers process cart callbacks
    if action not in ("add", "plus", "minus", "checkout"):
        return

    if action == "add":
        prod_id = int(data["product_id"])
        result = await db_session.execute(select(Product).where(Product.id == prod_id))
        product = result.scalar_one_or_none()

        if not product:
            await callback.answer("Товар не найден")
            return

        if product.quantity <= 0:
            await callback.answer("❌ Товар закончился!")
            return

        # Get or create user
        result = await db_session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        # Get or create cart
        db_cart = await get_or_create_cart(db_session, user.id, callback.from_user.id)
        cart = json.loads(db_cart.data) if db_cart.data else {}
        cart[str(prod_id)] = cart.get(str(prod_id), 0) + 1
        if cart[str(prod_id)] > product.quantity:
            cart[str(prod_id)] -= 1
            await callback.answer(f"❌ В наличии только {product.quantity} шт!")
            db_cart.data = json.dumps(cart)
            await recalculate_cart(db_session, db_cart)
            await state.update_data(cart=cart)
            return
        db_cart.data = json.dumps(cart)
        await recalculate_cart(db_session, db_cart)

        # Sync FSM state
        await state.update_data(cart=cart)

        # Save navigation context for back button
        await save_cart_back_context(state)

        await callback.answer(f"✅ {product.name} добавлен в корзину!")

        # Обновить корзину с кнопками +/-
        total = 0
        lines = ["🛒 Ваша корзина:\n"]
        cart_for_kb = []
        for prod_id_str, qty in cart.items():
            pid = int(prod_id_str)
            result = await db_session.execute(select(Product).where(Product.id == pid))
            p = result.scalar_one_or_none()
            if p:
                line_total = p.price * qty
                total += line_total
                lines.append(f"  🌹 {p.name} x{qty} — {line_total:.0f} ₽")
                cart_for_kb.append({"product": p, "qty": qty})

        lines.append(f"\n💰 Итого: {total:.0f} ₽\n\nВыберите действие:")
        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=get_cart_keyboard(cart_for_kb, total, back_to="catalog"))
        except TelegramBadRequest:
            await callback.message.answer("\n".join(lines), reply_markup=get_cart_keyboard(cart_for_kb, total, back_to="catalog"))

    elif action == "plus":
        prod_id = str(data["product_id"])
        # Get user and cart from DB
        result = await db_session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            return
        db_cart = await get_or_create_cart(db_session, user.id, callback.from_user.id)
        cart = json.loads(db_cart.data) if db_cart.data else {}
        
        # Check stock before incrementing
        pid = int(prod_id)
        prod_result = await db_session.execute(select(Product).where(Product.id == pid))
        p = prod_result.scalar_one_or_none()
        if p and cart.get(prod_id, 0) + 1 > p.quantity:
            await callback.answer(f"❌ В наличии только {p.quantity} шт!")
            return
        
        cart[prod_id] = cart.get(prod_id, 0) + 1
        db_cart.data = json.dumps(cart)
        await recalculate_cart(db_session, db_cart)
        await state.update_data(cart=cart)
        await callback.answer()
        await refresh_cart_message(callback, db_session, cart)

    elif action == "minus":
        prod_id = str(data["product_id"])
        # Get user and cart from DB
        result = await db_session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            return
        db_cart = await get_or_create_cart(db_session, user.id, callback.from_user.id)
        cart = json.loads(db_cart.data) if db_cart.data else {}
        current = cart.get(prod_id, 1)
        if current > 1:
            cart[prod_id] = current - 1
        else:
            cart.pop(prod_id, None)
        db_cart.data = json.dumps(cart)
        await recalculate_cart(db_session, db_cart)
        await state.update_data(cart=cart)
        await callback.answer()
        await refresh_cart_message(callback, db_session, cart)

    elif action == "checkout":


        # Get user and cart from DB
        result = await db_session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        db_cart = await get_or_create_cart(db_session, user.id, callback.from_user.id)
        cart = json.loads(db_cart.data) if db_cart.data else {}

        if not cart:
            await callback.answer("Корзина пуста!")
            return

        # Get previous addresses to decide which message to show
        prev_addresses_result = await db_session.execute(
            select(Order.delivery_address)
            .where(Order.user_id == user.id, Order.delivery_address.isnot(None), Order.delivery_address != "")
            .order_by(Order.id.desc())
        )
        addresses = [row[0] for row in prev_addresses_result.all() if row[0]]
        # Deduplicate preserving order
        seen = set()
        unique = []
        for addr in addresses:
            if addr not in seen:
                seen.add(addr)
                unique.append(addr)
        prev_addresses = unique[:5]

        await state.set_state(OrderForm.waiting_for_address)
        await state.update_data(prev_addresses=prev_addresses, cart=cart, _address_sent=True)

        if prev_addresses:
            text = "📍 Выберите адрес или введите новый:"
            keyboard = get_address_history_keyboard(prev_addresses)
            try:
                await callback.message.edit_text(text, reply_markup=keyboard)
            except TelegramBadRequest:
                await callback.message.answer(text, reply_markup=keyboard)
            await _save_outgoing(user.id, text, keyboard)
        else:
            text = "📍 Введите адрес доставки:\n\nНапример: г. Нижний Новгород, ул. Белинского, д. 10, кв. 5"
            try:
                await callback.message.edit_text(text)
            except TelegramBadRequest:
                await callback.message.answer(text)
            await _save_outgoing(user.id, text)


# NOTE: "Назад" из корзины обрабатывается через cart_back_context в catalog_router.cb_handle_back
# Не добавляем отдельный handler для back в cart_router — это блокирует catalog_router
