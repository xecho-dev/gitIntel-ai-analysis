"""
GitIntel Agent Layer - FastAPI 入口
AI-powered GitHub repository analysis
"""
import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from schemas.response import HealthResponse
from routers import (
    analysis_router,
    history_router,
    user_router,
    export_router,
    git_ops_router,
    pr_router,
    chat_router,
    auth_router,
    admin_management_router,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.setLevel(logging.INFO)
gitintel_logger = logging.getLogger("gitintel")
gitintel_logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("GitIntel Agent Layer started")
    yield
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

# 注册路由
app.include_router(analysis_router)
app.include_router(history_router)
app.include_router(user_router)
app.include_router(export_router)
app.include_router(git_ops_router)
app.include_router(pr_router)
app.include_router(chat_router)
app.include_router(auth_router)
app.include_router(admin_management_router)


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    return HealthResponse(status="ok")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
