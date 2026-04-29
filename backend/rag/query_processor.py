"""
Query Processor — 查询处理层。

职责：
  1. HyDE 假设文档生成（先用 LLM 生成"假设答案"，再用于检索）
  2. LLM-Based 意图分类（factual / analytical / conversational / code_related）
  3. LLM-Based 特殊标记检测（代码相关、仓库相关、技术栈）
  4. 关键词提取
  5. 语言检测

HyDE 流程：
  用户查询 → 生成假设文档 → 向量检索（用假设文档） → 真实文档
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

_logger = logging.getLogger("gitintel")


# ─── HyDE Prompt Templates ──────────────────────────────────────────────

HYDE_SYSTEM_PROMPT = """你是一个专业的技术文档助手。你的任务是根据用户问题生成一个"假设的技术文档"。

要求：
1. 这个假设文档应该是一个完整、详细的技术回答
2. 包含具体的代码示例、技术细节、实现方法
3. 使用真实的技术术语和概念
4. 文档长度适中（200-500字），足够提供丰富的语义信息用于检索
5. 不要求回答完全正确，重点是提供丰富的检索信号"""

HYDE_USER_PROMPT_TEMPLATE = """【用户问题】
{query}

【任务】
请根据上述问题，生成一段详细的技术文档作为"假设回答"。
这段文档将用于向量检索，因此需要包含丰富的技术术语和概念。

【输出格式】
直接输出一段技术文档，不需要额外说明。"""


# ─── 查询分析 Prompt Templates ─────────────────────────────────────────

QUERY_ANALYSIS_SYSTEM_PROMPT = """你是一个查询分析助手。请分析用户查询，返回结构化的分析结果。

分析维度：
1. intent（意图）: factual(事实) | analytical(分析) | conversational(对话) | code_related(代码相关)
2. language（语言）: zh(中文) | en(英文) | mixed(混合)
3. is_code_related（是否代码相关）: true | false
4. detected_tech_stack（检测到的技术栈）: 数组，如 ["react", "typescript"]
5. repo_url（仓库URL）: 如果提到了 GitHub 仓库则返回完整 URL，否则返回 null

请严格按 JSON 格式返回，不要输出其他内容。"""

QUERY_ANALYSIS_USER_PROMPT_TEMPLATE = """【用户查询】
{query}

【输出格式】
直接返回 JSON，不要任何解释：
{{"intent": "...", "language": "...", "is_code_related": ..., "detected_tech_stack": [...], "repo_url": null或完整URL}}"""


# ─── 假设文档缓存（避免重复生成）────────────────────────────────────────

_hyde_cache: dict[str, str] = {}
_query_analysis_cache: dict[str, dict] = {}
_CACHE_MAX_SIZE = 200


# ─── ProcessedQuery ──────────────────────────────────────────────────────

@dataclass
class ProcessedQuery:
    """处理后的查询对象"""
    original: str
    keywords: list[str]
    expanded_terms: list[str]
    intent: str  # factual | analytical | conversational | code_related
    language: str  # zh | en | mixed
    is_code_related: bool
    is_repo_related: bool
    repo_url: Optional[str] = None
    detected_tech_stack: list[str] = field(default_factory=list)
    # HyDE 字段
    hyde_document: Optional[str] = None  # LLM 生成的假设文档
    hyde_enabled: bool = False


# ─── 查询分析（LLM-Based，替代规则穷举）────────────────────────────────

async def _analyze_query_llm(query: str) -> dict:
    """
    使用 LLM 分析查询意图、语言、技术栈等。
    替代原有的穷举式规则匹配。
    """
    cache_key = query[:100]
    if cache_key in _query_analysis_cache:
        _logger.debug(f"[QueryAnalysis] Cache hit for: {query[:30]}...")
        return _query_analysis_cache[cache_key]

    try:
        from utils.llm_factory import get_llm_with_tracking

        llm = get_llm_with_tracking(
            agent_name="query_analyzer",
            model=None,
            temperature=0.0,  # 分析不需要创造性，一致性更重要
            max_tokens=256,
        )

        if llm is None:
            return _default_analysis()

        messages = [
            SystemMessage(content=QUERY_ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(content=QUERY_ANALYSIS_USER_PROMPT_TEMPLATE.format(query=query)),
        ]

        response = await llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        result = json.loads(content.strip())

        if len(_query_analysis_cache) >= _CACHE_MAX_SIZE:
            _query_analysis_cache.clear()
        _query_analysis_cache[cache_key] = result

        return result

    except Exception as e:
        _logger.warning(f"[QueryAnalysis] LLM 分析失败: {e}，使用默认分析")
        return _default_analysis()


def _default_analysis() -> dict:
    """当 LLM 不可用时的默认分析"""
    return {
        "intent": "conversational",
        "language": "mixed",
        "is_code_related": False,
        "detected_tech_stack": [],
        "repo_url": None,
    }


# ─── 关键词提取 ─────────────────────────────────────────────────────────

def _extract_keywords(query: str) -> list[str]:
    """提取查询关键词（轻量规则，作为 HyDE 的补充）"""
    stop_words = {
        "的", "是", "在", "有", "和", "了", "我", "你", "他", "她", "它",
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "as", "into", "through",
    }

    words = re.split(r'[\s,，.。!！?？;；:：()（）\[\]【】""''""''《》<>\/]+', query)
    words = [w.strip().lower() for w in words if w.strip()]

    keywords = [w for w in words if w not in stop_words and len(w) >= 2]
    return list(dict.fromkeys(keywords))  # 去重保持顺序


# ─── HyDE: 假设文档生成 ─────────────────────────────────────────────────

async def _generate_hyde_document(query: str, is_code_related: bool) -> Optional[str]:
    """
    使用 LLM 生成假设文档（HyDE）。

    Args:
        query: 原始用户查询
        is_code_related: 是否代码相关（影响 prompt 风格）

    Returns:
        假设文档文本，失败时返回 None
    """
    cache_key = f"{query[:100]}_{is_code_related}"
    if cache_key in _hyde_cache:
        _logger.debug(f"[HyDE] Cache hit for query: {query[:30]}...")
        return _hyde_cache[cache_key]

    try:
        from utils.llm_factory import get_llm_with_tracking

        llm = get_llm_with_tracking(
            agent_name="hyde_generator",
            model=None,
            temperature=0.7,  # HyDE 需要一定创造性
            max_tokens=512,
        )

        if llm is None:
            _logger.warning("[HyDE] LLM 不可用，跳过假设文档生成")
            return None

        if is_code_related:
            system_prompt = (
                "你是一个专业的代码技术助手。根据用户问题，生成一段包含代码示例的技术文档。\n"
                "要求：\n"
                "1. 包含具体的代码实现\n"
                "2. 解释代码逻辑和原理\n"
                "3. 指出潜在的注意事项\n"
                "4. 使用 markdown 代码块\n"
                "5. 长度 200-400 字"
            )
        else:
            system_prompt = HYDE_SYSTEM_PROMPT

        user_prompt = HYDE_USER_PROMPT_TEMPLATE.format(query=query)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await llm.ainvoke(messages)
        hyde_doc = response.content if hasattr(response, "content") else str(response)

        if len(_hyde_cache) >= _CACHE_MAX_SIZE:
            _hyde_cache.clear()
        _hyde_cache[cache_key] = hyde_doc

        _logger.info(f"[HyDE] Generated document for query: {query[:30]}...")
        return hyde_doc

    except Exception as e:
        _logger.warning(f"[HyDE] 生成假设文档失败: {e}")
        return None


# ─── 基于 HyDE 提取扩展词 ───────────────────────────────────────────────

def _expand_query_from_hyde(hyde_doc: Optional[str]) -> list[str]:
    """
    从假设文档中提取扩展词。
    不再依赖硬编码的 TERM_MAPPINGS。
    """
    if not hyde_doc:
        return []

    expanded = []

    # 从引号中提取术语
    quoted = re.findall(r'[""「『]([^""」』]+)[""」』]', hyde_doc)
    expanded.extend(t.strip().lower() for t in quoted if len(t.strip()) >= 2)

    # 从代码块中提取标识符
    code_blocks = re.findall(r'```[\s\S]*?```', hyde_doc)
    for block in code_blocks:
        identifiers = re.findall(r'\b([a-zA-Z_]\w{2,20})\b', block)
        expanded.extend(i.lower() for i in identifiers)

    # 从 backtick 中提取技术关键词
    tech_terms = re.findall(r'`([^`]+)`', hyde_doc)
    expanded.extend(t.strip().lower() for t in tech_terms if len(t) >= 2)

    # 去重
    seen = set()
    for term in expanded:
        term = term.strip()
        if term and term not in seen and len(term) >= 2:
            seen.add(term)

    return list(seen)[:12]


# ─── 主流程 ─────────────────────────────────────────────────────────────

async def process_query(query: str, enable_hyde: bool = True) -> ProcessedQuery:
    """
    Query Processing 主函数：分析用户查询，并可选地生成 HyDE 假设文档。

    流程：
      原始查询 → LLM 意图/语言/技术栈分析 → HyDE 生成假设文档
              → 扩展词提取 → ProcessedQuery
    """
    # 1. LLM 查询分析（意图、语言、技术栈、代码相关、仓库URL）
    analysis = await _analyze_query_llm(query)

    intent: str = analysis.get("intent", "conversational")
    language: str = analysis.get("language", "mixed")
    is_code_related: bool = analysis.get("is_code_related", False)
    detected_tech_stack: list = analysis.get("detected_tech_stack", [])
    raw_repo_url: Optional[str] = analysis.get("repo_url")

    is_repo_related = raw_repo_url is not None
    repo_url: Optional[str] = None
    if is_repo_related and raw_repo_url:
        url = raw_repo_url.strip()
        if not url.startswith("github.com/") and not url.startswith("http"):
            repo_url = f"github.com/{url}"
        else:
            repo_url = url

    # 2. 关键词提取（轻量规则，作为 HyDE 的补充信号）
    keywords = _extract_keywords(query)

    # 3. HyDE 假设文档生成
    hyde_document: Optional[str] = None
    if enable_hyde:
        hyde_document = await _generate_hyde_document(query, is_code_related)

    # 4. 扩展词（基于 HyDE 提取）
    expanded_terms = _expand_query_from_hyde(hyde_document)

    _logger.info(
        f"[QueryProcessor] query='{query[:50]}...', "
        f"intent={intent}, lang={language}, "
        f"code={is_code_related}, repo={is_repo_related}, "
        f"tech_stack={detected_tech_stack}, "
        f"hyde={'✓' if hyde_document else '✗'}"
    )

    return ProcessedQuery(
        original=query,
        keywords=keywords,
        expanded_terms=expanded_terms,
        intent=intent,
        language=language,
        is_code_related=is_code_related,
        is_repo_related=is_repo_related,
        repo_url=repo_url,
        detected_tech_stack=detected_tech_stack,
        hyde_document=hyde_document,
        hyde_enabled=bool(hyde_document),
    )
