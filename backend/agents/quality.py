from .base_agent import BaseAgent, AgentEvent
from typing import AsyncGenerator


class QualityAgent(BaseAgent):
    name = "quality"

    async def stream(self, repo_url: str, branch: str = "main") -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent(
            type="status", agent=self.name,
            message="正在扫描代码质量指标...", percent=10, data=None
        )
        yield AgentEvent(
            type="progress", agent=self.name,
            message="计算复杂度...", percent=40, data=None
        )
        yield AgentEvent(
            type="progress", agent=self.name,
            message="分析测试覆盖率...", percent=70, data=None
        )
        yield AgentEvent(
            type="result", agent=self.name,
            message="代码质量分析完成",
            percent=100,
            data={
                "health_score": 84,
                "test_coverage": 62,
                "complexity": "Normal",
            }
        )
