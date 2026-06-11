"""
管理员身份验证中间件和实用程序。
使用本地 PostgreSQL 数据库验证管理员令牌。
"""
import os
import secrets
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

import asyncpg


def _generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(32)


async def create_admin_token(
    pool: asyncpg.Pool,
    admin_user_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[str, datetime]:
    """
    Issue a new admin login token, store it in admin_tokens table.
    Returns (token, expires_at).
    """
    async with pool.acquire() as conn:
        token = _generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ADMIN_TOKEN_TTL_HOURS)

        await conn.execute(
            """
            INSERT INTO admin_tokens (admin_user_id, token, expires_at, ip_address, user_agent)
            VALUES ($1, $2, $3, $4, $5)
            """,
            admin_user_id,
            token,
            expires_at,
            ip_address,
            user_agent,
        )

    return token, expires_at


async def verify_admin_token(pool: asyncpg.Pool, token: str) -> Optional[dict]:
    """
    Verify an admin token. Returns the admin_user row if valid and not expired.
    Returns None if invalid or expired.
    """
    if not token:
        return None

    async with pool.acquire() as conn:
        token_row = await conn.fetchrow(
            """
            SELECT admin_user_id, expires_at FROM admin_tokens
            WHERE token = $1 AND expires_at > NOW()
            """,
            token,
        )

        if token_row is None:
            return None

        admin_user_id = token_row["admin_user_id"]

        user_row = await conn.fetchrow(
            """
            SELECT id, username, nickname, avatar, role FROM admin_users
            WHERE id = $1 AND is_active = true
            """,
            admin_user_id,
        )

        if user_row is None:
            return None

        return {
            "id": str(user_row["id"]),
            "username": user_row["username"],
            "nickname": user_row["nickname"],
            "avatar": user_row["avatar"],
            "role": user_row["role"],
        }


async def revoke_admin_token(pool: asyncpg.Pool, token: str) -> bool:
    """Revoke (delete) an admin token."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM admin_tokens WHERE token = $1",
            token,
        )
        return result != "DELETE 0"


async def revoke_all_tokens_for_user(pool: asyncpg.Pool, admin_user_id: str) -> int:
    """Revoke all tokens for a given admin user."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM admin_tokens WHERE admin_user_id = $1",
            admin_user_id,
        )
        import re
        m = re.match(r"DELETE (\d+)", result)
        return int(m.group(1)) if m else 0


async def require_admin_auth(request: Request, pool: asyncpg.Pool) -> dict:
    """
    FastAPI dependency: verify the admin token from Authorization header.
    Raises HTTPException 401 if invalid.
    Returns the admin user dict on success.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少管理员授权凭证")

    token = auth_header[7:]
    admin = await verify_admin_token(pool, token)
    if not admin:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    return admin


async def get_admin_user_by_username(pool: asyncpg.Pool, username: str) -> Optional[dict]:
    """Look up an admin user by username (for login verification)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM admin_users WHERE username = $1 AND is_active = true",
            username,
        )
        if row is None:
            return None
        return dict(row)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
