"""Inline calendar keyboard for date and time selection in Telegram bot."""

from datetime import date, timedelta, datetime
from math import ceil

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.keyboards import pack_cb

# Day names (Monday first — Russian convention)
_DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Month names in Russian (nominative)
_MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

# Default time slots (every 30 min, 24/7)
def _generate_time_slots():
    """Generate 30-minute slots for a full 24-hour day (00:00–23:30)."""
    slots = []
    for hour in range(24):
        slots.append(f"{hour:02d}:00")
        slots.append(f"{hour:02d}:30")
    return slots

_DEFAULT_TIME_SLOTS = _generate_time_slots()


def get_time_keyboard(
    selected_time: str = None,
    available_slots: list = None,
    prefix: str = "",
) -> InlineKeyboardMarkup:
    """Generate an inline keyboard with time slot buttons.

    Args:
        selected_time: Currently selected time (if any)
        available_slots: List of available time slots (default: 09:00-21:00)
        prefix: Prefix for callback data type to avoid router conflicts

    Returns:
        InlineKeyboardMarkup with time buttons
    """
    if available_slots is None:
        available_slots = _DEFAULT_TIME_SLOTS

    keyboard = []
    # Header
    keyboard.append([
        InlineKeyboardButton(
            text="🕐 Выберите время доставки",
            callback_data=pack_cb(type=f"{prefix}time", action="header"),
        )
    ])

    # Time buttons in rows of 3
    for i in range(0, len(available_slots), 3):
        row = []
        for slot in available_slots[i:i+3]:
            if slot == selected_time:
                symbol = f"✅ {slot}"
            else:
                symbol = slot
            row.append(InlineKeyboardButton(
                text=symbol,
                callback_data=pack_cb(type=f"{prefix}time", action="select", tm=slot),
            ))
        keyboard.append(row)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def format_time_display(t: str) -> str:
    """Format time string for display."""
    return t


def get_calendar_keyboard(
    year: int,
    month: int,
    selected_date: date = None,
    min_date: date = None,
    max_date: date = None,
    prefix: str = "",
) -> InlineKeyboardMarkup:
    """Generate an inline calendar keyboard for a given year/month.

    Args:
        year: Calendar year to display
        month: Calendar month (1-12)
        selected_date: Currently selected date (if any)
        min_date: Minimum selectable date (disabled before this)
        max_date: Maximum selectable date (disabled after this)
        prefix: Prefix for callback data type to avoid router conflicts

    Returns:
        InlineKeyboardMarkup with calendar buttons
    """
    if min_date is None:
        min_date = date.today()
    if max_date is None:
        # Allow selecting up to 3 months ahead
        max_dt = datetime(year, month, 1) + timedelta(days=90)
        max_date = max_dt.date()

    keyboard = []

    # Header: month name + year
    month_name = _MONTH_NAMES[month - 1]
    keyboard.append([
        InlineKeyboardButton(
            text=f"{month_name} {year}",
            callback_data=pack_cb(type=f"{prefix}cal", action="header"),
        )
    ])

    # Day names row
    keyboard.append([
        InlineKeyboardButton(text=name, callback_data=pack_cb(type=f"{prefix}cal", action="day_name"))
        for name in _DAY_NAMES
    ])

    # Calculate calendar grid
    first_day = date(year, month, 1)
    # weekday(): Monday=0 ... Sunday=6 (matches _DAY_NAMES order)
    start_weekday = first_day.weekday()

    # Last day of month
    if month == 12:
        last_day_month = date(year, 12, 28) + timedelta(days=4)
    else:
        last_day_month = date(year, month + 1, 1) - timedelta(days=1)

    # First day to display (go back to start of week)
    display_start = first_day - timedelta(days=start_weekday)

    # Build 6 rows max (enough for any month starting on any weekday)
    for row_idx in range(6):
        row_start = display_start + timedelta(days=row_idx * 7)
        buttons = []

        for day_idx in range(7):
            current = row_start + timedelta(days=day_idx)

            if current.month != month:
                # Empty cell (from prev/next month)
                buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
                continue

            # Determine button style
            is_selected = current == selected_date
            is_disabled = current < min_date or current > max_date
            is_today = current == date.today()

            if is_disabled:
                symbol = f"🔒{current.day}"
            elif is_selected:
                symbol = f"✅{current.day}"
            elif is_today:
                symbol = f"🔵{current.day}"
            else:
                symbol = str(current.day)

            buttons.append(InlineKeyboardButton(
                text=symbol,
                callback_data=pack_cb(
                    type=f"{prefix}cal",
                    action="select_date",
                    y=current.year,
                    m=current.month,
                    d=current.day,
                ),
            ))

        keyboard.append(buttons)

    # Navigation row
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Пред", callback_data=pack_cb(type=f"{prefix}cal", action="prev_month")),
        InlineKeyboardButton(text="След ➡️", callback_data=pack_cb(type=f"{prefix}cal", action="next_month")),
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_date_from_callback(callback_data: str) -> date:
    """Extract date from calendar callback data."""
    import json
    data = json.loads(callback_data)
    return date(data["y"], data["m"], data["d"])


def format_date_display(d: date) -> str:
    """Format date for display in Russian locale."""
    return d.strftime("%d.%m.%Y")
