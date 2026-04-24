"""
PR 相关路由 (/api/pr)
代码修改方案生成和 PR 创建
"""
import logging

from pydantic import BaseModel
from fastapi import APIRouter, Request, HTTPException

from dependencies import get_auth_user_id
from agents.fix_generator import FixGeneratorAgent
from services.github_pr_service import GitHubPRService

router = APIRouter(prefix="/api/pr", tags=["pr"])
logger = logging.getLogger("gitintel")


class PRGenerateRequest(BaseModel):
    """生成代码修改方案的请求。"""
    repo_url: str
    branch: str = "main"
    suggestions: list[dict]  # SuggestionAgent 返回的建议列表
    file_contents: dict | None = None  # 可选：文件内容字典


class PRCreateRequest(BaseModel):
    """创建 PR 的请求。"""
    repo_url: str
    branch: str = "main"
    fixes: list[dict]  # FixGeneratorAgent 返回的修改方案
    base_branch: str | None = None
    pr_title: str | None = None
    commit_message: str | None = None


@router.post("/generate")
async def api_pr_generate(req: PRGenerateRequest, request: Request):
    """
    基于分析建议生成代码修改方案（FixGeneratorAgent）。
    返回 CodeFix[] 列表供前端预览。
    """
    auth_user_id = get_auth_user_id(request)

    agent = FixGeneratorAgent()
    fixes_result = None

    async for event in agent.stream(
        repo_path=req.repo_url,
        branch=req.branch,
        suggestions=req.suggestions,
        file_contents=req.file_contents,
    ):
        if event["type"] == "result":
            fixes_result = event["data"]

    if not fixes_result:
        return {"success": False, "fixes": [], "error": "生成失败"}

    return {
        "success": True,
        "fixes": fixes_result.get("fixes", []),
        "total": fixes_result.get("total", 0),
        "message": fixes_result.get("message", ""),
    }


@router.post("/create")
async def api_pr_create(req: PRCreateRequest, request: Request):
    """
    创建 GitHub Pull Request。
    流程：创建分支 → 提交文件修改 → 创建 PR

    GitHub Token 从 BFF 通过 X-GitHub-Token header 传递（不经过 JWT 解码）。
    若未授权 repo 权限，直接报错，不允许使用服务端 GITHUB_TOKEN 降级。
    """
    auth_user_id = get_auth_user_id(request)

    # 直接从 BFF 传递的 header 读取 GitHub OAuth token
    user_github_token = request.headers.get("X-GitHub-Token")
    if not user_github_token:
        raise HTTPException(
            status_code=403,
            detail="GitHub 授权不足：创建 PR 需要用户的 GitHub OAuth Token（包含 repo 权限）。"
                   "请重新登录 GitHub 并授权 repo 权限后重试。",
        )

    logger.info("[PR Create] 使用用户 GitHub OAuth Token")
    service = GitHubPRService(token=user_github_token)
    result = await service.create_pr(
        repo_url=req.repo_url,
        branch=req.branch,
        fixes=req.fixes,
        base_branch=req.base_branch,
        pr_title=req.pr_title,
        commit_message=req.commit_message,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return {
        "success": True,
        "pr_url": result.pr_url,
        "pr_number": result.pr_number,
        "pr_title": result.pr_title,
        "is_fork": result.is_fork,
        "fork_url": result.fork_url,
    }
