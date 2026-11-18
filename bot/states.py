from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    waiting_for_address = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_phone = State()
    waiting_for_comment = State()


class CustomBouquetForm(StatesGroup):
    waiting_for_description = State()
    waiting_for_budget = State()
    waiting_for_delivery_date = State()
    waiting_for_time = State()
    waiting_for_address = State()
    waiting_for_phone = State()
    waiting_for_comment = State()


class NavigationState(StatesGroup):
    set = State()  # Общий state для хранения навигационного контекста
