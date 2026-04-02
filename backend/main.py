from services.pdf_service import build_pdf_bytes

import io
import os
import logging
from contextlib import asynccontextmanager

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
    """分析仓库 - SSE 流式响应（需要登录）"""
    import logging
    logger = logging.getLogger("gitintel")

    logger.info(f"[/api/analyze] 收到请求: repo_url={req.repo_url}, branch={req.branch}")

    user = require_auth(request)
    logger.info(f"[/api/analyze] 认证通过: user_id={user.get('sub') or user.get('id')}")

    async def event_stream():
        try:
            async for event in stream_analysis_sse(req.repo_url, req.branch):
                yield event
        except Exception as e:
            logger.error(f"[/api/analyze] stream 异常: {type(e).__name__}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

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

    # 确保用户 uuid 存在
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        raise HTTPException(status_code=404, detail="用户不存在，请先同步用户信息")

    result = save_analysis(sb, user_uuid, req.repo_url, req.branch, req.result_data)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
