"""
BaseAgent — 所有 Agent 的基类，定义统一接口和事件规范。

设计约定：
  - 每个 Agent 继承 BaseAgent，实现 stream() 方法流式输出 AgentEvent
  - run() 方法是 stream() 的同步封装，收集 result 事件并返回数据字典
  - _make_event() 辅助函数用于构造标准 AgentEvent TypedDict
  - _calc_complexity / _calc_maintainability 是通用评分工具，供子类复用
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, TypedDict


class AgentEvent(TypedDict):
    type: str       # "status" | "progress" | "result" | "error"
    agent: str      # agent name
    message: str | None
    percent: int | None
    data: dict | None


def _make_event(
    agent: str,
    type_: str,
    message: str,
    percent: int,
    data: dict | None = None,
) -> AgentEvent:
    """构造标准 AgentEvent 的辅助函数。"""
    return AgentEvent(
        type=type_, agent=agent, message=message, percent=percent, data=data
    )


class BaseAgent(ABC):
    """所有 Agent 的基类，定义统一接口。"""

    name: str

    @abstractmethod
    async def stream(
        self, repo_path: str, branch: str = "main", **kwargs
    ) -> AsyncGenerator[AgentEvent, None]:
        """流式输出事件（SSE 用）。

        Args:
            repo_path: 已在本地 checked-out 的仓库路径（由 RepoLoaderAgent 准备）。
            branch: 分支名（仅作参考，代码已在 repo_path 中）。
            **kwargs: 子类可定义额外参数，如 file_contents, code_parser_result 等。
        """
        ...

    async def run(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
        **kwargs,
    ) -> dict:
        """执行 Agent，收集并返回最终 result 数据。

        子类可以传递任意额外参数（会被转发给 stream()）。
        """
        result = None
        async for event in self.stream(repo_path, branch, file_contents=file_contents, **kwargs):
            if event["type"] == "result":
                result = event["data"]
        return result or {}

    # ─── 通用工具方法（子类可直接调用）─────────────────────────────

    @staticmethod
    def _calc_complexity(score: float) -> str:
        """根据综合得分返回复杂度描述。

        规则：≥80 → Low，≥50 → Medium，<50 → High
        """
        if score >= 80:
            return "Low"
        elif score >= 50:
            return "Medium"
        return "High"

    @staticmethod
    def _calc_maintainability(score: float) -> str:
        """根据综合得分返回可维护性等级（类似 GitHub 代码评分）。

        规则：≥85 → A+，≥75 → A，≥65 → B+，≥55 → B，≥40 → C，<40 → C-
        """
        if score >= 85:
            return "A+"
        elif score >= 75:
            return "A"
        elif score >= 65:
            return "B+"
        elif score >= 55:
            return "B"
        elif score >= 40:
            return "C"
        return "C-"
