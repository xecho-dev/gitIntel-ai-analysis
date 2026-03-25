from abc import ABC, abstractmethod
from typing import AsyncGenerator, TypedDict


class AgentEvent(TypedDict):
    type: str       # "status" | "progress" | "result" | "error"
    agent: str      # agent name
    message: str | None
    percent: int | None
    data: dict | None


class BaseAgent(ABC):
    name: str

    @abstractmethod
    async def stream(self, repo_url: str, branch: str = "main") -> AsyncGenerator[AgentEvent, None]:
        """流式输出事件（SSE 用）"""
        ...

    async def run(self, repo_url: str, branch: str = "main") -> dict:
        """执行 Agent，返回结果字典"""
        result = None
        async for event in self.stream(repo_url, branch):
            if event["type"] == "result":
                result = event["data"]
        return result or {}
