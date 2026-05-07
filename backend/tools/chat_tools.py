"""
Chat 专用工具集 — 供 LangGraph Chat Agent 通过 Function Calling 调用。

这些工具让 Agent 能够自主决定：
  1. 检索知识库（rag_search_knowledge_base）
  2. 查询仓库分析结果（lookup_repo_analysis）
  3. 分析用户粘贴的代码（parse_file_ast / calculate_complexity / detect_code_smells）
  4. 搜索相似项目经验（rag_search_similar）
  5. 存储有价值的建议（rag_store_suggestion）
"""

import json
import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("gitintel")


# ─── RAG 知识库工具 ────────────────────────────────────────────────────────


def _get_rag_store() -> Any:
    """懒加载 Chroma Store。"""
    global _rag_store
    if _rag_store is None:
        try:
            from memory.chromadb_store import ChromaStore
            _rag_store = ChromaStore(collection_type="knowledge")
        except ImportError:
            _rag_store = None
    return _rag_store


_rag_store: Any = None


@tool
def rag_search_knowledge_base(
    query: str,
    top_k: int = 5,
    category: str = "",
    tech_stack: str = "",
) -> str:
    """搜索 GitIntel 知识库，获取相关的分析经验、最佳实践、技术建议。

    用途：Agent 回答知识库相关问题时，先检索历史分析经验。

    Args:
        query:      搜索 query（可以是问题、技术栈、问题类型等）
        top_k:      返回结果数量，默认 5
        category:   按类别过滤（security | performance | architecture | dependency | ...）
        tech_stack: 按技术栈过滤（逗号分隔）

    Returns:
        JSON 对象：{results: [...], total: int}
    """
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"error": "RAG Store 不可用", "results": []}, ensure_ascii=False)

    try:
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
                "content": r.content[:600],
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
        logger.info(f"[chat_tools] rag_search_knowledge_base('{query}') -> {len(items)} results")
        return json.dumps({"results": items, "total": len(items)}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[chat_tools] 知识库检索失败: {e}")
        return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)


@tool
def rag_search_similar(
    query: str,
    top_k: int = 5,
) -> str:
    """搜索与当前问题相似的历史分析经验。

    用途：Agent 生成建议时，参考同类项目的分析经验。

    Args:
        query: 搜索查询（如 "React 项目性能问题", "Python FastAPI 架构"）
        top_k: 返回结果数量，默认 5

    Returns:
        JSON 对象：{results: [...], total: int}
    """
    return rag_search_knowledge_base.invoke({"query": query, "top_k": top_k})


@tool
def rag_search_by_category(
    category: str,
    top_k: int = 5,
) -> str:
    """按类别搜索优化建议（不区分项目）。

    用途：Agent 需要查找某类问题的通用最佳实践。

    Args:
        category: 类别名称（security | testing | complexity | dependency | architecture | ...）
        top_k:    返回结果数量，默认 5

    Returns:
        JSON 对象：{results: [...], total: int}
    """
    return rag_search_knowledge_base.invoke({"query": category, "top_k": top_k, "category": category})


# ─── 仓库分析结果查询工具 ───────────────────────────────────────────────────


@tool
def lookup_repo_analysis(repo_url: str) -> str:
    """查询某个仓库是否已有分析结果。

    用途：用户询问具体仓库的分析结果时，先检查是否有缓存数据。

    Args:
        repo_url: 仓库 URL（owner/repo 格式）

    Returns:
        JSON 对象：{found: bool, data: {...} 或 null}
    """
    try:
        # 尝试从内存缓存获取
        from services.analysis_cache import get_cached_result
        result = get_cached_result(repo_url)
        if result:
            return json.dumps({"found": True, "data": result}, ensure_ascii=False)
    except ImportError:
        pass

    # 尝试从数据库获取最新分析记录
    try:
        from services.database import get_latest_analysis_result
        result = get_latest_analysis_result(repo_url)
        if result:
            return json.dumps({"found": True, "data": result}, ensure_ascii=False)
    except ImportError:
        pass

    return json.dumps({"found": False, "data": None}, ensure_ascii=False)


# ─── 代码分析工具（复用 code_tools）──────────────────────────────────────────


@tool
def analyze_code(content: str, language: str = "python") -> str:
    """分析用户粘贴的代码片段（综合分析：结构 + 复杂度 + 异味）。

    用途：用户粘贴代码后，Agent 自动决定是否调用此工具来深度分析。

    Args:
        content:  代码内容字符串
        language: 编程语言（python/javascript/typescript/go/rust/java/cpp 等）

    Returns:
        JSON 对象：{
            summary: str,           # 文件结构摘要
            complexity: {...},       # 圈复杂度分析
            smells: [...],           # 代码异味列表
            imports: [...],          # 导入语句
            dependencies: {...}     # 依赖使用情况
        }
    """
    try:
        from tools.code_tools import (
            summarize_code_file,
            calculate_complexity,
            detect_code_smells,
            detect_imports,
            detect_dependencies,
        )

        summary = summarize_code_file.invoke({"content": content, "language": language})
        complexity = calculate_complexity.invoke({"content": content, "language": language})
        smells = detect_code_smells.invoke({"content": content, "language": language})
        imports = detect_imports.invoke({"content": content, "language": language})
        dependencies = detect_dependencies.invoke({"content": content, "language": language})

        # 解析 JSON 字符串
        def parse_json(raw):
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except Exception:
                    return {"raw": raw[:200]}
            return raw

        return json.dumps({
            "summary": summary if isinstance(summary, str) else str(summary),
            "complexity": parse_json(complexity),
            "smells": parse_json(smells),
            "imports": parse_json(imports),
            "dependencies": parse_json(dependencies),
        }, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[chat_tools] analyze_code 失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def detect_code_language(content: str) -> str:
    """根据代码内容自动识别编程语言。

    用途：用户粘贴代码但未指定语言时，Agent 自动检测。

    Args:
        content: 代码内容字符串（前几行即可）

    Returns:
        语言名称字符串，如 "python", "javascript", "typescript", "go", "rust", ...
    """
    content_lower = content.lower().strip()

    signals = {
        "python": ["def ", "import ", "from ", "if __name__", "print(", "elif ", "async def"],
        "javascript": ["const ", "let ", "function ", "=> {", "console.log", "require(", "export "],
        "typescript": ["interface ", ": string", ": number", ": boolean", "type ", "as "],
        "go": ["func ", "package ", "import (", 'fmt.', ":= ", "go func"],
        "rust": ["fn ", "let mut", "impl ", "pub fn", "use ", "-> ", "println!"],
        "java": ["public class", "private ", "System.out.", "void ", "import java."],
        "cpp": ["#include", "std::", "int main(", "cout <<", "nullptr", "namespace "],
        "ruby": ["def ", "end", "puts ", "require '", "attr_", "each do"],
        "swift": ["func ", "var ", "let ", "import ", "struct ", "guard "],
        "kotlin": ["fun ", "val ", "var ", "import ", "class ", "suspend "],
    }

    scores = {}
    for lang, keywords in signals.items():
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scores[lang] = score

    if not scores:
        return "unknown"

    return max(scores, key=scores.get)


# ─── 存储建议工具 ────────────────────────────────────────────────────────────


@tool
def store_suggestion(
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
    """将一条有价值的建议存储到知识库（供后续分析复用）。

    用途：Agent 生成高质量建议后，将其存入向量库。

    Args:
        repo_url:     仓库 URL（为空表示通用建议）
        category:     建议类别（security | performance | architecture | dependency | ...）
        title:        建议标题
        content:      建议正文
        priority:     优先级 high / medium / low
        tech_stack:   技术栈（逗号分隔）
        languages:    编程语言（逗号分隔）
        project_scale: 项目规模（small | medium | large）
        code_fix:     code_fix JSON 字符串
        verified:     是否经过工具验证
        issue_type:   问题类型

    Returns:
        JSON 对象：{success: bool, message: str, count: int}
    """
    return rag_search_knowledge_base.invoke({})  # placeholder; real impl below


def _store_suggestion_impl(
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
    """rag_store_suggestion 的底层实现（同步）。"""
    store = _get_rag_store()
    if store is None or not store.is_available:
        return json.dumps({"success": False, "message": "RAG Store 不可用"}, ensure_ascii=False)

    try:
        code_fix_obj = {}
        if code_fix:
            try:
                code_fix_obj = json.loads(code_fix)
            except json.JSONDecodeError:
                pass

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
            repo_url=repo_url or "general",
            suggestions=suggestions,
            category=category,
            tech_stack=tech_stack_list,
            languages=languages_list,
            project_scale=project_scale,
        )
        logger.info(f"[chat_tools] store_suggestion('{title}') -> 成功, count={count}")
        return json.dumps({"success": True, "message": "建议已存储", "count": count}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[chat_tools] 存储建议失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


# ─── 工具列表（供 Agent 绑定）───────────────────────────────────────────────

CHAT_TOOLS = [
    rag_search_knowledge_base,
    rag_search_similar,
    rag_search_by_category,
    lookup_repo_analysis,
    analyze_code,
    detect_code_language,
]
