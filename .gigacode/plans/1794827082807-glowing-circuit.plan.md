# План: Индивидуальный заказ букета

## Цель
Добавить возможность пользователю создать заказ с описанием желаемого букета свободным текстом, вместо выбора из каталога.

---

## Шаг 1: Модель Order — добавить поля

**Файл:** `bot/models.py`

В класс `Order` добавить два поля после `comment`:

```python
is_custom = Column(Boolean, default=False)
custom_description = Column(Text, nullable=True)
```

---

## Шаг 2: Миграция базы данных

Создать миграцию Alembic:

```bash
alembic revision --autogenerate -m "add_custom_bouquet_fields"
```

Новые колонки в таблице `orders`:
- `is_custom` — BOOLEAN, NOT NULL, DEFAULT 0
- `custom_description` — TEXT, NULLABLE

Применить: `alembic upgrade head`

---

## Шаг 3: FSM-состояния

**Файл:** `bot/states.py`

Добавить новую группу состояний:

```python
class CustomBouquetForm(StatesGroup):
    waiting_for_description = State()  # описание букета
    waiting_for_budget = State()       # бюджет (опционально)
    waiting_for_delivery_date = State() # дата доставки (опционально)
    waiting_for_address = State()       # адрес доставки
    waiting_for_phone = State()         # телефон
    waiting_for_comment = State()       # комментарий
```

6 состояний — полный процесс оформления как у обычного заказа, но с описанием вместо корзины.

---

## Шаг 4: Кнопка «✨ Хочу букет» в главном меню

**Файл:** `bot/keyboards.py`, функция `get_main_keyboard()`

Добавить третий ряд:

```python
[KeyboardButton(text="✨ Хочу букет")]
```

---

## Шаг 5: Обработчик `bot/handlers/custom_bouquet.py`

Новый файл с роутером:

```
✨ Хочу букет → waiting_for_description
waiting_for_description → waiting_for_budget (сохраняет description)
waiting_for_budget → waiting_for_delivery_date (сохраняет budget, "Пропустить" = skip)
waiting_for_delivery_date → waiting_for_address (валидация даты ДД.ММ.ГГГГ, "Пропустить" = skip)
waiting_for_address → waiting_for_phone
waiting_for_phone → waiting_for_comment
waiting_for_comment → СОЗДАНИЕ ЗАКАЗА
```

При создании заказа:
- `is_custom = True`
- `custom_description = description`
- `comment = f"Бюджет: {budget}"` если бюджет указан
- `delivery_address`, `delivery_date`, `delivery_time`, `phone` — как у обычного заказа
- `total_price = 0.0` (админ сообщит по телефону)
- `status = "new"`
- Без `OrderItem` записей

Уведомление админу через `notify_admin(bot, order, is_custom=True)`.

---

## Шаг 6: Обновить `notify_admin()` в `bot/handlers/admin.py`

Добавить параметр `is_custom: bool = False`. При `is_custom=True` — отправлять уведомление с описанием букета, бюджетом и датой, без состава заказа и без адреса/телефона (так как они собираются позже).

---

## Шаг 7: Обновить отображение кастомных заказов

### 7a. `bot/handlers/admin.py` — callback `order_detail`
Добавить условие: если `order.is_custom`, показывать описание букета вместо списка товаров.

### 7b. `bot/handlers/user_orders.py` — callback `order_detail`
Аналогично — при просмотре заказа пользователем показывать описание для кастомных заказов.

### 7c. `bot/keyboards.py` — `get_admin_orders_keyboard()`
Добавить префикс `✨ ` для кастомных заказов в списке.

### 7d. `admin_web/templates/orders.html`
Добавить бейдж `✨ Инд.` для кастомных заказов.

### 7e. `admin_web/templates/order_detail.html`
Добавить секцию «Индивидуальный заказ» с описанием и бюджетом.

---

## Шаг 8: Регистрация роутера

**Файл:** `bot/handlers/__init__.py`

```python
from bot.handlers.custom_bouquet import custom_bouquet_router

# в register_handlers:
dp.include_routers(
    start_router, catalog_router, cart_router, order_router,
    user_orders_router, admin_router, custom_bouquet_router,
)
```

---

## Файлы для изменения

| Файл | Действие |
|------|----------|
| `bot/models.py` | Добавить поля `is_custom`, `custom_description` |
| `bot/states.py` | Добавить `CustomBouquetForm` |
| `bot/keyboards.py` | Кнопка в главном меню, индикатор в админ-списке |
| `bot/handlers/custom_bouquet.py` | **Новый файл** — основной обработчик |
| `bot/handlers/admin.py` | Обновить `notify_admin`, `order_detail` |
| `bot/handlers/user_orders.py` | Обновить `order_detail` |
| `bot/handlers/__init__.py` | Регистрация роутера |
| `admin_web/templates/orders.html` | Бейдж для кастомных заказов |
| `admin_web/templates/order_detail.html` | Секция описания |
| `migrations/versions/` | Новая миграция |

---

## Проверка

1. `alembic upgrade head` — миграция прошла успешно
2. Запуск бота → главное меню имеет 3 ряда кнопок
3. «✨ Хочу букет» → описание → бюджет → дата → адрес → телефон → комментарий → подтверждение
4. Админ получает уведомление с описанием букета
5. «📋 Мои заказы» → кастомный заказ отображается с описанием
6. Админ-панель → заказы → бейдж ✨ → детали с описанием
