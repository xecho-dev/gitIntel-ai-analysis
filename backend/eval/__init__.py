"""
Eval Module — RAG 回复质量评测。

入口：
    from eval.ragas_evaluator import RAGASEvaluator, evaluate_rag_response, RAGAS_METRICS_INFO

推荐用法：
    evaluator = RAGASEvaluator(user_avatar="xxx")
    result = await evaluator.evaluate(
        question="...",
        answer="...",
        retrieved_contexts=["...", "..."],
        ground_truth="...",  # 可选
    )

命令行评测：
    python eval/rag_eval.py
    python eval/rag_eval.py --limit 3 --verbose
    python eval/rag_eval.py --data eval/examples/test_data.csv --name my_eval
"""

from .ragas_evaluator import (
    RAGASEvaluator,
    EvaluationResult,
    BatchEvaluationResult,
    evaluate_rag_response,
    RAGAS_METRICS_INFO,
)

__all__ = [
    "RAGASEvaluator",
    "EvaluationResult",
    "BatchEvaluationResult",
    "evaluate_rag_response",
    "RAGAS_METRICS_INFO",
]
