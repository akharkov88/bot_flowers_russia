from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import get_main_keyboard, get_contacts_keyboard
from bot.config import settings
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
        f"📞 Телефон: {settings.store_phone_display}\n\n"
        "🕐 Время работы:\n"
        "Пн-Пт: 9:00 - 21:00\n"
        "Сб-Вс: 9:00 - 21:00\n\n"
        "📧 Email: tsvety-porusski@yandex.ru\n\n"
        "Выберите раздел:"
    )

    await message.answer(contacts_text, reply_markup=get_main_keyboard())


@start_router.message(F.text == "📞 Позвонить")
async def msg_call(message: Message):
    # Telegram автоматически делает номер телефона кликабельным на мобильных устройствах
    # При нажатии откроется набор номера через сотового оператора
    call_text = (
        f"📞 Позвоните нам:\n\n"
        f"{settings.store_phone}\n\n"
        f"Нажмите на номер, чтобы позвонить через сотового оператора"
    )
    await message.answer(call_text, reply_markup=get_main_keyboard())
