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
    Pushes the NEW screen context onto the stack (not the current one).
    """
    current_data = await state.get_data()
    current_screen = current_data.get("screen", SCREEN_MAIN_MENU)
    current_cat_id = current_data.get("cat_id", 0)
    current_product_id = current_data.get("product_id", 0)

    new_cat_id = kwargs.get("cat_id", 0)
    new_product_id = kwargs.get("product_id", 0)

    stack = await get_navigation_stack(state)
    logger.info(f"DEBUG push: screen={screen}, cur={current_screen}, cur_cat={current_cat_id}, stack={stack}, kwargs={kwargs}")

    # Не добавляем main_menu в стек
    if screen == SCREEN_MAIN_MENU:
        await state.set_state(NavigationState.set)
        await state.update_data(screen=SCREEN_MAIN_MENU, cat_id=0, product_id=0)
        await set_navigation_stack(state, stack)
        logger.info(f"DEBUG push: main_menu, no stack update. stack={stack}")
        return

    # Не добавляем дубли: если новый экран уже на вершине с тем же cat_id
    if stack and stack[-1]["screen"] == screen and stack[-1]["cat_id"] == new_cat_id:
        await state.set_state(NavigationState.set)
        await state.update_data(screen=screen, cat_id=new_cat_id, product_id=new_product_id)
        await set_navigation_stack(state, stack)
        logger.info(f"DEBUG push: same screen+cat as top, updated without push. stack={stack}")
        return

    # Если стек пустой — инициализируем
    if not stack:
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
        logger.info(f"DEBUG push: init stack with {screen}, stack={stack}")
        return

    # Push the NEW screen onto the stack
    stack.append({
        "screen": screen,
        "cat_id": new_cat_id,
        "product_id": new_product_id,
    })
    logger.info(f"DEBUG push: appended {screen} to stack, stack={stack}")

    # Set new screen in state
    await state.set_state(NavigationState.set)
    await state.update_data(
        screen=screen,
        cat_id=new_cat_id,
        product_id=new_product_id,
    )
    await set_navigation_stack(state, stack)
    logger.info(f"DEBUG push: stack_after={stack}")


async def pop_navigation(state: FSMContext) -> dict | None:
    """
    Pop the current screen from the stack and return the previous context.
    Returns None if stack is empty (means go to main menu).
    """
    stack = await get_navigation_stack(state)
    logger.info(f"DEBUG pop: stack_before={stack}")

    if not stack:
        logger.info(f"DEBUG pop: stack empty, returning None")
        return None

    # Pop current entry
    stack.pop()
    if not stack:
        logger.info(f"DEBUG pop: stack empty after pop, returning None")
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
