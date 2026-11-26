"""Navigation helpers using a stack-based approach for step-by-step back navigation."""

from aiogram.fsm.context import FSMContext
from bot.states import NavigationState
from bot.utils.logger import logger

# Screen type constants
SCREEN_MAIN_MENU = "main_menu"
SCREEN_CATEGORIES = "categories"
SCREEN_PRODUCTS = "products"
SCREEN_PRODUCT = "product"


async def get_navigation_stack(state: FSMContext) -> list:
    """Get the navigation stack from FSM state."""
    data = await state.get_data()
    return data.get("navigation_stack", [])


async def set_navigation_stack(state: FSMContext, stack: list):
    """Set the navigation stack in FSM state."""
    await state.update_data(navigation_stack=stack)


async def push_navigation(state: FSMContext, screen: str, **kwargs):
    """
    Push a new screen onto the navigation stack.
    Always pushes — no duplicate checks.
    """
    new_cat_id = kwargs.get("cat_id", 0)
    new_product_id = kwargs.get("product_id", 0)

    stack = await get_navigation_stack(state)
    logger.info(f"DEBUG push: screen={screen}, cat_id={new_cat_id}, product_id={new_product_id}, stack_before={stack}")

    # Не добавляем main_menu в стек
    if screen == SCREEN_MAIN_MENU:
        await state.set_state(NavigationState.set)
        await state.update_data(screen=SCREEN_MAIN_MENU, cat_id=0, product_id=0)
        await set_navigation_stack(state, stack)
        return

    # Всегда добавляем новый экран в стек
    stack.append({
        "screen": screen,
        "cat_id": new_cat_id,
        "product_id": new_product_id,
    })

    await state.set_state(NavigationState.set)
    await state.update_data(
        screen=screen,
        cat_id=new_cat_id,
        product_id=new_product_id,
    )
    await set_navigation_stack(state, stack)
    logger.info(f"DEBUG push: stack_after={stack}")


async def peek_previous_navigation(state: FSMContext) -> dict | None:
    """
    Peek at the previous screen WITHOUT removing the current screen from the stack.
    Returns the previous context for navigation purposes.
    Returns None if stack has only one entry (means go to main menu).
    """
    stack = await get_navigation_stack(state)

    if len(stack) <= 1:
        return None

    # Return the second-to-last entry (previous screen)
    prev = stack[-2]
    return {
        "screen": prev.get("screen", SCREEN_MAIN_MENU),
        "cat_id": prev.get("cat_id", 0),
        "product_id": prev.get("product_id", 0),
    }


async def pop_navigation(state: FSMContext) -> dict | None:
    """
    Pop the current screen from the stack and return the previous context.
    DEPRECATED: Use peek_previous_navigation for back button navigation.
    This function is destructive and should be used only for clearing navigation.
    Returns None if stack is empty or has only one entry.
    """
    logger.info(f"DEBUG pop: ENTERING")
    stack = await get_navigation_stack(state)
    logger.info(f"DEBUG pop: stack_before={stack}")

    if len(stack) <= 1:
        return None

    # Pop current entry
    stack.pop()
    if not stack:
        return None

    # Get previous context
    prev = stack[-1]
    prev_screen = prev.get("screen", SCREEN_MAIN_MENU)
    prev_cat_id = prev.get("cat_id", 0)
    prev_product_id = prev.get("product_id", 0)

    logger.info(f"DEBUG pop: returning prev={prev}")

    # Update FSM state to previous screen
    await state.set_state(NavigationState.set)
    await state.update_data(
        screen=prev_screen,
        cat_id=prev_cat_id,
        product_id=prev_product_id,
    )
    await set_navigation_stack(state, stack)

    return {
        "screen": prev_screen,
        "cat_id": prev_cat_id,
        "product_id": prev_product_id,
    }


async def clear_navigation(state: FSMContext):
    """Clear the navigation stack."""
    await state.set_state(NavigationState.set)
    await state.update_data(
        navigation_stack=[],
        screen=SCREEN_MAIN_MENU,
        cat_id=0,
        product_id=0,
    )


async def save_cart_back_context(state: FSMContext):
    """Save the current navigation context for cart back navigation."""
    data = await state.get_data()
    current_screen = data.get("screen", SCREEN_MAIN_MENU)
    current_cat_id = data.get("cat_id", 0)

    await state.update_data(
        cart_back_to="catalog",
        cart_back_cat_id=current_cat_id,
        cart_back_screen=current_screen,
    )


async def get_cart_back_context(state: FSMContext) -> dict:
    """Get the saved cart back context."""
    data = await state.get_data()
    return {
        "back_to": data.get("cart_back_to", "main"),
        "cat_id": data.get("cart_back_cat_id", 0),
        "screen": data.get("cart_back_screen", SCREEN_MAIN_MENU),
    }
