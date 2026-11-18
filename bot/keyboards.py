import json
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def pack_cb(**kwargs) -> str:
    """Pack callback data as compact JSON string with short keys"""
    # Map short keys to long keys
    SHORT_KEYS = {'t': 'type', 'a': 'action', 'id': 'id', 'p': 'page', 'q': 'qty',
                  'pid': 'product_id', 'cid': 'cat_id', 's': 'screen', 'bt': 'back_to',
                  'bc': 'back_context'}
    short = {}
    for k, v in kwargs.items():
        if k in SHORT_KEYS:
            short[SHORT_KEYS[k]] = v  # keep long names for compatibility
        else:
            short[k] = v
    # Use very short keys manually
    short_map = {'type': 't', 'action': 'a', 'id': 'id', 'page': 'p', 'qty': 'q',
                 'product_id': 'pid', 'cat_id': 'cid', 'screen': 's', 'back_to': 'bt',
                 'back_context': 'bc'}
    compact = {}
    for k, v in short.items():
        compact[short_map.get(k, k)] = v
    return json.dumps(compact, separators=(',', ':'))


def unpack_cb(data: str) -> dict:
    """Unpack callback data from JSON string (supports both short and long keys)"""
    result = json.loads(data)
    # Map short keys to long keys for compatibility
    LONG_KEYS = {'t': 'type', 'a': 'action', 'p': 'page', 'q': 'qty',
                 'pid': 'product_id', 'cid': 'cat_id', 's': 'screen', 'bt': 'back_to',
                 'bc': 'back_context'}
    for short, long_key in LONG_KEYS.items():
        if short in result and long_key not in result:
            result[long_key] = result.pop(short)
    return result


def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌸 Каталог"), KeyboardButton(text="🛒 Корзина")],
            [KeyboardButton(text="📋 Мои заказы"), KeyboardButton(text="📍 Контакты")],
            [KeyboardButton(text="✨ Хочу букет которого нет в каталоге")],
        ],
        resize_keyboard=True,
    )


def get_categories_keyboard(categories: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardMarkup(inline_keyboard=[])
    for cat in categories:
        emoji = cat.emoji or '📂'
        builder.inline_keyboard.append(
            [InlineKeyboardButton(text=f"{emoji} {cat.name}", callback_data=pack_cb(type="cat", action="view", id=cat.id, page="0"))]
        )
    builder.inline_keyboard.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", screen="categories", cat_id=0))]
    )
    return builder


def get_products_keyboard(products: list, cat_id: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardMarkup(inline_keyboard=[])
    for prod in products:
        builder.inline_keyboard.append(
            [InlineKeyboardButton(
                text=f"{prod.name} — {prod.price:.0f} ₽",
                callback_data=pack_cb(type="prod", action="view", id=prod.id, cat_id=cat_id)
            )]
        )
    builder.inline_keyboard.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", screen="products", cat_id=cat_id))]
    )
    return builder


def get_product_detail_keyboard(product, cat_id: int = 0) -> InlineKeyboardMarkup:
    stock_text = f" ({product.quantity} шт.)" if product.quantity > 0 else " (нет в наличии)"
    builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🛒 В корзину" if product.quantity > 0 else "❌ Нет в наличии",
            callback_data=pack_cb(type="cart", action="add", product_id=product.id, qty=1)
        )],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", screen="products", cat_id=cat_id))],
    ])
    return builder


def get_cart_keyboard(cart_items: list, total: float, back_to: str = "catalog") -> InlineKeyboardMarkup:
    builder = InlineKeyboardMarkup(inline_keyboard=[])
    for item in cart_items:
        product = item["product"]
        qty = item["qty"]
        builder.inline_keyboard.append([
            InlineKeyboardButton(text=f"{product.name} x{qty}", callback_data=pack_cb(type="cart", action="view", product_id=product.id, qty=qty)),
            InlineKeyboardButton(text="➖", callback_data=pack_cb(type="cart", action="minus", product_id=product.id, qty=qty)),
            InlineKeyboardButton(text="➕", callback_data=pack_cb(type="cart", action="plus", product_id=product.id, qty=qty)),
        ])
    builder.inline_keyboard.append([
        InlineKeyboardButton(text=f"Итого: {total:.0f} ₽", callback_data="total"),
    ])
    builder.inline_keyboard.append([
        InlineKeyboardButton(text="✅ Оформить заказ", callback_data=pack_cb(type="cart", action="checkout", product_id=0, qty=0)),
    ])
    builder.inline_keyboard.append([
        InlineKeyboardButton(text="⬅️ В каталог", callback_data=pack_cb(type="back", action="back", screen="cart", back_to=back_to)),
    ])
    return builder


def get_order_status_keyboard(order) -> InlineKeyboardMarkup:
    status_map = {
        "new": "🆕 Новый",
        "processing": "⏳ В обработке",
        "confirmed": "✅ Подтверждён",
        "delivered": "🚚 Доставлен",
        "cancelled": "❌ Отменён",
        "not_connected": "📵 Не дозвонились",
    }
    status_text = status_map.get(order.status, order.status)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_text, callback_data=pack_cb(type="order", action="status", id=order.id))],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", id=0))],
    ])


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Товары", callback_data=pack_cb(type="admin", action="products", id=0, page="0"))],
        [InlineKeyboardButton(text="📋 Заказы", callback_data=pack_cb(type="admin", action="orders", id=0, page="0"))],
        [InlineKeyboardButton(text="📊 Статистика", callback_data=pack_cb(type="admin", action="stats", id=0, page="0"))],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", id=0, page="0"))],
    ])


def get_admin_products_keyboard(products: list, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardMarkup(inline_keyboard=[])
    for prod in products:
        status = "🟢" if prod.is_active else "⚫"
        builder.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {prod.name}",
                callback_data=pack_cb(type="admin", action="product_detail", id=prod.id, page=str(page))
            )
        ])
    builder.inline_keyboard.append([
        InlineKeyboardButton(text="➕ Добавить товар", callback_data=pack_cb(type="admin", action="add_product", id=0, page=str(page))),
    ])
    builder.inline_keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", id=0, page="0")),
    ])
    return builder


def get_admin_orders_keyboard(orders: list, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardMarkup(inline_keyboard=[])
    for order in orders:
        status_emoji = {"new": "🆕", "processing": "⏳", "confirmed": "✅", "delivered": "🚚", "cancelled": "❌", "not_connected": "📵"}.get(order.status, "❓")
        prefix = "✨ " if order.is_custom else ""
        builder.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{status_emoji} {prefix}#{order.id} — {order.total_price:.0f} ₽",
                callback_data=pack_cb(type="admin", action="order_detail", id=order.id, page=str(page))
            )
        ])
    builder.inline_keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", id=0, page="0")),
    ])
    return builder


def get_admin_order_status_keyboard(order) -> InlineKeyboardMarkup:
    status_buttons = [
        ("processing", "⏳ В обработке"),
        ("confirmed", "✅ Подтверждён"),
        ("delivered", "🚚 Доставлен"),
        ("cancelled", "❌ Отменён"),
        ("not_connected", "📵 Не дозвонились"),
    ]
    rows = []
    for status, text in status_buttons:
        rows.append([InlineKeyboardButton(
            text=text,
            callback_data=pack_cb(type="admin", action="update_status", id=order.id, page=status)
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", id=0, page="0"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_custom_bouquet_keyboard(back_context: str = "main", cat_id: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой Назад для кастомного букета"""
    if back_context == "catalog" and cat_id > 0:
        # Возвращаемся к продуктам категории
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", back_context="catalog", cat_id=cat_id))]
        ])
    elif back_context == "catalog":
        # Возвращаемся к категориям
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", back_context="catalog", cat_id=0))]
        ])
    else:
        # Возвращаемся в главное меню
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=pack_cb(type="back", action="back", back_context="main", cat_id=0))]
        ])
