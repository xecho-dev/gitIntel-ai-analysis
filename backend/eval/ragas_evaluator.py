"""
RAGAS Evaluation Module — RAG 回复质量评测模块。

集成 RAGAS 0.4.x 框架，对 RAG Pipeline 的回复质量进行多维度评测：

评测维度（基于 RAGAS 标准指标）：
  1. faithfulness     — 回答是否忠实于检索到的上下文
  2. answer_relevancy — 回答与问题的相关程度
  3. context_precision — 上下文块按相关度排序的精确度
  4. context_recall   — 上下文是否覆盖了标准答案的关键点

使用方式：
    from eval.ragas_evaluator import RAGASEvaluator, evaluate_rag_response

    # 方式一：单次评测
    result = await evaluate_rag_response(
        question="...",
        answer="...",
        retrieved_contexts=["...", "..."],
        ground_truth="...",          # 可选，有则同时输出 context_recall
        user_avatar="xxx",           # 可选，用于日志区分
    )

    # 方式二：Evaluator 实例（推荐，批量评测）
    evaluator = RAGASEvaluator(user_avatar="xxx")
    result = await evaluator.evaluate(
        question="...",
        answer="...",
        retrieved_contexts=["...", "..."],
        ground_truth="...",
    )
"""

import logging
import os
import time
import warnings
from dataclasses import dataclass, field
from typing import Optional

_logger = logging.getLogger("gitintel")


# ─── 指标说明 ──────────────────────────────────────────────────────────

RAGAS_METRICS_INFO = {
    "faithfulness": {
        "description": "衡量回答中忠实于检索上下文的程度，"
        "即回答中的事实性陈述有多少能从上下文中推导出来。取值 0~1，越高越好。",
        "weight": 0.30,
    },
    "answer_relevancy": {
        "description": "衡量回答与原始问题的相关程度，"
        "通过计算回答隐含的子问题与原问题的语义相似度来评估。取值 0~1，越高越好。",
        "weight": 0.30,
    },
    "context_precision": {
        "description": "衡量检索到的上下文块是否按相关度精确排序，"
        "高分表示 top-k 块中相关性最高的内容排在最前面。取值 0~1，越高越好。",
        "weight": 0.20,
    },
    "context_recall": {
        "description": "衡量上下文是否覆盖了标准答案（ground_truth）的关键信息，"
        "需要传入 ground_truth 才可计算。取值 0~1，越高越好。",
        "weight": 0.20,
    },
}


# ─── 评测结果数据结构 ──────────────────────────────────────────────────


@dataclass
class EvaluationResult:
    """单次评测结果"""

    question: str
    answer: str
    # 各指标得分
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: Optional[float]  # 无 ground_truth 时为 None
    # 综合得分（加权平均）
    overall_score: float
    # 耗时
    latency_ms: float
    # 指标详情
    metrics_detail: dict = field(default_factory=dict)
    # 错误信息（部分失败时记录）
    error: Optional[str] = None


@dataclass
class BatchEvaluationResult:
    """批量评测结果"""

    results: list[EvaluationResult]
    average_scores: dict
    total_latency_ms: float
    success_count: int
    failure_count: int


# ─── 单次评测函数 ──────────────────────────────────────────────────────


async def evaluate_rag_response(
    question: str,
    answer: str,
    retrieved_contexts: list[str],
    ground_truth: Optional[str] = None,
    user_avatar: Optional[str] = None,
) -> EvaluationResult:
    """
    对单次 RAG 回复进行 RAGAS 评测。

    Args:
        question           : 用户问题
        answer            : LLM 生成的回答
        retrieved_contexts : 检索到的上下文列表（原始内容字符串）
        ground_truth      : 标准答案（可选，有则额外输出 context_recall）
        user_avatar       : 用户标识（用于日志）

    Returns:
        EvaluationResult: 包含各指标得分和综合得分的评测结果
    """
    evaluator = RAGASEvaluator(user_avatar=user_avatar)
    return await evaluator.evaluate(
        question=question,
        answer=answer,
        retrieved_contexts=retrieved_contexts,
        ground_truth=ground_truth,
    )


# ─── RAGASEvaluator ────────────────────────────────────────────────────


class RAGASEvaluator:
    """
    RAGAS 评测器。

    封装 RAGAS 0.4.x 核心指标的计算，提供：
      - 单次评测（evaluate）
      - 批量评测（evaluate_batch）
      - 便捷的 llm / embedding 初始化（复用项目现有 LLM 配置）

    使用项目现有 LLM 工厂获取 LLM 实例，无需额外配置 API Key。
    """

    def __init__(
        self,
        user_avatar: Optional[str] = None,
        evaluation_llm_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        """
        Args:
            user_avatar          : 用户标识（用于日志）
            evaluation_llm_model : 评测用 LLM 模型名，默认使用项目配置
            embedding_model      : 嵌入模型，默认使用项目配置
        """
        self.user_avatar = user_avatar or "unknown"
        self._eval_llm = None
        self._eval_llm_model = evaluation_llm_model
        self._embedding_model = embedding_model
        self._initialized = False

    # ── LLM 初始化（复用现有 llm_factory） ─────────────────────────────

    def _init_llm(self):
        """通过 llm_factory 获取评测用 LLM（复用项目现有 API Key 配置）。"""
        if self._eval_llm is not None:
            return

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            _logger.warning("[RAGASEvaluator] OPENAI_API_KEY 未配置，跳过 RAGAS 评测")
            return

        # 复用项目 LLM 工厂的 LangSmith 配置
        try:
            from utils.llm_factory import _configure_langsmith_env
        except ImportError:
            pass
        else:
            _configure_langsmith_env()

        try:
            from langchain_openai import ChatOpenAI

            base_url = os.getenv(
                "OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            model = (
                self._eval_llm_model
                or os.getenv("EVAL_LLM_MODEL")
                or "qwen3.6-plus-2026-04-02"
            )

            self._eval_llm = ChatOpenAI(
                model=model,
                temperature=0.0,
                openai_api_key=api_key,
                base_url=base_url,
                max_retries=5,
                timeout=120.0,
            )
            _logger.info(
                f"[RAGASEvaluator] 评测 LLM 初始化完成: model={model}, user={self.user_avatar}"
            )
        except Exception as exc:
            _logger.warning(
                f"[RAGASEvaluator] 评测 LLM 初始化失败: {exc}，跳过 RAGAS 评测"
            )
            self._eval_llm = None

    def _ensure_initialized(self):
        """延迟初始化 LLM。"""
        if not self._initialized:
            self._init_llm()
            self._initialized = True

    # ── 核心评测 ──────────────────────────────────────────────────────

    async def evaluate(
        self,
        question: str,
        answer: str,
        retrieved_contexts: list[str],
        ground_truth: Optional[str] = None,
    ) -> EvaluationResult:
        """
        对单次 RAG 回复进行 RAGAS 多维度评测。

        Args:
            question           : 用户问题
            answer             : LLM 生成的回答
            retrieved_contexts : 检索到的上下文列表
            ground_truth       : 标准答案（可选）

        Returns:
            EvaluationResult
        """

        start = time.perf_counter()
        self._ensure_initialized()

        if self._eval_llm is None:
            return self._error_result(question, answer, "LLM 未初始化")

        # 数据校验
        if not answer or not answer.strip():
            _logger.warning("[RAGASEvaluator] 回答为空，跳过评测")
            return self._empty_result(question, answer, start)

        if not retrieved_contexts:
            _logger.warning("[RAGASEvaluator] 上下文为空，跳过评测")
            return self._empty_result(question, answer, start)

        # 构建 RAGAS Dataset（使用 EvaluationDataset.from_list）
        dataset = self._build_dataset(
            question, answer, retrieved_contexts, ground_truth
        )

        # 确定需要计算的指标
        metrics = self._build_metrics(ground_truth is not None)

        # 执行评测（ragas.evaluate 是同步的，但内部使用 asyncio）
        scores: dict[str, Optional[float]] = {}
        eval_error: Optional[str] = None

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from ragas import evaluate

                result = evaluate(
                    dataset,
                    metrics=metrics,
                    llm=self._eval_llm,
                    raise_exceptions=True,
                    allow_nest_asyncio=True,
                )

            # 从 DataFrame 中提取分数
            df = result.to_pandas()
            if len(df) > 0:
                row = df.iloc[0]
                scores["faithfulness"] = _safe_float(row.get("faithfulness"))
                scores["answer_relevancy"] = _safe_float(row.get("answer_relevancy"))
                scores["context_precision"] = _safe_float(row.get("context_precision"))
                if ground_truth:
                    scores["context_recall"] = _safe_float(row.get("context_recall"))
        except Exception as exc:
            eval_error = f"{type(exc).__name__}: {exc}"
            _logger.warning(f"[RAGASEvaluator] RAGAS evaluate 失败: {eval_error}")
            # 部分失败不影响其他指标记录
            for key in [
                "faithfulness",
                "answer_relevancy",
                "context_precision",
                "context_recall",
            ]:
                if key not in scores:
                    scores[key] = None

        # 计算综合得分
        valid_scores = {k: v for k, v in scores.items() if v is not None}
        overall_score = self._compute_weighted_score(valid_scores)
        latency_ms = (time.perf_counter() - start) * 1000

        result_obj = EvaluationResult(
            question=question,
            answer=answer,
            faithfulness=scores.get("faithfulness", 0.0) or 0.0,
            answer_relevancy=scores.get("answer_relevancy", 0.0) or 0.0,
            context_precision=scores.get("context_precision", 0.0) or 0.0,
            context_recall=scores.get("context_recall"),
            overall_score=overall_score,
            latency_ms=latency_ms,
            metrics_detail={
                name: {
                    "description": RAGAS_METRICS_INFO[name]["description"],
                    "weight": RAGAS_METRICS_INFO[name]["weight"],
                }
                for name in RAGAS_METRICS_INFO
            },
            error=eval_error,
        )

        _logger.info(
            f"[RAGASEvaluator] 评测完成: user={self.user_avatar}, "
            f"faithfulness={scores.get('faithfulness')}, "
            f"answer_relevancy={scores.get('answer_relevancy')}, "
            f"context_precision={scores.get('context_precision')}, "
            f"context_recall={scores.get('context_recall')}, "
            f"overall={overall_score:.3f}, latency={latency_ms:.0f}ms"
        )

        return result_obj

    # ── 批量评测 ──────────────────────────────────────────────────────

    async def evaluate_batch(
        self,
        samples: list[dict],
    ) -> BatchEvaluationResult:
        """
        批量评测多个样本。

        Args:
            samples: 列表，每个元素为 dict，需包含：
                - question           (str)
                - answer             (str)
                - retrieved_contexts (list[str])
                - ground_truth       (str, optional)

        Returns:
            BatchEvaluationResult
        """
        import asyncio

        total_start = time.perf_counter()
        results: list[EvaluationResult] = []

        tasks = [
            self.evaluate(
                question=s.get("question", ""),
                answer=s.get("answer", ""),
                retrieved_contexts=s.get("retrieved_contexts", []),
                ground_truth=s.get("ground_truth"),
            )
            for s in samples
        ]

        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        for i, item in enumerate(gathered):
            if isinstance(item, Exception):
                results.append(
                    self._error_result(
                        samples[i].get("question", ""),
                        samples[i].get("answer", ""),
                        f"{type(item).__name__}: {item}",
                    )
                )
            else:
                results.append(item)

        total_latency_ms = (time.perf_counter() - total_start) * 1000
        success_count = len([r for r in results if r.error is None])
        failure_count = len(results) - success_count

        # 计算平均分
        valid_results = [r for r in results if r.error is None]
        average_scores = {}
        if valid_results:
            for key in [
                "faithfulness",
                "answer_relevancy",
                "context_precision",
                "context_recall",
            ]:
                vals = [
                    getattr(r, key)
                    for r in valid_results
                    if getattr(r, key) is not None
                ]
                if vals:
                    average_scores[key] = sum(vals) / len(vals)
            overall_vals = [r.overall_score for r in valid_results]
            if overall_vals:
                average_scores["overall_score"] = sum(overall_vals) / len(overall_vals)

        return BatchEvaluationResult(
            results=results,
            average_scores=average_scores,
            total_latency_ms=total_latency_ms,
            success_count=success_count,
            failure_count=failure_count,
        )

    # ── 内部辅助方法 ──────────────────────────────────────────────────

    def _build_dataset(
        self,
        question: str,
        answer: str,
        retrieved_contexts: list[str],
        ground_truth: Optional[str] = None,
    ):
        """构建 RAGAS EvaluationDataset 对象。"""
        from ragas.dataset_schema import EvaluationDataset

        row: dict[str, object] = {
            "user_input": question,
            "response": answer,
            "retrieved_contexts": retrieved_contexts,
        }
        if ground_truth:
            row["reference"] = ground_truth

        return EvaluationDataset.from_list([row])

    def _build_metrics(self, has_ground_truth: bool) -> list:
        """根据是否需要 context_recall 构建指标列表。"""
        from ragas.metrics import (
            Faithfulness,
            ResponseRelevancy,
            ContextPrecision,
            ContextRecall,
        )

        metrics = [
            Faithfulness(llm=self._eval_llm),
            ResponseRelevancy(llm=self._eval_llm),
            ContextPrecision(llm=self._eval_llm),
        ]
        if has_ground_truth:
            metrics.append(ContextRecall(llm=self._eval_llm))

        return metrics

    def _compute_weighted_score(self, scores: dict) -> float:
        """
        计算综合得分（加权平均）。

        权重配置见 RAGAS_METRICS_INFO。
        若某些指标不可用，按剩余权重重新归一化。
        """
        if not scores:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for name, info in RAGAS_METRICS_INFO.items():
            if name in scores and scores[name] is not None:
                weighted_sum += scores[name] * info["weight"]
                total_weight += info["weight"]

        if total_weight == 0:
            return 0.0

        return weighted_sum / total_weight

    def _empty_result(
        self, question: str, answer: str, start: float
    ) -> EvaluationResult:
        """返回空/无效输入时的降级结果。"""
        return EvaluationResult(
            question=question,
            answer=answer,
            faithfulness=0.0,
            answer_relevancy=0.0,
            context_precision=0.0,
            context_recall=None,
            overall_score=0.0,
            latency_ms=(time.perf_counter() - start) * 1000,
            metrics_detail={"note": "输入为空，跳过评测"},
            error="empty_input",
        )

    def _error_result(self, question: str, answer: str, error: str) -> EvaluationResult:
        """返回评测失败时的降级结果。"""
        return EvaluationResult(
            question=question,
            answer=answer,
            faithfulness=0.0,
            answer_relevancy=0.0,
            context_precision=0.0,
            context_recall=None,
            overall_score=0.0,
            latency_ms=0.0,
            metrics_detail={},
            error=error,
        )

    # ── 结果导出 ──────────────────────────────────────────────────────

    def result_to_dict(self, result: EvaluationResult) -> dict:
        """将 EvaluationResult 转换为可序列化的 dict（便于存入 DB / 写入文件）。"""
        return {
            "question": result.question,
            "answer": result.answer,
            "metrics": {
                "faithfulness": result.faithfulness,
                "answer_relevancy": result.answer_relevancy,
                "context_precision": result.context_precision,
                "context_recall": result.context_recall,
            },
            "overall_score": result.overall_score,
            "latency_ms": round(result.latency_ms, 2),
            "metrics_detail": result.metrics_detail,
            "error": result.error,
        }


# ─── 辅助函数 ──────────────────────────────────────────────────────────


def _safe_float(value) -> Optional[float]:
    """安全地将值转换为 float。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
