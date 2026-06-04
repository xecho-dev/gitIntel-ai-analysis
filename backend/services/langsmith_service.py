"""LangSmith 服务层 — 查询 AI 调用的真实追踪数据。

通过 LangSmith Python SDK 查询 run 级别的 token 消耗、费用和运行次数。
关联方式（按优先级）：
  1. thread_id — LangGraph checkpoint 的 thread_id，精确关联
  2. langsmith_trace_id — LangChain 自动生成的 trace ID
  3. 时间窗口 — ±15 分钟兜底查找

使用方式：
    from services.langsmith_service import get_langsmith_stats

    stats = get_langsmith_stats("owner/repo", thread_id="owner/repo::main")
    if stats:
        print(stats.total_tokens, stats.total_cost_usd)
"""

import os
import json
import logging
from typing import Optional
from dataclasses import dataclass

_logger = logging.getLogger("gitintel")


@dataclass
class LangSmithRun:
    id: str
    name: str
    agent: str
    status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_ms: Optional[int] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None


@dataclass
class LangSmithStats:
    project_name: str
    run_url: str
    trace_id: Optional[str]
    total_runs: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_usd: float
    total_duration_ms: int
    runs: list[LangSmithRun]
    agents: list[str]


def _normalize_agent_name(name: str) -> str:
    name_lower = name.lower()
    if "tech_stack" in name_lower:
        return "tech_stack"
    if "quality" in name_lower:
        return "quality"
    if "dependency" in name_lower:
        return "dependency"
    if "architecture" in name_lower:
        return "architecture"
    if "suggestion" in name_lower or "optimization" in name_lower:
        return "suggestion"
    if "code_parser" in name_lower:
        return "code_parser"
    if "repo_loader" in name_lower or "fetch" in name_lower:
        return "repo_loader"
    return name


def _get_run_attrs(run) -> dict:
    """从 LangSmith Run 对象提取所有可能存在的属性。"""
    attrs = {}
    for attr_name in dir(run):
        if attr_name.startswith("_"):
            continue
        try:
            val = getattr(run, attr_name)
            if not callable(val):
                attrs[attr_name] = val
        except Exception:
            pass
    return attrs


def _parse_run(run, base_url: str, project_name: str) -> Optional[LangSmithRun]:
    """将 LangSmith Run 对象解析为 LangSmithRun dataclass。"""
    try:
        run_id = str(run.id)
        name = run.name or run_id

        # 尝试多种 token 属性名
        prompt_tokens = 0
        completion_tokens = 0
        extra = getattr(run, "extra", None) or {}
        prompt_usage = getattr(run, "prompt_tokens", None)
        completion_usage = getattr(run, "completion_tokens", None)
        total_usage = getattr(run, "total_tokens", None)
        if prompt_usage:
            prompt_tokens = int(prompt_usage)
        if completion_usage:
            completion_tokens = int(completion_usage)
        if total_usage:
            if not prompt_usage:
                prompt_tokens = int(total_usage) // 2
            if not completion_usage:
                completion_tokens = int(total_usage) // 2
        total = prompt_tokens + completion_tokens

        # 费用
        cost = 0.0
        cost_attr = getattr(run, "cost", None)
        if cost_attr is not None:
            cost = float(cost_attr)

        # 时长
        duration_ms = None
        start = getattr(run, "start_time", None)
        end = getattr(run, "end_time", None)
        if start and end:
            try:
                from datetime import datetime as dt

                if isinstance(start, str):
                    start = dt.fromisoformat(start.replace("Z", "+00:00"))
                if isinstance(end, str):
                    end = dt.fromisoformat(end.replace("Z", "+00:00"))
                duration_ms = int((end - start).total_seconds() * 1000)
            except Exception:
                pass

        return LangSmithRun(
            id=run_id,
            name=name,
            agent=_normalize_agent_name(name),
            status=getattr(run, "status", "unknown"),
            start_time=str(start) if start else None,
            end_time=str(end) if end else None,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            cost_usd=cost,
            error=getattr(run, "error", None),
        )
    except Exception as e:
        _logger.debug(f"解析 run 失败: {e}")
        return None


def _get_client():
    """获取 LangSmith Client，失败返回 None。"""
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from langsmith import Client

        endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
        return Client(api_key=api_key, api_url=endpoint)
    except ImportError:
        _logger.warning("[LangSmith] langsmith SDK 未安装")
        return None
    except Exception as e:
        _logger.warning(f"[LangSmith] Client 初始化失败: {e}")
        return None


def get_langsmith_stats(
    repo_name: str,
    trace_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Optional[LangSmithStats]:
    """查询某次分析的 LangSmith 统计数据。

    关联方式（按优先级）：
    1. thread_id — LangGraph 的 thread_id，精确关联
    2. trace_id — LangChain 自动生成的 trace ID
    3. 时间窗口 ±15 分钟 — 兜底

    Args:
        repo_name: 仓库名（owner/repo）
        trace_id: LangChain 自动生成的 trace ID
        thread_id: LangGraph checkpoint 的 thread_id（精确查找）
        created_at: 分析记录创建时间（兜底）

    Returns:
        LangSmithStats 对象；未启用或查询失败时返回 None
    """
    client = _get_client()
    if client is None:
        return None

    project_name = os.getenv("LANGSMITH_PROJECT", "default")
    base_url = os.getenv(
        "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
    ).rstrip("/")

    runs = []
    run_ids_seen = set()

    # 策略 1: trace_id 精确查找
    if trace_id:
        try:
            filter_str = f'{{"trace_id": "{trace_id}"}}'
            candidate_runs = list(
                client.list_runs(
                    project_name=project_name,
                    filter=filter_str,
                    limit=200,
                )
            )
            runs = [
                r
                for r in candidate_runs
                if r.id not in run_ids_seen and not run_ids_seen.add(r.id)
            ]
            _logger.info(f"[LangSmith] trace_id={trace_id} 找到 {len(runs)} 个 runs")
        except Exception as e:
            _logger.warning(f"[LangSmith] trace_id 查询失败: {e}")

    # 策略 2: thread_id 查找（LangGraph checkpoint 关联）
    if not runs and thread_id:
        try:
            filter_str = f'{{"thread_id": "{thread_id}"}}'
            candidate_runs = list(
                client.list_runs(
                    project_name=project_name,
                    filter=filter_str,
                    limit=200,
                )
            )
            runs = [
                r
                for r in candidate_runs
                if r.id not in run_ids_seen and not run_ids_seen.add(r.id)
            ]
            _logger.info(f"[LangSmith] thread_id={thread_id} 找到 {len(runs)} 个 runs")
        except Exception as e:
            _logger.warning(f"[LangSmith] thread_id 查询失败: {e}")

    # 策略 3: 时间窗口查找（兜底）
    if not runs and created_at:
        try:
            from datetime import datetime as dt, timedelta

            created_dt = dt.fromisoformat(created_at.replace("Z", "+00:00"))
            start_window = (created_dt - timedelta(minutes=15)).isoformat()
            end_window = (created_dt + timedelta(minutes=15)).isoformat()
            filter_str = json.dumps(
                {"start_time": {"$gte": start_window, "$lte": end_window}}
            )
            candidate_runs = list(
                client.list_runs(
                    project_name=project_name,
                    filter=filter_str,
                    limit=300,
                )
            )
            runs = [
                r
                for r in candidate_runs
                if r.id not in run_ids_seen and not run_ids_seen.add(r.id)
            ]
            _logger.info(f"[LangSmith] 时间窗口查到 {len(runs)} 个 runs")
        except Exception as e:
            _logger.warning(f"[LangSmith] 时间窗口查询失败: {e}")

    if not runs:
        return None

    # 解析 runs
    parsed_runs: list[LangSmithRun] = []
    total_prompt = total_completion = total_cost = 0.0
    total_duration = 0
    seen_agents: set[str] = set()
    resolved_trace_id = trace_id

    for run in runs:
        pr = _parse_run(run, base_url, project_name)
        if pr:
            parsed_runs.append(pr)
            total_prompt += pr.prompt_tokens
            total_completion += pr.completion_tokens
            total_cost += pr.cost_usd
            if pr.duration_ms:
                total_duration += pr.duration_ms
            seen_agents.add(pr.agent)
            if resolved_trace_id is None and hasattr(run, "trace_id") and run.trace_id:
                resolved_trace_id = str(run.trace_id)

    if not parsed_runs:
        return None

    return LangSmithStats(
        project_name=project_name,
        run_url=f"{base_url}/projects/{project_name}",
        trace_id=resolved_trace_id,
        total_runs=len(parsed_runs),
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_tokens=total_prompt + total_completion,
        total_cost_usd=round(total_cost, 6),
        total_duration_ms=total_duration,
        runs=parsed_runs,
        agents=sorted(seen_agents),
    )
