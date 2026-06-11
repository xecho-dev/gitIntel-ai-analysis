"""
Admin 认证相关路由 (/api/admin/*)
管理员登录、注销、个人信息
"""
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import APIRouter, Request, Depends

from dependencies import get_current_admin, get_db


router = APIRouter(prefix="/api/admin", tags=["admin-auth"])


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    expires_at: str
    user: dict


@router.post("/login", response_model=AdminLoginResponse)
async def api_admin_login(req: AdminLoginRequest, request: Request):
    """
    管理员登录接口。
    验证用户名密码，签发 token，返回给前端存储。
    """
    from middleware.admin_auth import get_admin_user_by_username, verify_password, create_admin_token

    pool = await get_db()
    admin_user = await get_admin_user_by_username(pool, req.username)
    if not admin_user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(req.password, admin_user["password_hash"]):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    token, expires_at = await create_admin_token(
        pool,
        admin_user_id=admin_user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE admin_users SET last_login_at = $1 WHERE id = $2",
                datetime.now(timezone.utc),
                admin_user["id"],
            )
    except Exception:
        pass

    return AdminLoginResponse(
        token=token,
        expires_at=expires_at.isoformat(),
        user={
            "id": admin_user["id"],
            "username": admin_user["username"],
            "nickname": admin_user.get("nickname") or admin_user["username"],
            "avatar": admin_user.get("avatar"),
            "role": admin_user.get("role", "admin"),
        },
    )


@router.post("/logout")
async def api_admin_logout(request: Request, admin: dict = Depends(get_current_admin)):
    """注销当前 token（删除服务端 token 记录）。"""
    from middleware.admin_auth import revoke_admin_token

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    pool = await get_db()
    await revoke_admin_token(pool, token)
    return {"success": True, "admin": admin}


@router.get("/me")
async def api_admin_me(admin: dict = Depends(get_current_admin)):
    """获取当前登录管理员信息。"""
    return admin
