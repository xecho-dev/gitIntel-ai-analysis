"""
工具包装器 — 为 LangChain StructuredTool 添加通用预处理逻辑。

解决的问题：
  1. LLM 返回的参数类型错误（如 paths="a,b,c" 而非 ["a,b,c"]）
  2. 上下文参数注入（owner/repo/branch → 自动填充）
  3. 工具层连续相同错误兜底（第 3 次直接抛异常打断 agent 循环）
  4. 错误兜底（返回友好错误而非让 Pydantic 抛异常）

用法：
    from agents.react.tool_wrapper import wrap_tools, inject_context

    wrapped = wrap_tools(
        tools=REACT_TOOLS,
        owner="owner", repo="repo", branch="main"
    )
    agent = create_agent(model=llm, tools=wrapped, ...)
"""

import logging

from langchain_core.tools import StructuredTool

from utils.tool_result import ToolResult

logger = logging.getLogger("gitintel")

# 连续相同错误超过此次数则抛 ToolLoopInterrupt 打断 agent 循环
_LOOP_THRESHOLD = 3


# ─── 异常定义 ────────────────────────────────────────────────────────────────


class ToolLoopInterrupt(BaseException):
    """工具层错误循环打断异常（继承 BaseException，LangGraph ToolNode 不会 catch）。

    当同一工具连续失败 _LOOP_THRESHOLD 次时抛出，
    LangGraph 异常传播链：ToolNode._execute_tool_sync → re-raises →
    ToolNode._run_one → 不 catch BaseException → 传播到 ainvoke 外部。

    用法：
        except ToolLoopInterrupt as e:
            # Agent 被打断，提前返回已有结果
            return result
    """

    def __init__(self, tool_name: str, pattern: str, count: int):
        self.tool_name = tool_name
        self.pattern = pattern
        self.count = count
        super().__init__(
            f"Agent 因工具 {tool_name} 连续 {count} 次相同错误打断: '{pattern[:80]}...'"
        )


# ─── 参数标准化 ────────────────────────────────────────────────────────────

# 工具函数签名（位置参数顺序），用于映射 args 列表到具名参数
# 注意：owner/repo/ref 已由 inject_context 自动注入，无需在 args 列表中
_POSITIONAL_MAPPINGS: dict[str, list[str]] = {
    "read_file_content": ["path"],  # owner/repo/ref 由系统自动注入
    "search_code": ["query", "language"],  # owner/repo 由系统自动注入
    "batch_search_code": ["queries"],  # owner/repo 由系统自动注入
    "get_file_blobs": ["owner", "repo", "paths", "ref"],
    "get_commit_history": ["owner", "repo", "ref"],
    "get_pull_requests": ["owner", "repo", "ref"],
}


def _normalize_all(raw_args: dict) -> dict:
    """全局参数标准化：修正 LLM 常见的类型错误。"""
    if not isinstance(raw_args, dict):
        return raw_args

    args = dict(raw_args)

    # paths: 字符串 → 列表，数字 → 列表
    paths = args.get("paths")
    if isinstance(paths, str):
        args["paths"] = [p.strip() for p in paths.split(",") if p.strip()]
    elif isinstance(paths, int):
        args["paths"] = [str(paths)]

    # 过滤空字符串参数
    for key in list(args.keys()):
        if isinstance(args[key], str) and not args[key].strip():
            args.pop(key, None)

    return args


def _normalize_invocation_args(args: dict, tool_name: str) -> dict:
    """将各种调用格式规范化为具名参数 dict。

    LangChain create_agent 有多种参数格式，统一处理：
      1. {"args": [...], "config": {}}          → args 列表映射为具名参数
      2. {"input": {"args": [...], "config": {}}} → 同上，input 包装层
      3. {"kwargs": {"query": ...}}             → kwargs 提升到外层
      4. {"query": ...}                        → 直接返回
      5. {"args": "query=\"...\", language=\"...\""} → 解析 Python 风格字符串
    """
    if not isinstance(args, dict):
        return {}

    # 格式 5: {"args": "query=\"...\", language=\"...\""} - Python 风格字符串
    # 这种情况出现在 LLM 返回的 args 是字符串而非列表/字典
    if "args" in args and isinstance(args.get("args"), str):
        raw_args_str = args["args"]
        parsed = _parse_python_style_args(raw_args_str)
        if parsed:
            # 保留其他 key（如 tool_call_id），合并解析结果
            others = {k: v for k, v in args.items() if k not in ("args", "config")}
            return {**others, **parsed}

    # 格式 1 & 2: {"args": [...], "config": {}}
    # 出现在顶层或在 "input"/"kwargs" 嵌套层中
    raw_list = None

    if "args" in args and "config" in args:
        raw_list = args.get("args", [])
    elif "input" in args:
        inner = args["input"]
        if isinstance(inner, dict):
            if "args" in inner and "config" in inner:
                raw_list = inner.get("args", [])
            elif "kwargs" in inner:
                # 格式 3: {"input": {"kwargs": {...}}}
                inner_kw = inner.get("kwargs", {})
                if isinstance(inner_kw, dict):
                    return {**args, **inner_kw}
        elif isinstance(inner, str):
            import json

            try:
                parsed = json.loads(inner)
                if isinstance(parsed, dict) and "args" in parsed and "config" in parsed:
                    raw_list = parsed.get("args", [])
            except json.JSONDecodeError:
                # JSON 解析失败时，尝试用 ast.literal_eval 解析 Python 字典格式
                import ast

                try:
                    parsed = ast.literal_eval(inner)
                    if isinstance(parsed, dict):
                        if "args" in parsed and "config" in parsed:
                            raw_list = parsed.get("args", [])
                        elif "kwargs" in parsed:
                            inner_kw = parsed.get("kwargs", {})
                            if isinstance(inner_kw, dict):
                                return {**args, **inner_kw}
                except (ValueError, SyntaxError, TypeError):
                    pass

    if isinstance(raw_list, list) and tool_name in _POSITIONAL_MAPPINGS:
        keys = _POSITIONAL_MAPPINGS[tool_name]
        mapped = {}
        for i, key in enumerate(keys):
            if i < len(raw_list):
                mapped[key] = raw_list[i]
        # 保留非 args/config 的其他 key（如 tool_call_id）
        others = {k: v for k, v in args.items() if k not in ("args", "config", "input")}
        return {**others, **mapped}

    return args


# ─── 辅助函数 ───────────────────────────────────────────────────────────────


def _parse_python_style_args(args_str: str) -> dict | None:
    """解析 Python 风格的参数字符串。

    处理 LLM 返回的错误格式，如：
      "query=\"shelljs\", language=\"javascript\""
      'query="foo", language="bar"'
      "path='src/main.js'"

    返回：
      {"query": "shelljs", "language": "javascript"}
    """
    import re

    if not args_str or not isinstance(args_str, str):
        return None

    result = {}

    # 匹配 key="value" 或 key='value' 格式
    # 支持值包含空格、连字符、下划线等
    pattern = r'(\w+)=["\']([^"\']*)["\']'
    matches = re.findall(pattern, args_str)

    if matches:
        for key, value in matches:
            result[key] = value
        return result if result else None

    # 如果上面没匹配到，尝试匹配 key=value（无引号）
    # 但这种情况下值不能包含特殊字符
    pattern2 = r"(\w+)=([\w.-]+)"
    matches2 = re.findall(pattern2, args_str)

    if matches2:
        for key, value in matches2:
            # 转换为字符串
            result[key] = str(value)
        return result if result else None

    return None


def _filter_tree(languages: list[str], tree: list[dict]) -> list[dict]:
    """根据语言扩展名过滤文件树（供 inject_context 使用）。"""
    from utils.tree_filter import filter_file_tree

    return filter_file_tree(tree, languages)


def inject_context(
    tool: StructuredTool,
    owner: str = "",
    repo: str = "",
    ref: str = "",
    languages: list[str] | None = None,
) -> StructuredTool:
    """包装单个工具：注入上下文 + 参数标准化 + 错误循环打断。

    四个职责：
      1. 自动填充 owner/repo/ref 等上下文参数
      2. 修正参数类型（字符串→列表、空字符串过滤等）
      3. 同一工具连续 3 次相同错误 → 抛 ToolLoopInterrupt 打断 agent 循环
      4. get_file_tree: 按代码语言过滤文件树（去掉 test/docs 等低价值文件）
    """
    orig_invoke = tool.invoke
    name = tool.name

    # 错误循环检测（每个工具独立追踪）
    _error_count = 0
    _last_error = ""

    # 空参数时的友好错误提示（提供具体修正指导）
    # 必须以 [ERROR] 开头，供 tool_wrapper 的错误循环检测识别
    _EMPTY_ERRORS: dict[str, str] = {
        "read_file_content": (
            "[ERROR] path 参数为空。请使用 search_code 工具先搜索文件，"
            "或基于仓库结构推断文件路径（如 main.py、src/index.js、package.json）。"
            "正确调用示例：read_file_content(path='src/index.js')"
        ),
        "search_code": (
            "[ERROR] query 参数为空。search_code 只需要两个参数：query（搜索关键词）和 language（可选）。\n"
            "⚠️ 注意：owner 和 repo 由系统自动注入，【不要】在调用时传递它们！\n"
            "正确调用示例：\n"
            "  ✅ search_code(query='useEffect', language='javascript')\n"
            "  ✅ search_code(query='def authenticate', language='python')\n"
            "  ❌ search_code(owner='facebook', repo='react', query='useEffect')  ← 错误！\n"
            "如果你想搜索 React Hook 使用情况，应该这样调用：search_code(query='useEffect', language='javascript')"
        ),
        "batch_search_code": (
            "[ERROR] queries 参数为空。batch_search_code 只需要一个参数：queries（查询列表）。\n"
            "⚠️ 注意：owner 和 repo 由系统自动注入，【不要】在调用时传递它们！\n"
            "queries 是 list[dict]，每个元素包含 query 和可选的 language。\n"
            "正确调用示例：\n"
            "  ✅ batch_search_code(queries=[{'query': 'useEffect', 'language': 'javascript'}, {'query': 'useState', 'language': 'javascript'}])\n"
            "  ✅ batch_search_code(queries=[{'query': 'def auth'}, {'query': 'class User'}])\n"
            "  ❌ batch_search_code(queries=[...], owner='facebook', repo='react')  ← 错误！"
        ),
    }

    def wrapped_invoke(raw_args=None, **kwargs):
        nonlocal _error_count, _last_error

        # 合并 kwargs（LangChain 有时以 keyword args 调用）
        if kwargs:
            if isinstance(raw_args, dict):
                raw_args = {**kwargs, **raw_args}
            else:
                raw_args = kwargs
        if raw_args is None:
            raw_args = {}

        # 标准化参数格式：各种调用格式 → 具名参数 dict
        args = _normalize_invocation_args(raw_args, name)
        args = _normalize_all(args)
        tool_args = dict(args)

        def _call_tool(params: dict) -> str:
            """调用原始工具。"""
            try:
                return orig_invoke(params)
            except Exception as e:
                err_msg = str(e)
                if "validation error" in err_msg.lower():
                    return (
                        f"[ERROR] 工具参数验证失败：{name}，{err_msg}。"
                        f"请检查参数类型：paths 必须是 list[str]，path/query 必须是 str。"
                    )
                return f"[ERROR] 工具执行错误：{type(e).__name__}: {err_msg}"

        # ── 工具分发：构建参数并调用 ──────────────────────────────────────

        result: str

        if name == "get_repo_info":
            result = _call_tool({"owner": owner, "repo": repo})

        elif name == "get_file_tree":
            raw_result = _call_tool({"owner": owner, "repo": repo, "ref": ref})
            # 按语言过滤文件树（去掉 test/docs/assets 等低价值文件）
            if languages and languages is not None:
                try:
                    import json

                    tree = json.loads(raw_result)
                    filtered = _filter_tree(languages, tree)
                    raw_result = json.dumps(filtered, ensure_ascii=False)
                    logger.info(
                        f"[inject_context] get_file_tree 过滤: {len(tree)} → {len(filtered)} 条"
                    )
                except Exception:
                    pass  # 解析失败时返回原始结果
            result = raw_result

        elif name == "get_commit_history":
            tool_args.setdefault("owner", owner)
            tool_args.setdefault("repo", repo)
            tool_args.setdefault("ref", ref)
            result = _call_tool(tool_args)

        elif name == "get_pull_requests":
            tool_args.setdefault("owner", owner)
            tool_args.setdefault("repo", repo)
            result = _call_tool(tool_args)

        elif name == "read_file_content":
            path = tool_args.get("path", "").strip()

            # 检测 LLM 是否错误地传入了额外参数（如 owner/repo）
            if "owner" in tool_args or "repo" in tool_args:
                result = (
                    "[ERROR] 参数错误：read_file_content 不需要 owner 和 repo 参数！\n"
                    "owner/repo/ref 由系统自动注入，你只需要提供 path。\n"
                    "正确调用示例：read_file_content(path='src/index.js')\n"
                    "请重试，只传 path 参数。"
                )
            elif not path:
                result = _EMPTY_ERRORS.get(name, "path 参数为空")
            else:
                result = _call_tool(
                    {
                        "owner": owner,
                        "repo": repo,
                        "path": path,
                        "ref": ref,
                    }
                )

        elif name == "get_file_blobs":
            result = _call_tool(
                {
                    "owner": owner,
                    "repo": repo,
                    "paths": tool_args.get("paths", []),
                    "ref": ref,
                }
            )

        elif name == "search_code":
            query = tool_args.get("query", "").strip()
            language = tool_args.get("language", "")

            # 检测 LLM 是否错误地传入了额外参数（如 owner/repo）
            if "owner" in tool_args or "repo" in tool_args:
                result = (
                    "[ERROR] 参数错误：search_code 不需要 owner 和 repo 参数！\n"
                    "owner/repo 由系统自动注入，你只需要提供 query 和 language。\n"
                    "正确调用示例：search_code(query='useEffect', language='javascript')\n"
                    "请重试，只传 query 和 language 参数。"
                )
            elif not query:
                result = _EMPTY_ERRORS.get(name, "query 参数为空")
            else:
                result = _call_tool(
                    {
                        "owner": owner,
                        "repo": repo,
                        "query": query,
                        "language": language,
                    }
                )

        elif name == "batch_search_code":
            queries = tool_args.get("queries", [])

            # 处理 LLM 返回 JSON 字符串的情况
            if isinstance(queries, str):
                import json

                try:
                    queries = json.loads(queries)
                except json.JSONDecodeError:
                    import ast

                    try:
                        queries = ast.literal_eval(queries)
                    except (ValueError, SyntaxError):
                        result = (
                            "[ERROR] 参数解析失败：queries 应该是 list[dict] 格式，但收到了无法解析的字符串。\n"
                            "正确调用示例：batch_search_code(queries=[{'query': 'useEffect', 'language': 'javascript'}])\n"
                            f"你收到的是：{queries[:100]}..."
                        )
                        _error_count = 0
                        _last_error = ""
                        return result

            if "owner" in tool_args or "repo" in tool_args:
                result = (
                    "[ERROR] 参数错误：batch_search_code 不需要 owner 和 repo 参数！\n"
                    "owner/repo 由系统自动注入，你只需要提供 queries。\n"
                    "正确调用示例：batch_search_code(queries=[{'query': 'useEffect', 'language': 'javascript'}])\n"
                    "请重试，只传 queries 参数。"
                )
            elif not queries:
                result = _EMPTY_ERRORS.get(name, "queries 参数为空")
            else:
                result = _call_tool(
                    {
                        "owner": owner,
                        "repo": repo,
                        "queries": queries,
                    }
                )

        elif name == "get_default_branch":
            result = _call_tool({"owner": owner, "repo": repo})

        else:
            result = _call_tool(tool_args)

        # ── 错误循环检测：连续 3 次相同错误 → 抛 ToolLoopInterrupt ────────
        # 使用 ToolResult.is_error() 判断，不再依赖关键词匹配
        _is_error = ToolResult.is_error(result)

        if _is_error:
            pattern = result[:80].strip()
            if pattern == _last_error:
                _error_count += 1
            else:
                _error_count = 1
                _last_error = pattern

            if _error_count >= _LOOP_THRESHOLD:
                # 抛 BaseException：LangGraph ToolNode 不会 catch，直接传播打断 agent
                raise ToolLoopInterrupt(
                    tool_name=name, pattern=pattern, count=_error_count
                )
        else:
            # 成功调用，重置计数
            _error_count = 0
            _last_error = ""

        return result

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=None,
        func=wrapped_invoke,
        infer_schema=False,
    )


def wrap_tools(
    tools: list,
    owner: str = "",
    repo: str = "",
    ref: str = "",
    languages: list[str] | None = None,
) -> list[StructuredTool]:
    """包装一组工具，自动注入 owner/repo/ref。"""
    return [
        inject_context(t, owner=owner, repo=repo, ref=ref, languages=languages)
        for t in tools
    ]
