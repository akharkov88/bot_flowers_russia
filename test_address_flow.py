"""Test script for address/phone history feature"""
import asyncio
import time
from aiogram import Bot
BOT_TOKEN = "9239151532:AAF8aIy_PB4kWK7R9pKTt5Qwy9BKLZfVpw0"
CHAT_ID = 622070505

bot = Bot(token=BOT_TOKEN)

async def send_msg(text):
    resp = await bot.send_message(CHAT_ID, text)
    print(f"  → Sent: {text[:60]}")
    return resp

async def wait_for_messages(timeout=3):
    """Wait and collect new messages"""
    await asyncio.sleep(timeout)

async def get_last_user_messages():
    """Get last user messages from bot.log"""
    with open("/home/aleksey/pythonProject/bot_russia_flowers/bot.log", "r") as f:
        lines = f.readlines()
    
    messages = []
    for line in lines[-200:]:
        if "Saved incoming message from user" in line:
            import re
            match = re.search(r"Saved incoming message from user \d+: (.+)", line)
            if match:
                messages.append(match.group(1))
    return messages[-10:]

async def check_for_duplicates():
    """Check if address prompt shows duplicate messages"""
    with open("/home/aleksey/pythonProject/bot_russia_flowers/bot.log", "r") as f:
        content = f.read()
    
    # Look for recent address-related messages
    import re
    address_sends = re.findall(r"Saved incoming message from user \d+: (.+)", content[-5000:])
    return address_sends

async def test():
    print("=" * 60)
    print("TEST: Address/Phone History Feature")
    print("=" * 60)
    
    # Step 1: Send /start
    print("\n1. Sending /start...")
    await send_msg("/start")
    await wait_for_messages(2)
    
    # Step 2: Send catalog
    print("2. Sending '🌸 Каталог'...")
    await send_msg("🌸 Каталог")
    await wait_for_messages(2)
    
    # Step 3: Send cart
    print("3. Sending '🛒 Корзина'...")
    await send_msg("🛒 Корзина")
    await wait_for_messages(2)
    
    # Step 4: Check what messages were sent
    print("\n4. Checking recent user messages from log...")
    messages = await get_last_user_messages()
    print(f"   Last {len(messages)} messages: {messages}")
    
    # Step 5: Check for duplicate address prompts
    print("\n5. Checking for duplicate address prompts...")
    address_msgs = await check_for_duplicates()
    print(f"   Recent messages: {address_msgs}")
    
    print("\n" + "=" * 60)
    print("MANUAL TEST REQUIRED:")
    print("   1. In the bot, go to Cart → Checkout")
    print("   2. Watch for the address prompt")
    print("   3. Verify: ONLY ONE message should appear with keyboard")
    print("   4. Click on an address from history")
    print("   5. Verify: It should go to date prompt (not duplicate)")
    print("=" * 60)

async def main():
    try:
        await test()
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
