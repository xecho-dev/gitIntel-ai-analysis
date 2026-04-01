"""
Pipeline Executor — Agent 执行引擎，封装 SSE 和同步执行的公共逻辑。

职责：
  - 统一 Agent 执行入口
  - SSE 事件格式化
  - 错误处理和重试
  - 公共参数提取

使用方式：
  # SSE 流式执行
  async for sse_event in stream_agent_events(agent, repo_id, branch, **kwargs):
      yield sse_event

  # 同步执行
  result = run_agent_sync(agent, repo_id, branch, **kwargs)

  # 从 state 提取参数
  repo_id, branch, file_contents = get_inputs_from_state(state)
"""
import asyncio
import json
from typing import Any, AsyncGenerator, Callable, TypeVar, ParamSpec

from .state import SharedState


P = ParamSpec("P")
T = TypeVar("T")


# ─── SSE 事件格式化 ────────────────────────────────────────────────

def format_sse_event(event: dict) -> str:
    """将 AgentEvent 格式化为 SSE 格式字符串。"""
    return f"data: {json.dumps(event)}\n\n"


def format_sse_error(agent: str, message: str, data: dict | None = None) -> str:
    """格式化 SSE 错误事件。"""
    return format_sse_event({
        "type": "error",
        "agent": agent,
        "message": message,
        "percent": 0,
        "data": data,
    })


# ─── 通用 Agent 执行 ────────────────────────────────────────────────

async def stream_agent_events(
    agent,
    repo_id: str,
    branch: str,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """流式执行 Agent，yield SSE 格式事件。

    Args:
        agent: Agent 实例（有 stream 方法）
        repo_id: 仓库标识（owner/repo）
        branch: 分支名
        **kwargs: 传递给 agent.stream 的额外参数

    Yields:
        SSE 格式字符串
    """
    try:
        async for event in agent.stream(repo_id, branch, **kwargs):
            yield format_sse_event(event)
    except Exception as e:
        yield format_sse_error(agent.name, f"执行异常: {e}")


def run_agent_sync(
    agent,
    repo_id: str,
    branch: str,
    **kwargs,
) -> dict:
    """同步执行 Agent，返回结果。

    使用 asyncio.run() 在当前线程运行异步代码。

    Args:
        agent: Agent 实例（有 run 方法）
        repo_id: 仓库标识
        branch: 分支名
        **kwargs: 传递给 agent.run 的额外参数

    Returns:
        Agent 执行结果字典
    """
    try:
        return asyncio.run(agent.run(repo_id, branch, **kwargs))
    except Exception as e:
        agent_name = getattr(agent, "name", "unknown")
        return {"error": str(e), "agent": agent_name}


# ─── State 参数提取 ────────────────────────────────────────────────

def parse_repo_url(url: str) -> tuple[str, str] | None:
    """解析 GitHub URL，返回 (owner, repo)。

    支持格式:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
      owner/repo
    """
    import re

    # 处理 .git 后缀
    url = re.sub(r"\.git$", "", url)

    m = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", url)
    if m:
        return m.group(1), m.group(2)

    m = re.match(r"git@github\.com:([^/]+)/([^/]+)$", url)
    if m:
        return m.group(1), m.group(2)

    m = re.match(r"^([^/]+)/([^/]+)$", url.strip())
    if m:
        return m.group(1), m.group(2)

    return None


def get_inputs_from_state(state: SharedState) -> tuple[str, str, dict]:
    """从 SharedState 提取公共输入参数。

    Returns:
        tuple[repo_id, branch, file_contents]

    Note:
        repo_id 在 GitHub 模式下是 "owner/repo" 格式的字符串
    """
    file_contents = state.get("loaded_files") or state.get("file_contents") or {}

    repo_id = state.get("local_path", "")
    if not repo_id:
        rlr = state.get("repo_loader_result")
        if rlr:
            repo_id = rlr.get("repo", "")

    branch = state.get("branch", "main")
    return repo_id, branch, file_contents


def has_loader_result(state: SharedState) -> bool:
    """判断 RepoLoader 是否成功执行并返回了文件内容。"""
    return bool(state.get("loaded_files") or state.get("file_contents"))


# ─── Agent 结果收集 ────────────────────────────────────────────────

async def collect_agent_result(
    agent,
    repo_id: str,
    branch: str,
    result_key: str,
    errors: list[str],
    finished_agents: list[str],
    state: SharedState,
    **kwargs,
) -> dict:
    """执行 Agent 并收集结果，生成 LangGraph 节点更新字典。

    Args:
        agent: Agent 实例
        repo_id: 仓库标识
        branch: 分支名
        result_key: 结果在 state 中的 key（如 "code_parser_result"）
        errors: 错误列表（会原地修改）
        finished_agents: 已完成 agent 列表（会原地修改）
        state: 当前状态（用于获取 file_contents）
        **kwargs: 传递给 agent.run 的额外参数

    Returns:
        LangGraph 节点更新字典
    """
    # 如果 agent 需要 file_contents，从 kwargs 中获取或从 state 推断
    if "file_contents" not in kwargs:
        _, _, file_contents = get_inputs_from_state(state)
        kwargs["file_contents"] = file_contents or None

    result = run_agent_sync(agent, repo_id, branch, **kwargs)

    if not result:
        errors.append(f"{agent.name}: 执行返回空结果")

    finished_agents.append(agent.name)

    return {
        result_key: result,
        "errors": errors,
        "finished_agents": finished_agents,
    }
