"""
历史记录相关路由 (/api/history)
用户的分析历史 CRUD 操作
"""
from fastapi import APIRouter, Query, Request, HTTPException

from dependencies import get_auth_user_id, get_sb_client
from schemas.history import SaveAnalysisRequest, HistoryListResponse
from services.database import save_analysis, get_history, delete_analysis, get_user_uuid

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=HistoryListResponse)
async def api_get_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
):
    """获取当前用户的分析历史（分页）。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()
    return get_history(sb, auth_user_id, page, page_size, search)


@router.post("/save", response_model=dict)
async def api_save_analysis(req: SaveAnalysisRequest, request: Request):
    """保存一次完整的分析结果到数据库。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    if not get_user_uuid(sb, auth_user_id):
        raise HTTPException(
            status_code=404,
            detail="用户资料未同步，请先在账户中心完成 GitHub 资料同步后再保存。",
        )

    result = save_analysis(sb, auth_user_id, req.repo_url, req.branch, req.result_data,
                           thread_id=f"{req.repo_url}::{req.branch}")
    return {"id": result.id, "created_at": result.created_at}


@router.delete("/{history_id}", response_model=dict)
async def api_delete_history(history_id: str, request: Request):
    """删除指定历史记录。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    ok = delete_analysis(sb, auth_user_id, history_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在或无权限删除")
    return {"deleted": True}
