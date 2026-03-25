import json
from typing import AsyncGenerator

from agents.architecture import ArchitectureAgent
from agents.quality import QualityAgent
from agents.dependency import DependencyAgent
from agents.optimization import OptimizationAgent
from .state import AnalysisState


architecture_agent = ArchitectureAgent()
quality_agent = QualityAgent()
dependency_agent = DependencyAgent()
optimization_agent = OptimizationAgent()


async def stream_analysis(repo_url: str, branch: str = "main") -> AsyncGenerator[str, None]:
    """并行执行四个 Agent，流式输出所有事件"""
    agents = [
        ("architecture", architecture_agent),
        ("quality", quality_agent),
        ("dependency", dependency_agent),
        ("optimization", optimization_agent),
    ]

    import asyncio

    async def run_agent(name: str, agent) -> list:
        results = []
        async for event in agent.stream(repo_url, branch):
            results.append(event)
        return results

    # 并行执行所有 Agent
    tasks = [run_agent(name, agent) for name, agent in agents]
    all_results = await asyncio.gather(*tasks)

    # 按顺序 yield 每个 Agent 的事件
    for agent_results in all_results:
        for event in agent_results:
            yield f"data: {json.dumps(event)}\n\n"

    yield "data: [DONE]\n\n"


def build_analysis_state(repo_url: str, branch: str = "main") -> AnalysisState:
    """构建初始状态"""
    return AnalysisState(
        repo_url=repo_url,
        branch=branch,
        architecture_result=None,
        quality_result=None,
        dependency_result=None,
        optimization_result=None,
        errors=[],
    )
