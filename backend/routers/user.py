"""
用户资料相关路由 (/api/user)
用户资料查询和更新
"""
from fastapi import APIRouter, Request

from dependencies import get_auth_user_id, get_db
from schemas.history import UpsertUserRequest, UserProfile
from services.database import get_user_profile, upsert_user

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/profile", response_model=UserProfile)
async def api_get_profile(request: Request):
    """获取当前用户资料。"""
    auth_user_id = get_auth_user_id(request)
    pool = await get_db()

    profile = await get_user_profile(pool, auth_user_id)
    if not profile:
        placeholder_login = auth_user_id[:8]
        await upsert_user(pool, auth_user_id, {"login": placeholder_login})
        profile = await get_user_profile(pool, auth_user_id)
    return profile


@router.post("/profile", response_model=UserProfile)
async def api_upsert_profile(req: UpsertUserRequest, request: Request):
    """创建或更新用户资料（通常在登录后由前端调用，同步 GitHub 信息）。"""
    auth_user_id = get_auth_user_id(request)
    pool = await get_db()
    return await upsert_user(pool, auth_user_id, req.model_dump())
