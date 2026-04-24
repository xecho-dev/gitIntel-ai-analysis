"""
Git 操作相关路由 (/api/git)
本地 Git 状态和 commit 操作
"""
from pydantic import BaseModel

from fastapi import APIRouter, Request, HTTPException

from dependencies import get_auth_user_id
from services.git_service import get_git_status, get_staged_diff, run_git_commit

router = APIRouter(prefix="/api/git", tags=["git"])


class GitCommitRequest(BaseModel):
    message: str


@router.post("/commit")
async def api_git_commit(req: GitCommitRequest, request: Request):
    """
    执行 git commit（需要认证）。
    返回 staged diff 列表供前端预览。
    """
    auth_user_id = get_auth_user_id(request)

    # 获取当前 staged diff（预览用）
    staged_diffs = get_staged_diff(repo_path=".")

    # 执行 commit
    result = run_git_commit(req.message, repo_path=".")

    if result.success:
        return {
            "success": True,
            "commit_hash": result.commit_hash,
            "message": result.message,
            "staged_diffs": [
                {"filename": d.filename, "diff": d.diff} for d in staged_diffs
            ],
        }
    else:
        raise HTTPException(status_code=400, detail=result.error or "提交失败")


@router.get("/status")
async def api_git_status(request: Request):
    """获取当前 git 状态和 staged diff（需要认证）。"""
    auth_user_id = get_auth_user_id(request)

    status = get_git_status(repo_path=".")
    staged_diffs = get_staged_diff(repo_path=".")

    return {
        "is_repo": status.is_repo,
        "current_branch": status.current_branch,
        "staged_files": status.staged_files,
        "unstaged_files": status.unstaged_files,
        "untracked_files": status.untracked_files,
        "clean": status.clean,
        "staged_diffs": [
            {"filename": d.filename, "diff": d.diff} for d in staged_diffs
        ],
    }
