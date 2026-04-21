"""
RAG 工具集 — 封装向量检索操作，供 Agent 调用以获取历史分析经验。

工具列表：
  - rag_search_similar:  搜索相似项目经验
  - rag_search_by_repo:  搜索同一仓库的历史分析
  - rag_search_by_category: 按类别搜索优化建议
  - rag_search_code_pattern: 搜索代码模式相关的历史建议
  - rag_store_suggestion: 存储分析建议到向量库（写操作）

这些工具让 Agent 在生成建议时能够主动检索历史经验。
"""
import json
import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("gitintel")


def _get_rag_store() -> Any:
    """懒加载 DashVector Store（复用 suggestion.py 的实现）。"""
    global _rag_store
    if _rag_store is None:
        try:
            from memory.dashvector_store import DashVectorStore
            _rag_store = DashVectorStore()
            logger.info(f"[rag_tools] RAG Store 初始化完成，可用: {_rag_store.is_available}")
        except ImportError:
            logger.warning("[rag_tools] DashVectorStore 未安装，RAG 工具将不可用")
            _rag_store = None
    return _rag_store


_rag_store: Any = None


def _rag_search_similar_impl(query: str, top_k: int = 5) -> str:
    """rag_search_similar 的底层实现（同步，供 run_in_executor 使用）。"""
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"error": "RAG Store 不可用", "results": []}, ensure_ascii=False)

    try:
        results = store.retrieve_similar(query, top_k=min(top_k, 20))
        items = [
            {
                "repo_url": r.repo_url,
                "category": r.category,
                "title": r.title,
                "content": r.content[:300],
                "score": getattr(r, "score", None),
                "created_at": getattr(r, "created_at", ""),
            }
            for r in results
        ]
        return json.dumps({"results": items, "total": len(items)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)


def _rag_store_suggestion_impl(
    repo_url: str,
    category: str,
    title: str,
    content: str,
    priority: str = "medium",
) -> str:
    """rag_store_suggestion 的底层实现（同步，供 run_in_executor 使用）。"""
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"success": False, "message": "RAG Store 不可用"}, ensure_ascii=False)

    try:
        suggestions = [{
            "title": title,
            "content": content,
            "category": category,
            "priority": priority,
        }]
        store.store_suggestions(repo_url=repo_url, suggestions=suggestions, category=category)
        return json.dumps({"success": True, "message": "建议已存储", "count": 1}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


@tool
def rag_search_similar(query: str, top_k: int = 5) -> str:
    """搜索与当前项目相似的历史分析经验。

    用途：Agent 生成优化建议时，主动检索同类项目的分析经验作为参考。
    例如：搜索 "React + TypeScript 项目" 可以找到类似技术栈项目的建议。

    Args:
        query:     搜索查询（如 "React 项目", "Python FastAPI", "机器学习项目"）
        top_k:     返回的最相似结果数量，默认 5

    Returns:
        JSON 数组字符串，每项包含：
          repo_url, category, title, content, score, created_at
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"error": "RAG Store 不可用", "results": []}, ensure_ascii=False)

    try:
        results = store.retrieve_similar(query, top_k=min(top_k, 20))
        items = [
            {
                "repo_url": r.repo_url,
                "category": r.category,
                "title": r.title,
                "content": r.content[:300],
                "score": getattr(r, "score", None),
                "created_at": getattr(r, "created_at", ""),
            }
            for r in results
        ]
        logger.info(f"[rag_tools] rag_search_similar('{query}') -> {len(items)} results")
        return json.dumps({"results": items, "total": len(items)}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] RAG 搜索失败: {e}")
        return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)


@tool
def rag_search_by_repo(repo_url: str, top_k: int = 5) -> str:
    """搜索同一仓库的历史分析记录。

    用途：分析同一个仓库多次时，Agent 可以检索之前的分析结论，
    了解哪些问题已经修复、哪些仍然存在。

    Args:
        repo_url:  仓库 URL（如 "owner/repo" 或完整 URL）
        top_k:     返回结果数量，默认 5

    Returns:
        JSON 数组字符串，每项包含：
          category, title, content, created_at
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"error": "RAG Store 不可用", "results": []}, ensure_ascii=False)

    try:
        results = store.retrieve_by_repo(repo_url, top_k=min(top_k, 20))
        items = [
            {
                "category": r.category,
                "title": r.title,
                "content": r.content[:300],
                "created_at": getattr(r, "created_at", ""),
            }
            for r in results
        ]
        logger.info(f"[rag_tools] rag_search_by_repo('{repo_url}') -> {len(items)} results")
        return json.dumps({"results": items, "total": len(items)}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] RAG 按仓库搜索失败: {e}")
        return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)


@tool
def rag_search_by_category(category: str, top_k: int = 5) -> str:
    """按类别搜索优化建议（不区分项目）。

    用途：Agent 需要查找某类问题的通用最佳实践时使用。
    例如：搜索 "security" 可以找到所有安全相关的历史建议。

    Args:
        category:  类别名称（security / testing / complexity / dependency /
                   architecture / infrastructure / readability / maintenance）
        top_k:    返回结果数量，默认 5

    Returns:
        JSON 数组字符串，每项包含：
          repo_url, category, title, content, score
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"error": "RAG Store 不可用", "results": []}, ensure_ascii=False)

    try:
        # 通过相似搜索实现（用类别关键词作为 query）
        results = store.retrieve_similar(category, top_k=min(top_k, 20))
        items = [
            {
                "repo_url": r.repo_url,
                "category": r.category,
                "title": r.title,
                "content": r.content[:300],
                "score": getattr(r, "score", None),
            }
            for r in results
            if r.category == category
        ]
        logger.info(f"[rag_tools] rag_search_by_category('{category}') -> {len(items)} results")
        return json.dumps({"results": items, "total": len(items)}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] RAG 类别搜索失败: {e}")
        return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)


@tool
def rag_search_code_pattern(code_pattern: str, top_k: int = 3) -> str:
    """搜索与特定代码模式相关的历史建议。

    用途：Agent 分析代码时，发现某个模式后主动检索相关经验。
    例如：发现 "async/await" 模式时搜索相关的最佳实践建议。

    Args:
        code_pattern: 代码模式关键词（如 "async", "decorator", "context manager"）
        top_k:        返回结果数量，默认 3

    Returns:
        JSON 数组字符串，每项包含：
          repo_url, title, content
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"error": "RAG Store 不可用", "results": []}, ensure_ascii=False)

    try:
        results = store.retrieve_similar(code_pattern, top_k=min(top_k, 10))
        items = [
            {
                "repo_url": r.repo_url,
                "title": r.title,
                "content": r.content[:200],
            }
            for r in results
        ]
        return json.dumps({"results": items, "total": len(items)}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] RAG 代码模式搜索失败: {e}")
        return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)


@tool
def rag_store_suggestion(
    repo_url: str,
    category: str,
    title: str,
    content: str,
    priority: str = "medium",
) -> str:
    """存储一条优化建议到向量库（供后续分析复用）。

    用途：分析完成后，Agent 将高优先级建议存入向量库，
    使后续分析同类项目时能够检索到相关经验。

    Args:
        repo_url:  仓库 URL（作为记录标识）
        category:  建议类别
        title:     建议标题
        content:   建议正文内容
        priority:  优先级 high / medium / low

    Returns:
        JSON 对象字符串：{success, message, id}
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"success": False, "message": "RAG Store 不可用"}, ensure_ascii=False)

    try:
        suggestions = [{
            "title": title,
            "content": content,
            "category": category,
            "priority": priority,
        }]
        store.store_suggestions(repo_url=repo_url, suggestions=suggestions, category=category)
        logger.info(f"[rag_tools] rag_store_suggestion('{title}') -> 成功")
        return json.dumps({"success": True, "message": "建议已存储", "count": 1}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] RAG 存储失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)
