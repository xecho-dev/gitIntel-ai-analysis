import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agents import BaseAgent, AgentEvent
from graph.analysis_graph import stream_analysis, build_analysis_state
from schemas.request import AnalyzeRequest, HealthRequest
from schemas.response import HealthResponse


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    return HealthResponse(status="ok")


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """分析仓库 - SSE 流式响应"""
    initial_state = build_analysis_state(req.repo_url, req.branch)

    async def event_stream():
        async for event in stream_analysis(req.repo_url, req.branch):
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
