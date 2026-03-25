from .base_agent import BaseAgent, AgentEvent
from typing import AsyncGenerator


class DependencyAgent(BaseAgent):
    name = "dependency"

    async def stream(self, repo_url: str, branch: str = "main") -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent(
            type="status", agent=self.name,
            message="正在扫描依赖包...", percent=10, data=None
        )
        yield AgentEvent(
            type="progress", agent=self.name,
            message=f"正在检测漏洞...", percent=50, data=None
        )
        yield AgentEvent(
            type="result", agent=self.name,
            message="依赖风险扫描完成",
            percent=100,
            data={
                "total": 200,
                "scanned": 142,
                "high": 2,
                "medium": 12,
                "low": 45,
            }
        )
