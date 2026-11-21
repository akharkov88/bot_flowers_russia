from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import get_main_keyboard
from bot.utils.logger import logger

start_router = Router()


@start_router.message(Command("start"))
async def cmd_start(message: Message):
    logger.info(f"cmd_start called for user {message.from_user.id}")
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
