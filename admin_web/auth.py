import bcrypt

from bot.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


def is_authenticated(request) -> bool:
    session = request.cookies.get("session")
    return session == "authenticated"


def require_auth(request) -> None:
    """Check if user is authenticated via session cookie"""
    if not is_authenticated(request):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Redirect to login"
        )
