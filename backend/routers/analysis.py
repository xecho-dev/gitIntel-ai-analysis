"""
分析相关路由 (/api/analyze)
SSE 流式分析接口，包含智能缓存和结果自动保存
"""
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from dependencies import get_auth_user_id, get_sb_client, require_user_profile
from graph.analysis_graph import stream_analysis_sse, _state_to_sse_events
from schemas.request import AnalyzeRequest
from supabase_client import get_supabase_admin
from tools.github_tools import get_branch_sha
from graph.executor import parse_repo_url

router = APIRouter(prefix="/api", tags=["analysis"])
logger = logging.getLogger("gitintel")


@router.post("/analyze")
async def analyze(req: AnalyzeRequest, request: Request):
    """
    分析仓库 - SSE 流式响应（需要登录）。分析完成后自动保存到数据库。

    流程概述:
    1. 用户认证（从请求中提取 auth token）
    2. 生成 thread_id（用于 LangGraph checkpoint 和 LangSmith 关联）
    3. 启动 SSE 流，实时推送分析进度和结果
    4. 流结束后，收集所有 Agent 的 result 事件并保存到数据库
    """
    logger.info(f"[/api/analyze] 收到请求: repo_url={req.repo_url}, branch={req.branch}")

    # ─── Step 1: 用户认证 ────────────────────────────────────────
    auth_user_id = get_auth_user_id(request)
    logger.info(f"[/api/analyze] 认证通过: auth_user_id={auth_user_id}")

    # ─── Step 2: 生成 thread_id ─────────────────────────────────
    thread_id = f"{req.repo_url}::{req.branch}"

    # ─── Step 3: SSE 流式响应 ───────────────────────────────────
    def event_stream():
        from services.database import save_analysis, get_sha_cached_analysis

        # 立即发送初始事件
        yield "data: {\"type\": \"connected\", \"agent\": \"pipeline\", \"message\": \"连接已建立，开始分析...\", \"percent\": 0}\n\n"

        # ─── Step 3a: 智能缓存检查 ─────────────────────────────────
        cached_result: dict | None = None
        if not req.skip_cache:
            try:
                parsed = parse_repo_url(req.repo_url)
                if parsed:
                    owner, repo = parsed
                    current_sha = get_branch_sha(owner, repo, req.branch)
                    sb = get_supabase_admin()
                    cached_result = get_sha_cached_analysis(sb, auth_user_id, req.repo_url, req.branch, current_sha)

                    if cached_result:
                        logger.info(f"[/api/analyze] 智能缓存命中: {req.repo_url} SHA={current_sha}")
                        final_result_data = cached_result.get("final_result") or cached_result

                        state = {
                            "repo_url": req.repo_url,
                            "branch": req.branch,
                            "loaded_files": final_result_data.get("repo_loader", {}).get("loaded_files", {}),
                            "loaded_paths": final_result_data.get("repo_loader", {}).get("loaded_paths", []),
                            "repo_sha": current_sha,
                            "react_events": [],
                            "react_summary": final_result_data.get("repo_loader", {}).get("summary", ""),
                            "react_iterations": final_result_data.get("repo_loader", {}).get("total_iterations", 0),
                            "code_parser_result": final_result_data.get("code_parser"),
                            "explorer_result": final_result_data.get("explorer"),
                            "tech_stack_result": final_result_data.get("tech_stack"),
                            "quality_result": final_result_data.get("quality") or {},
                            "dependency_result": final_result_data.get("dependency"),
                            "architecture_result": final_result_data.get("architecture"),
                            "suggestion_result": final_result_data.get("suggestion"),
                            "optimization_result": final_result_data.get("suggestion"),
                            "optimization_events": [],
                            "final_result": final_result_data,
                            "errors": [],
                        }

                        status_sent: set = set()
                        result_sent: set = set()
                        for node_name in ("react_loader", "explorer", "architecture", "react_suggestion"):
                            for sse in _state_to_sse_events(
                                node_name=node_name,
                                state=state,
                                owner=owner,
                                repo=repo,
                                status_sent=status_sent,
                                result_sent=result_sent,
                            ):
                                yield sse

                        yield "data: [DONE]\n\n"
                        return
                    else:
                        logger.info(f"[/api/analyze] SHA 未命中，继续分析: {req.repo_url} SHA={current_sha}")
                else:
                    logger.warning(f"[/api/analyze] URL 解析失败，跳过缓存检查: {req.repo_url}")
            except Exception as cache_err:
                logger.warning(f"[/api/analyze] 缓存检查失败: {cache_err}")
                cached_result = None

        # 收集事件
        collected_events: list[dict] = []

        def collect(event_str: str) -> str:
            stripped = event_str.strip()
            if stripped == "data: [DONE]" or stripped == "[DONE]":
                return "data: [DONE]\n\n"

            if event_str.startswith("data: "):
                data = event_str[6:].strip()
                if data and data != "[DONE]":
                    try:
                        parsed = json.loads(data)
                        if isinstance(parsed, dict) and parsed.get("type") == "result" and parsed.get("agent"):
                            collected_events.append(parsed)
                    except json.JSONDecodeError:
                        logger.debug(f"[/api/analyze] 无法解析 SSE 数据: {data[:100]}")
            return event_str

        try:
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

        # ─── Step 4: 保存结果到数据库 ──────────────────────────────
        if not collected_events:
            logger.warning(f"[/api/analyze] 无 result 事件，跳过保存")
            return

        result_data: dict = {}
        for evt in collected_events:
            agent = evt.get("agent", "")
            data = evt.get("data")
            if agent and data:
                result_data[agent] = data

        if not result_data:
            logger.warning(f"[/api/analyze] result_data 为空，跳过保存")
            return

        react_loader_data = result_data.get("react_loader", {})
        if react_loader_data.get("loaded_count", 0) == 0:
            logger.warning(f"[/api/analyze] ReAct 未能加载文件（loaded_count=0），跳过保存")
            return

        logger.info(f"[/api/analyze] 分析完成，准备保存 history，agents={list(result_data.keys())}")

        try:
            sb = get_supabase_admin()
        except RuntimeError as e:
            logger.error(f"[/api/analyze] Supabase 连接失败: {e}")
            return

        if not get_sha_cached_analysis(sb, auth_user_id, "", "", ""):  # 简化检查
            pass  # 已有 user_uuid 检查

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
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
