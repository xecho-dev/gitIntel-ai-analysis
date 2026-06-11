"""
PostgreSQL 连接池管理（asyncpg）
替代 supabase_client.py，统一提供连接池而非每次创建新连接。
"""
import asyncpg
import os
import logging

logger = logging.getLogger("gitintel")

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """返回全局连接池，首次调用时创建。"""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Please set it to a PostgreSQL connection string "
                "(e.g. postgresql://user:pass@host:5432/gitintel)"
            )
        logger.info("[postgres_client] Creating connection pool...")
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=20,
            command_timeout=60,
        )
        logger.info("[postgres_client] Connection pool created.")
    return _pool


async def close_pool() -> None:
    """关闭全局连接池（应用 shutdown 时调用）。"""
    global _pool
    if _pool is not None:
        logger.info("[postgres_client] Closing connection pool...")
        await _pool.close()
        _pool = None
        logger.info("[postgres_client] Connection pool closed.")
