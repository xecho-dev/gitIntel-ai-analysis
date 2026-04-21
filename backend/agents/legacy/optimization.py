"""OptimizationAgent — 真正的 LLM 驱动优化建议 Agent。

该 Agent 内部委托给 SuggestionAgent，后者综合了：
  1. 规则引擎：基于质量/依赖/技术栈/结构数据的结构性建议
  2. LLM 增强：调用 LLM 生成深度优化建议（LangChain Prompt）

前端 `OptimizationResult` 类型定义：
  - suggestions: Suggestion[]
  其中 Suggestion: { id, type, title, description, priority }
"""
from typing import AsyncGenerator

from .base_agent import AgentEvent, _make_event
from .suggestion import SuggestionAgent


class OptimizationAgent(SuggestionAgent):
    """优化建议 Agent（委托给 SuggestionAgent）。

    直接复用 SuggestionAgent 的流式事件系统，只做字段名映射兼容。
    内部会自动：
      - 规则引擎兜底建议（始终执行）
      - LLM 深度优化建议（OPENAI_API_KEY 可用时）
    """

    name = "optimization"

    async def stream(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict | None = None,
        *,
        code_parser_result: dict | None = None,
        tech_stack_result: dict | None = None,
        quality_result: dict | None = None,
        dependency_result: dict | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """流式输出优化建议（SSE 用）。

        内部委托给 SuggestionAgent，将返回的 suggestion 结果映射为
        前端期望的 OptimizationResult 格式。
        """
        yield _make_event(
            self.name, "status",
            "正在生成优化建议…", 10, None
        )

        # 委托给 SuggestionAgent
        async for event in SuggestionAgent.stream(
            self,
            repo_path,
            branch,
            code_parser_result=code_parser_result,
            tech_stack_result=tech_stack_result,
            quality_result=quality_result,
            dependency_result=dependency_result,
        ):
            # 转发所有事件，但如果是 result 事件，做字段映射
            if event["type"] == "result" and event["data"] is not None:
                data = event["data"]
                suggestions = data.get("suggestions", [])

                # 映射为前端期望的 OptimizationResult 格式
                # 保留 code_fix（original/updated）供 PR 创建时使用
                mapped_suggestions = [
                    {
                        "id": s["id"],
                        "type": s.get("type", "general"),
                        "title": s.get("title", ""),
                        "description": s.get("description", ""),
                        "priority": s.get("priority", "medium"),
                        **(
                            {"code_fix": s["code_fix"]}
                            if s.get("code_fix")
                            else {}
                        ),
                    }
                    for s in suggestions
                ]

                yield _make_event(
                    self.name, "result",
                    event.get("message") or "优化建议生成完成",
                    100,
                    {
                        "suggestions": mapped_suggestions,
                        "total": data.get("total", len(mapped_suggestions)),
                        "high_priority": data.get("high_priority", 0),
                        "medium_priority": data.get("medium_priority", 0),
                        "low_priority": data.get("low_priority", 0),
                    },
                )
            else:
                # status / progress / error 事件直接转发
                yield AgentEvent(
                    type=event["type"],
                    agent=self.name,  # 统一使用 optimization 作为 agent 名
                    message=event.get("message"),
                    percent=event.get("percent"),
                    data=event.get("data"),
                )
