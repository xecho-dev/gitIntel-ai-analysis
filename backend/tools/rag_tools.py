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
                "content": r.content[:500],
                "score": getattr(r, "score", None),
                "priority": r.priority,
                "tech_stack": r.tech_stack,
                "languages": r.languages,
                "project_scale": r.project_scale,
                "code_fix": r.code_fix,
                "verified": r.verified,
                "issue_type": r.issue_type,
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
    tech_stack: list[str] = None,
    languages: list[str] = None,
    project_scale: str = "",
    code_fix: dict = None,
    verified: bool = False,
    issue_type: str = "",
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
            "code_fix": code_fix or {},
            "verified": verified,
            "type": issue_type,
        }]
        store.store_suggestions(
            repo_url=repo_url,
            suggestions=suggestions,
            category=category,
            tech_stack=tech_stack or [],
            languages=languages or [],
            project_scale=project_scale,
        )
        return json.dumps({"success": True, "message": "建议已存储", "count": 1}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


def _rag_store_analysis_impl(repo_url: str, analysis_result: dict) -> str:
    """存储完整分析结果（多维度批量存储）。"""
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"success": False, "message": "RAG Store 不可用"}, ensure_ascii=False)

    try:
        result = store.store_analysis_result(repo_url=repo_url, analysis_result=analysis_result)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        _logger.error(f"[rag_tools] 综合存储失败: {e}")
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
                "content": r.content[:500],
                "score": getattr(r, "score", None),
                "priority": r.priority,
                "tech_stack": r.tech_stack,
                "languages": r.languages,
                "code_fix": r.code_fix,
                "verified": r.verified,
                "issue_type": r.issue_type,
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
                "content": r.content[:500],
                "priority": r.priority,
                "tech_stack": r.tech_stack,
                "languages": r.languages,
                "code_fix": r.code_fix,
                "verified": r.verified,
                "issue_type": r.issue_type,
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
                "content": r.content[:500],
                "score": getattr(r, "score", None),
                "priority": r.priority,
                "tech_stack": r.tech_stack,
                "languages": r.languages,
                "code_fix": r.code_fix,
                "verified": r.verified,
                "issue_type": r.issue_type,
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
                "content": r.content[:500],
                "category": r.category,
                "priority": r.priority,
                "tech_stack": r.tech_stack,
                "code_fix": r.code_fix,
                "issue_type": r.issue_type,
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
    tech_stack: str = "",
    languages: str = "",
    project_scale: str = "",
    code_fix: str = "",
    verified: bool = False,
    issue_type: str = "",
) -> str:
    """存储一条优化建议到向量库（供后续分析复用）。

    用途：分析完成后，Agent 将优化建议存入向量库，
    使后续分析同类项目时能够检索到相关经验。

    Args:
        repo_url:     仓库 URL（作为记录标识）
        category:     建议类别（security | performance | architecture | dependency | ...）
        title:        建议标题
        content:      建议正文内容
        priority:     优先级 high / medium / low
        tech_stack:   技术栈（逗号分隔，如 "react,typescript,next.js"）
        languages:    编程语言（逗号分隔，如 "TypeScript,Python"）
        project_scale: 项目规模（small | medium | large）
        code_fix:     code_fix JSON 字符串（包含 file、type、original、updated）
        verified:     是否经过工具验证
        issue_type:   问题类型（N+1查询 | 硬编码密码 | 循环依赖 | ...）

    Returns:
        JSON 对象字符串：{success, message, count}
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"success": False, "message": "RAG Store 不可用"}, ensure_ascii=False)

    try:
        # 解析 code_fix
        code_fix_obj = {}
        if code_fix:
            try:
                code_fix_obj = json.loads(code_fix)
            except json.JSONDecodeError:
                pass

        # 解析技术栈
        tech_stack_list = [t.strip() for t in tech_stack.split(",") if t.strip()] if tech_stack else []
        languages_list = [l.strip() for l in languages.split(",") if l.strip()] if languages else []

        suggestions = [{
            "title": title,
            "content": content,
            "category": category,
            "priority": priority,
            "code_fix": code_fix_obj,
            "verified": verified,
            "type": issue_type,
        }]
        count = store.store_suggestions(
            repo_url=repo_url,
            suggestions=suggestions,
            category=category,
            tech_stack=tech_stack_list,
            languages=languages_list,
            project_scale=project_scale,
        )
        logger.info(f"[rag_tools] rag_store_suggestion('{title}') -> 成功, count={count}")
        return json.dumps({"success": True, "message": "建议已存储", "count": count}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] RAG 存储失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


@tool
def rag_store_analysis(
    repo_url: str,
    analysis_result: str,
) -> str:
    """综合存储完整分析结果（多维度批量存储）。

    用途：分析完成后，一次性存储完整的分析结果到向量库，
    包括：优化建议、架构洞察、依赖风险、技术栈特征。

    Args:
        repo_url:        仓库 URL
        analysis_result: final_result JSON 字符串

    Returns:
        JSON 对象字符串：{success, counts: {suggestions, architecture, dependency, tech_stack}}
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"success": False, "message": "RAG Store 不可用"}, ensure_ascii=False)

    try:
        result = json.loads(analysis_result)
        output = store.store_analysis_result(repo_url=repo_url, analysis_result=result)
        logger.info(f"[rag_tools] rag_store_analysis('{repo_url}') -> 成功, total={output.get('total', 0)}")
        return json.dumps(output, ensure_ascii=False)
    except json.JSONDecodeError as e:
        logger.warning(f"[rag_tools] analysis_result JSON 解析失败: {e}")
        return json.dumps({"success": False, "message": f"JSON 解析失败: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] 综合存储失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


@tool
def rag_search_knowledge_base(
    query: str,
    top_k: int = 5,
    category: str = "",
    tech_stack: str = "",
) -> str:
    """知识库问答检索（支持多维度过滤）。

    用途：用户进行知识库问答时，根据 query 检索相关历史分析经验。

    Args:
        query:      检索 query（可以是问题、技术栈、问题类型等）
        top_k:      返回结果数量，默认 5
        category:   按类别过滤（security | performance | architecture | dependency | ...）
        tech_stack: 按技术栈过滤（逗号分隔）

    Returns:
        JSON 数组字符串，每项包含：
          repo_url, category, title, content, score, code_fix, tech_stack, languages
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"error": "RAG Store 不可用", "results": []}, ensure_ascii=False)

    try:
        # 构建增强 query
        enhanced_query = query
        if tech_stack:
            tech_parts = [t.strip() for t in tech_stack.split(",") if t.strip()]
            if tech_parts:
                enhanced_query = f"{enhanced_query} {' '.join(tech_parts)}"

        results = store.retrieve_similar(
            enhanced_query,
            top_k=min(top_k, 20),
            category=category if category else None,
        )
        items = [
            {
                "repo_url": r.repo_url,
                "category": r.category,
                "title": r.title,
                "content": r.content[:500],
                "score": r.score,
                "priority": r.priority,
                "tech_stack": r.tech_stack,
                "languages": r.languages,
                "code_fix": r.code_fix,
                "verified": r.verified,
                "issue_type": r.issue_type,
            }
            for r in results
        ]
        logger.info(f"[rag_tools] rag_search_knowledge_base('{query}') -> {len(items)} results")
        return json.dumps({"results": items, "total": len(items)}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[rag_tools] 知识库检索失败: {e}")
        return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)
