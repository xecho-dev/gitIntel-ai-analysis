"""
共享依赖（Dependencies）
所有路由共用的认证和数据库连接依赖
"""
from fastapi import Request, HTTPException
from supabase_client import get_supabase_admin
from middleware.auth import require_auth


def get_current_admin(request: Request) -> dict:
    """
    管理员认证依赖。
    从 Authorization header 中验证 admin token，验证失败抛出 401。
    成功时返回管理员信息 dict: {id, username, nickname, avatar, role}
    """
    from middleware.admin_auth import require_admin_auth
    return require_admin_auth(request)


def get_auth_user_id(request: Request) -> str:
    """
    获取当前登录用户的 auth_user_id。
    从 JWT payload 中提取 sub 或 id 字段。
    """
    payload = require_auth(request)
    auth_user_id = payload.get("sub") or payload.get("id") or ""
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="无法识别用户身份")
    return auth_user_id


def get_sb_client() -> "Client":
    """
    获取 Supabase Admin 客户端（绕过 RLS）。
    连接失败时抛出 503 错误。
    """
    try:
        return get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


def require_user_profile(sb: "Client", auth_user_id: str) -> str:
    """
    确保用户已完成 GitHub 资料同步（users 表中有记录）。
    返回 user_uuid，失败时抛出 HTTPException。
    """
    from services.database import get_user_uuid
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        raise HTTPException(
            status_code=404,
            detail="用户资料未同步，请先在账户中心完成 GitHub 资料同步。",
        )
    return str(user_uuid)
