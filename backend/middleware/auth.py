import os
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

bearer_scheme = HTTPBearer(auto_error=False)


def decode_jwt_token(token: str) -> Optional[dict]:
    """使用 JWT_SECRET 验证并解码 NextAuth 发行的 JWT"""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        return None
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except JWTError:
        return None


def get_token_from_request(request: Request) -> Optional[str]:
    """从请求中提取 Bearer token"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    credentials: HTTPAuthorizationCredentials | None = bearer_scheme(request)
    if credentials:
        return credentials.credentials
    return None


def require_auth(request: Request) -> dict:
    """验证请求中的 JWT，返回解码后的 payload。用于保护 API 端点。"""
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录，请先使用 GitHub 账号登录")

    payload = decode_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    return payload
