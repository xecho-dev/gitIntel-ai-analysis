"""
统一工具返回格式 — 替代所有工具的字符串返回值。

设计原则：
  - 所有工具返回 ToolResult 而非裸字符串
  - ToolResult 保持向后兼容：str(result) 对 LLM 友好
  - 错误用 [ERROR] 前缀标记，供 tool_wrapper 精确识别
  - 成功数据仍然可以 JSON 解析

用法：
    from utils.tool_result import ToolResult, ToolSuccess, ToolError

    def my_tool(...) -> str:
        try:
            data = do_work()
            return ToolSuccess(data).to_str()
        except Exception as e:
            return ToolError(str(e)).to_str()
"""

import json
from typing import Any


class ToolResult:
    """统一工具返回格式。

    支持两种构造方式：
      - ToolSuccess(data): 成功，数据可以是 dict/list/str
      - ToolError(message): 失败，附带错误信息

    to_str() 方法：
      - 成功时返回 JSON 序列化后的字符串（供 LLM 解析）
      - 失败时返回 "[ERROR] message"（供 tool_wrapper 检测）

    外部通过 startswith("[ERROR]") 判断是否错误，不再依赖关键词匹配。
    """

    _ERROR_PREFIX = "[ERROR]"
    _WARN_PREFIX = "[WARNING]"
    _SUCCESS_PREFIX = "[OK]"

    def __init__(
        self, success: bool, data: Any = None, error: str = None, warn: str = None
    ):
        self.success = success
        self.data = data
        self.error = error
        self.warn = warn

    def to_str(self) -> str:
        """转换为字符串，供 LangChain tool 返回。

        格式约定：
          - 成功：JSON 字符串（dict/list）或纯文本
          - 失败：[ERROR] 错误信息
          - 警告：[WARNING] 警告信息（成功但有需要注意的情况）
        """
        if self.error:
            return f"{self._ERROR_PREFIX} {self.error}"
        if self.warn:
            return f"{self._WARN_PREFIX} {self.warn}"
        if self.data is None:
            return ""
        if isinstance(self.data, str):
            return self.data
        if isinstance(self.data, (dict, list)):
            return json.dumps(self.data, ensure_ascii=False)
        return str(self.data)

    def to_dict(self) -> dict:
        """转换为字典，内部使用。"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "warn": self.warn,
        }

    @classmethod
    def is_error(cls, s: str) -> bool:
        """判断字符串是否为错误响应（用于 tool_wrapper 错误循环检测）。"""
        return isinstance(s, str) and s.startswith(cls._ERROR_PREFIX)

    @classmethod
    def is_warning(cls, s: str) -> bool:
        """判断字符串是否为警告响应。"""
        return isinstance(s, str) and s.startswith(cls._WARN_PREFIX)

    @classmethod
    def is_success(cls, s: str) -> bool:
        """判断字符串是否为成功响应。"""
        if not isinstance(s, str):
            return False
        return (
            s
            and not s.startswith(cls._ERROR_PREFIX)
            and not s.startswith(cls._WARN_PREFIX)
        )

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        status = "OK" if self.success else "ERROR"
        return f"ToolResult({status}, data={repr(self.data)}, error={repr(self.error)})"


class ToolSuccess(ToolResult):
    """成功响应。"""

    def __init__(self, data: Any):
        super().__init__(success=True, data=data)


class ToolError(ToolResult):
    """失败响应。"""

    def __init__(self, error: str):
        super().__init__(success=False, error=error)


class ToolWarn(ToolResult):
    """警告响应（成功但有需要注意的情况）。"""

    def __init__(self, warn: str, data: Any = None):
        super().__init__(success=True, data=data, warn=warn)
