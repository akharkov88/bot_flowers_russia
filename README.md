# 🌸 Цветы по русски — Telegram-бот для цветочного магазина

Полноценный сервис для продажи букетов и цветочных композиций на базе Telegram.

## Возможности

### Для клиентов:
- 🌸 Каталог букетов с категориями и карточками товаров
- 🛒 Корзина с управлением количеством
- 📦 Оформление доставки (адрес, дата, время)
- 📋 История заказов со статусами
- 📍 Контакты магазина

### Для администратора:
- ⚙️ Управление товарами (добавление, редактирование, скрытие)
- 📋 Управление заказами (просмотр, смена статуса)
- 📊 Статистика (заказы, выручка, пользователи)
- 🔔 Уведомления о новых заказах в Telegram
- 🌐 Веб-панель администратора с авторизацией

## Стек технологий

- **Python 3.11+**
- **aiogram 3.x** — Telegram-бот
- **FastAPI** — веб-панель админа
- **PostgreSQL** — база данных
- **SQLAlchemy 2.0** — ORM
- **Alembic** — миграции БД
- **Jinja2** — шаблоны HTML

## Установка

### 1. Клонировать репозиторий

```bash
cd bot_russia_flowers
```

### 2. Установить зависимости

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Настроить окружение

Отредактируйте файл `.env`:

```env
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_TELEGRAM_IDS=123456789
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/flowers_db
WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=admin123
WEB_ADMIN_HOST=0.0.0.0
WEB_ADMIN_PORT=8000
```

### 4. Настроить базу данных

```bash
# Создать базу данных в PostgreSQL
createdb flowers_db

# Применить миграции
alembic upgrade head

# Заполнить начальными данными
python seed_data.py
```

### 5. Получить токен бота

Напишите @BotFather в Telegram, создайте нового бота и получите токен.

## Запуск

### Полный запуск (бот + веб-панель):

```bash
./run.sh
```

### Или по отдельности:

```bash
# Бот
python -m bot.main

# Веб-панель (отдельно)
uvicorn admin_web.main:app --host 0.0.0.0 --port 8000 --reload
```

## Структура проекта

```
bot_russia_flowers/
├── bot/                    # Telegram-бот
│   ├── main.py            # Точка входа
│   ├── config.py          # Конфигурация
│   ├── database.py        # SQLAlchemy setup
│   ├── models.py          # ORM модели
│   ├── keyboards.py       # Клавиатуры
│   ├── states.py          # FSM состояния
│   ├── handlers/          # Обработчики
│   ├── middlewares/       # Middleware
│   └── utils/             # Утилиты
├── admin_web/             # Веб-панель админа
│   ├── main.py            # FastAPI app
│   ├── routes.py          # HTML маршруты
│   ├── api.py             # REST API
│   ├── auth.py            # Авторизация
│   ├── templates/         # HTML шаблоны
│   └── static/            # CSS, JS
├── migrations/            # Alembic миграции
├── seed_data.py           # Начальные данные
├── requirements.txt
└── .env
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `BOT_TOKEN` | Токен Telegram-бота | — |
| `ADMIN_TELEGRAM_IDS` | ID админов (через запятую) | — |
| `DATABASE_URL` | URL подключения к PostgreSQL | `postgresql+asyncpg://...` |
| `WEB_ADMIN_USER` | Логин веб-панели | `admin` |
| `WEB_ADMIN_PASSWORD` | Пароль веб-панели | `admin123` |
| `WEB_ADMIN_HOST` | Хост веб-панели | `0.0.0.0` |
| `WEB_ADMIN_PORT` | Порт веб-панели | `8000` |

## Лицензия

© 2026 Цветы по русски. Все права защищены.
