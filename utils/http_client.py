"""HTTP client manager with connection pooling and thread safety"""

import asyncio
from typing import Optional

import httpx
from loguru import logger


class HTTPClientManager:
    """Manages a shared HTTP client with connection pooling

    Thread-safe singleton pattern ensures only one client instance is created,
    avoiding connection leaks and improving performance through connection reuse.
    """

    _client: Optional[httpx.AsyncClient] = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def get_client(
        cls,
        timeout: float = 30.0,
        connect_timeout: float = 10.0,
        max_keepalive_connections: int = 50,
        max_connections: int = 100,
    ) -> httpx.AsyncClient:
        """Get or create a shared HTTP client

        Args:
            timeout: Total request timeout in seconds
            connect_timeout: Connection timeout in seconds
            max_keepalive_connections: Maximum keep-alive connections
            max_connections: Maximum total connections

        Returns:
            Shared httpx.AsyncClient instance
        """
        # Fast path: client already exists and is open
        if cls._client is not None and not cls._client.is_closed:
            return cls._client

        # Slow path: need to create client (with lock for thread safety)
        async with cls._lock:
            # Double-check after acquiring lock
            if cls._client is not None and not cls._client.is_closed:
                return cls._client

            # Create new client with connection pooling
            timeout_config = httpx.Timeout(
                timeout,
                connect=connect_timeout,
                pool=connect_timeout,
            )
            limits = httpx.Limits(
                max_keepalive_connections=max_keepalive_connections,
                max_connections=max_connections,
            )

            cls._client = httpx.AsyncClient(
                timeout=timeout_config,
                limits=limits,
                http2=True,  # Enable HTTP/2 for better performance
            )

            logger.debug(
                f"Created HTTP client: max_connections={max_connections}, " f"keepalive={max_keepalive_connections}"
            )

            return cls._client

    @classmethod
    async def close(cls) -> None:
        """Close the shared HTTP client and release resources"""
        async with cls._lock:
            if cls._client is not None and not cls._client.is_closed:
                await cls._client.aclose()
                logger.debug("HTTP client closed")
            cls._client = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if the HTTP client is available"""
        return cls._client is not None and not cls._client.is_closed


async def get_http_client() -> httpx.AsyncClient:
    """Convenience function to get the shared HTTP client"""
    return await HTTPClientManager.get_client()


async def close_http_client() -> None:
    """Convenience function to close the shared HTTP client"""
    await HTTPClientManager.close()
