from fastapi import APIRouter, Request, Form, HTTPException, UploadFile, File, Form as FastAPIForm
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy import select, func, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.database import async_session_factory
from bot.models import Product, Category, Order, OrderItem, User, ProductImage, Notification, Cart, Message, Post, PostRecipient, PostStats
from admin_web.auth import is_authenticated

import os
import uuid
import json
import asyncio
from datetime import datetime, date, time, timedelta, timezone

# MSK timezone (UTC+3)
MSK = timezone(timedelta(hours=3))
from bot.utils.logger import logger
from admin_web.utils import format_callback_data

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin_web", "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter()

# render_template will be set by main.py to avoid circular import
render_template = None


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    status_filter = request.query_params.get("status", "")
    async with async_session_factory() as session:
        query = select(Order).order_by(Order.created_at.desc())
        if status_filter:
            query = query.where(Order.status == status_filter)
        result = await session.execute(query)
        orders = result.scalars().all()
    status_labels = {
        "new": "🆕 Новый",
        "processing": "⏳ В обработке",
        "confirmed": "✅ Подтверждён",
        "delivered": "🚚 Доставлен",
        "cancelled": "❌ Отменён",
        "not_connected": "📵 Не дозвонились",
    }
    return HTMLResponse(content=render_template("orders.html", {
        "request": request,
        "orders": orders,
        "status_filter": status_filter,
        "status_labels": status_labels,
    }))


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail_page(request: Request, order_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Заказ не найден")

        result = await session.execute(
            select(OrderItem)
            .options(joinedload(OrderItem.product))
            .where(OrderItem.order_id == order_id)
        )
        items = result.scalars().all()

        result = await session.execute(select(User).where(User.id == order.user_id))
        user = result.scalar_one_or_none()

    status_labels = {
        "new": "🆕 Новый",
        "processing": "⏳ В обработке",
        "confirmed": "✅ Подтверждён",
        "delivered": "🚚 Доставлен",
        "cancelled": "❌ Отменён",
        "not_connected": "📵 Не дозвонились",
    }
    return HTMLResponse(content=render_template("order_detail.html", {
        "request": request,
        "order": order,
        "items": items,
        "user": user,
        "status_labels": status_labels,
    }))


@router.post("/orders/{order_id}/status")
async def update_order_status(order_id: int, status: str = Form(...)):
    async with async_session_factory() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        order.status = status

        # Create notification for user and order chat
        result = await session.execute(select(User).where(User.id == order.user_id))
        user = result.scalar_one_or_none()
        if user and user.telegram_id:
            from bot.config import settings
            status_labels = {
                "new": "🆕 Новый",
                "processing": "⏳ В обработке",
                "confirmed": "✅ Подтверждён",
                "delivered": "🚚 Доставлен",
                "cancelled": "❌ Отменён",
                "not_connected": "📵 Не дозвонились",
            }
            status_text = status_labels.get(status, status)

            # Notification to user
            session.add(Notification(
                user_id=user.id,
                telegram_id=user.telegram_id,
                text=(
                    f"📦 Заказ #{order.id}\n\n"
                    f"Ваш заказ теперь имеет статус: {status_text}\n\n"
                    f"Спасибо за покупку! 🌸"
                ),
            ))
            # Notification to order chat
            if settings.order_chat_id:
                session.add(Notification(
                    chat_id=settings.order_chat_id,
                    text=(
                        f"📦 Заказ #{order.id}\n"
                        f"Статус: {status_text}"
                    ),
                ))

        await session.commit()
    return RedirectResponse(url=f"/orders/{order_id}", status_code=302)


@router.post("/orders/{order_id}/edit")
async def update_order_details(
    order_id: int,
    delivery_address: str = Form(""),
    delivery_date: str = Form(""),
    delivery_time: str = Form(""),
    phone: str = Form(""),
    comment: str = Form(""),
):
    async with async_session_factory() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Заказ не найден")

        # Collect changed fields
        changes = []

        if delivery_address is not None:
            old_val = order.delivery_address or "не указан"
            new_val = delivery_address.strip() if delivery_address.strip() else None
            if old_val != (new_val or "не указан"):
                changes.append(f"Адрес: {old_val} → {new_val or 'не указан'}")
            order.delivery_address = new_val

        if delivery_date is not None:
            old_val = str(order.delivery_date) if order.delivery_date else "не указана"
            new_val = delivery_date.strip() if delivery_date.strip() else None
            if old_val != (new_val or "не указана"):
                changes.append(f"Дата: {old_val} → {new_val or 'не указана'}")
            if new_val:
                try:
                    parts = new_val.split(".")
                    if len(parts) == 3:
                        order.delivery_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
                    else:
                        order.delivery_date = None
                except (ValueError, IndexError):
                    order.delivery_date = None
            else:
                order.delivery_date = None

        if delivery_time is not None:
            old_val = str(order.delivery_time) if order.delivery_time else "не указано"
            new_val = delivery_time.strip() if delivery_time.strip() else None
            if old_val != (new_val or "не указано"):
                changes.append(f"Время: {old_val} → {new_val or 'не указано'}")
            if new_val:
                try:
                    if ":" in new_val:
                        hour, minute = map(int, new_val.split(":"))
                        order.delivery_time = time(hour, minute)
                    else:
                        order.delivery_time = time(int(new_val), 0)
                except (ValueError, IndexError):
                    order.delivery_time = None
            else:
                order.delivery_time = None

        if phone is not None:
            old_val = order.phone or "не указан"
            new_val = phone.strip() if phone.strip() else None
            if old_val != (new_val or "не указан"):
                changes.append(f"Телефон: {old_val} → {new_val or 'не указан'}")
            order.phone = new_val

        if comment is not None:
            old_val = order.comment or "не указан"
            new_val = comment.strip() if comment.strip() else None
            if old_val != (new_val or "не указан"):
                changes.append(f"Комментарий: {old_val} → {new_val or 'не указан'}")
            order.comment = new_val

        await session.commit()

        # Notify user about changes
        result = await session.execute(select(User).where(User.id == order.user_id))
        user = result.scalar_one_or_none()
        if user and user.telegram_id and changes:
            from bot.config import settings
            changes_text = "\n".join(f"• {c}" for c in changes)
            session.add(Notification(
                user_id=user.id,
                telegram_id=user.telegram_id,
                text=(
                    f"📝 Заказ #{order.id}\n\n"
                    f"Администратор уточнил данные:\n\n"
                    f"{changes_text}\n\n"
                    f"Спасибо за покупку! 🌸"
                ),
            ))
            if settings.order_chat_id:
                session.add(Notification(
                    chat_id=settings.order_chat_id,
                    text=(
                        f"📝 Заказ #{order.id}\n"
                        f"Данные уточнены:\n\n"
                        f"{changes_text}"
                    ),
                ))
            await session.commit()

    return RedirectResponse(url=f"/orders/{order_id}", status_code=302)


@router.get("/products", response_class=HTMLResponse)
async def products_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(
            select(Product)
            .options(joinedload(Product.category))
            .order_by(Product.id)
        )
        products = result.unique().scalars().all()
    return HTMLResponse(content=render_template("products.html", {
        "request": request,
        "products": products,
    }))


@router.get("/products/add", response_class=HTMLResponse)
async def product_add_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Category).where(Category.is_active == True).order_by(Category.sort_order, Category.id))
        categories = result.scalars().all()
    return HTMLResponse(content=render_template("product_form.html", {
        "request": request,
        "product": None,
        "categories": categories,
    }))


@router.post("/products/upload-image")
async def upload_product_image(request: Request, image: UploadFile = File(...)):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    # Validate file
    if not image.filename or not image.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return JSONResponse(status_code=400, content={"error": "Invalid file type"})

    # Generate unique filename
    ext = os.path.splitext(image.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # Save file
    with open(filepath, "wb") as f:
        content = await image.read()
        f.write(content)

    # Return URL
    image_url = f"/static/uploads/{filename}"
    return JSONResponse(content={"image_url": image_url})


@router.post("/products/{product_id}/add-image")
async def add_product_image(product_id: int, request: Request, image: UploadFile = File(...)):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    # Validate file
    if not image.filename or not image.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return JSONResponse(status_code=400, content={"error": "Invalid file type"})

    # Generate unique filename
    ext = os.path.splitext(image.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # Save file
    with open(filepath, "wb") as f:
        content = await image.read()
        f.write(content)

    image_url = f"/static/uploads/{filename}"
    
    async with async_session_factory() as session:
        # Get max order
        result = await session.execute(
            select(func.coalesce(func.max(ProductImage.order), 0)).where(ProductImage.product_id == product_id)
        )
        max_order = result.scalar()
        
        product_image = ProductImage(
            product_id=product_id,
            image_url=image_url,
            order=max_order + 1,
        )
        session.add(product_image)
        await session.commit()
    
    return JSONResponse(content={"image_url": image_url})


@router.post("/products/{product_id}/delete-image/{image_id}")
async def delete_product_image(product_id: int, image_id: int, request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(ProductImage).where(ProductImage.id == image_id, ProductImage.product_id == product_id))
        product_image = result.scalar_one_or_none()
        
        if product_image:
            # Delete file from disk
            filename = os.path.basename(product_image.image_url)
            filepath = os.path.join(UPLOAD_DIR, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
            
            await session.delete(product_image)
            await session.commit()
    
    return RedirectResponse(url=f"/products/{product_id}/edit", status_code=302)


@router.post("/products/add")
async def product_add_submit(
    request: Request,
    name: str = FastAPIForm(...),
    description: str = FastAPIForm(...),
    price: float = FastAPIForm(...),
    category_id: int = FastAPIForm(...),
    composition: str = FastAPIForm(""),
    quantity: int = FastAPIForm(0),
    image_url: str = FastAPIForm(""),
    images: str = FastAPIForm(""),
):
    import json
    async with async_session_factory() as session:
        product = Product(
            name=name,
            description=description,
            price=price,
            category_id=category_id,
            composition=composition,
            quantity=quantity,
            is_active=quantity > 0,
            image_url=image_url if image_url else None,
        )
        session.add(product)
        await session.flush()

        # Save additional images from pendingImages
        if images:
            image_list = json.loads(images)
            for order, img_url in enumerate(image_list):
                session.add(ProductImage(
                    product_id=product.id,
                    image_url=img_url,
                    order=order,
                ))

        await session.commit()
    return RedirectResponse(url="/products", status_code=302)


@router.get("/products/{product_id}/edit", response_class=HTMLResponse)
async def product_edit_page(request: Request, product_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Product).options(joinedload(Product.category), joinedload(Product.images)).where(Product.id == product_id))
        product = result.unique().scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Товар не найден")

        result = await session.execute(select(Category).where(Category.is_active == True).order_by(Category.sort_order, Category.id))
        categories = result.scalars().all()
    return HTMLResponse(content=render_template("product_form.html", {
        "request": request,
        "product": product,
        "categories": categories,
    }))


@router.post("/products/{product_id}/edit")
async def product_edit_submit(
    request: Request,
    product_id: int,
    name: str = FastAPIForm(...),
    description: str = FastAPIForm(...),
    price: float = FastAPIForm(...),
    category_id: int = FastAPIForm(...),
    composition: str = FastAPIForm(""),
    is_active: bool = FastAPIForm(True),
    quantity: int = FastAPIForm(0),
    image_url: str = FastAPIForm(""),
    images: str = FastAPIForm(""),
):
    import json
    async with async_session_factory() as session:
        result = await session.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Товар не найден")

        product.name = name
        product.description = description
        product.price = price
        product.category_id = category_id
        product.composition = composition
        product.quantity = quantity
        product.is_active = is_active and quantity > 0
        if image_url:
            product.image_url = image_url

        # Save additional images from pendingImages
        if images:
            image_list = json.loads(images)
            for order, img_url in enumerate(image_list):
                session.add(ProductImage(
                    product_id=product_id,
                    image_url=img_url,
                    order=order,
                ))

        await session.commit()
    response = RedirectResponse(url="/products", status_code=302)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@router.post("/products/{product_id}/delete")
async def product_delete(request: Request, product_id: int):
    async with async_session_factory() as session:
        result = await session.execute(
            select(Product).options(joinedload(Product.images))
            .where(Product.id == product_id)
        )
        product = result.unique().scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Товар не найден")

        # Delete images from disk
        for img in product.images:
            filename = os.path.basename(img.image_url)
            filepath = os.path.join(UPLOAD_DIR, filename)
            if os.path.exists(filepath):
                os.remove(filepath)

        await session.delete(product)
        await session.commit()
    return RedirectResponse(url="/products", status_code=302)


@router.post("/products/{product_id}/toggle")
async def product_toggle(product_id: int):
    async with async_session_factory() as session:
        result = await session.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Товар не найден")
        if product.quantity <= 0:
            raise HTTPException(status_code=400, detail="Нельзя активировать товар с количеством 0")
        product.is_active = not product.is_active
        await session.commit()
    return RedirectResponse(url="/products", status_code=302)


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Category).order_by(Category.sort_order, Category.id))
        categories = result.scalars().all()
    return HTMLResponse(content=render_template("categories.html", {
        "request": request,
        "categories": categories,
    }))


@router.get("/customers", response_class=HTMLResponse)
async def customers_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    status_filter = request.query_params.get("status", "")
    search = request.query_params.get("search", "")

    async with async_session_factory() as session:
        query = select(User).order_by(User.created_at.desc())

        if search:
            search_term = f"%{search}%"
            query = query.where(
                (User.first_name.ilike(search_term)) |
                (User.last_name.ilike(search_term)) |
                (User.username.ilike(search_term)) |
                (User.telegram_id.cast(String).ilike(search_term))
            )

        result = await session.execute(query)
        users = result.scalars().all()

        # Normalize is_blocked and user_blocked_bot to boolean
        for user in users:
            # Normalize is_blocked
            if isinstance(user.is_blocked, str):
                user.is_blocked = user.is_blocked.lower().strip() in ('true', '1', 'yes')
            elif user.is_blocked is None:
                user.is_blocked = False
            else:
                user.is_blocked = bool(user.is_blocked)
            # Normalize user_blocked_bot
            if isinstance(user.user_blocked_bot, str):
                user.user_blocked_bot = user.user_blocked_bot.lower().strip() in ('true', '1', 'yes')
            elif user.user_blocked_bot is None:
                user.user_blocked_bot = False
            else:
                user.user_blocked_bot = bool(user.user_blocked_bot)

        # Enrich users with order and cart stats
        user_stats = {}
        for user in users:
            # Count orders
            order_result = await session.execute(
                select(func.count(Order.id)).where(Order.user_id == user.id)
            )
            order_count = order_result.scalar() or 0

            # Total spent
            total_result = await session.execute(
                select(func.sum(Order.total_price)).where(Order.user_id == user.id, Order.status != "cancelled")
            )
            total_spent = total_result.scalar() or 0

            # Latest cart
            cart_result = await session.execute(
                select(Cart).where(Cart.user_id == user.id)
                .order_by(Cart.updated_at.desc())
                .limit(1)
            )
            latest_cart = cart_result.scalar_one_or_none()

            # Active cart
            active_cart_result = await session.execute(
                select(Cart).where(
                    Cart.user_id == user.id,
                    Cart.status == "active"
                ).order_by(Cart.updated_at.desc()).limit(1)
            )
            active_cart = active_cart_result.scalar_one_or_none()

            # Abandoned carts
            abandoned_result = await session.execute(
                select(func.count(Cart.id)).where(
                    Cart.user_id == user.id,
                    Cart.status == "abandoned"
                )
            )
            abandoned_count = abandoned_result.scalar() or 0

            # Unfinished orders (not delivered and not cancelled)
            unfinished_result = await session.execute(
                select(func.count(Order.id)).where(
                    Order.user_id == user.id,
                    Order.status.not_in(["delivered", "cancelled"])
                )
            )
            unfinished_count = unfinished_result.scalar() or 0

            user_stats[user.id] = {
                "order_count": order_count,
                "total_spent": total_spent,
                "latest_cart": latest_cart,
                "active_cart": active_cart,
                "abandoned_count": abandoned_count,
                "unfinished_count": unfinished_count,
            }

    return HTMLResponse(content=render_template("customers.html", {
        "request": request,
        "users": users,
        "user_stats": user_stats,
        "status_filter": status_filter,
        "search": search,
    }))


@router.post("/categories/reorder")
async def categories_reorder(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    data = await request.form()
    category_ids_str = data.get("ids", "")
    ids = [int(x.strip()) for x in category_ids_str.split(",") if x.strip()]

    async with async_session_factory() as session:
        for index, cat_id in enumerate(ids):
            result = await session.execute(select(Category).where(Category.id == cat_id))
            cat = result.scalar_one_or_none()
            if cat:
                cat.sort_order = index
        await session.commit()

    return RedirectResponse(url="/categories", status_code=302)


@router.get("/categories/add", response_class=HTMLResponse)
async def category_add_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)
    return HTMLResponse(content=render_template("category_form.html", {
        "request": request,
        "category": None,
    }))


@router.post("/categories/upload-image")
async def upload_category_image(request: Request, image: UploadFile = File(...)):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    if not image.filename or not image.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return HTMLResponse(status_code=400, content="Invalid file type")

    ext = os.path.splitext(image.filename)[1]
    filename = f"cat_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        content = await image.read()
        f.write(content)

    image_url = f"/static/uploads/{filename}"
    return HTMLResponse(content=image_url)


@router.post("/categories/add")
async def category_add_submit(
    request: Request,
    name: str = FastAPIForm(...),
    emoji: str = FastAPIForm(""),
    image_url: str = FastAPIForm(""),
    is_active: bool = FastAPIForm(True),
):
    async with async_session_factory() as session:
        category = Category(
            name=name,
            emoji=emoji if emoji else None,
            image_url=image_url if image_url else None,
            is_active=is_active,
        )
        session.add(category)
        await session.commit()
    return RedirectResponse(url="/categories", status_code=302)


@router.get("/categories/{category_id}/edit", response_class=HTMLResponse)
async def category_edit_page(request: Request, category_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        if not category:
            raise HTTPException(status_code=404, detail="Категория не найдена")
    return HTMLResponse(content=render_template("category_form.html", {
        "request": request,
        "category": category,
    }))


@router.post("/categories/{category_id}/edit")
async def category_edit_submit(
    request: Request,
    category_id: int,
    name: str = FastAPIForm(...),
    emoji: str = FastAPIForm(""),
    image_url: str = FastAPIForm(""),
    is_active: bool = FastAPIForm(True),
):
    async with async_session_factory() as session:
        result = await session.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        if not category:
            raise HTTPException(status_code=404, detail="Категория не найдена")

        category.name = name
        category.emoji = emoji if emoji else None
        category.image_url = image_url if image_url else None
        category.is_active = is_active
        await session.commit()
    return RedirectResponse(url="/categories", status_code=302)


@router.post("/categories/{category_id}/delete")
async def category_delete(request: Request, category_id: int):
    async with async_session_factory() as session:
        result = await session.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        if not category:
            raise HTTPException(status_code=404, detail="Категория не найдена")

        # Check if category has active products
        result = await session.execute(
            select(func.count(Product.id)).where(
                Product.category_id == category_id,
                Product.is_active == True
            )
        )
        active_count = result.scalar() or 0
        if active_count > 0:
            raise HTTPException(status_code=400, detail="Нельзя удалить категорию с активными товарами")

        await session.delete(category)
        await session.commit()
    return RedirectResponse(url="/categories", status_code=302)


@router.post("/categories/{category_id}/toggle")
async def category_toggle(category_id: int):
    async with async_session_factory() as session:
        result = await session.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        if not category:
            raise HTTPException(status_code=404, detail="Категория не найдена")

        # Check if trying to deactivate and category has active products
        if category.is_active:
            result = await session.execute(
                select(func.count(Product.id)).where(
                    Product.category_id == category_id,
                    Product.is_active == True
                )
            )
            active_count = result.scalar() or 0
            if active_count > 0:
                raise HTTPException(status_code=400, detail="Нельзя деактивировать категорию с активными товарами")

        category.is_active = not category.is_active
        await session.commit()
    return RedirectResponse(url="/categories", status_code=302)


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(func.count(Order.id)))
        total_orders = result.scalar() or 0

        result = await session.execute(select(func.sum(Order.total_price)))
        total_revenue = result.scalar() or 0

        result = await session.execute(
            select(Order.status, func.count(Order.id))
            .group_by(Order.status)
        )
        status_counts = {row[0]: row[1] for row in result.all()}

        result = await session.execute(select(func.count(User.id)))
        total_users = result.scalar() or 0

        result = await session.execute(select(func.count(Product.id)).where(Product.is_active == True))
        active_products = result.scalar() or 0

        # Top products by quantity ordered
        result = await session.execute(
            select(
                Product.id,
                Product.name,
                Product.image_url,
                func.sum(OrderItem.quantity).label("total_quantity"),
                func.sum(OrderItem.quantity * OrderItem.price).label("total_revenue")
            )
            .join(OrderItem, Product.id == OrderItem.product_id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.status != "cancelled")
            .group_by(Product.id, Product.name, Product.image_url)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(10)
        )
        top_products = result.all()

    status_labels = {
        "new": "🆕 Новый",
        "processing": "⏳ В обработке",
        "confirmed": "✅ Подтверждён",
        "delivered": "🚚 Доставлен",
        "cancelled": "❌ Отменён",
        "not_connected": "📵 Не дозвонились",
    }
    return HTMLResponse(content=render_template("stats.html", {
        "request": request,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "status_counts": status_counts,
        "total_users": total_users,
        "active_products": active_products,
        "status_labels": status_labels,
        "top_products": top_products,
    }))


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    status_filter = request.query_params.get("status", "all")
    async with async_session_factory() as session:
        query = select(Notification).order_by(Notification.created_at.desc())
        result = await session.execute(query)
        all_notifs = result.scalars().all()

        # Count stats
        total_messages = len(all_notifs)
        unread_messages = sum(1 for n in all_notifs if not n.sent)

        # Filter by status
        if status_filter == "new":
            filtered = [n for n in all_notifs if not n.sent]
        elif status_filter == "old":
            filtered = [n for n in all_notifs if n.sent]
        else:
            filtered = all_notifs

        # Build notification items with user info
        notifications = []
        for n in filtered:
            user = None
            if n.user_id:
                result_u = await session.execute(select(User).where(User.id == n.user_id))
                user = result_u.scalar_one_or_none()

            user_name = user.first_name if user else (user.username if user else f"ID: {n.telegram_id}")

            notifications.append({
                "id": n.id,
                "user_name": user_name,
                "user_id": user.id if user else None,
                "telegram_id": n.telegram_id,
                "text": n.text,
                "created_at": n.created_at.strftime("%d.%m.%Y %H:%M:%S") if n.created_at else "",
                "read": n.sent,
                "user": user,
            })

    return HTMLResponse(content=render_template("notifications.html", {
        "request": request,
        "notifications": notifications,
        "total_messages": total_messages,
        "unread_messages": unread_messages,
        "status_filter": status_filter,
    }))


@router.get("/customers/{user_id}", response_class=HTMLResponse)
async def customer_detail_page(request: Request, user_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Get orders
        result = await session.execute(select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()))
        orders = result.scalars().all()

        # Get all carts
        result = await session.execute(select(Cart).where(Cart.user_id == user_id).order_by(Cart.updated_at.desc()))
        carts = result.scalars().all()

        # Get latest cart items
        cart_items = []
        for cart in carts:
            if cart.data:
                import json
                cart_data = json.loads(cart.data)
                for prod_id_str, qty in cart_data.items():
                    pid = int(prod_id_str)
                    result = await session.execute(select(Product).where(Product.id == pid))
                    product = result.scalar_one_or_none()
                    if product:
                        cart_items.append({"product": product, "qty": qty, "cart": cart})

    status_labels = {
        "new": "🆕 Новый",
        "processing": "⏳ В обработке",
        "confirmed": "✅ Подтверждён",
        "delivered": "🚚 Доставлен",
        "cancelled": "❌ Отменён",
        "not_connected": "📵 Не дозвонились",
    }
    return HTMLResponse(content=render_template("customer_detail.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "carts": carts,
        "cart_items": cart_items,
        "status_labels": status_labels,
    }))


@router.get("/customers/{user_id}/chat", response_class=HTMLResponse)
async def customer_chat_page(request: Request, user_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        result = await session.execute(
            select(Message).where(Message.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(500)
        )
        messages = list(reversed(result.scalars().all()))

        # Format callback_data for human-readable display
        for msg in messages:
            if msg.callback_data:
                msg._formatted_callback = format_callback_data(msg.callback_data)
            # Convert created_at to MSK
            if msg.created_at:
                msg._created_at_msk = msg.created_at.replace(tzinfo=MSK)

    return HTMLResponse(content=render_template("customer_chat.html", {
        "request": request,
        "user": user,
        "messages": messages,
    }))


@router.post("/customers/{user_id}/chat/send")
async def send_chat_message(user_id: int, request: Request):
    try:
        async with async_session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

            form = await request.form()
            message = form.get("message") or ""

            # Get all image files using getlist
            image_files = form.getlist("image")

            logger.info(f"Chat send for user {user_id}: message={repr(message[:50])}, image_files={len(image_files)}")
            for i, img in enumerate(image_files):
                logger.info(f"  Image {i}: filename={img.filename}, size={img.size}")

            text = message.strip() if message else ""
            image_urls = []

            # Handle image uploads
            for image in image_files:
                if image.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    ext = os.path.splitext(image.filename)[1]
                    filename = f"chat_{user.id}_{uuid.uuid4().hex}{ext}"
                    filepath = os.path.join(UPLOAD_DIR, filename)

                    with open(filepath, "wb") as f:
                        content = await image.read()
                        f.write(content)

                    image_urls.append(f"/static/uploads/{filename}")

            if not text and not image_urls:
                return RedirectResponse(url=f"/customers/{user_id}/chat", status_code=302)

            # Create message records for each image
            for image_url in image_urls:
                msg = Message(
                    user_id=user.id,
                    direction="outgoing",
                    text=text if len(image_urls) == 1 else None,
                    image_url=image_url,
                )
                session.add(msg)

            # If no images, create text-only message
            if not image_urls and text:
                msg = Message(
                    user_id=user.id,
                    direction="outgoing",
                    text=text,
                )
                session.add(msg)

            await session.flush()
            logger.info(f"Saved outgoing message for user {user_id}: text={repr(text[:50])}")

            # Create notification for bot to send
            notification_text = text if text else "📷 Фото"
            notification = Notification(
                telegram_id=user.telegram_id,
                text=notification_text,
                user_id=user.id,
            )
            session.add(notification)

            # Create separate notifications for each image
            for image_url in image_urls:
                image_notif = Notification(
                    telegram_id=user.telegram_id,
                    text=text if len(image_urls) == 1 else "📷 Фото",
                    image_url=image_url,
                    user_id=user.id,
                )
                session.add(image_notif)

            await session.commit()
            logger.info(f"Committed outgoing message + notification for user {user_id}")
    except Exception as e:
        logger.error(f"Error in send_chat_message for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    return RedirectResponse(url=f"/customers/{user_id}/chat", status_code=302)


@router.post("/customers/{user_id}/chat/upload-image")
async def upload_chat_image(user_id: int, request: Request, image: UploadFile = File(...)):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    if not image.filename or not image.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return JSONResponse(status_code=400, content={"error": "Invalid file type"})

    ext = os.path.splitext(image.filename)[1]
    filename = f"chat_{user_id}_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        content = await image.read()
        f.write(content)

    image_url = f"/static/uploads/{filename}"
    return JSONResponse(content={"image_url": image_url})


@router.get("/customers/{user_id}/chat/messages")
async def get_chat_messages(user_id: int):
    async with async_session_factory() as session:
        result = await session.execute(
            select(Message).where(Message.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(500)
        )
        messages = list(reversed(result.scalars().all()))

    messages_data = [
        {
            "id": m.id,
            "direction": m.direction,
            "text": m.text,
            "image_url": m.image_url,
            "callback_data": m.callback_data,
            "formatted_callback": format_callback_data(m.callback_data) if m.callback_data else "",
            "keyboard": m.keyboard,
            "created_at": m.created_at.replace(tzinfo=MSK).strftime("%d.%m.%Y %H:%M:%S") if m.created_at else "",
        }
        for m in messages
    ]
    return JSONResponse(content={"messages": messages_data})


@router.post("/customers/{user_id}/chat/{message_id}/delete")
async def delete_chat_message(user_id: int, message_id: int, request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Message).where(Message.id == message_id, Message.user_id == user_id))
        message = result.scalar_one_or_none()
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")

        await session.delete(message)
        await session.commit()

    return RedirectResponse(url=f"/customers/{user_id}/chat", status_code=302)


# ==================== POSTS ====================

@router.get("/posts", response_class=HTMLResponse)
async def posts_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    status_filter = request.query_params.get("status", "")
    async with async_session_factory() as session:
        query = select(Post).order_by(Post.created_at.desc())
        if status_filter:
            query = query.where(Post.status == status_filter)
        result = await session.execute(query)
        posts = result.scalars().all()

    status_labels = {
        "draft": "📝 Черновик",
        "sending": "📤 Отправка",
        "sent": "✅ Отправлен",
        "failed": "❌ Ошибка",
        "scheduled": "⏰ Запланирован",
    }
    return HTMLResponse(content=render_template("posts.html", {
        "request": request,
        "posts": posts,
        "status_filter": status_filter,
        "status_labels": status_labels,
    }))


@router.get("/posts/create", response_class=HTMLResponse)
async def post_create_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()

    return HTMLResponse(content=render_template("post_form.html", {
        "request": request,
        "post": None,
        "users": users,
        "selected_user_ids": "",
    }))


@router.post("/posts/create")
async def post_create_submit(
    request: Request,
    title: str = FastAPIForm(...),
    text: str = FastAPIForm(...),
    image_urls: str = FastAPIForm(""),
    send_type: str = FastAPIForm("instant"),
    scheduled_at: str = FastAPIForm(""),
    audience_type: str = FastAPIForm("all"),
    selected_user_ids: str = FastAPIForm(""),
    is_active: bool = FastAPIForm(True),
):
    import json
    from datetime import datetime

    # Parse images
    images = json.loads(image_urls) if image_urls else []

    # Parse audience
    if audience_type == "selected" and selected_user_ids:
        user_ids = [int(x.strip()) for x in selected_user_ids.split(",") if x.strip()]
        audience = json.dumps({"type": "selected", "user_ids": user_ids})
    else:
        audience = json.dumps({"type": "all"})

    # Parse scheduled_at
    scheduled_at_dt = None
    if send_type == "scheduled" and scheduled_at:
        try:
            scheduled_at_dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except:
            scheduled_at_dt = None

    status = "scheduled" if send_type == "scheduled" else "draft"

    async with async_session_factory() as session:
        post = Post(
            title=title,
            text=text,
            images=json.dumps(images) if images else None,
            send_type=send_type,
            scheduled_at=scheduled_at_dt,
            status=status,
            audience=audience,
        )
        session.add(post)
        await session.commit()

    return RedirectResponse(url="/posts", status_code=302)


@router.get("/posts/{post_id}/edit", response_class=HTMLResponse)
async def post_edit_page(request: Request, post_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=404, detail="Пост не найден")

        result = await session.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()

    # Parse audience to get selected user IDs
    selected_user_ids = ""
    if post and post.audience:
        try:
            audience_data = json.loads(post.audience)
            if audience_data.get("type") == "selected":
                selected_user_ids = ", ".join(str(uid) for uid in audience_data.get("user_ids", []))
        except:
            pass

    return HTMLResponse(content=render_template("post_form.html", {
        "request": request,
        "post": post,
        "users": users,
        "selected_user_ids": selected_user_ids,
    }))


@router.post("/posts/{post_id}/edit")
async def post_edit_submit(
    request: Request,
    post_id: int,
    title: str = FastAPIForm(...),
    text: str = FastAPIForm(...),
    image_urls: str = FastAPIForm(""),
    send_type: str = FastAPIForm("instant"),
    scheduled_at: str = FastAPIForm(""),
    audience_type: str = FastAPIForm("all"),
    selected_user_ids: str = FastAPIForm(""),
):
    import json
    from datetime import datetime

    async with async_session_factory() as session:
        result = await session.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=404, detail="Пост не найден")

        images = json.loads(image_urls) if image_urls else []

        if audience_type == "selected" and selected_user_ids:
            user_ids = [int(x.strip()) for x in selected_user_ids.split(",") if x.strip()]
            audience = json.dumps({"type": "selected", "user_ids": user_ids})
        else:
            audience = json.dumps({"type": "all"})

        scheduled_at_dt = None
        if send_type == "scheduled" and scheduled_at:
            try:
                scheduled_at_dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            except:
                scheduled_at_dt = None

        post.title = title
        post.text = text
        post.images = json.dumps(images) if images else None
        post.send_type = send_type
        post.scheduled_at = scheduled_at_dt
        post.audience = audience

        if post.status == "draft":
            post.status = "scheduled" if send_type == "scheduled" else "draft"

        await session.commit()

    return RedirectResponse(url="/posts", status_code=302)


@router.post("/posts/{post_id}/delete")
async def post_delete(request: Request, post_id: int):
    async with async_session_factory() as session:
        result = await session.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=404, detail="Пост не найден")

        # Delete images from disk
        if post.images:
            import json
            images = json.loads(post.images)
            for img_url in images:
                filename = os.path.basename(img_url)
                filepath = os.path.join(UPLOAD_DIR, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)

        await session.delete(post)
        await session.commit()

    return RedirectResponse(url="/posts", status_code=302)


@router.post("/posts/upload-image")
async def upload_post_image(request: Request, image: UploadFile = File(...)):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    if not image.filename or not image.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return HTMLResponse(status_code=400, content="Invalid file type")

    ext = os.path.splitext(image.filename)[1]
    filename = f"post_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        content = await image.read()
        f.write(content)

    # Return full URL for local access
    image_url = f"/static/uploads/{filename}"
    return HTMLResponse(content=image_url)


@router.post("/posts/{post_id}/send")
async def send_post_now(request: Request, post_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=404, detail="Пост не найден")

        if post.status in ["sent", "sending"]:
            return RedirectResponse(url=f"/posts/{post_id}/stats", status_code=302)

        # Mark as sending
        post.status = "sending"
        await session.commit()

        # Get audience
        import json
        audience = json.loads(post.audience) if post.audience else {"type": "all"}

        # Get users
        if audience.get("type") == "selected":
            user_ids = audience.get("user_ids", [])
            result = await session.execute(
                select(User).where(User.id.in_(user_ids))
            )
            users = result.scalars().all()
        else:
            result = await session.execute(select(User))
            users = result.scalars().all()

        # Create recipients
        for user in users:
            recipient = PostRecipient(
                post_id=post.id,
                user_id=user.id,
                telegram_id=user.telegram_id,
                status="pending",
            )
            session.add(recipient)

        await session.commit()

    return RedirectResponse(url=f"/posts/{post_id}/stats", status_code=302)


@router.get("/posts/{post_id}/stats", response_class=HTMLResponse)
async def post_stats_page(request: Request, post_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=404, detail="Пост не найден")

        result = await session.execute(
            select(PostRecipient)
            .where(PostRecipient.post_id == post_id)
            .order_by(PostRecipient.created_at.desc())
        )
        recipients = result.scalars().all()

        result = await session.execute(select(PostStats).where(PostStats.post_id == post_id))
        stats = result.scalar_one_or_none()

    status_labels = {
        "pending": "⏳ Ожидает",
        "sent": "✅ Отправлено",
        "failed": "❌ Ошибка",
    }
    return HTMLResponse(content=render_template("post_stats.html", {
        "request": request,
        "post": post,
        "recipients": recipients,
        "stats": stats,
        "status_labels": status_labels,
    }))


async def process_post_sending(post_id: int):
    """Background task to send post to all recipients"""
    from bot.main import bot
    from bot.database import async_session_factory
    from aiogram.types import InputFile
    import json

    try:
        async with async_session_factory() as session:
            result = await session.execute(select(Post).where(Post.id == post_id))
            post = result.scalar_one_or_none()
            if not post:
                return

            result = await session.execute(
                select(PostRecipient)
                .where(PostRecipient.post_id == post_id, PostRecipient.status == "pending")
            )
            pending_recipients = result.scalars().all()

            # Update stats
            total = len(pending_recipients)
            stats_result = await session.execute(
                select(PostStats).where(PostStats.post_id == post_id)
            )
            stats = stats_result.scalar_one_or_none()
            if not stats:
                stats = PostStats(post_id=post_id, total_pending=total)
                session.add(stats)
            else:
                stats.total_pending = total

            await session.commit()

        # Send to each user
        for recipient in pending_recipients:
            try:
                # Send photo
                images = json.loads(post.images) if post.images else []
                photo_url = images[0] if images else None

                if photo_url:
                    # Convert relative URL to local file path
                    filename = os.path.basename(photo_url)
                    filepath = os.path.join(UPLOAD_DIR, filename)
                    if os.path.exists(filepath):
                        await bot.send_photo(
                            chat_id=recipient.telegram_id,
                            photo=InputFile(filepath),
                            caption=post.text
                        )
                    else:
                        await bot.send_message(
                            chat_id=recipient.telegram_id,
                            text=post.text + f"\n\n[Фото не найдено: {filename}]"
                        )
                else:
                    await bot.send_message(
                        chat_id=recipient.telegram_id,
                        text=post.text
                    )

                # Create Message record for admin chat view
                async with async_session_factory() as msg_session:
                    msg = Message(
                        user_id=recipient.user_id,
                        direction="outgoing",
                        text=f"📢 Пост: {post.title}\n\n{post.text}",
                    )
                    msg_session.add(msg)
                    await msg_session.commit()
                    logger.info(f"Saved outgoing post message for user {recipient.user_id}: {post.title}")

                # Update recipient
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(PostRecipient)
                        .where(PostRecipient.id == recipient.id)
                    )
                    rec = result.scalar_one_or_none()
                    if rec:
                        rec.status = "sent"
                        rec.sent_at = datetime.now()
                        await session.commit()

                # Update stats
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(PostStats).where(PostStats.post_id == post_id)
                    )
                    stats = result.scalar_one_or_none()
                    if stats:
                        stats.total_pending -= 1
                        stats.total_sent += 1
                        await session.commit()

            except Exception as e:
                # Update recipient with error
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(PostRecipient)
                        .where(PostRecipient.id == recipient.id)
                    )
                    rec = result.scalar_one_or_none()
                    if rec:
                        rec.status = "failed"
                        rec.error_message = str(e)[:500]
                        await session.commit()

                # Update stats
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(PostStats).where(PostStats.post_id == post_id)
                    )
                    stats = result.scalar_one_or_none()
                    if stats:
                        stats.total_pending -= 1
                        stats.total_failed += 1
                        await session.commit()

        # Update post status
        async with async_session_factory() as session:
            result = await session.execute(select(Post).where(Post.id == post_id))
            post = result.scalar_one_or_none()
            if post:
                result = await session.execute(
                    select(func.count(PostRecipient.id))
                    .where(PostRecipient.post_id == post_id, PostRecipient.status == "failed")
                )
                failed_count = result.scalar() or 0

                post.status = "failed" if failed_count > 0 else "sent"
                post.sent_at = datetime.now()
                await session.commit()

    except Exception as e:
        logger.error(f"Error processing post {post_id}: {e}")


# ==================== BAN / UNBAN ====================

@router.post("/customers/{user_id}/ban")
async def ban_customer(request: Request, user_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        user.is_blocked = True
        await session.commit()

    return RedirectResponse(url="/customers", status_code=302)


@router.post("/customers/{user_id}/unban")
async def unban_customer(request: Request, user_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        user.is_blocked = False
        await session.commit()

    return RedirectResponse(url="/customers", status_code=302)
