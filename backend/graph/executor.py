"""
Pipeline Executor — Agent 执行引擎，封装 SSE 和同步执行的公共逻辑。

职责：
  - 统一 Agent 执行入口
  - SSE 事件格式化
  - 错误处理和重试
  - 公共参数提取

使用方式：
  # 同步执行
  result = run_agent_sync(agent, repo_id, branch, **kwargs)

  # 从 state 提取参数
  repo_id, branch, file_contents = get_inputs_from_state(state)
"""
import asyncio
import json
from typing import Any, ParamSpec, TypeVar

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
