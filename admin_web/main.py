import asyncio
import os
import uvicorn
import logging

from fastapi import FastAPI, Request, Form, HTTPException, Response

logger = logging.getLogger("bot_russia_flowers")
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from jinja2 import Environment, FileSystemLoader

from bot.config import settings
from bot.database import async_session_factory
from admin_web.auth import verify_password, is_authenticated, require_auth, get_password_hash

app = FastAPI(title="Цветы по русски — Админ-панель")

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Setup Jinja2 templates directly (avoids Starlette caching bug)
template_dir = os.path.join(os.path.dirname(__file__), "templates")
jinja_env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=True,
)

def render_template(filename: str, context: dict) -> str:
    template = jinja_env.get_template(filename)
    return template.render(**context)


# Dependency for DB session
async def get_db():
    async with async_session_factory() as session:
        yield session


# Import and include routers AFTER templates is defined
from admin_web import routes, api  # noqa: E402
routes.render_template = render_template  # noqa: E304
app.include_router(routes.router)
app.include_router(api.router, prefix="/api")


# Login page
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return HTMLResponse(content=render_template("login.html", {"request": request}))


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == settings.web_admin_user and verify_password(password, get_password_hash(settings.web_admin_password)):
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(key="session", value="authenticated", httponly=True)
        return response
    return HTMLResponse(
        content=render_template("login.html", {"request": request, "error": "Неверный логин или пароль"})
    )


# Logout
@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="session")
    return response


# Root - dashboard
@app.get("/")
async def dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=307)

    async with async_session_factory() as session:
        from bot.models import Order, User, Product
        from sqlalchemy import func, select

        total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
        revenue = (await session.execute(select(func.sum(Order.total_price)).where(Order.status == "delivered"))).scalar() or 0
        total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
        from sqlalchemy.orm import joinedload
        recent_orders = (await session.execute(
            select(Order).options(joinedload(Order.user)).order_by(Order.created_at.desc()).limit(50)
        )).scalars().all()

    status_labels = {
        "new": "🆕 Новый",
        "processing": "⏳ В обработке",
        "confirmed": "✅ Подтверждён",
        "delivered": "🚚 Доставлен",
        "cancelled": "❌ Отменён",
        "not_connected": "📵 Не дозвонились",
    }
    return HTMLResponse(content=render_template("dashboard.html", {
        "request": request,
        "total_orders": total_orders,
        "revenue": revenue,
        "total_users": total_users,
        "recent_orders": recent_orders,
        "status_labels": status_labels,
    }))


async def run_admin_web():
    """Run the admin web panel with uvicorn"""
    import socket
    
    # Check if port is already in use
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', settings.web_admin_port))
    sock.close()
    
    if result == 0:
        logger = __import__('bot.utils.logger', fromlist=['logger']).logger
        logger.warning(f"Port {settings.web_admin_port} is already in use. Admin panel may fail to start.")
    
    config = uvicorn.Config(
        app,
        host=settings.web_admin_host,
        port=settings.web_admin_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    
    try:
        await server.serve()
    except (SystemExit, OSError) as e:
        # Don't crash the whole bot if admin panel fails
        logger = __import__('bot.utils.logger', fromlist=['logger']).logger
        logger.error(f"Admin panel failed to start: {e}. Bot will continue running without web panel.")
