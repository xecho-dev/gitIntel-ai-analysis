"""
Chat Agents — 多 Agent 协作问答系统。

目录结构：
  agents/chat/
  ├── __init__.py            # 本文件（统一导出）
  ├── base_chat_agent.py     # ChatAgent 基类
  ├── supervisor_agent.py    # Supervisor Agent（意图分类 + 路由）
  ├── knowledge_agent.py      # KnowledgeAgent（知识库问答）
  ├── code_agent.py          # CodeAgent（代码相关问题）
  ├── analysis_agent.py      # AnalysisAgent（分析结果查询）
  ├── general_agent.py       # GeneralAgent（通用问题）
  └── multi_agent_router.py  # 路由编排层（串联各 Agent）
"""

from .base_chat_agent import ChatAgent
from .supervisor_agent import SupervisorAgent
from .knowledge_agent import KnowledgeAgent
from .code_agent import CodeAgent
from .analysis_agent import AnalysisAgent
from .general_agent import GeneralAgent
from .multi_agent_router import MultiAgentRouter

# 从 LangGraph 工作流导入（新的 LangGraph 实现）
from graph.chat_graph import multi_agent_chat_stream as multi_agent_chat_stream

__all__ = [
    "ChatAgent",
    "SupervisorAgent",
    "KnowledgeAgent",
    "CodeAgent",
    "AnalysisAgent",
    "GeneralAgent",
    "MultiAgentRouter",
    "multi_agent_chat_stream",
]
