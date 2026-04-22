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
    AdminOverviewResponse,
    AdminUserListResponse,
    AdminHistoryListResponse,
)
from services.database import (
    save_analysis,
    get_history,
    delete_analysis,
    upsert_user,
    get_user_profile,
    get_user_uuid,
    db_get_overview_stats,
    db_get_all_users,
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
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
]
if os.getenv("FRONTEND_URL"):
    _allowed_origins.append(os.getenv("FRONTEND_URL"))
_allowed_origins.extend([
    "https://gitintel.top",
    "http://gitintel.top",
])

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
    """
    分析仓库 - SSE 流式响应（需要登录）。分析完成后自动保存到数据库。

    流程概述:
    1. 用户认证（从请求中提取 auth token）
    2. 生成 thread_id（用于 LangGraph checkpoint 和 LangSmith 关联）
    3. 启动 SSE 流，实时推送分析进度和结果
    4. 流结束后，收集所有 Agent 的 result 事件并保存到数据库
    """
    import logging
    logger = logging.getLogger("gitintel")

    logger.info(f"[/api/analyze] 收到请求: repo_url={req.repo_url}, branch={req.branch}")

    # ─── Step 1: 用户认证 ────────────────────────────────────────
    # require_auth 从请求的 cookie/header 中解析 JWT，验证用户身份
    user = require_auth(request)
    # 获取用户的 auth_user_id（来自 Supabase Auth 的唯一标识）
    # 兼容不同版本的 Supabase 返回格式（"sub" 或 "id"）
    auth_user_id = user.get("sub") or user.get("id") or ""
    logger.info(f"[/api/analyze] 认证通过: auth_user_id={auth_user_id}")

    # ─── Step 2: 生成 thread_id ─────────────────────────────────
    # LangGraph 使用 thread_id 来恢复/checkpoint 工作流状态
    # 同时用于在 LangSmith 中关联同一次分析的所有 trace
    thread_id = f"{req.repo_url}::{req.branch}"

    # ─── Step 3: SSE 流式响应 ───────────────────────────────────
    def event_stream():
        # 立即发送初始事件，解锁 HTTP 响应头和 StreamingResponse 的初始传输
        # 否则 FastAPI/uvicorn 可能在等待第一个 yield 后才发送 HTTP headers，
        # 导致客户端长时间无响应
        yield "data: {\"type\": \"connected\", \"agent\": \"pipeline\", \"message\": \"连接已建立，开始分析...\", \"percent\": 0}\n\n"

        # collected_events 用于在流结束后聚合同一 agent 的 result 事件
        collected_events: list[dict] = []

        def collect(event_str: str) -> str:
            """
            解析 SSE 事件字符串，收集 type=result 的事件。

            SSE 格式示例:
                data: {"type": "status", "agent": "architecture", "message": "..."}
                data: {"type": "result", "agent": "architecture", "data": {...}}
                data: [DONE]

            只有 type=result 且包含 agent 字段的事件才需要保存（包含最终分析数据）
            """
            # 处理 [DONE] 事件（可能被错误地包装为 data: [DONE]）
            stripped = event_str.strip()
            if stripped == "data: [DONE]":
                return "data: [DONE]\n\n"
            if stripped == "[DONE]":
                return "data: [DONE]\n\n"

            if event_str.startswith("data: "):
                data = event_str[6:].strip()
                if data and data != "[DONE]":
                    try:
                        parsed = json.loads(data)
                        # 判断是否为 Agent 的最终结果（用于数据库持久化）
                        if isinstance(parsed, dict) and parsed.get("type") == "result" and parsed.get("agent"):
                            collected_events.append(parsed)
                    except json.JSONDecodeError:
                        # JSON 解析失败不影响事件转发，继续 yield 原始字符串
                        logger.debug(f"[/api/analyze] 无法解析 SSE 数据: {data[:100]}")
                        pass
            return event_str

        try:
            # stream_analysis_sse 是同步生成器，FastAPI 会自动在线程池中运行它
            # 这确保 SSE 事件能实时 flush 到客户端，而不会阻塞 FastAPI 事件循环
            for event in stream_analysis_sse(req.repo_url, req.branch, thread_id=thread_id):
                collected = collect(event)
                if collected:
                    yield collected
        except Exception as e:
            logger.error(f"[/api/analyze] stream 异常: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"[/api/analyze] 堆栈: {traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # ─── Step 4: 流结束，保存结果到数据库 ──────────────────────
        # 此时所有 Agent 已执行完毕，collected_events 包含所有 result 事件

        if not collected_events:
            # 边界情况：没有收到任何 result 事件（如所有 Agent 都超时/失败）
            logger.warning(f"[/api/analyze] 无 result 事件，跳过保存")
            return

        # 将 collected_events 按 agent 分组，合并为 result_data
        # result_data 格式: { "architecture": {...}, "quality": {...}, ... }
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

        # ─── Step 4a: 初始化 Supabase 客户端 ──────────────────
        # 使用服务角色 key 的 admin 客户端（绕过 RLS 限制）
        try:
            sb = get_supabase_admin()
        except RuntimeError as e:
            logger.error(f"[/api/analyze] Supabase 连接失败: {e}")
            return

        # ─── Step 4b: 验证用户是否已完成 GitHub 资料同步 ───────
        # auth_user_id（Auth 表主键）和 users 表（profiles 表）需要通过 GitHub OAuth 关联
        # 若用户从未访问过账户页，users 表中就不会有对应记录，导致外键关联失败
        if not get_user_uuid(sb, auth_user_id):
            logger.warning(
                f"[/api/analyze] users 表中无 auth_user_id={auth_user_id}，跳过保存。"
                "请先访问账户页完成 GitHub 资料同步。"
            )
            return

        # ─── Step 4c: 持久化历史记录 ───────────────────────────
        try:
            saved = save_analysis(sb, auth_user_id, req.repo_url, req.branch, result_data, thread_id=thread_id)
            logger.info(f"[/api/analyze] 历史记录保存成功: id={saved.id}")
        except Exception as e:
            logger.error(f"[/api/analyze] 保存历史记录失败: {type(e).__name__}: {e}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",         # 保持长连接，支持 SSE
            "X-Accel-Buffering": "no",           # 禁用 Nginx 缓冲，确保实时推送
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

    result = save_analysis(sb, auth_user_id, req.repo_url, req.branch, req.result_data,
                           thread_id=f"{req.repo_url}::{req.branch}")
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
    }, enable_ai_image=req.enable_ai_image)

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

    GitHub Token 从 BFF 通过 X-GitHub-Token header 传递（不经过 JWT 解码）。
    若未授权 repo 权限，直接报错，不允许使用服务端 GITHUB_TOKEN 降级。
    """
    # 先用 require_auth 验证用户身份（BFF 已在 X-User-Id 中提供）
    payload = require_auth(request)
    if not (payload.get("sub") or payload.get("id")):
        raise HTTPException(status_code=401, detail="无法识别用户身份")

    # 直接从 BFF 传递的 header 读取 GitHub OAuth token，不再从 JWT 解码
    user_github_token = request.headers.get("X-GitHub-Token")
    if not user_github_token:
        raise HTTPException(
            status_code=403,
            detail="GitHub 授权不足：创建 PR 需要用户的 GitHub OAuth Token（包含 repo 权限）。"
                   "请重新登录 GitHub 并授权 repo 权限后重试。"
        )

    gitintel_logger.info("[PR Create] 使用用户 GitHub OAuth Token")
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


# ─── Admin 管理端 API ──────────────────────────────────────────────────────────

@app.get("/api/admin/overview", response_model=AdminOverviewResponse)
async def api_admin_overview():
    """系统概览统计数据（无需登录，供 admin 后台使用）"""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    from services.database import db_get_overview_stats
    try:
        stats = db_get_overview_stats(sb)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/users", response_model=AdminUserListResponse)
async def api_admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: str | None = Query(None),
):
    """管理端：获取全部用户列表（分页）"""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    from services.database import db_get_all_users
    return db_get_all_users(sb, page, page_size, search)


@app.put("/api/admin/users/{user_id}", response_model=dict)
async def api_admin_update_user(user_id: str, body: dict, request: Request):
    """管理端：更新指定用户（如禁用/启用）"""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    from services.database import db_update_user
    ok = db_update_user(sb, user_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True}


@app.get("/api/admin/analysis-history", response_model=AdminHistoryListResponse)
async def api_admin_list_history(
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
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    from services.database import db_get_filtered_history
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


@app.get("/api/admin/analysis-history/{record_id}", response_model=dict)
async def api_admin_history_detail(record_id: str):
    """管理端：获取单条分析记录的完整详情（包含关联用户信息 + 真实 LangSmith 追踪数据）"""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    from services.database import db_get_history_by_id, db_get_user_by_id
    from services.langsmith_service import get_langsmith_stats
    from schemas.history import AdminHistoryDetailResponse, LangSmithTraceInfo

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


@app.get("/api/admin/users/{user_id}/history", response_model=dict)
async def api_admin_user_history(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: str | None = Query(None),
):
    """管理端：获取指定用户的分析历史（包含用户信息）"""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    from services.database import db_get_user_by_id, db_get_user_analysis_history
    from schemas.history import AdminUserHistoryResponse

    user = db_get_user_by_id(sb, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    history = db_get_user_analysis_history(sb, user_id, page, page_size, search)
    return AdminUserHistoryResponse(user=user, history=history).model_dump(mode="json")


# ─── Chat API ─────────────────────────────────────────────────────────────────

from schemas.chat import (
    SendMessageRequest,
    CreateSessionRequest,
)
from services.rag_chat_service import rag_chat as do_rag_chat
from services.database import (
    create_chat_session,
    get_chat_sessions,
    get_chat_messages,
    save_chat_message,
    delete_chat_session,
    get_session_owner,
    get_user_uuid,
)


@app.post("/api/chat/sessions", response_model=dict)
async def api_create_chat_session(body: CreateSessionRequest, request: Request):
    """创建新的 Chat Session。"""
    user = require_auth(request)
    auth_user_id = user.get("sub") or user.get("id") or ""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="用户未完善 GitHub 资料，请先访问账户页")

    session = create_chat_session(sb, str(user_uuid), body.title)
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
    }


@app.get("/api/chat/sessions", response_model=dict)
async def api_list_chat_sessions(request: Request):
    """获取当前用户所有 Chat Sessions。"""
    user = require_auth(request)
    auth_user_id = user.get("sub") or user.get("id") or ""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        return {"items": [], "total": 0}

    sessions = get_chat_sessions(sb, str(user_uuid))
    return {
        "items": [
            {"id": s.id, "title": s.title, "created_at": s.created_at, "updated_at": s.updated_at}
            for s in sessions
        ],
        "total": len(sessions),
    }


@app.get("/api/chat/sessions/{session_id}/messages", response_model=dict)
async def api_get_chat_messages(session_id: str, request: Request):
    """获取某个 Session 的所有消息。"""
    user = require_auth(request)
    auth_user_id = user.get("sub") or user.get("id") or ""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    owner = get_session_owner(sb, session_id)
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    messages = get_chat_messages(sb, session_id)
    return {
        "items": [m.model_dump(mode="json") for m in messages],
    }


@app.post("/api/chat/send", response_model=dict)
async def api_send_message(body: SendMessageRequest, request: Request):
    """发送消息并获取 RAG 回答。"""
    user = require_auth(request)
    auth_user_id = user.get("sub") or user.get("id") or ""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # 权限校验
    owner = get_session_owner(sb, body.session_id)
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    # 1. 保存用户消息
    user_msg = save_chat_message(sb, body.session_id, "user", body.content)

    # 2. RAG 问答
    answer, rag_sources = do_rag_chat(body.content)

    # 3. 保存 Assistant 回答
    assistant_msg = save_chat_message(
        sb,
        body.session_id,
        "assistant",
        answer,
        rag_context=[s.model_dump(mode="json") for s in rag_sources],
    )

    return {
        "message": assistant_msg.model_dump(mode="json"),
        "answer": answer,
        "rag_sources": [s.model_dump(mode="json") for s in rag_sources],
    }


@app.delete("/api/chat/sessions/{session_id}", response_model=dict)
async def api_delete_chat_session(session_id: str, request: Request):
    """删除一个 Chat Session。"""
    user = require_auth(request)
    auth_user_id = user.get("sub") or user.get("id") or ""
    try:
        sb = get_supabase_admin()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="用户未完善 GitHub 资料")

    ok = delete_chat_session(sb, session_id, str(user_uuid))
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在或无权限删除")
    return {"deleted": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
