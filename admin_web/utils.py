import json


def format_callback_data(callback_data: str) -> str:
    """Convert raw callback JSON to human-readable text for admin panel."""
    if not callback_data:
        return ""

    try:
        data = json.loads(callback_data)
    except (json.JSONDecodeError, TypeError):
        return callback_data

    t = data.get("type", data.get("t", ""))
    a = data.get("action", data.get("a", ""))
    pid = data.get("product_id", data.get("pid", 0))
    cid = data.get("cat_id", data.get("cid", 0))
    q = data.get("qty", data.get("q", 0))
    page = data.get("page", data.get("p", ""))
    screen = data.get("screen", data.get("s", ""))
    back_to = data.get("back_to", data.get("bt", ""))
    back_context = data.get("back_context", data.get("bc", ""))

    # Cart actions
    if t == "cart":
        if a == "add":
            return f"🛒 Добавил товар в корзину (id={pid})"
        elif a == "minus":
            return f"🛒 Уменьшил количество товара в корзине (id={pid})"
        elif a == "plus":
            return f"🛒 Увеличил количество товара в корзине (id={pid})"
        elif a == "checkout":
            return "✅ Оформил заказ (нажал 'Оформить заказ')"
        elif a == "view":
            return f"🛒 Просмотрел товар в корзине (id={pid}, кол-во={q})"

    # Navigation / back
    elif t == "back":
        labels = {
            "catalog": "каталог",
            "cart": "корзину",
            "categories": "список категорий",
            "products": "список товаров",
            "main": "главное меню",
            "custom_bouquet": "форму кастомного букета",
        }
        back_label = labels.get(back_to, back_to) or labels.get(screen, screen) or "назад"
        return f"⬅️ Перешёл обратно в {back_label}"

    # Category view
    elif t == "cat":
        if a == "view":
            return f"📂 Открыл категорию (id={cid})"

    # Product view
    elif t == "prod":
        if a == "view":
            return f"🌸 Открыл карточку товара (id={pid})"

    # Order (admin bot)
    elif t == "order":
        if a == "status":
            return f"📦 Просмотрел статус заказа (id={pid})"

    # Admin bot actions
    elif t == "admin":
        admin_labels = {
            "products": "📦 Товары",
            "product_detail": "📦 Детали товара",
            "orders": "📋 Заказы",
            "order_detail": "📋 Детали заказа",
            "stats": "📊 Статистика",
            "add_product": "➕ Добавить товар",
            "update_status": "📋 Изменить статус заказа",
        }
        label = admin_labels.get(a, a)
        return f"⚙️ Админ-панель: {label} (id={pid})"

    # Fallback
    return callback_data
