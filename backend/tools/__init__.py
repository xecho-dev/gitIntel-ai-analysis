"""
GitIntel 工具层 — 统一的 Function Calling / Tool Use 抽象。

每个工具都遵循 LangChain @tool 装饰器规范，支持 Agent 通过
Function Calling 动态调用，而非硬编码的工具调用。

目录结构：
  github_tools.py  — GitHub API 相关工具
  code_tools.py    — 代码分析工具（AST、复杂度等）
  rag_tools.py     — RAG 检索工具
  __init__.py      — 统一导出

使用方式：
  from tools import (
      # GitHub 工具
      get_repo_info, get_file_tree, read_file_content,
      get_file_blobs, search_code, get_commit_history,
      get_pull_requests, get_default_branch,
      # 代码分析工具
      parse_file_ast, calculate_complexity, detect_code_smells,
      summarize_code_file, detect_imports, detect_dependencies,
      # RAG 工具
      rag_search_similar, rag_search_by_repo, rag_search_by_category,
      rag_search_code_pattern, rag_store_suggestion,
  )

  # 绑定到 LLM
  llm_with_tools = llm.bind_tools(tools)
  response = await llm_with_tools.ainvoke([...])
"""

from tools.github_tools import (
    get_repo_info,
    get_file_tree,
    read_file_content,
    get_file_blobs,
    search_code,
    get_commit_history,
    get_pull_requests,
    get_default_branch,
)

from tools.code_tools import (
    parse_file_ast,
    calculate_complexity,
    detect_code_smells,
    summarize_code_file,
    detect_imports,
    detect_dependencies,
)

from tools.rag_tools import (
    rag_search_similar,
    rag_search_by_repo,
    rag_search_by_category,
    rag_search_code_pattern,
    rag_store_suggestion,
    rag_search_knowledge_base,
    rag_store_analysis,
)
from tools.chat_tools import (
    rag_search_knowledge_base as chat_rag_search_knowledge_base,
    rag_search_similar as chat_rag_search_similar,
    rag_search_by_category as chat_rag_search_by_category,
    lookup_repo_analysis,
    analyze_code,
    detect_code_language,
    CHAT_TOOLS,
)

# 所有工具的聚合列表（方便批量绑定到 LLM）
ALL_TOOLS = [
    # GitHub
    get_repo_info,
    get_file_tree,
    read_file_content,
    get_file_blobs,
    search_code,
    get_commit_history,
    get_pull_requests,
    get_default_branch,
    # Code
    parse_file_ast,
    calculate_complexity,
    detect_code_smells,
    summarize_code_file,
    detect_imports,
    detect_dependencies,
    # RAG
    rag_search_similar,
    rag_search_by_repo,
    rag_search_by_category,
    rag_search_code_pattern,
    rag_store_suggestion,
    # Chat
    *CHAT_TOOLS,
]

__all__ = [
    # GitHub
    "get_repo_info", "get_file_tree", "read_file_content", "get_file_blobs",
    "search_code", "get_commit_history", "get_pull_requests", "get_default_branch",
    # Code
    "parse_file_ast", "calculate_complexity", "detect_code_smells",
    "summarize_code_file", "detect_imports", "detect_dependencies",
    # RAG
    "rag_search_similar", "rag_search_by_repo", "rag_search_by_category",
    "rag_search_code_pattern", "rag_store_suggestion", "rag_search_knowledge_base",
    "rag_store_analysis",
    # Chat
    "lookup_repo_analysis", "analyze_code", "detect_code_language", "CHAT_TOOLS",
    # All
    "ALL_TOOLS",
]
