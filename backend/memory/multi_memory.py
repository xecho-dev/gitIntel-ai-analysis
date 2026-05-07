"""
多层记忆系统 — 短期记忆 + 长期记忆（GPT 类异步抽取架构）。

架构：
  短期记忆（ShortTermMemory） → ChatMessageHistory 缓冲，保留最近 N 轮对话
  长期记忆（LongTermMemory）  → 异步轻量抽取 + 分层向量存储 + 按需检索

长期记忆存储判断标准（GPT 类系统）：
  1. 是否是"稳定信息"（长期不变）  → Profile 类（名字、职业、居住地）→ 永不过期
  2. 是否"与用户身份强绑定"        → Preference 类（喜欢/讨厌）      → 长期有效
  3. 是否"值得未来使用"           → Knowledge 类（正在做的项目）    → 有过期时间

存储分层：
  profile    → 永不过期（用户身份核心信息）
  permanent  → 长期有效（偏好、习惯）
  temporary  → 有过期时间（当前项目、技术点）

异步抽取流程：
  add_turn() → 立即存短期 → 后台任务 → LLM 判断 → 分层向量存储
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore")

import os
import re
import json
import logging
import hashlib
import time
import threading
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from .embeddings import DashScopeEmbedder
from .chromadb_store import ChromaStore
from langchain_core.messages import HumanMessage

_logger = logging.getLogger("gitintel")


# ─── 数据模型 ───────────────────────────────────────────────────────────────

class FactType(str, Enum):
    """事实类型，决定存储层次和过期策略"""
    PROFILE    = "profile"    # 用户画像核心：名字/职业/位置 → 永不过期
    PREFERENCE = "preference" # 用户偏好：喜欢/讨厌/习惯    → 长期有效（90天）
    KNOWLEDGE  = "knowledge"  # 正在做的项目/技术栈         → 中期（30天）
    TEMPORARY  = "temporary"  # 临时状态/情绪/代码问题     → 短期（7天）
    IGNORE     = "ignore"     # 不值得存储：代码片段/报错    → 不存储


@dataclass
class ExtractedFact:
    """从对话中抽取的事实"""
    content: str           # 事实内容，如"用户喜欢鹿角蕨"
    fact_type: FactType    # 事实类型
    expires_at: float      # 过期时间戳（0=永不过期）
    source_turn: float     # 来源对话的时间戳
    confidence: float = 1.0  # 置信度（0-1）

    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at


@dataclass
class MemoryResult:
    """记忆检索结果"""
    content: str
    source: str   # "short_term" | "profile" | "permanent" | "temporary"
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


# ─── 异步抽取任务队列 ────────────────────────────────────────────────────────

class ExtractionTask:
    """异步抽取任务"""
    __slots__ = (
        "user_message", "assistant_message", "timestamp",
        "session_id", "user_id", "result", "error", "_long_term",
    )

    def __init__(
        self,
        user_message: str,
        assistant_message: str,
        timestamp: float,
        session_id: str,
        user_id: str,
        long_term: "LongTermMemory",
    ):
        self.user_message = user_message
        self.assistant_message = assistant_message
        self.timestamp = timestamp
        self.session_id = session_id
        self.user_id = user_id
        self._long_term = long_term
        self.result: Optional[list[ExtractedFact]] = None
        self.error: Optional[str] = None


class ExtractionQueue:
    """
    后台抽取队列：每轮对话后异步将任务加入队列，
    由后台线程消费，执行 LLM 抽取后存入长期记忆。
    """

    def __init__(self):
        self._queue: list[ExtractionTask] = []
        self._lock = threading.Lock()
        self._worker_started = False

    def enqueue(self, task: ExtractionTask) -> None:
        with self._lock:
            self._queue.append(task)
        if not self._worker_started:
            t = threading.Thread(target=self._worker, daemon=True, name="memory-extraction")
            t.start()
            self._worker_started = True

    def _worker(self) -> None:
        while True:
            task = None
            with self._lock:
                if self._queue:
                    task = self._queue.pop(0)

            if task is None:
                time.sleep(0.5)
                continue

            try:
                facts = _extract_facts_sync(task)
                task.result = facts
                # 立即存储 LLM 抽取的事实
                if facts:
                    for fact in facts:
                        task._long_term._store_fact(
                            fact=fact,
                            user_message=task.user_message,
                            assistant_message=task.assistant_message,
                            timestamp=task.timestamp,
                        )
            except Exception as exc:
                task.error = str(exc)


# ─── LLM 抽取核心（同步版，供后台线程调用）───────────────────────────────────

def _extract_facts_sync(task: ExtractionTask) -> list[ExtractedFact]:
    """
    同步抽取：用 LLM 判断每条消息是否值得存入长期记忆，并分类。
    在后台线程中执行，不阻塞主请求。
    """
    try:
        from backend.utils.llm_factory import get_llm
    except ImportError:
        try:
            from utils.llm_factory import get_llm
        except ImportError:
            _logger.warning("[Extraction] 无法导入 LLM，跳过长期记忆抽取")
            return []

    try:
        llm = get_llm(model="qwen-long")
    except Exception:
        try:
            llm = get_llm(model="qwen-plus")
        except Exception as exc:
            _logger.warning(f"[Extraction] 无法获取 LLM，跳过抽取: {exc}")
            return []

    user_msg = task.user_message.strip()
    asst_msg = task.assistant_message.strip()

    if not user_msg or len(user_msg) < 3:
        return []

    prompt = f"""你是一个记忆管理系统。请分析以下对话，判断哪些信息值得存入长期记忆。

判断标准（满足任一即存储）：
1. 是否是"稳定信息"（长期不变）：用户名字、职业、居住地、技术栈 → 永不过期
2. 是否"与用户身份强绑定"：偏好（喜欢/讨厌）、习惯、禁忌           → 长期有效（90天）
3. 是否"值得未来使用"：正在做的项目、目标、计划                        → 中期（30天）

不值得存储（IGNORE）：
- 代码片段、bug 报错、临时问题
- 情绪/状态（"我今天很累"、"刚吃了饭"）
- 一般性闲聊，不包含用户身份信息
- "这个问题我不太懂"等无意义回复

对话：
用户：{user_msg}
助手：{asst_msg}

请严格按以下 JSON 格式输出（只输出 JSON，不要其他内容）：
[
  {{
    "content": "抽取的事实内容，用第三人称描述，如'用户名叫XXX'或'用户喜欢YYY'",
    "fact_type": "profile|preference|knowledge|temporary|ignore",
    "confidence": 0.0-1.0
  }}
]

注意：
- fact_type=profile（名字/职业/位置等信息）→ expires_in=0（永不过期）
- fact_type=preference（喜欢/讨厌/习惯等信息）→ expires_in=7776000（90天）
- fact_type=knowledge（项目/计划/技术等信息）→ expires_in=2592000（30天）
- fact_type=temporary（临时状态等信息）→ expires_in=604800（7天）
- fact_type=ignore → 不输出
- content 最多 80 字符
- 只输出有价值的记忆，不要输出无意义的闲聊
"""

    try:
        response = llm.invoke(prompt)
        content = ""
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, str):
            content = response
        else:
            content = str(response)

        content = content.strip()
        json_match = re.search(r"\[[\s\S]*\]", content)
        if not json_match:
            _logger.debug(f"[Extraction] 无法解析 JSON，原始响应: {content[:200]}")
            return []

        facts_json = json.loads(json_match.group(0))
        now = time.time()
        facts: list[ExtractedFact] = []

        for item in facts_json:
            if item.get("fact_type") == "ignore":
                continue
            try:
                ft_str = item.get("fact_type", "ignore")
                ft = FactType(ft_str) if ft_str in [e.value for e in FactType] else FactType.TEMPORARY
            except ValueError:
                ft = FactType.TEMPORARY

            expires_in = 0
            if ft == FactType.PROFILE:
                expires_in = 0
            elif ft == FactType.PREFERENCE:
                expires_in = 90 * 24 * 3600
            elif ft == FactType.KNOWLEDGE:
                expires_in = 30 * 24 * 3600
            elif ft == FactType.TEMPORARY:
                expires_in = 7 * 24 * 3600

            facts.append(ExtractedFact(
                content=item.get("content", "")[:80],
                fact_type=ft,
                expires_at=now + expires_in if expires_in > 0 else 0,
                source_turn=task.timestamp,
                confidence=float(item.get("confidence", 0.8)),
            ))
            _logger.info(f"[Extraction] 抽取事实: [{ft.value}] {item.get('content', '')[:50]}")

        return facts

    except Exception as exc:
        _logger.warning(f"[Extraction] LLM 抽取失败: {exc}")
        return []


# ─── 规则快速抽取（同步，不走 LLM）─────────────────────────────────────────

def _quick_extract_rule_based(user_msg: str, asst_msg: str, timestamp: float) -> list[ExtractedFact]:
    """
    规则快速抽取（无 LLM）：仅用于偏好类关键词快速预提取。
    名字/职业等语义信息统一由 LLM 抽取，避免正则误匹配。
    """
    facts: list[ExtractedFact] = []
    msg = user_msg.strip()

    # 偏好/兴趣（关键词预提取，LLM 会进一步核实和补充）
    preference_keywords = ("喜欢", "爱", "讨厌", "不喜欢", "关心", "热衷")
    for kw in preference_keywords:
        if kw in msg:
            fact = msg.replace("我", "用户", 1)
            fact = re.sub(r"[，,]\s*你记住.*$", "", fact)
            fact = re.sub(r"[，,]\s*记住.*$", "", fact)
            fact = fact.strip()[:80]
            if len(fact) >= 3:
                facts.append(ExtractedFact(
                    content=fact,
                    fact_type=FactType.PREFERENCE,
                    expires_at=time.time() + 90 * 24 * 3600,
                    source_turn=timestamp,
                ))
                _logger.info(f"[QuickExtract] 偏好预提取: {fact[:50]}")
            break

    return facts


# ─── 短期记忆（消息缓冲）────────────────────────────────────────────────────

class ShortTermMemory:
    """
    短期记忆：当前会话窗口的上下文。

    基于 ChatMessageHistory 缓冲，保留最近 N 轮原始对话。
    对话窗口关闭即消失（Session 结束时清空）。
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        max_token_limit: int = 2000,
        max_turns: int = 20,
        output_key: str = "history",
        input_key: str = "input",
    ):
        from langchain_community.chat_message_histories import ChatMessageHistory

        self._max_turns = max_turns
        self._max_token_limit = max_token_limit
        self._output_key = output_key
        self._llm = llm
        self._summary: str = ""

        self._chat_memory = ChatMessageHistory()
        _logger.info(
            f"[ShortTermMemory] 初始化: max_turns={max_turns}, "
            f"max_tokens={max_token_limit}, llm={'有' if llm else '无'}"
        )

    def add_user_message(self, message: str) -> None:
        self._chat_memory.add_user_message(message)
        self._trim_turns()

    def add_ai_message(self, message: str) -> None:
        self._chat_memory.add_ai_message(message)
        self._trim_turns()

    def _trim_turns(self) -> None:
        """超过 max_turns 时裁剪最早的一轮对话"""
        try:
            messages = list(self._chat_memory.messages)
            if len(messages) > self._max_turns * 2:
                excess = len(messages) - self._max_turns * 2
                self._chat_memory.messages = messages[excess:]
        except Exception as exc:
            _logger.warning(f"[ShortTermMemory] 裁剪失败: {exc}")

    def load_memory_variables(self, inputs: Optional[dict] = None) -> dict:
        return {self._output_key: self.get_context()}

    def get_context(self, query: str = "") -> str:
        """获取当前短期记忆的上下文（纯净对话格式，无标题标签）"""
        try:
            messages = list(self._chat_memory.messages)
            if not messages:
                return ""
            recent = messages[-(self._max_turns * 2):]
            lines = []
            for m in recent:
                role = "用户" if m.type == "human" else "助手"
                content = (getattr(m, "content", "") or "")[:400]
                lines.append(f"{role}：{content}")
            return "\n".join(lines)
        except Exception:
            return ""

    def clear(self) -> None:
        """清空短期记忆（会话结束）"""
        self._chat_memory.clear()
        self._summary = ""
        _logger.info("[ShortTermMemory] 已清空")

    @property
    def memory(self) -> Any:
        return self


# ─── 长期记忆（分层向量存储）─────────────────────────────────────────────────

class LongTermMemory:
    """
    长期记忆：异步轻量抽取 + 分层存储 + 按需检索。

    存储分层：
      profile    → 永不过期（用户名字/职业/位置）
      permanent  → 长期有效（偏好/习惯）
      temporary  → 有过期时间（项目/技术/临时状态）

    异步抽取流程：
      add_turn() → 规则快速抽取（同步，核心信息立即生效）
                  → 任务入队（后台 LLM 抽取，异步）
                  → 后台线程消费 → 分层存储到 Chroma
    """

    LAYER_TO_DOCTYPE = {
        "profile":    "memory_profile",
        "permanent":  "memory_permanent",
        "temporary":  "memory_temporary",
    }

    def __init__(
        self,
        vectorstore: Optional[ChromaStore] = None,
        session_id: str = "default",
        user_id: str = "",
        top_k: int = 5,
    ):
        self.vectorstore = vectorstore or ChromaStore(collection_type="memory")
        self.session_id = session_id
        self.user_id = user_id
        self.top_k = top_k
        self._extraction_queue = ExtractionQueue()

        _logger.info(
            f"[LongTermMemory] 初始化: session={session_id}, user_id={user_id}, top_k={top_k}"
        )

    def add_turn(
        self,
        user_message: str,
        assistant_message: str,
        timestamp: float,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        添加对话到长期记忆：
          1. 规则快速抽取（同步，立即生效）
          2. 任务入队（后台 LLM 异步抽取）
        """
        # Step 1: 规则快速抽取（同步，保证关键信息立即可用）
        quick_facts = _quick_extract_rule_based(
            user_message, assistant_message, timestamp
        )
        for fact in quick_facts:
            self._store_fact(fact, user_message, assistant_message, timestamp, metadata)

        # Step 2: 异步 LLM 抽取（后台，不阻塞主流程）
        task = ExtractionTask(
            user_message=user_message,
            assistant_message=assistant_message,
            timestamp=timestamp,
            session_id=self.session_id,
            user_id=self.user_id,
            long_term=self,
        )
        self._extraction_queue.enqueue(task)

    def _store_fact(
        self,
        fact: ExtractedFact,
        user_message: str,
        assistant_message: str,
        timestamp: float,
        metadata: Optional[dict] = None,
    ) -> None:
        """将事实存储到对应的 Chroma 分层中"""
        from .chromadb_store import RAGDocument

        if fact.fact_type == FactType.PROFILE:
            layer = "profile"
        elif fact.fact_type in (FactType.PREFERENCE,):
            layer = "permanent"
        elif fact.fact_type in (FactType.KNOWLEDGE, FactType.TEMPORARY):
            layer = "temporary"
        else:
            return

        doc_type = self.LAYER_TO_DOCTYPE[layer]

        # 去重：同层 + 高相似度 → 跳过
        if self._is_duplicate(layer, fact.content):
            _logger.debug(f"[LongTermMemory] 跳过重复事实: {fact.content[:40]}")
            return

        doc = RAGDocument(
            repo_url="",
            category=f"conversation_{layer}",
            title=f"[{layer.upper()}] {fact.content[:30]}",
            content=fact.content,
            doc_type=doc_type,
            session_id=self.session_id,
            metadata={
                "user_message": user_message,
                "assistant_message": assistant_message,
                "timestamp": timestamp,
                "fact_type": fact.fact_type.value,
                "expires_at": fact.expires_at,
                "confidence": fact.confidence,
                "source": "rule" if fact.source_turn == timestamp else "llm",
                **(metadata or {}),
            },
        )
        self.vectorstore.upsert_documents([doc])
        _logger.info(
            f"[LongTermMemory] 存储事实 [{layer}]: {fact.content[:50]}, "
            f"expires={fact.expires_at}"
        )

    def _is_duplicate(self, layer: str, content: str, threshold: float = 0.85) -> bool:
        """检查是否与已有事实重复（高相似度即重复）。对比前先去标签。"""
        try:
            results = self.vectorstore.retrieve_similar(
                query=content,
                top_k=5,
                category=f"conversation_{layer}",
            )
            pure_content = content
            if "]" in content:
                pure_content = content.split("]", 1)[1].strip()
            compare_hash = pure_content[:30].lower()
            for r in results:
                r_pure = r.content
                if "]" in r.content:
                    r_pure = r.content.split("]", 1)[1].strip()
                r_hash = r_pure[:30].lower()
                if compare_hash == r_hash or r.score >= threshold:
                    return True
            return False
        except Exception:
            return False

    def get_profile_facts(self) -> list[MemoryResult]:
        """直接取当前用户所有 profile 层文档（绕过语义检索）"""
        results: list[MemoryResult] = []
        try:
            raw = self.vectorstore.get_by_session_and_category(
                session_id=self.session_id,
                category="conversation_profile",
                top_k=50,
            )
            for r in raw:
                meta = r.metadata if isinstance(r.metadata, dict) else {}
                results.append(MemoryResult(
                    content=r.content,
                    source="profile",
                    score=1.0,
                    metadata=meta,
                ))
        except Exception as exc:
            _logger.warning(f"[LongTermMemory] get_profile_facts 失败: {exc}")
        return results

    def retrieve(self, query: str, top_k: Optional[int] = None) -> list[MemoryResult]:
        """
        按需检索：同时查所有分层，返回合并结果（已去重）。自动过滤过期记录。

        去重策略：
          1. 跨层内容去重：提取纯净内容（去 [fact_type] 标签）后对比，重复则跳过
          2. 同层互斥：同一 fact_type 只保留分数最高的条目
          3. Question-Phrase 降权：内容像在"问问题"的，降低分数
          4. 新鲜度加权：timestamp 越新权重越高
          5. profile 层 boost：profile 层分数 +2000
        """
        effective_k = top_k or self.top_k
        now = time.time()
        results: list[MemoryResult] = []
        seen_content_hashes: set[str] = set()
        layer_type_latest: dict[str, dict[str, tuple[float, MemoryResult]]] = {}

        for layer, doc_type in self.LAYER_TO_DOCTYPE.items():
            try:
                raw = self.vectorstore.retrieve_similar(
                    query=query,
                    top_k=effective_k,
                    category=f"conversation_{layer}",
                )
                for r in raw:
                    meta = r.metadata if isinstance(r.metadata, dict) else {}

                    expires_at = meta.get("expires_at", 0)
                    if expires_at > 0 and now > expires_at:
                        _logger.debug(f"[LongTermMemory] 过滤过期记录: {r.content[:40]}")
                        continue

                    pure_content = r.content
                    if "]" in pure_content:
                        pure_content = pure_content.split("]", 1)[1].strip()

                    content_hash = pure_content[:30].lower()
                    fact_field = meta.get("fact_type", layer)

                    # 跨层去重
                    if content_hash in seen_content_hashes:
                        _logger.debug(f"[LongTermMemory] 跨层去重 [{layer}]: {pure_content[:40]}")
                        continue
                    seen_content_hashes.add(content_hash)

                    # 同层互斥：同一 fact_type 只保留分数最高的
                    if layer not in layer_type_latest:
                        layer_type_latest[layer] = {}
                    existing = layer_type_latest[layer].get(fact_field)
                    if existing is not None:
                        _, existing_score = existing
                        if r.score > existing_score:
                            layer_type_latest[layer][fact_field] = (r, r.score)
                        continue

                    layer_type_latest[layer][fact_field] = (r, r.score)

            except Exception as exc:
                _logger.warning(f"[LongTermMemory] 检索 layer={layer} 失败: {exc}")

        for layer, type_map in layer_type_latest.items():
            for fact_field, (r, base_score) in type_map.items():
                meta = r.metadata if isinstance(r.metadata, dict) else {}
                confidence = meta.get("confidence", 0.5)
                r_timestamp = meta.get("timestamp", 0)

                pure_content = r.content
                if "]" in pure_content:
                    pure_content = pure_content.split("]", 1)[1].strip()

                # Question-Phrase 降权
                question_penalty = 0.0
                q_indicators = ("吗", "什么", "谁", "哪", "怎么", "多少", "是不是", "?")
                if any(pure_content.endswith(q) or pure_content.startswith(q) for q in q_indicators):
                    question_penalty = 100.0
                    _logger.debug(f"[LongTermMemory] Question-Phrase 降权: {pure_content[:40]}")

                # profile 层 boost
                score_boost = 2000.0 if layer == "profile" else 0.0

                # 新鲜度加权（跨度 30 天归一化）
                freshness_weight = 0.0
                if r_timestamp > 0:
                    age_days = (now - r_timestamp) / 86400.0
                    freshness_weight = max(0, 100.0 - age_days * 3.0)

                final_score = base_score + score_boost - question_penalty + confidence * 10 + freshness_weight

                results.append(MemoryResult(
                    content=pure_content,
                    source=layer,
                    score=final_score,
                    metadata=meta,
                ))
                _logger.debug(
                    f"[LongTermMemory] 最终候选 [{layer}]: {pure_content[:40]}, "
                    f"score={final_score:.2f} (base={base_score:.2f}, boost={score_boost}, "
                    f"q_penalty={question_penalty}, fresh={freshness_weight:.1f})"
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:effective_k]

    def get_context(self, query: str = "", top_k: Optional[int] = None) -> str:
        """获取长期记忆上下文（纯净格式，无标签前缀，无内容重复）"""
        results = self.retrieve(query, top_k=top_k)
        if not results:
            return ""

        # 直接输出纯净内容，不加任何层标签（层标签在检索阶段已用于 boost 排序）
        parts = []
        for r in results:
            parts.append(r.content)

        return "\n".join(parts)


# ─── 用户画像（Profile 层特殊管理）──────────────────────────────────────────

@dataclass
class UserProfile:
    """用户画像：跨会话持久化用户身份信息"""
    user_id: str = ""
    name: str = ""
    bio: str = ""
    preferences: dict = field(default_factory=dict)
    last_updated: float = 0.0

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "bio": self.bio,
            "preferences": self.preferences,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        return cls(
            user_id=data.get("user_id", ""),
            name=data.get("name", ""),
            bio=data.get("bio", ""),
            preferences=data.get("preferences", {}),
            last_updated=data.get("last_updated", 0.0),
        )


class UserProfileManager:
    """用户画像管理器 — 跨会话持久化用户身份（profile 层数据）"""

    def __init__(self, user_id: str, long_term: "LongTermMemory" = None):
        self.user_id = user_id
        self.long_term = long_term

    def extract_and_update(self, user_message: str, assistant_message: str = "") -> bool:
        """
        画像同步更新入口。

        名字/性别等 profile 信息统一由 LLM 异步抽取后写入 Chroma，
        此方法不再执行规则提取，保持为空实现以保证接口兼容。
        如需主动触发，可在此调用 LLM 抽取（未来优化方向）。
        """
        # 规则提取已移除，统一走 LLM 异步抽取
        return False

    def get_enriched_query(self, query: str) -> str:
        """画像辅助检索：当查询涉及身份时，把画像信息注入查询"""
        summary = self.get_identity_summary()
        if not summary:
            return query
        # 只要有画像信息就注入，不管查询是否含 identity 关键词
        return f"{query}，{summary}"

    def has_identity_info(self) -> bool:
        """只要有画像就不为空（优先查 Chroma，再查文件兜底）"""
        return bool(self.get_identity_summary())

    def get_identity_summary(self) -> str:
        """
        从 Chroma profile 层读取用户画像事实（跨 session 持久化）。
        完全动态，不硬编码任何字段。
        """
        parts: list[str] = []
        seen: set[str] = set()

        # 来源 1: Chroma profile 层（直接取，不用语义检索）
        if self.long_term:
            try:
                results = self.long_term.get_profile_facts()
                for r in results:
                    key = r.content[:20]
                    if key not in seen:
                        seen.add(key)
                        parts.append(r.content)
            except Exception as exc:
                _logger.debug(f"[UserProfile] Chroma 读取失败: {exc}")

        return "\uff0c".join(parts) if parts else ""


# ─── 短期记忆会话缓存

_short_term_cache: dict[str, "ShortTermMemory"] = {}
_short_term_cache_lock = threading.Lock()


def _get_short_term_memory(
    session_id: str,
    llm: Optional[Any],
    max_token_limit: int,
    max_turns: int,
) -> "ShortTermMemory":
    """获取或创建短期记忆实例（会话级缓存）"""
    with _short_term_cache_lock:
        if session_id in _short_term_cache:
            return _short_term_cache[session_id]
        mem = ShortTermMemory(
            llm=llm,
            max_token_limit=max_token_limit,
            max_turns=max_turns,
        )
        _short_term_cache[session_id] = mem
        return mem


def clear_short_term_cache(session_id: str) -> None:
    """清空指定会话的短期记忆缓存（会话结束时调用）"""
    with _short_term_cache_lock:
        if session_id in _short_term_cache:
            _short_term_cache[session_id].clear()
            del _short_term_cache[session_id]
            _logger.info(f"[MultiLayerMemory] 短期记忆缓存已清空: session={session_id}")


# ─── 多层记忆管理器 ─────────────────────────────────────────────────────────

class MultiLayerMemory:
    """
    多层记忆管理器 — 统一短期 + 长期记忆接口。

    整合：
      - ShortTermMemory  → 当前会话窗口（ChatMessageHistory 缓冲）
      - LongTermMemory   → 跨会话长期记忆（异步抽取 + 分层向量存储）
      - UserProfile      → 用户画像文件（永不过期的身份信息）
    """

    def __init__(
        self,
        session_id: str = "default",
        user_id: str = "",
        llm: Optional[Any] = None,
        vectorstore: Optional[ChromaStore] = None,
        short_term_tokens: int = 2000,
        short_term_turns: int = 20,
        long_term_top_k: int = 5,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.timestamp = time.time()

        # Layer 0: 用户画像（文件存储，永不过期）
        # long_term 延迟传入（避免循环引用），由 MultiLayerMemory 统一注入
        self.user_profile = UserProfileManager(user_id) if user_id else None

        # Layer 1: 短期记忆（会话窗口，关闭即消失）
        # 通过 session_id 缓存，同一会话的多请求共享实例，跨请求保留对话历史
        self.short_term = _get_short_term_memory(
            session_id=session_id,
            llm=llm,
            max_token_limit=short_term_tokens,
            max_turns=short_term_turns,
        )

        # Layer 2: 长期记忆（异步抽取 + 分层向量存储）
        self.long_term = LongTermMemory(
            vectorstore=vectorstore,
            session_id=session_id,
            user_id=user_id,
            top_k=long_term_top_k,
        )

        # Layer 0 依赖 Layer 2 完成后再注入（避免循环引用）
        if self.user_profile:
            self.user_profile.long_term = self.long_term

        _logger.info(
            f"[MultiLayerMemory] 初始化: session={session_id}, user_id={user_id}, "
            f"short_turns={short_term_turns}, long_k={long_term_top_k}, "
            f"has_profile={self.user_profile is not None and self.user_profile.has_identity_info()}"
        )

    def add_turn(self, user_message: str, assistant_message: str, metadata: dict = None) -> None:
        """
        添加一轮对话到所有记忆层。

        流程：
          1. 更新用户画像（同步，文件存储）
          2. 添加到短期记忆（同步，消息缓冲，会话内跨请求共享）
          3. 添加到长期记忆（异步抽取，后台线程执行 LLM 抽取）
        """
        turn_timestamp = metadata.get("timestamp", time.time()) if metadata else time.time()

        # Layer 0: 画像抽取（同步）
        if self.user_profile:
            self.user_profile.extract_and_update(user_message, assistant_message)

        # Layer 1: 短期记忆（同步）
        self.short_term.add_user_message(user_message)
        self.short_term.add_ai_message(assistant_message)

        # Layer 2: 长期记忆（异步抽取，后台线程）
        self.long_term.add_turn(
            user_message=user_message,
            assistant_message=assistant_message,
            timestamp=turn_timestamp,
            metadata=metadata,
        )

        _logger.debug(
            f"[MultiLayerMemory] 添加对话: user_len={len(user_message)}, "
            f"asst_len={len(assistant_message)}"
        )

    def get_full_context(
        self,
        query: str = "",
        include_knowledge: bool = True,
    ) -> dict[str, str]:
        """
        获取多层记忆上下文（已去重，无标签污染）。

        核心原则：记忆不是越多越好，而是越精准越好。
        所有层统一在输出前做内容去重，避免同一信息重复出现。

        Args:
            query: 当前查询，用于画像注入和长期记忆检索
            include_knowledge: 保留参数（向后兼容）

        Returns:
            {
                "short_term": str,  # 纯净对话历史（无标题）
                "long_term":  str,  # 跨会话检索结果（已去重，无标签）
                "profile":   str,   # 用户画像（纯净内容，无标签）
                "combined":  str,   # 合并后整体去重的上下文
            }
        """
        # 画像注入查询
        enriched_query = query
        if self.user_profile and self.user_profile.has_identity_info():
            enriched_query = self.user_profile.get_enriched_query(query)

        # 短期记忆（当前会话，无标题）
        short_context = self.short_term.get_context(enriched_query)

        # 长期记忆（跨会话，已在 retrieve 中去重，输出已去标签）
        long_context = self.long_term.get_context(enriched_query)

        # 用户画像（纯净内容，无标签）
        profile_context = ""
        if self.user_profile and self.user_profile.has_identity_info():
            summary = self.user_profile.get_identity_summary()
            profile_context = summary

        # ── 合并 + 整体内容去重 ─────────────────────────────────────────────
        # 原则：short_term 的对话历史是 LLM 最容易直接使用的，不做去重
        #       long_term 和 profile 需要去重，避免同一内容重复出现
        combined_parts: list[str] = []
        seen_combined: set[str] = set()

        # 短期记忆放最前面（相关性最高）
        if short_context:
            combined_parts.append(short_context)
            # short_term 的每行做去重
            for line in short_context.splitlines():
                line = line.strip()
                if line:
                    key = line[:30].lower()
                    seen_combined.add(key)

        def _add_if_new(text: str, label: str) -> None:
            """添加到 combined，重复则跳过"""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                key = line[:30].lower()
                if key and key not in seen_combined:
                    seen_combined.add(key)
                    combined_parts.append(line)
                else:
                    _logger.debug(f"[get_full_context] 跨层去重 [{label}]: {line[:40]}")

        # 画像和长期记忆各取 top 3，避免信息过载
        if profile_context:
            profile_lines = profile_context.splitlines()[:3]
            _add_if_new("\n".join(profile_lines), "profile")

        if long_context:
            long_lines = long_context.splitlines()[:5]
            _add_if_new("\n".join(long_lines), "long_term")

        combined = "\n".join(combined_parts)

        _logger.info(
            f"[get_full_context] short={len(short_context)} chars, "
            f"long={len(long_context)} chars, profile={len(profile_context)} chars, "
            f"combined={len(combined)} chars, deduped_lines={len(combined_parts)}"
        )

        return {
            "short_term": short_context,
            "long_term":  long_context,
            "profile":    profile_context,
            "combined":   combined,
            # 向后兼容别名
            "working":    short_context,
            "semantic":   long_context,
            "knowledge":  "",
        }

    def clear_session(self) -> None:
        """清空当前会话的所有记忆（短期清空，长期按 session_id 清空）"""
        clear_short_term_cache(self.session_id)
        self.long_term.clear_session()
        _logger.info(f"[MultiLayerMemory] 清空会话 {self.session_id}")


# ─── 工厂函数 ────────────────────────────────────────────────────────────────

def create_multi_layer_memory(
    session_id: str,
    user_id: str = "",
    llm: Optional[Any] = None,
    vectorstore: Optional[ChromaStore] = None,
) -> MultiLayerMemory:
    """创建多层记忆实例的便捷函数"""
    return MultiLayerMemory(
        session_id=session_id,
        user_id=user_id,
        llm=llm,
        vectorstore=vectorstore,
    )


# ─── 向后兼容别名（导出旧类名，不推荐继续使用）───────────────────────────────

class WorkingMemory(ShortTermMemory):
    """向后兼容别名：WorkingMemory → ShortTermMemory"""

    def __init__(self, llm=None, max_token_limit=2000, output_key="history", input_key="input"):
        super().__init__(llm=llm, max_token_limit=max_token_limit, max_turns=20,
                         output_key=output_key, input_key=input_key)


class SemanticMemory(LongTermMemory):
    """向后兼容别名：SemanticMemory → LongTermMemory"""

    def __init__(self, vectorstore=None, session_id="default", top_k=3, search_kwargs=None):
        super().__init__(vectorstore=vectorstore, session_id=session_id,
                         user_id="", top_k=top_k)


class KnowledgeMemory(LongTermMemory):
    """向后兼容别名：KnowledgeMemory → LongTermMemory"""

    def __init__(self, vectorstore=None):
        super().__init__(vectorstore=vectorstore, session_id="global",
                         user_id="", top_k=5)
