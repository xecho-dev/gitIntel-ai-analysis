"""
用户资料相关路由 (/api/user)
用户资料查询和更新
"""
from fastapi import APIRouter, Request

from dependencies import get_auth_user_id, get_sb_client
from schemas.history import UpsertUserRequest, UserProfile
from services.database import get_user_profile, upsert_user

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/profile", response_model=UserProfile)
async def api_get_profile(request: Request):
    """获取当前用户资料。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    profile = get_user_profile(sb, auth_user_id)
    if not profile:
        # 新用户：自动创建一行，login 用 auth_user_id 前8位做占位
        placeholder_login = auth_user_id[:8]
        upsert_user(sb, auth_user_id, {"login": placeholder_login})
        profile = get_user_profile(sb, auth_user_id)
    return profile


@router.post("/profile", response_model=UserProfile)
async def api_upsert_profile(req: UpsertUserRequest, request: Request):
    """创建或更新用户资料（通常在登录后由前端调用，同步 GitHub 信息）。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()
    return upsert_user(sb, auth_user_id, req.model_dump())
