"""
Admin 认证相关路由 (/api/admin/*)
管理员登录、注销、个人信息
"""
from datetime import datetime, timezone

from pydantic import BaseModel
from fastapi import APIRouter, Request, Depends, HTTPException

from dependencies import get_current_admin, get_sb_client
from supabase_client import get_supabase_admin

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
    from middleware.admin_auth import (
        get_admin_user_by_username,
        verify_password,
        create_admin_token,
    )

    # 1. 查询用户
    admin_user = get_admin_user_by_username(req.username)
    if not admin_user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 2. 验证密码
    if not verify_password(req.password, admin_user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 3. 生成 token 并记录
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    token, expires_at = create_admin_token(
        admin_user_id=admin_user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    # 4. 更新最后登录时间
    try:
        sb = get_supabase_admin()
        sb.table("admin_users").update({
            "last_login_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", admin_user["id"]).execute()
    except Exception:
        pass  # 不影响登录流程

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
async def api_admin_logout(
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """注销当前 token（删除服务端 token 记录）。"""
    from middleware.admin_auth import revoke_admin_token

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    revoke_admin_token(token)
    return {"success": True, "admin": admin}


@router.get("/me")
async def api_admin_me(admin: dict = Depends(get_current_admin)):
    """获取当前登录管理员信息。"""
    return admin
