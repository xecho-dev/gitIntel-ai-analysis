from .base_agent import BaseAgent, AgentEvent
from typing import AsyncGenerator


class OptimizationAgent(BaseAgent):
    name = "optimization"

    async def stream(self, repo_url: str, branch: str = "main") -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent(
            type="status", agent=self.name,
            message="正在生成优化建议...", percent=10, data=None
        )
        yield AgentEvent(
            type="progress", agent=self.name,
            message="分析性能瓶颈...", percent=50, data=None
        )
        yield AgentEvent(
            type="result", agent=self.name,
            message="优化建议生成完成",
            percent=100,
            data={
                "suggestions": [
                    {
                        "id": 1,
                        "type": "performance",
                        "title": "性能提升建议 #1",
                        "description": "将 Context.Provider 拆分为更细粒度的组件以减少重绘。",
                        "priority": "high",
                    },
                    {
                        "id": 2,
                        "type": "refactor",
                        "title": "重构建议 #2",
                        "description": "检测到 3 处冗余的 useEffect 逻辑，建议合并为自定义 Hook。",
                        "priority": "medium",
                    }
                ]
            }
        )
