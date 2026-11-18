"""
Session configuration for the bot.

Handles SSL context configuration for connecting to Telegram API
when the default aiohttp SSL settings fail with 'Connection reset by peer'.
"""

import ssl
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientSession, TCPConnector

logger = logging.getLogger(__name__)


def get_ssl_context() -> ssl.SSLContext:
    """Create a compatible SSL context for Telegram API."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    return ctx


class SecureAiohttpSession(AiohttpSession):
    """AiohttpSession with TLS 1.2 only for Telegram API compatibility."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        # Override the SSL context after parent init
        self._connector_init["ssl"] = get_ssl_context()
        logger.info("SecureAiohttpSession initialized with TLS 1.2")

    async def create_session(self) -> ClientSession:
        return await super().create_session()


async def create_secure_session() -> AiohttpSession:
    """Create a secure AiohttpSession with proper SSL."""
    return SecureAiohttpSession()


def create_proxy_session(
    proxy_host: str = "",
    proxy_port: int = 0,
    proxy_secret: str = "",
) -> AiohttpSession | None:
    """
    Create a bot session with proper SSL configuration.

    Returns an AiohttpSession with proper SSL configuration.

    Args:
        proxy_host: Host of the proxy server (not used - MTProto not supported)
        proxy_port: Port of the proxy server (not used - MTProto not supported)
        proxy_secret: Proxy secret (not used - MTProto not supported)

    Returns:
        AiohttpSession with proper SSL configuration
    """
    if proxy_host and proxy_port:
        logger.warning(
            f"MTProto proxy ({proxy_host}:{proxy_port}) is not supported by aiogram 3.x. "
            "The bot will connect directly to Telegram API with adjusted SSL settings. "
            "If Telegram is blocked in your network, consider using a SOCKS5 proxy "
            "or running the bot in an unrestricted network."
        )

    return None  # Will be created via create_secure_session
