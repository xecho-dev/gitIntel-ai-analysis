"""
管理员身份验证中间件和实用程序。
使用Supabase验证登录时颁发的管理员令牌。
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

from supabase_client import get_supabase_admin


ADMIN_TOKEN_TTL_HOURS = int(os.getenv("ADMIN_TOKEN_TTL_HOURS", "24"))


def _generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(32)


def create_admin_token(
    admin_user_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[str, datetime]:
    """
    Issue a new admin login token, store it in admin_tokens table.
    Returns (token, expires_at).
    """
    sb = get_supabase_admin()
    token = _generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ADMIN_TOKEN_TTL_HOURS)

    sb.table("admin_tokens").insert({
        "admin_user_id": admin_user_id,
        "token": token,
        "expires_at": expires_at.isoformat(),
        "ip_address": ip_address,
        "user_agent": user_agent,
    }).execute()

    return token, expires_at


def verify_admin_token(token: str) -> Optional[dict]:
    """
    Verify an admin token. Returns the admin_user row if valid and not expired.
    Returns None if invalid or expired.
    """
    if not token:
        return None

    sb = get_supabase_admin()

    # Two-step query: first find token, then look up user (avoids FK schema-cache issues)
    token_result = (
        sb.table("admin_tokens")
        .select("admin_user_id, expires_at")
        .eq("token", token)
        .gte("expires_at", datetime.now(timezone.utc).isoformat())
        .execute()
    )

    if not token_result.data:
        return None

    admin_user_id = token_result.data[0]["admin_user_id"]

    user_result = (
        sb.table("admin_users")
        .select("id, username, nickname, avatar, role")
        .eq("id", admin_user_id)
        .eq("is_active", True)
        .execute()
    )

    if not user_result.data:
        return None

    user = user_result.data[0]
    return {
        "id": user["id"],
        "username": user["username"],
        "nickname": user["nickname"],
        "avatar": user["avatar"],
        "role": user["role"],
    }


def revoke_admin_token(token: str) -> bool:
    """Revoke (delete) an admin token."""
    sb = get_supabase_admin()
    result = sb.table("admin_tokens").delete().eq("token", token).execute()
    return len(result.data) > 0


def revoke_all_tokens_for_user(admin_user_id: str) -> int:
    """Revoke all tokens for a given admin user."""
    sb = get_supabase_admin()
    result = sb.table("admin_tokens").delete().eq("admin_user_id", admin_user_id).execute()
    return len(result.data)


def require_admin_auth(request: Request) -> dict:
    """
    FastAPI dependency: verify the admin token from Authorization header.
    Raises HTTPException 401 if invalid.
    Returns the admin user dict on success.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少管理员授权凭证")

    token = auth_header[7:]
    admin = verify_admin_token(token)
    if not admin:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    return admin


def get_admin_user_by_username(username: str) -> Optional[dict]:
    """Look up an admin user by username (for login verification)."""
    sb = get_supabase_admin()
    result = (
        sb.table("admin_users")
        .select("*")
        .eq("username", username)
        .eq("is_active", True)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
