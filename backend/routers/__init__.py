"""
路由汇总
"""
from .analysis import router as analysis_router
from .history import router as history_router
from .user import router as user_router
from .export import router as export_router
from .git_ops import router as git_ops_router
from .pr import router as pr_router
from .chat import router as chat_router
from .admin import auth_router, management_router as admin_management_router

__all__ = [
    "analysis_router",
    "history_router",
    "user_router",
    "export_router",
    "git_ops_router",
    "pr_router",
    "chat_router",
    "auth_router",
    "admin_management_router",
]
