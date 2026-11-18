"""
Скрипт для заполнения базы данных начальными данными.
Запуск: python seed_data.py
"""
import asyncio
from sqlalchemy import select

from bot.database import async_session_factory, init_db
from bot.models import Category, Product


async def seed():
    await init_db()
    async with async_session_factory() as session:
        # Check if already seeded
        result = await session.execute(select(Category).limit(1))
        if result.scalar_one_or_none():
            print("База данных уже заполнена. Пропускаем.")
            return

        print("Заполнение базы данных...")

        # Create categories
        categories_data = [
            {"name": "🌹 Букеты", "sort_order": 1},
            {"name": "🌻 Композиции", "sort_order": 2},
            {"name": "🧺 Корзины", "sort_order": 3},
            {"name": "💐 Свадебные", "sort_order": 4},
            {"name": "🎁 Подарки", "sort_order": 5},
        ]

        categories = []
        for i, cat_data in enumerate(categories_data):
            cat = Category(name=cat_data["name"], sort_order=cat_data["sort_order"], is_active=True)
            session.add(cat)
            categories.append(cat)

        await session.flush()

        # Create products
        products_data = [
            # Букеты
            {
                "name": "Розы Эквадора",
                "description": "Роскошный букет из 25 розовых роз высшего сорта",
                "price": 5500,
                "category": categories[0],
                "composition": "Розы Эквадора, эвкалипт, атласная лента",
            },
            {
                "name": "Весеннее настроение",
                "description": "Яркий микс из тюльпанов и нарциссов",
                "price": 3200,
                "category": categories[0],
                "composition": "Тюльпаны, нарциссы, гвоздики, зелень",
            },
            {
                "name": "Белое облако",
                "description": "Элегантный букет из белых хризантем",
                "price": 2800,
                "category": categories[0],
                "composition": "Хризантемы белые, альстромерия, зелень",
            },
            # Композиции
            {
                "name": "Русское раздолье",
                "description": "Большая композиция в русском народном стиле",
                "price": 8500,
                "category": categories[1],
                "composition": "Подсолнухи, ромашки, колоски, льняная ткань",
            },
            {
                "name": "Барская усадьба",
                "description": "Роскошная композиция в классическом стиле",
                "price": 7200,
                "category": categories[1],
                "composition": "Пионы, розы, эвкалипт, декоративная корзина",
            },
            # Корзины
            {
                "name": "Корзина счастья",
                "description": "Плоская корзина с миксом сезонных цветов",
                "price": 6800,
                "category": categories[2],
                "composition": "Розы, хризантемы, альстромерия, зелень",
            },
            {
                "name": "Корзина нежности",
                "description": "Нежная корзина с розами и лавандой",
                "price": 7500,
                "category": categories[2],
                "composition": "Розы розовые, лаванда, эвкалипт",
            },
            # Свадебные
            {
                "name": "Невеста",
                "description": "Классический свадебный букет",
                "price": 4500,
                "category": categories[3],
                "composition": "Пионы, розы, эвкалипт, атласная лента",
            },
            {
                "name": "Полевая невеста",
                "description": "Букет в стиле boho с полевыми цветами",
                "price": 3800,
                "category": categories[3],
                "composition": "Ромашки, колоски, лаванда, полевые цветы",
            },
            # Подарки
            {
                "name": "Коробка любви",
                "description": "Подарочная коробка с 15 розами",
                "price": 6200,
                "category": categories[4],
                "composition": "Розы, атласная лента, открытка",
            },
            {
                "name": "Сладкий букет",
                "description": "Букет из макарун и цветов",
                "price": 5800,
                "category": categories[4],
                "composition": "Макаруны, розы, хризантемы, декор",
            },
        ]

        for prod_data in products_data:
            prod = Product(
                name=prod_data["name"],
                description=prod_data["description"],
                price=prod_data["price"],
                category_id=prod_data["category"].id,
                composition=prod_data["composition"],
                is_active=True,
            )
            session.add(prod)

        await session.commit()
        print(f"✅ Создано {len(categories)} категорий и {len(products_data)} товаров.")


if __name__ == "__main__":
    asyncio.run(seed())
