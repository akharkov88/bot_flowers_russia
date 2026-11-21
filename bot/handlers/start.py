from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import get_main_keyboard

start_router = Router()


# Known menu button texts that should be handled by other routers
_MENU_BUTTONS = {
    "🌸 Каталог",
    "🛒 Корзина",
    "📋 Мои заказы",
    "✨ Хочу букет которого нет в каталоге",
    "📍 Контакты",
}


# Catch-all handler for any unmatched messages - ensures middleware runs
@start_router.message(F.text & ~F.text.in_(_MENU_BUTTONS))
async def msg_any_text(message: Message):
    """Handle any text message that doesn't match other handlers.
    FSM handlers (order form, etc.) take priority via aiogram's router order.
    """
    pass


@start_router.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = (
        "Добро пожаловать в цветочный магазин «Цветы по-русски»! 🌸\n\n"
        "Мы создаём букеты и композиции с элементами русского стиля\n"
        "для ваших самых важных моментов.\n\n"
        "📍 Наш адрес: Вятская д.7, Нижний Новгород\n\n"
        "Выберите раздел:"
    )

    await message.answer(welcome_text, reply_markup=get_main_keyboard())


@start_router.message(F.text == "📍 Контакты")
async def msg_contacts(message: Message):
    contacts_text = (
        "📍 Контакты:\n\n"
        "🏠 Адрес: Вятская д.7, Нижний Новгород\n\n"
        "📞 Телефон: +7 (996) 041-22-27\n\n"
        "🕐 Время работы:\n"
        "Пн-Пт: 9:00 - 21:00\n"
        "Сб-Вс: 9:00 - 21:00\n\n"
        "📧 Email: tsvety-porusski@yandex.ru\n\n"
        "Выберите раздел:"
    )

    await message.answer(contacts_text, reply_markup=get_main_keyboard())
