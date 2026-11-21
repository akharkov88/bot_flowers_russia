"""Full checkout flow test - tests address/phone history feature"""
import asyncio
import re
from aiogram import Bot

BOT_TOKEN = "9239151532:AAF8aIy_PB4kWK7R9pKTt5Qwy9BKLZfVpw0"
CHAT_ID = 622070505

bot = Bot(token=BOT_TOKEN)

async def send_msg(text):
    resp = await bot.send_message(CHAT_ID, text)
    print(f"  → Sent: {text[:50]}")
    return resp

async def wait(seconds=2):
    await asyncio.sleep(seconds)

def get_recent_user_messages(lines, user_id=622070505):
    messages = []
    for line in lines[-200:]:
        if f"Saved incoming message from user {user_id}" in line:
            match = re.search(r"Saved incoming message from user \d+: (.+)", line)
            if match:
                messages.append(match.group(1))
    return messages[-10:]

async def check_address_prompts(lines):
    """Check for duplicate address prompts"""
    prompts = []
    for line in lines[-100:]:
        if "Введите адрес доставки" in line or "Выберите адрес" in line:
            prompts.append(line.strip())
    return prompts

async def test_checkout_flow():
    print("=" * 60)
    print("TEST: Full Checkout Flow")
    print("=" * 60)
    
    # Step 1: /start
    print("\n1. /start")
    await send_msg("/start")
    await wait(2)
    
    # Step 2: Catalog
    print("2. Каталог")
    await send_msg("🌸 Каталог")
    await wait(2)
    
    # Step 3: Cart
    print("3. Корзина")
    await send_msg("🛒 Корзина")
    await wait(2)
    
    # Read log to see what happened
    with open("/home/aleksey/pythonProject/bot_russia_flowers/bot.log", "r") as f:
        lines = f.readlines()
    
    messages = get_recent_user_messages(lines)
    print(f"\n   Recent messages: {messages}")
    
    # Check if cart was shown
    cart_shown = any("Корзина" in l or "cart" in l.lower() for l in lines[-50:])
    print(f"   Cart shown: {cart_shown}")
    
    print("\n" + "=" * 60)
    print("MANUAL TEST:")
    print("   1. Click '✅ Оформить заказ' in cart")
    print("   2. Watch for address prompt")
    print("   3. Should see ONLY ONE message with keyboard")
    print("   4. Click an address from history")
    print("   5. Should go to date prompt")
    print("=" * 60)

async def test_address_selection():
    """Test address selection from history"""
    print("\n" + "=" * 60)
    print("TEST: Address Selection from History")
    print("=" * 60)
    
    with open("/home/aleksey/pythonProject/bot_russia_flowers/bot.log", "r") as f:
        lines = f.readlines()
    
    # Check for address callback
    addr_callbacks = [l for l in lines[-50:] if '"t":"addr"' in l]
    print(f"\n   Address callbacks found: {len(addr_callbacks)}")
    for cb in addr_callbacks[-3:]:
        print(f"   - {cb.strip()[:100]}")
    
    # Check for duplicate messages
    duplicate_checks = [l for l in lines[-50:] if "not handled" in l]
    print(f"\n   Unhandled updates: {len(duplicate_checks)}")
    
    print("=" * 60)

async def main():
    try:
        await test_checkout_flow()
        await wait(5)
        await test_address_selection()
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
