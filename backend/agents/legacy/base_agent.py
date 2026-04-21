"""BaseAgent — 引用根目录的共享基类，避免代码重复。"""

from ..base_agent import BaseAgent, AgentEvent, _make_event

__all__ = ["BaseAgent", "AgentEvent", "_make_event"]
