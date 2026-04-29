"""
Query Processor — 查询处理层。

职责：
  1. 查询意图分类（factual / analytical / conversational / code_related）
  2. 关键词提取
  3. 查询扩展（同义词、相关概念）
  4. 语言检测
  5. 特殊标记（代码相关、仓库相关）
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

_logger = logging.getLogger("gitintel")


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


# ─── 领域术语映射（用于查询扩展）───────────────────────────────────────

TERM_MAPPINGS: dict[str, list[str]] = {
    "性能": ["performance", "优化", "慢", "卡顿", "响应时间", "加载速度", "渲染"],
    "安全": ["security", "漏洞", "风险", "攻击", "权限", "认证", "授权", "xss", "csrf", "sql注入"],
    "架构": ["architecture", "设计模式", "结构", "模块化", "分层", "微服务", "monolith"],
    "依赖": ["dependency", "包管理", "版本", "npm", "pip", "conflict", "升级", "迁移"],
    "代码质量": ["code quality", "重构", "规范", "lint", "format", "clean code"],
    "测试": ["testing", "单元测试", "集成测试", "e2e", "coverage", "jest", "pytest"],
    "typescript": ["ts", "类型安全", "interface", "type", "泛型"],
    "python": ["python", "py", "pip", "django", "flask", "fastapi"],
    "react": ["react", "hooks", "组件", "state", "props", "jsx", "next.js"],
    "前端": ["frontend", "ui", "css", "html", "浏览器", "dom"],
    "后端": ["backend", "api", "server", "数据库", "db"],
    "部署": ["deployment", "ci/cd", "docker", "k8s", "nginx", "vercel"],
    "内存泄漏": ["memory leak", "gc", "垃圾回收", "堆栈", "heap"],
    "并发": ["concurrency", "并行", "异步", "多线程", "锁", "race condition"],
}


# ─── 意图分类规则 ─────────────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "factual": [
        "是什么", "什么是", "有什么区别", "哪个好", "如何实现",
        "怎么实现", "怎么做", "方法", "步骤", "流程",
        "explain", "what is", "how to", "difference between",
    ],
    "analytical": [
        "分析", "评估", "对比", "建议", "优化", "改进",
        "原因", "为什么", "哪里问题", "风险",
        "analyze", "evaluate", "compare", "suggest", "optimize",
    ],
    "code_related": [
        "代码", "函数", "算法", "class ", "def ", "const ", "let ",
        "async ", "await", "this.", "import ", "export ", "interface ",
        "复杂度", "时间", "空间", "bug", "报错", "error", "exception",
    ],
    "conversational": [
        "你好", "hi", "hello", "嗨", "help", "怎么用", "是什么",
        "请问", "问一下", "问一下", "谢谢你", "thanks",
    ],
}


# ─── 代码模式检测 ─────────────────────────────────────────────────────

CODE_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 函数定义
    ("python_def", re.compile(r'\bdef\s+\w+\s*\(')),
    ("js_function", re.compile(r'\bfunction\s+\w+\s*\(')),
    ("ts_interface", re.compile(r'\binterface\s+\w+\s*\{')),
    ("rust_fn", re.compile(r'\bfn\s+\w+\s*\(')),
    ("go_func", re.compile(r'\bfunc\s+\w+\s*\(')),
    # 代码符号
    ("arrow", re.compile(r'=>\s*\{')),
    ("async", re.compile(r'\basync\s+(def|function|fn)')),
    ("class_def", re.compile(r'\bclass\s+\w+')),
    ("import", re.compile(r'\b(import|from|require|include)\s+')),
    ("decorator", re.compile(r'@\w+')),
    # 代码内容
    ("console", re.compile(r'console\.(log|error|warn)')),
    ("print", re.compile(r'\bprint\s*\(')),
]


# ─── 仓库 URL 检测 ────────────────────────────────────────────────────

REPO_PATTERNS: list[re.Pattern] = [
    re.compile(r'github\.com/[\w-]+/[\w.-]+'),
    re.compile(r'[\w-]+/[\w.-]+'),  # owner/repo 格式
]


def _detect_language(text: str) -> str:
    """检测查询语言"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))

    if chinese_chars > english_chars * 0.3:
        return "zh"
    elif english_chars > chinese_chars * 3:
        return "en"
    return "mixed"


def _classify_intent(query: str, is_code_related: bool) -> str:
    """基于关键词规则分类意图"""
    q = query.lower()

    # 代码相关优先
    if is_code_related:
        return "code_related"

    # 检查各意图关键词
    scores: dict[str, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        if intent == "code_related":
            continue
        score = sum(1 for kw in keywords if kw.lower() in q)
        scores[intent] = score

    # 返回得分最高的意图
    if scores:
        best_intent = max(scores, key=scores.get)
        if scores[best_intent] > 0:
            return best_intent

    return "conversational"


def _extract_keywords(query: str, language: str) -> list[str]:
    """提取查询关键词"""
    # 移除标点符号和停用词
    stop_words = {"的", "是", "在", "有", "和", "了", "我", "你", "他", "她", "它",
                   "a", "an", "the", "is", "are", "was", "were", "be", "been",
                   "have", "has", "had", "do", "does", "did", "will", "would",
                   "could", "should", "may", "might", "can", "to", "of", "in",
                   "for", "on", "with", "at", "by", "from", "as", "into", "through"}

    # 简单分词（按空格和标点）
    words = re.split(r'[\s,，.。!！?？;；:：()（）\[\]【】""''""''《》<>\/]+', query)
    words = [w.strip().lower() for w in words if w.strip()]

    # 过滤停用词和短词
    keywords = [w for w in words if w not in stop_words and len(w) >= 2]

    return list(dict.fromkeys(keywords))  # 去重保持顺序


def _expand_query(query: str, keywords: list[str]) -> list[str]:
    """查询扩展：增加同义词和相关概念"""
    expanded = list(keywords)

    for kw in keywords:
        # 精确匹配
        if kw in TERM_MAPPINGS:
            for synonym in TERM_MAPPINGS[kw]:
                if synonym not in expanded:
                    expanded.append(synonym)

        # 部分匹配（中文字符串可能包含关键词）
        for term, synonyms in TERM_MAPPINGS.items():
            if term in query or any(s in query for s in synonyms[:3]):
                for synonym in synonyms:
                    if synonym not in expanded:
                        expanded.append(synonym)

    return expanded[:12]  # 限制扩展词数量


def _detect_code_patterns(query: str) -> bool:
    """检测查询是否涉及代码"""
    for _, pattern in CODE_PATTERNS:
        if pattern.search(query):
            return True
    return False


def _detect_repo_patterns(query: str) -> tuple[bool, Optional[str]]:
    """检测查询是否涉及仓库URL"""
    for pattern in REPO_PATTERNS:
        match = pattern.search(query)
        if match:
            repo_url = match.group(0)
            if not repo_url.startswith("github.com/"):
                repo_url = f"github.com/{repo_url}"
            return True, repo_url
    return False, None


def _detect_tech_stack(query: str) -> list[str]:
    """检测查询中提到的技术栈"""
    detected = []
    tech_patterns = {
        "react": re.compile(r'\breact\b', re.I),
        "vue": re.compile(r'\bvue\b', re.I),
        "angular": re.compile(r'\bangular\b', re.I),
        "next.js": re.compile(r'\bnext\.?js?\b', re.I),
        "nuxt": re.compile(r'\bnuxt\b', re.I),
        "svelte": re.compile(r'\bsvelte\b', re.I),
        "django": re.compile(r'\bdjango\b', re.I),
        "flask": re.compile(r'\bflask\b', re.I),
        "fastapi": re.compile(r'\bfastapi\b', re.I),
        "express": re.compile(r'\bexpress\b', re.I),
        "spring": re.compile(r'\bspring\b', re.I),
        "golang": re.compile(r'\b(go|golang)\b', re.I),
        "rust": re.compile(r'\brust\b', re.I),
        "typescript": re.compile(r'\btypescript\b', re.I),
        "python": re.compile(r'\bpython\b', re.I),
        "java": re.compile(r'\bjava\b', re.I),
        "docker": re.compile(r'\bdocker\b', re.I),
        "kubernetes": re.compile(r'\bkubernetes\b', re.I),
        "aws": re.compile(r'\baws\b', re.I),
        "azure": re.compile(r'\bazure\b', re.I),
    }

    for tech, pattern in tech_patterns.items():
        if pattern.search(query):
            detected.append(tech)

    return detected


def process_query(query: str) -> ProcessedQuery:
    """
    Query Processing 主函数：分析用户查询

    Args:
        query: 原始用户查询

    Returns:
        ProcessedQuery: 处理后的查询对象
    """
    # 1. 语言检测
    language = _detect_language(query)

    # 2. 特殊标记
    is_code_related = _detect_code_patterns(query)
    is_repo_related, repo_url = _detect_repo_patterns(query)

    # 3. 技术栈检测
    detected_tech_stack = _detect_tech_stack(query)

    # 4. 关键词提取
    keywords = _extract_keywords(query, language)

    # 5. 查询扩展
    expanded_terms = _expand_query(query, keywords)

    # 6. 意图分类
    intent = _classify_intent(query, is_code_related)

    _logger.info(
        f"[QueryProcessor] query='{query[:50]}...', "
        f"intent={intent}, lang={language}, "
        f"code={is_code_related}, repo={is_repo_related}, "
        f"keywords={keywords[:5]}, expanded={expanded_terms[:5]}"
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
    )
