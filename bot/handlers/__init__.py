from aiogram import Dispatcher

from bot.handlers.start import start_router
from bot.handlers.catalog import catalog_router
from bot.handlers.cart import cart_router
from bot.handlers.order import order_router
from bot.handlers.user_orders import user_orders_router
from bot.handlers.admin import admin_router
from bot.handlers.custom_bouquet import custom_bouquet_router


def register_handlers(dp: Dispatcher):
    dp.include_routers(
        start_router,
        catalog_router,
        cart_router,
        order_router,
        user_orders_router,
        admin_router,
        custom_bouquet_router,
    )
    print("✅ All routers registered")
