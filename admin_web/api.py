from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import async_session_factory
from bot.models import Product, Category, Order, OrderItem, User, Notification

router = APIRouter()


@router.get("/orders")
async def api_get_orders(status: str = Query(None)):
    async with async_session_factory() as session:
        query = select(Order).order_by(Order.created_at.desc())
        if status:
            query = query.where(Order.status == status)
        result = await session.execute(query)
        orders = result.scalars().all()
        return [
            {
                "id": o.id,
                "status": o.status,
                "total_price": o.total_price,
                "delivery_address": o.delivery_address,
                "delivery_date": str(o.delivery_date) if o.delivery_date else None,
                "phone": o.phone,
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ]


@router.get("/orders/{order_id}")
async def api_get_order(order_id: int):
    async with async_session_factory() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
        items = result.scalars().all()
        return {
            "id": order.id,
            "status": order.status,
            "total_price": order.total_price,
            "delivery_address": order.delivery_address,
            "delivery_date": str(order.delivery_date) if order.delivery_date else None,
            "delivery_time": str(order.delivery_time) if order.delivery_time else None,
            "phone": order.phone,
            "comment": order.comment,
            "created_at": order.created_at.isoformat(),
            "items": [
                {
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in items
            ],
        }


@router.patch("/orders/{order_id}/status")
async def api_update_order_status(order_id: int, status: str):
    async with async_session_factory() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        order.status = status
        await session.commit()
    return {"status": "ok"}


@router.get("/products")
async def api_get_products():
    async with async_session_factory() as session:
        result = await session.execute(select(Product).where(Product.is_active == True).order_by(Product.id))
        products = result.scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "category_id": p.category_id,
                "composition": p.composition,
                "image_url": p.image_url,
            }
            for p in products
        ]


@router.get("/categories")
async def api_get_categories():
    async with async_session_factory() as session:
        result = await session.execute(select(Category).where(Category.is_active == True))
        categories = result.scalars().all()
        return [{"id": c.id, "name": c.name} for c in categories]


@router.get("/users")
async def api_get_users():
    async with async_session_factory() as session:
        result = await session.execute(select(User).order_by(User.created_at.desc()).limit(100))
        users = result.scalars().all()
        return [
            {
                "id": u.id,
                "telegram_id": u.telegram_id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ]


@router.get("/stats")
async def api_get_stats():
    async with async_session_factory() as session:
        total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
        revenue = (await session.execute(select(func.sum(Order.total_price)).where(Order.status == "delivered"))).scalar() or 0
        total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
        active_products = (await session.execute(select(func.count(Product.id)).where(Product.is_active == True))).scalar() or 0
        return {
            "total_orders": total_orders,
            "revenue": revenue,
            "total_users": total_users,
            "active_products": active_products,
        }


@router.get("/notifications/unread")
async def api_get_unread_notifications():
    """Get count of unread notifications (sent=False)."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(func.count(Notification.id)).where(Notification.sent == False)
        )
        count = result.scalar() or 0
        return {"count": count}


@router.get("/notifications/recent")
async def api_get_recent_notifications(limit: int = 10):
    """Get recent unread notifications with user info."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Notification)
            .where(Notification.sent == False)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        notifs = result.scalars().all()

        items = []
        for n in notifs:
            user = None
            if n.user_id:
                result_u = await session.execute(select(User).where(User.id == n.user_id))
                user = result_u.scalar_one_or_none()

            user_name = user.first_name if user else (user.username if user else f"ID: {n.telegram_id}")

            items.append({
                "id": n.id,
                "user_id": user.id if user else None,
                "user_name": user_name,
                "telegram_id": n.telegram_id,
                "text": n.text,
                "created_at": n.created_at.isoformat(),
            })

        return {"notifications": items}


@router.post("/notifications/mark-read")
async def api_mark_notifications_read():
    """Mark all notifications as read (sent=True)."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Notification).where(Notification.sent == False)
        )
        notifs = result.scalars().all()
        for n in notifs:
            n.sent = True
        count = len(notifs)
        await session.commit()
    return {"marked": count}
