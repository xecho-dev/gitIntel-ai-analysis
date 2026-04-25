"""
Chat LangGraph Workflow — 多 Agent 协作的 LangGraph 工作流。

核心思想：
  - Supervisor 作为图的第一个节点，负责意图分类（LLM 路由）
  - 每个专业 Agent 都是一个子图（ReAct 循环），可以自主调用工具
  - 支持 mixed 意图：主 Agent 处理完后，辅 Agent 补充回答
  - 全链路接入 LangSmith 追踪

图结构：

    ┌──────────────┐
    │  supervisor  │  ← 意图分类 + 路由决策（写入 state.primary_agent）
    └──────┬───────┘
           │
    ┌──────▼───────┐
    │ knowledge?   │──no──►┌────────┐
    │ code?        │       │ general │
    │ analysis?    │──yes──►┌────────┐
    │ general?     │        │ primary │──no──► secondary
    └──────────────┘        │  agent  │──yes──► END
                             │  done?  │
                             └────────┘

每个 Agent 节点内部是 ReAct 循环：
  ┌──────────────────────────────────────────────────────────────┐
  │  ReAct Agent Node                                          │
  │  ┌────────┐    ┌────────────┐    ┌─────────────┐           │
  │  │ model  │───►│  tool_node  │───►│  should_    │           │
  │  │+tools  │    │            │    │  continue?  │           │
  │  └────────┘    └────────────┘    └──────┬──────┘           │
  │       ▲                                 │                   │
  │       │            yes                  │ no                │
  │       └─────────────────────────────────┘                   │
  └──────────────────────────────────────────────────────────────┘
"""

import json
import logging
import os
import re
from typing import AsyncGenerator, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from graph.chat_state import ChatState
from schemas.multi_agent import Intent, RouteDecision, MultiAgentChatEvent
from utils.llm_factory import get_llm_with_tracking

from tools.chat_tools import (
    CHAT_TOOLS,
    rag_search_knowledge_base,
    rag_search_similar,
    rag_search_by_category,
    lookup_repo_analysis,
    analyze_code,
    detect_code_language,
)

logger = logging.getLogger("gitintel")

# ─── LangSmith 配置 ──────────────────────────────────────────────────────────


def _configure_langsmith():
    """确保 LangSmith 环境变量已配置。"""
    tracing = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes")
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    if tracing and api_key:
        os.environ.setdefault("LANGSMITH_ENDPOINT", os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
        os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGSMITH_PROJECT", "gitintel-chat"))
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_API_KEY", api_key)
        logger.info(f"[chat_graph] LangSmith 追踪已启用，项目: {os.getenv('LANGSMITH_PROJECT')}")


_configure_langsmith()

# ─── Checkpointer ────────────────────────────────────────────────────────────

_checkpointer = MemorySaver()

# ─── Agent System Prompts ────────────────────────────────────────────────────


SUPERVISOR_PROMPT = """你是一个智能路由 Agent，负责分析用户问题并将其分配给最合适的专业 Agent。

## 意图分类

用户问题属于以下五种意图之一：

1. **knowledge（知识库问答）**: 询问 GitIntel 分析经验、最佳实践、技术建议，不涉及特定仓库的具体分析结果。
   典型问题："React 项目常见的性能问题有哪些？""依赖风险一般怎么评估？"

2. **code（代码相关）**: 涉及具体代码片段、算法实现、代码优化、调试问题的讨论。
   典型问题："这个函数的时间复杂度是多少？""帮我分析这段代码的逻辑"

3. **analysis（分析结果查询）**: 用户想查看某个仓库的具体分析结果（架构、质量、依赖等）。
   典型问题："帮我看看这个仓库的分析结果""那个项目的架构怎么样？"

4. **general（通用问题）**: 闲聊、使用说明、项目无关的通用问题。
   典型问题："你好""怎么使用这个工具？""GitIntel 是做什么的？"

5. **mixed（混合意图）**: 问题涉及多个方面，需要多个 Agent 协作回答。

## 路由规则

- 用户提到具体仓库（URL、owner/repo 格式、仓库描述）→ analysis 或 mixed
- 用户询问最佳实践、经验分享、通用技术建议 → knowledge
- 用户贴出代码、讨论代码逻辑/算法/bug → code
- 用户打招呼、问如何使用、闲聊 → general
- 问题跨越多个类别 → mixed，primary=最相关，secondary=辅助

## 输出格式

直接输出 JSON 格式的路由决策，不要有任何前缀或说明：
```json
{
  "intent": "knowledge|code|analysis|general|mixed",
  "confidence": 0.0~1.0,
  "reason": "判定理由（1-2句话）",
  "primary_agent": "knowledge|code|analysis|general",
  "secondary_agent": "knowledge|code|analysis|general|null",
  "context_hints": {
    "repo_url": "owner/repo（如果有）"
  }
}
```
"""


def _build_agent_system_prompt(role: Literal["knowledge", "code", "analysis", "general"]) -> str:
    base = """你是一个专业的 AI 助手，基于 GitIntel 的分析知识库和工具回答用户问题。

回答规则：
1. 优先基于检索到的知识或分析结果回答
2. 如果需要更多信息，先使用工具获取
3. 结合工具结果，用专业但易懂的语言解释
4. 保持简洁，突出关键信息
"""
    prompts = {
        "knowledge": base + """

## 你的专业能力：知识库问答

你专注于 GitIntel 知识库中的分析经验、最佳实践和技术建议。

你的专长：
1. 解读 GitIntel 分析结果中的优化建议和经验教训
2. 对比不同技术栈、规模的项目的分析结论
3. 给出架构设计、质量改进、依赖管理的通用建议
4. 结合具体案例（从知识库中）说明最佳实践

你应该：
- 先理解用户的问题
- 主动使用 rag_search_knowledge_base 或 rag_search_similar 检索相关经验
- 基于检索结果生成回答
- 如果没有检索到相关内容，坦诚告知并给出通用建议
""",
        "code": base + """

## 你的专业能力：代码分析

你专注于代码相关的深度分析，包括：
1. 代码结构与逻辑解读
2. 时间复杂度 / 空间复杂度分析
3. 代码问题诊断与调试建议
4. 代码优化与重构建议

你应该：
- 先理解用户的问题和粘贴的代码
- 使用 analyze_code 或 detect_code_language 分析代码
- 基于分析结果给出专业建议
- 如有必要，使用 calculate_complexity 计算复杂度
""",
        "analysis": base + """

## 你的专业能力：分析结果查询

你专注于展示 GitIntel 对具体仓库的分析结果。

你应该：
- 先使用 lookup_repo_analysis 查询仓库是否有缓存的分析结果
- 基于查询结果解读架构评估、质量评分、依赖风险
- 如果没有找到分析结果，坦诚告知并建议发起分析
""",
        "general": base + """

## 你的专业能力：通用问答

你是一个友好、专业的 AI 助手，回答 GitIntel 平台相关的通用问题。

你应该：
- 友好、简洁、专业
- 积极引导用户使用 GitIntel 的核心功能
- 如用户询问具体分析功能，引导其发起仓库分析

关于 GitIntel：
- GitIntel 是一个 GitHub 仓库智能分析平台
- 支持架构分析、代码质量评估、依赖风险检测、优化建议生成
""",
    }
    return prompts.get(role, base)


# ─── Supervisor Node ──────────────────────────────────────────────────────────


async def supervisor_node(state: ChatState) -> dict:
    """节点 1：Supervisor 意图分类 + 路由决策。

    调用 LLM 进行意图分类，将结果写入 state。
    """
    question = state.get("question", "")
    history = state.get("history") or []

    llm = get_llm_with_tracking(agent_name="supervisor", temperature=0.1)
    if llm is None:
        return {
            "primary_agent": "general",
            "secondary_agent": None,
            "intent": "general",
            "primary_step": 0,
            "secondary_step": 0,
            "primary_done": False,
            "secondary_done": False,
            "phase": "primary",
            "routed_agents": [],
            "errors": ["Supervisor: LLM 不可用，降级为 general"],
        }

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [SystemMessage(content=SUPERVISOR_PROMPT), HumanMessage(content=f"用户问题：{question}")]

    if history:
        history_text = "\n".join(
            f"{'用户' if h.get('role') == 'user' else '助手'}：{h.get('content', '')}"
            for h in history[-4:]
        )
        if history_text:
            messages.append(HumanMessage(content=f"最近对话历史：\n{history_text}"))

    try:
        response = await llm.ainvoke(messages)
        raw = response.content if hasattr(response, "content") else str(response)
        decision = _parse_route_decision(raw)
        if decision:
            logger.info(
                f"[chat_graph] Supervisor: intent={decision.intent}, "
                f"primary={decision.primary_agent}, secondary={decision.secondary_agent}"
            )
            return {
                "primary_agent": decision.primary_agent,
                "secondary_agent": decision.secondary_agent,
                "intent": decision.intent.value,
                "primary_step": 0,
                "secondary_step": 0,
                "primary_done": False,
                "secondary_done": False,
                "phase": "primary",
                "routed_agents": [],
            }
    except Exception as exc:
        logger.warning(f"[chat_graph] Supervisor LLM 调用失败: {exc}")

    return _fallback_route(question)


def _parse_route_decision(raw: str) -> RouteDecision | None:
    """从 LLM 输出中解析 RouteDecision JSON。"""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        raw = match.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]

    try:
        data = json.loads(raw)
        return RouteDecision(
            intent=Intent(data.get("intent", "general")),
            confidence=float(data.get("confidence", 0.5)),
            reason=str(data.get("reason", "")),
            primary_agent=str(data.get("primary_agent", "general")),
            secondary_agent=data.get("secondary_agent"),
            context_hints=data.get("context_hints", {}),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"[chat_graph] JSON 解析失败: {exc}, raw={raw[:200]}")
        return None


def _fallback_route(question: str) -> dict:
    """关键词匹配降级分类。"""
    q = question.lower()

    general_keywords = ["你好", "hi", "hello", "嗨", "help", "help me", "怎么用", "是什么", "请问"]
    if any(k in q for k in general_keywords):
        return {"primary_agent": "general", "secondary_agent": None, "intent": "general",
                "primary_step": 0, "secondary_step": 0, "primary_done": False, "secondary_done": False,
                "phase": "primary", "routed_agents": []}

    code_keywords = ["代码", "code", "函数", "function", "算法", "复杂度", "这段代码", "实现", "class ", "def ", "async ", "循环依赖"]
    code_score = sum(1 for k in code_keywords if k in q)

    knowledge_keywords = ["最佳实践", "best practice", "经验", "建议", "一般怎么", "应该怎么", "通常"]
    knowledge_score = sum(1 for k in knowledge_keywords if k in q)

    repo_patterns = ["github.com/", "http", "owner/repo"]
    has_repo = any(p in question for p in repo_patterns)

    if code_score >= 2:
        return {"primary_agent": "code", "secondary_agent": None, "intent": "code",
                "primary_step": 0, "secondary_step": 0, "primary_done": False, "secondary_done": False,
                "phase": "primary", "routed_agents": []}

    if has_repo:
        secondary = "knowledge" if knowledge_score >= 1 else None
        return {"primary_agent": "analysis", "secondary_agent": secondary, "intent": "mixed" if secondary else "analysis",
                "primary_step": 0, "secondary_step": 0, "primary_done": False, "secondary_done": False,
                "phase": "primary", "routed_agents": []}

    if knowledge_score >= 1:
        return {"primary_agent": "knowledge", "secondary_agent": None, "intent": "knowledge",
                "primary_step": 0, "secondary_step": 0, "primary_done": False, "secondary_done": False,
                "phase": "primary", "routed_agents": []}

    return {"primary_agent": "general", "secondary_agent": None, "intent": "general",
            "primary_step": 0, "secondary_step": 0, "primary_done": False, "secondary_done": False,
            "phase": "primary", "routed_agents": []}


# ─── Agent ReAct Nodes ───────────────────────────────────────────────────────


def _build_react_agent_node(
    agent_name: str,
    role: Literal["knowledge", "code", "analysis", "general"],
) -> callable:
    """构建一个 Agent 的 ReAct 循环节点（async 函数）。"""
    system_prompt = _build_agent_system_prompt(role)

    async def agent_node(state: ChatState) -> dict:
        role_name = agent_name.replace("_agent", "")
        is_primary = role_name == state.get("primary_agent")
        is_secondary = role_name == state.get("secondary_agent")

        messages_key = "primary_messages" if is_primary else "secondary_messages"
        step_key = "primary_step" if is_primary else "secondary_step"
        done_key = "primary_done" if is_primary else "secondary_done"
        answer_key = "primary_answer" if is_primary else "secondary_answer"

        messages = state.get(messages_key, [])
        current_step = state.get(step_key, 0)

        # 初始化消息列表
        if not messages:
            question = state.get("question", "")
            history = state.get("history") or []

            from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

            init = [SystemMessage(content=system_prompt)]

            # 添加上下文
            ctx_parts = []
            rag_results = state.get("rag_results", [])
            if rag_results:
                ctx_parts.append("=== 检索到的相关知识 ===")
                for r in rag_results[:3]:
                    ctx_parts.append(
                        f"[{r.get('category', '')}] {r.get('title', '')}\n{r.get('content', '')[:300]}"
                    )

            if ctx_parts:
                init.append(HumanMessage(content="\n\n".join(ctx_parts)))

            if history:
                history_text = "\n".join(
                    f"{'用户' if h.get('role') == 'user' else '助手'}：{h.get('content', '')}"
                    for h in history[-6:]
                )
                init.append(HumanMessage(content=f"=== 对话历史 ===\n{history_text}"))

            init.append(HumanMessage(content=f"用户问题：{question}"))
            messages = [{"role": "system", "content": system_prompt}] + [
                {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
                for m in init
                if isinstance(m, (HumanMessage, SystemMessage))
            ]

        # 构建 LangChain 消息
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

        lc_messages = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            elif role == "tool":
                lc_messages.append(ToolMessage(content=content, tool_call_id=m.get("tool_call_id", "")))

        # 调用绑定工具的 LLM
        llm = get_llm_with_tracking(agent_name=agent_name, temperature=0.3)
        if llm is None:
            answer = "抱歉，AI 服务暂时不可用。"
            messages.append({"role": "assistant", "content": answer})
            current_routed = list(state.get("routed_agents", []))
            current_routed.append(role_name)
            return {
                messages_key: messages,
                answer_key: answer,
                done_key: True,
                step_key: current_step + 1,
                "errors": [f"{agent_name}: LLM 不可用"],
                "phase": "secondary",
                "routed_agents": current_routed,
            }

        try:
            llm_with_tools = llm.bind_tools(CHAT_TOOLS, strict=False)
            response = await llm_with_tools.ainvoke(lc_messages)
            response_content = response.content if hasattr(response, "content") else str(response)

            # 检查是否有工具调用
            tool_calls = getattr(response, "tool_calls", None) or []
            logger.info(f"[chat_graph] {agent_name} response={response_content[:200]!r}, tool_calls={bool(tool_calls)}")

            messages.append({"role": "assistant", "content": response_content})

            if tool_calls and current_step < 5:  # 最多 5 步 ReAct
                # 先添加 AIMessage，再添加 ToolMessage
                lc_messages.append(AIMessage(content=response_content))

                for tc in tool_calls:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})

                    try:
                        tool_result = _invoke_chat_tool(tool_name, tool_args)
                    except Exception as tool_err:
                        logger.warning(f"[chat_graph] 工具 {tool_name} 调用失败: {tool_err}")
                        tool_result = json.dumps({"error": str(tool_err)}, ensure_ascii=False)

                    messages.append({
                        "role": "tool",
                        "content": tool_result,
                        "tool_call_id": tc.get("id", ""),
                        "tool_name": tool_name,
                    })
                    lc_messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=tc.get("id", ""),
                        name=tool_name,
                    ))

                # 继续推理（再调用一次 LLM，这次带上工具结果）
                response2 = await llm_with_tools.ainvoke(lc_messages)
                response2_content = response2.content if hasattr(response2, "content") else str(response2)
                messages.append({"role": "assistant", "content": response2_content})

            # 更新状态
            current_routed = list(state.get("routed_agents", []))
            current_routed.append(role_name)

            # 最终回答：有工具调用时用 response2，无工具时用 response
            final_content = response2_content if tool_calls else response_content

            return {
                messages_key: messages,
                answer_key: final_content,
                done_key: True,
                step_key: current_step + 1,
                "phase": "secondary",
                "routed_agents": current_routed,
            }

        except Exception as exc:
            logger.error(f"[chat_graph] {agent_name} Agent 调用失败: {exc}")
            messages.append({"role": "assistant", "content": f"处理失败：{str(exc)}"})
            current_routed = list(state.get("routed_agents", []))
            current_routed.append(role_name)
            return {
                messages_key: messages,
                answer_key: f"处理失败：{str(exc)}",
                done_key: True,
                step_key: current_step + 1,
                "errors": [f"{agent_name}: {str(exc)}"],
                "phase": "secondary",
                "routed_agents": current_routed,
            }

    return agent_node


def _invoke_chat_tool(tool_name: str, args: dict) -> str:
    """调用 chat 工具并返回结果字符串。"""
    tool_map = {
        "rag_search_knowledge_base": rag_search_knowledge_base,
        "rag_search_similar": rag_search_similar,
        "rag_search_by_category": rag_search_by_category,
        "lookup_repo_analysis": lookup_repo_analysis,
        "analyze_code": analyze_code,
        "detect_code_language": detect_code_language,
    }

    tool_fn = tool_map.get(tool_name)
    if tool_fn:
        try:
            return tool_fn.invoke(args) or ""
        except Exception as exc:
            return json.dumps({"error": f"工具执行失败: {exc}"}, ensure_ascii=False)

    return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)


# ─── 主图构建 ───────────────────────────────────────────────────────────────


def _build_chat_graph():
    """构建主聊天工作流图。

    图结构：
        supervisor ──[路由 primary]──► {agent} ──► END
    """
    main = StateGraph(ChatState)

    main.add_node("supervisor", supervisor_node)

    # Agent 节点（真实的 ReAct 节点，自动区分 primary/secondary）
    main.add_node("knowledge_agent", _build_react_agent_node("knowledge_agent", "knowledge"))
    main.add_node("code_agent", _build_react_agent_node("code_agent", "code"))
    main.add_node("analysis_agent", _build_react_agent_node("analysis_agent", "analysis"))
    main.add_node("general_agent", _build_react_agent_node("general_agent", "general"))

    main.set_entry_point("supervisor")

    # ── 条件边：supervisor 只路由到 primary agent ──────────────────────────────
    def route_from_supervisor(state: ChatState) -> Literal[
        "knowledge_agent", "code_agent", "analysis_agent",
        "general_agent", END
    ]:
        """Supervisor 一次性决定 primary agent，后续 secondary 在 SSE 层单独调用。"""
        primary = state.get("primary_agent", "general")
        valid = {"knowledge", "code", "analysis", "general"}
        if primary not in valid:
            primary = "general"
        return f"{primary}_agent"

    main.add_conditional_edges("supervisor", route_from_supervisor)

    # 所有 agent 完成后直接 END（secondary agent 在 SSE 层单独处理）
    main.add_edge("knowledge_agent", END)
    main.add_edge("code_agent", END)
    main.add_edge("analysis_agent", END)
    main.add_edge("general_agent", END)

    return main.compile(checkpointer=_checkpointer)


_workflow = _build_chat_graph()


# ─── SSE 流式输出层 ────────────────────────────────────────────────────────


async def chat_stream_sse(
    question: str,
    history: list[dict] | None = None,
    repo_url: str | None = None,
    analysis_cache: dict | None = None,
    thread_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """SSE 流式入口 — 包装 LangGraph 工作流为 SSE 事件流。

    Args:
        question:        用户问题
        history:         对话历史
        repo_url:        仓库 URL
        analysis_cache:  已缓存的分析结果
        thread_id:       LangGraph checkpoint thread ID
    """
    from utils.llm_factory import reset_token_stats
    reset_token_stats()

    thread = thread_id or f"chat::{question[:30]}::{hash(question)}"
    config = {"configurable": {"thread_id": thread}}

    initial_state: ChatState = {
        "question": question,
        "repo_url": repo_url,
        "history": history or [],
        "analysis_cache": analysis_cache,
        "primary_agent": "",
        "secondary_agent": None,
        "intent": "",
        "rag_results": [],
        "rag_queried": False,
        "primary_messages": [],
        "secondary_messages": [],
        "primary_step": 0,
        "secondary_step": 0,
        "primary_done": False,
        "secondary_done": False,
        "primary_answer": "",
        "secondary_answer": "",
        "final_answer": "",
        "used_knowledge": False,
        "sources": [],
        "errors": [],
        "phase": "primary",
        "routed_agents": [],
    }

    # 只 yield 原始 JSON，data: 前缀由 routers/chat.py 统一添加
    yield json.dumps({
        "type": "connected",
        "agent": "supervisor",
        "agent_name": "supervisor",
        "message": "正在分析问题...",
        "percent": 0,
    }, ensure_ascii=False)

    try:
        async for chunk in _workflow.astream(initial_state, config=config):
            for raw_event in _chunk_to_sse(chunk, question):
                if raw_event:
                    yield raw_event

        # 收集最终答案
        final_state = _workflow.get_state(config).values
        primary_answer = final_state.get("primary_answer", "")
        secondary_answer = final_state.get("secondary_answer", "")

        if secondary_answer:
            final_answer = f"{primary_answer}\n\n{secondary_answer}"
        else:
            final_answer = primary_answer

        sources = final_state.get("sources", [])
        used_knowledge = final_state.get("used_knowledge", False)

        logger.info(f"[chat_graph] done event: primary_answer={primary_answer[:100]!r}, final_answer={final_answer[:100]!r}")

        # 只 yield 原始 JSON，data: 前缀由 routers/chat.py 统一添加
        yield json.dumps({
            "type": "done",
            "agent": final_state.get("primary_agent", "general"),
            "agent_name": final_state.get("primary_agent", "general"),
            "message": "回答完成",
            "percent": 100,
            "answer": final_answer,
            "full_text": final_answer,
            "data": {
                "final_answer": final_answer,
                "primary_agent": final_state.get("primary_agent"),
                "secondary_agent": final_state.get("secondary_agent"),
                "intent": final_state.get("intent"),
                "used_knowledge": used_knowledge,
            },
        }, ensure_ascii=False)

    except Exception as exc:
        logger.error(f"[chat_graph] SSE 流异常: {exc}")
        import traceback
        logger.error(traceback.format_exc())
        yield json.dumps({
            "type": "error",
            "agent": "supervisor",
            "agent_name": "supervisor",
            "message": f"处理异常: {str(exc)}",
        }, ensure_ascii=False)

    yield "[DONE]"


def _chunk_to_sse(chunk: dict, question: str) -> list[str]:
    """将 LangGraph chunk 转换为 SSE 事件列表。"""
    events = []

    if not isinstance(chunk, dict):
        return events

    # 处理 updates 类型的 chunk
    updates = chunk.get("data", {})
    if not isinstance(updates, dict):
        updates = chunk

    for node_name, node_output in updates.items():
        if not isinstance(node_output, dict):
            continue

        if node_name == "supervisor":
            intent = node_output.get("intent", "")
            primary = node_output.get("primary_agent", "")
            secondary = node_output.get("secondary_agent")
            if primary:
                events.append(json.dumps({
                    "type": "route",
                    "agent": "supervisor",
                    "agent_name": "supervisor",
                    "message": f"正在使用 {primary} Agent 分析问题...",
                    "percent": 10,
                    "data": {
                        "intent": intent,
                        "primary_agent": primary,
                        "secondary_agent": secondary,
                    },
                }, ensure_ascii=False))

        elif node_name.endswith("_agent"):
            # 优先从 primary_answer / secondary_answer 读取
            answer = (
                node_output.get("primary_answer")
                or node_output.get("secondary_answer")
                or ""
            )
            # 如果 answer 为空但有 messages，从最后一条 assistant 消息提取
            if not answer:
                for msg_key in ("primary_messages", "secondary_messages"):
                    msgs = node_output.get(msg_key, [])
                    for msg in reversed(msgs):
                        if msg.get("role") == "assistant" and msg.get("content"):
                            answer = msg.get("content", "")
                            break
                    if answer:
                        break

            if answer:
                events.append(json.dumps({
                    "type": "token",
                    "agent": node_name.replace("_agent", ""),
                    "agent_name": node_name.replace("_agent", ""),
                    "delta": answer,
                    "full_text": answer,
                }, ensure_ascii=False))
            else:
                # answer 为空，打印 node_output 完整内容
                logger.info(f"[_chunk_to_sse] {node_name}: node_output keys={list(node_output.keys())}, primary_answer={node_output.get('primary_answer')!r}, secondary_answer={node_output.get('secondary_answer')!r}")

    logger.info(f"[_chunk_to_sse] chunk_keys={list(chunk.keys()) if isinstance(chunk, dict) else type(chunk)}, events_count={len(events)}, events={[(json.loads(e).get('type'), json.loads(e).get('delta', '')[:50] if json.loads(e).get('type')=='token' else '') for e in events]}")
    return events


# ─── 兼容层（供 router.py 继续使用）────────────────────────────────────────


async def multi_agent_chat_stream(
    question: str,
    history: list[dict] | None = None,
    repo_url: str | None = None,
    analysis_cache: dict | None = None,
) -> AsyncGenerator[str, None]:
    """包装 chat_stream_sse，统一返回纯 JSON 字符串（无 data: 前缀）。

    routers/chat.py 统一加 data: 前缀后转发给客户端。
    """
    async for event_str in chat_stream_sse(
        question=question,
        history=history,
        repo_url=repo_url,
        analysis_cache=analysis_cache,
    ):
        yield event_str
