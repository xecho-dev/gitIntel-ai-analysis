from .base_agent import BaseAgent, AgentEvent
from typing import AsyncGenerator


class ArchitectureAgent(BaseAgent):
    name = "architecture"

    async def stream(self, repo_url: str, branch: str = "main") -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent(
            type="status", agent=self.name,
            message="正在扫描项目目录...", percent=10, data=None
        )
        # TODO: 实现真正的 Git 仓库扫描逻辑
        yield AgentEvent(
            type="progress", agent=self.name,
            message="目录扫描完成", percent=30, data=None
        )
        yield AgentEvent(
            type="status", agent=self.name,
            message="正在解析核心组件...", percent=60, data=None
        )
        yield AgentEvent(
            type="result", agent=self.name,
            message="架构分析完成",
            percent=100,
            data={
                "complexity": "Medium",
                "components": 42,
                "tech_stack": ["React", "TypeScript", "Vite"],
                "maintainability": "A-",
            }
        )
