from services.pdf_service import build_pdf_bytes

import io
import json
import os
import logging
from contextlib import asynccontextmanager

from pydantic import BaseModel
from typing import Any
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv(override=True)  # 明确指定 backend 目录下的 .env

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# 设置 uvicorn 日志级别
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.setLevel(logging.INFO)
gitintel_logger = logging.getLogger("gitintel")
gitintel_logger.setLevel(logging.DEBUG)

from agents import BaseAgent, AgentEvent
from graph.analysis_graph import stream_analysis_sse
from middleware.auth import require_auth
from schemas.request import AnalyzeRequest, ExportPdfRequest
from schemas.response import HealthResponse
from schemas.history import (
    SaveAnalysisRequest,
    HistoryListResponse,
    UpsertUserRequest,
    UserProfile,
)
from services.database import (
    save_analysis,
    get_history,
    delete_analysis,
    upsert_user,
    get_user_profile,
    get_user_uuid,
)
from services.git_service import get_git_status, get_staged_diff, run_git_commit
from services.github_pr_service import GitHubPRService
from agents.fix_generator import FixGeneratorAgent
from supabase_client import get_supabase_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    print("GitIntel Agent Layer started")
    yield
    # 关闭时执行
    print("GitIntel Agent Layer stopped")


app = FastAPI(
    title="GitIntel Agent API",
    description="AI-powered GitHub repository analysis",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
_allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if os.getenv("FRONTEND_URL"):
    _allowed_origins.append(os.getenv("FRONTEND_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    return HealthResponse(status="ok")


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest, request: Request):
    """分析仓库 - SSE 流式响应（需要登录）。分析完成后自动保存到数据库。"""
    import logging
    logger = logging.getLogger("gitintel")

    logger.info(f"[/api/analyze] 收到请求: repo_url={req.repo_url}, branch={req.branch}")

    user = require_auth(request)
    auth_user_id = user.get("sub") or user.get("id") or ""
    logger.info(f"[/api/analyze] 认证通过: auth_user_id={auth_user_id}")

    async def event_stream():
        collected_events: list[dict] = []

        def collect(event_str: str) -> str:
            """解析并收集 result 类型的事件"""
            if event_str.startswith("data: "):
                data = event_str[6:].strip()
                if data and data != "[DONE]":
                    try:
                        parsed = json.loads(data)
                        if isinstance(parsed, dict) and parsed.get("type") == "result" and parsed.get("agent"):
                            collected_events.append(parsed)
                    except Exception:
                        pass
            return event_str

        try:
            async for event in stream_analysis_sse(req.repo_url, req.branch):
                yield collect(event)
        except Exception as e:
            logger.error(f"[/api/analyze] stream 异常: {type(e).__name__}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

        # SSE 结束，收集完毕，保存到数据库
        if not collected_events:
            logger.warning(f"[/api/analyze] 无 result 事件，跳过保存")
            return

        # 聚合 result_data
        result_data: dict[str, Any] = {}
        for evt in collected_events:
            agent = evt.get("agent", "")
            data = evt.get("data")
            if agent and data:
                result_data[agent] = data

        if not result_data:
            logger.warning(f"[/api/analyze] result_data 为空，跳过保存")
            return

        logger.info(f"[/api/analyze] 分析完成，准备保存 history，agents={list(result_data.keys())}")

        try:
            sb = get_supabase_admin()
        except RuntimeError as e:
            logger.error(f"[/api/analyze] Supabase 连接失败: {e}")
            return

        # save_analysis 第一个参数必须是 NextAuth 的 auth_user_id（sub），不是 users 表的主键 id
        if not get_user_uuid(sb, auth_user_id):
            logger.warning(
                f"[/api/analyze] users 表中无 auth_user_id={auth_user_id}，跳过保存。"
                "请先访问账户页完成 GitHub 资料同步。"
            )
            return

        try:
            saved = save_analysis(sb, auth_user_id, req.repo_url, req.branch, result_data)
            logger.info(f"[/api/analyze] 历史记录保存成功: id={saved.id}")
        except Exception as e:
            logger.error(f"[/api/analyze] 保存历史记录失败: {type(e).__name__}: {e}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── 分析历史 API ──────────────────────────────────────────────

@app.get("/api/history", response_model=HistoryListResponse)
async def api_get_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
):
    """获取当前用户的分析历史（分页）。"""
    payload = require_auth(request)
    auth_user_id = payload.get("sub") or payload.get("id")
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return get_history(sb, auth_user_id, page, page_size, search)


@app.post("/api/history/save", response_model=dict)
async def api_save_analysis(req: SaveAnalysisRequest, request: Request):
    """保存一次完整的分析结果到数据库。"""
    payload = require_auth(request)
    auth_user_id = payload.get("sub") or payload.get("id")
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not get_user_uuid(sb, auth_user_id):
        raise HTTPException(
            status_code=404,
            detail="用户资料未同步，请先在账户中心完成 GitHub 资料同步后再保存。",
        )

    result = save_analysis(sb, auth_user_id, req.repo_url, req.branch, req.result_data)
    return {"id": result.id, "created_at": result.created_at}


@app.delete("/api/history/{history_id}", response_model=dict)
async def api_delete_history(history_id: str, request: Request):
    """删除指定历史记录。"""
    payload = require_auth(request)
    auth_user_id = payload.get("sub") or payload.get("id")
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    ok = delete_analysis(sb, auth_user_id, history_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在或无权限删除")
    return {"deleted": True}


# ─── 用户资料 API ──────────────────────────────────────────────

@app.get("/api/user/profile", response_model=UserProfile)
async def api_get_profile(request: Request):
    """获取当前用户资料。"""
    payload = require_auth(request)
    auth_user_id = payload.get("sub") or payload.get("id")
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    profile = get_user_profile(sb, auth_user_id)
    if not profile:
        # 新用户：自动创建一行，login 用 auth_user_id 前8位做占位
        placeholder_login = auth_user_id[:8]
        upsert_user(sb, auth_user_id, {
            "login": placeholder_login,
        })
        profile = get_user_profile(sb, auth_user_id)
    return profile


@app.post("/api/user/profile", response_model=UserProfile)
async def api_upsert_profile(req: UpsertUserRequest, request: Request):
    """创建或更新用户资料（通常在登录后由前端调用，同步 GitHub 信息）。"""
    payload = require_auth(request)
    auth_user_id = payload.get("sub") or payload.get("id")
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return upsert_user(sb, auth_user_id, req.model_dump())


# ─── PDF 导出 API ──────────────────────────────────────────────

@app.post("/api/export/pdf")
async def api_export_pdf(req: ExportPdfRequest, request: Request):
    """将分析结果导出为 PDF 报告（需要登录）"""
    payload = require_auth(request)
    if not (payload.get("sub") or payload.get("id")):
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    pdf_bytes = build_pdf_bytes({
        "repo_url": req.repo_url,
        "branch": req.branch,
        **req.result_data,
    })

    import re
    repo_name = re.sub(r"[^a-zA-Z0-9_-]", "_", req.repo_url.split("/")[-1].replace(".git", ""))
    filename = f"gitintel_{repo_name}_{req.branch}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─── Git Commit API ─────────────────────────────────────────────

class GitCommitRequest(BaseModel):
    message: str


@app.post("/api/git/commit")
async def api_git_commit(req: GitCommitRequest, request: Request):
    """
    执行 git commit（需要认证）。

    返回 staged diff 列表供前端预览。
    """
    payload = require_auth(request)
    if not (payload.get("sub") or payload.get("id")):
        raise HTTPException(status_code=401, detail="无法识别用户身份")

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


@app.get("/api/git/status")
async def api_git_status(request: Request):
    """
    获取当前 git 状态和 staged diff（需要认证）。
    """
    payload = require_auth(request)
    if not (payload.get("sub") or payload.get("id")):
        raise HTTPException(status_code=401, detail="无法识别用户身份")

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


# ─── PR Auto-Create API ────────────────────────────────────────────

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
    commit_message: str | None = None  # 自定义 commit message，为空时使用 fix.reason


@app.post("/api/pr/generate")
async def api_pr_generate(req: PRGenerateRequest, request: Request):
    """
    基于分析建议生成代码修改方案（FixGeneratorAgent）。
    返回 CodeFix[] 列表供前端预览。
    """
    payload = require_auth(request)
    if not (payload.get("sub") or payload.get("id")):
        raise HTTPException(status_code=401, detail="无法识别用户身份")

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


@app.post("/api/pr/create")
async def api_pr_create(req: PRCreateRequest, request: Request):
    """
    创建 GitHub Pull Request。
    流程：创建分支 → 提交文件修改 → 创建 PR
    """
    payload = require_auth(request)
    if not (payload.get("sub") or payload.get("id")):
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    # 检查 GITHUB_TOKEN
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    if not github_token:
        raise HTTPException(
            status_code=400,
            detail="未配置 GITHUB_TOKEN，无法创建 PR。请在环境变量中设置 GitHub Personal Access Token。"
        )

    service = GitHubPRService(token=github_token)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
