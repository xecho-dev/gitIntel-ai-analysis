"""
Admin 管理端相关路由 (/api/admin/*)
用户管理、分析历史管理等
"""
from fastapi import APIRouter, Depends, Query, HTTPException

from dependencies import get_current_admin, get_sb_client
from schemas.history import (
    AdminOverviewResponse,
    AdminUserListResponse,
    AdminHistoryListResponse,
    AdminHistoryDetailResponse,
    AdminUserHistoryResponse,
    LangSmithTraceInfo,
)
from services.database import (
    db_get_overview_stats,
    db_get_all_users,
    db_update_user,
    db_get_filtered_history,
    db_get_history_by_id,
    db_get_user_by_id,
    db_get_user_analysis_history,
)
from services.langsmith_service import get_langsmith_stats

router = APIRouter(prefix="/api/admin", tags=["admin-management"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def api_admin_overview(admin: dict = Depends(get_current_admin)):
    """系统概览统计数据（需登录）。"""
    sb = get_sb_client()

    try:
        stats = db_get_overview_stats(sb)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users", response_model=AdminUserListResponse)
async def api_admin_list_users(
    admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: str | None = Query(None),
):
    """管理端：获取全部用户列表（分页）"""
    sb = get_sb_client()
    return db_get_all_users(sb, page, page_size, search)


@router.put("/users/{user_id}", response_model=dict)
async def api_admin_update_user(
    user_id: str,
    body: dict,
    admin: dict = Depends(get_current_admin),
):
    """管理端：更新指定用户（如禁用/启用）"""
    sb = get_sb_client()

    ok = db_update_user(sb, user_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True}


@router.get("/analysis-history", response_model=AdminHistoryListResponse)
async def api_admin_list_history(
    admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: str | None = Query(None),
    user_id: str | None = Query(None),
    risk_level: str | None = Query(None, description="高危|中等|极低"),
    quality_score_min: float | None = Query(None, ge=0, le=100),
    quality_score_max: float | None = Query(None, ge=0, le=100),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    repo_name: str | None = Query(None),
    branch: str | None = Query(None),
):
    """管理端：获取全站所有用户的分析历史（支持高级筛选分页）"""
    sb = get_sb_client()

    return db_get_filtered_history(
        sb,
        page=page,
        page_size=page_size,
        user_id=user_id,
        risk_level=risk_level,
        quality_score_min=quality_score_min,
        quality_score_max=quality_score_max,
        date_from=date_from,
        date_to=date_to,
        repo_name=repo_name,
        branch=branch,
        search=search,
    )


@router.get("/analysis-history/{record_id}", response_model=dict)
async def api_admin_history_detail(
    record_id: str,
    admin: dict = Depends(get_current_admin),
):
    """管理端：获取单条分析记录的完整详情"""
    sb = get_sb_client()

    history = db_get_history_by_id(sb, record_id)
    if not history:
        raise HTTPException(status_code=404, detail="记录不存在")

    user = db_get_user_by_id(sb, history.user_id)

    # 调用 LangSmith API 获取真实追踪数据
    langsmith_info = None
    ls_stats = get_langsmith_stats(
        repo_name=history.repo_name,
        trace_id=history.langsmith_trace_id,
        thread_id=history.thread_id,
        created_at=history.created_at,
    )
    if ls_stats:
        langsmith_info = LangSmithTraceInfo(
            project_name=ls_stats.project_name,
            run_url=ls_stats.run_url,
            trace_id=ls_stats.trace_id,
            total_tokens=ls_stats.total_tokens,
            total_cost_usd=ls_stats.total_cost_usd,
            total_runs=ls_stats.total_runs,
            agents=ls_stats.agents,
            total_prompt_tokens=ls_stats.total_prompt_tokens,
            total_completion_tokens=ls_stats.total_completion_tokens,
            total_duration_ms=ls_stats.total_duration_ms,
        )

    return AdminHistoryDetailResponse(
        history=history,
        user=user,
        langsmith=langsmith_info,
    ).model_dump(mode="json")


@router.get("/users/{user_id}/history", response_model=dict)
async def api_admin_user_history(
    user_id: str,
    admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: str | None = Query(None),
):
    """管理端：获取指定用户的分析历史（包含用户信息）"""
    sb = get_sb_client()

    user = db_get_user_by_id(sb, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    history = db_get_user_analysis_history(sb, user_id, page, page_size, search)
    return AdminUserHistoryResponse(user=user, history=history).model_dump(mode="json")
