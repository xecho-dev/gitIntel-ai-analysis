"""
ErrorLoopDetector — 错误循环检测 Mixin，防止 Agent 在同一错误上无限重试。

所有 LangChain Callback Handler 若需要错误循环检测，统一继承此类。

用法：
    class MyCallbackHandler(ErrorLoopDetector, AsyncCallbackHandler):
        MAX_CONSECUTIVE_SAME_ERRORS = 3  # 子类可覆盖

        def __init__(self):
            super().__init__()
            AsyncCallbackHandler.__init__()

        # on_tool_end / on_tool_error 中调用：
        #     self._check_error_pattern(output, tool_name, self.tool_calls)
        #     if self._stop_due_to_loop:
        #         self._propagate_interrupt()
"""

import logging

logger = logging.getLogger("gitintel")

# 检测关键词，同一模式连续出现超过此次数则判定为错误循环
_DEFAULT_MAX_CONSECUTIVE_SAME_ERRORS = 3


class LoopInterrupt(Exception):
    """Agent 错误循环中断异常。

    当 ErrorLoopDetector 检测到连续相同错误超过阈值时抛出，
    用于在 callback handler 中立即停止 Agent 循环。
    """

    def __init__(self, tool_name: str, pattern: str, count: int, tool_calls: list):
        self.tool_name = tool_name
        self.pattern = pattern
        self.count = count
        self.tool_calls = list(tool_calls)
        msg = (
            f"Agent 因错误循环中断: 连续 {count} 次相同错误 "
            f"'{pattern[:50]}...' (工具={tool_name})，"
            f"已完成 {len(tool_calls)} 次工具调用"
        )
        super().__init__(msg)


class ErrorLoopDetector:
    """错误循环检测 Mixin。

    检测同一错误模式在连续多次工具调用中重复出现，
    超过阈值后抛出 LoopInterrupt，立即停止 Agent 循环。
    """

    MAX_CONSECUTIVE_SAME_ERRORS = _DEFAULT_MAX_CONSECUTIVE_SAME_ERRORS

    def __init__(self):
        self._consecutive_same_error_count = 0
        self._last_error_pattern = ""
        self._stop_due_to_loop = False
        self._interrupt_exc: LoopInterrupt | None = None

    def _check_error_pattern(
        self, output: str, tool_name: str = "", tool_calls: list | None = None
    ) -> None:
        """检测连续相同错误的模式，防止死循环。

        Args:
            output: 工具返回的结果（字符串）
            tool_name: 工具名称（仅用于日志）
            tool_calls: 当前已收集的工具调用记录（用于中断异常）
        """
        if not output:
            return

        error_keywords = ["错误", "error", "不能为空", "invalid", "failed"]
        is_error = any(kw in output.lower() for kw in error_keywords)

        if is_error:
            pattern = output[:50].strip()
            if pattern == self._last_error_pattern:
                self._consecutive_same_error_count += 1
                if (
                    self._consecutive_same_error_count
                    >= self.MAX_CONSECUTIVE_SAME_ERRORS
                ):
                    logger.warning(
                        f"[ErrorLoopDetector] 检测到错误循环: "
                        f"连续 {self._consecutive_same_error_count} 次相同错误 "
                        f"'{pattern[:30]}...'"
                        + (f"，工具 {tool_name}" if tool_name else "")
                    )
                    self._stop_due_to_loop = True
                    exc = LoopInterrupt(
                        tool_name=tool_name,
                        pattern=pattern,
                        count=self._consecutive_same_error_count,
                        tool_calls=tool_calls or [],
                    )
                    self._interrupt_exc = exc
                    raise exc
            else:
                self._consecutive_same_error_count = 1
                self._last_error_pattern = pattern
        else:
            self._consecutive_same_error_count = 0
            self._last_error_pattern = ""

    def _propagate_interrupt(self) -> None:
        """重新抛出已记录的 LoopInterrupt，用于在 callback 外部中断。"""
        if self._interrupt_exc is not None:
            raise self._interrupt_exc
