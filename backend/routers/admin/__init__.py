"""
Admin 子路由汇总
"""
from .auth import router as auth_router
from .management import router as management_router

__all__ = ["auth_router", "management_router"]
