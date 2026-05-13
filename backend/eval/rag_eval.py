"""
RAGAS Evaluation Runner — 一键运行 RAG 质量评测实验。

用法：
    # 默认评测（使用内置测试集）
    python rag_eval.py

    # 指定测试数据文件
    python rag_eval.py --data examples/test_data.csv

    # 自定义实验名称
    python rag_eval.py --name my_experiment

    # 仅评测 N 条数据（快速验证）
    python rag_eval.py --limit 5

    # 显示详细输出
    python rag_eval.py -v

设置 API Key：
    export OPENAI_API_KEY="your-key"
    # 或
    python rag_eval.py --api-key "your-key"

输出：
    results/<experiment_name>/results.csv  — 每条数据的评测结果
    results/<experiment_name>/summary.txt  — 汇总统计
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 项目路径 ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── 默认测试数据集 ──────────────────────────────────────────────────────

DEFAULT_TEST_DATA = [
    {
        "question": "这个项目的技术架构是怎样的？",
        "ground_truth": "该项目采用 Next.js 前端 + FastAPI Agent 层的前后端分离架构，前端使用 Zustand 状态管理，Agent 层使用 LangGraph 工作流编排。",
    },
    {
        "question": "如何部署这个项目？",
        "ground_truth": "项目提供了 docker-compose.yml 和多阶段 Dockerfile，支持分别构建前端、后台和后端镜像，通过 Nginx 反向代理统一对外提供服务。",
    },
    {
        "question": "代码质量分析使用了哪些指标？",
        "ground_truth": "代码质量分析使用 lizard 进行圈复杂度、代码行数、函数数量等指标，结合 tree-sitter 进行多语言 AST 分析。",
    },
    {
        "question": "RAG 检索使用了什么策略？",
        "ground_truth": "RAG 检索采用多策略混合检索，包括向量语义检索、关键词 BM25 检索和 RRF 倒数排名融合，还支持 HyDE 假设文档兜底。",
    },
    {
        "question": "如何进行依赖风险分析？",
        "ground_truth": "依赖风险分析通过解析 package.json/pyproject.toml/requirements.txt 等依赖文件，结合 OSV 数据库查询已知漏洞，并使用 LLM 生成风险评估报告。",
    },
    {
        "question": "会话记忆是如何实现的？",
        "ground_truth": "会话记忆使用多层记忆系统，包括短期会话摘要记忆（ConversationSummaryMemory）、语义长期记忆（ChromaDB 向量存储）和画像记忆（按实体抽取）。",
    },
    {
        "question": "前端使用了哪些技术栈？",
        "ground_truth": "前端使用 Next.js App Router 架构，Tailwind CSS 样式，Zustand 状态管理，支持 SSE 流式响应和 BFF 路由代理。",
    },
    {
        "question": "Agent 之间如何协作？",
        "ground_truth": "Agent 之间通过 LangGraph 工作流并行执行，各 Agent 独立产出结果后汇总到 SharedState，最后由编排层统一输出。",
    },
    {
        "question": "数据存储用了哪些方案？",
        "ground_truth": "结构化数据使用 Supabase PostgreSQL，向量数据使用 ChromaDB，文件存储使用 GitHub Gist API。",
    },
    {
        "question": "如何扩展新的 Agent？",
        "ground_truth": "新增 Agent 需要继承 BaseAgent 基类，实现 stream() 方法，在 analysis_graph.py 中注册到 Agent 列表即可参与并行执行。",
    },
]


# ─── 数据模型 ──────────────────────────────────────────────────────────

@dataclass
class EvalSample:
    question: str
    ground_truth: Optional[str] = None
    category: str = "general"


@dataclass
class EvalRowResult:
    question: str
    answer: str
    num_contexts: int
    # RAGAS 指标
    faithfulness: Optional[float]
    answer_relevancy: Optional[float]
    context_precision: Optional[float]
    context_recall: Optional[float]
    overall_score: float
    # 耗时
    rag_latency_ms: float
    eval_latency_ms: float
    total_latency_ms: float
    # 状态
    success: bool
    error: Optional[str] = None


@dataclass
class EvalSummary:
    total_samples: int
    success_count: int
    failure_count: int
    average_scores: dict
    experiment_name: str
    duration_seconds: float
    timestamp: str
    results: list[EvalRowResult] = field(default_factory=list)


# ─── 核心评测函数 ──────────────────────────────────────────────────────

async def run_single_eval(
    sample: EvalSample,
    evaluator,
    verbose: bool = False,
) -> EvalRowResult:
    """对单条测试数据进行完整的 RAG + 评测流程。"""
    from rag import RAGPipeline
    from eval.ragas_evaluator import RAGASEvaluator

    question = sample.question

    # ── Step 1: RAG Pipeline ─────────────────────────────────────
    pipeline_start = time.perf_counter()
    pipeline = RAGPipeline(
        session_id="eval-session",
        user_id="ragas-evaluator",
        enable_ragas_eval=False,  # 评测在外部单独做
        enable_multi_layer_memory=False,  # 评测时禁用记忆，避免干扰
    )

    answer = ""
    retrieved_contexts: list[str] = []

    try:
        async for event in pipeline.chat(question):
            if event.startswith("data: "):
                raw = event[6:].strip()
                if raw == "[DONE]":
                    continue
                try:
                    data = json.loads(raw)
                    t = data.get("type", "")
                    if t == "done":
                        answer = data.get("answer") or data.get("full_text") or ""
                        sources = data.get("sources", [])
                        retrieved_contexts = [s.get("content", "") or "" for s in sources]
                    elif t == "sources":
                        sources = data.get("sources", [])
                        retrieved_contexts = [s.get("content", "") or "" for s in sources]
                except json.JSONDecodeError:
                    pass
    except Exception as exc:
        pass

    rag_latency_ms = (time.perf_counter() - pipeline_start) * 1000

    if verbose:
        print(f"    RAG done: {len(answer)} chars, {len(retrieved_contexts)} contexts, {rag_latency_ms:.0f}ms")

    # ── Step 2: RAGAS 评测 ─────────────────────────────────────
    eval_start = time.perf_counter()

    try:
        result = await evaluator.evaluate(
            question=question,
            answer=answer,
            retrieved_contexts=retrieved_contexts,
            ground_truth=sample.ground_truth,
        )
        eval_latency_ms = (time.perf_counter() - eval_start) * 1000

        return EvalRowResult(
            question=question,
            answer=answer[:200] + "..." if len(answer) > 200 else answer,
            num_contexts=len(retrieved_contexts),
            faithfulness=result.faithfulness,
            answer_relevancy=result.answer_relevancy,
            context_precision=result.context_precision,
            context_recall=result.context_recall,
            overall_score=result.overall_score,
            rag_latency_ms=rag_latency_ms,
            eval_latency_ms=eval_latency_ms,
            total_latency_ms=rag_latency_ms + eval_latency_ms,
            success=True,
            error=result.error,
        )
    except Exception as exc:
        eval_latency_ms = (time.perf_counter() - eval_start) * 1000
        return EvalRowResult(
            question=question,
            answer=answer[:200] + "..." if len(answer) > 200 else answer,
            num_contexts=len(retrieved_contexts),
            faithfulness=None,
            answer_relevancy=None,
            context_precision=None,
            context_recall=None,
            overall_score=0.0,
            rag_latency_ms=rag_latency_ms,
            eval_latency_ms=eval_latency_ms,
            total_latency_ms=rag_latency_ms + eval_latency_ms,
            success=False,
            error=str(exc),
        )


def compute_summary(results: list[EvalRowResult], experiment_name: str, duration: float) -> EvalSummary:
    """计算汇总统计。"""
    valid = [r for r in results if r.success]

    def avg(key: str) -> Optional[float]:
        vals = [getattr(r, key) for r in valid if getattr(r, key) is not None]
        return sum(vals) / len(vals) if vals else None

    return EvalSummary(
        total_samples=len(results),
        success_count=len(valid),
        failure_count=len(results) - len(valid),
        average_scores={
            "faithfulness": avg("faithfulness"),
            "answer_relevancy": avg("answer_relevancy"),
            "context_precision": avg("context_precision"),
            "context_recall": avg("context_recall"),
            "overall_score": avg("overall_score"),
        },
        experiment_name=experiment_name,
        duration_seconds=duration,
        timestamp=datetime.now().isoformat(),
        results=results,
    )


# ─── 报告生成 ─────────────────────────────────────────────────────────

def save_results(summary: EvalSummary, output_dir: Path):
    """保存评测结果到 CSV 和 summary 文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV
    csv_path = output_dir / "results.csv"
    fieldnames = [
        "question", "answer", "num_contexts",
        "faithfulness", "answer_relevancy", "context_precision", "context_recall",
        "overall_score", "rag_latency_ms", "eval_latency_ms", "total_latency_ms",
        "success", "error",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in summary.results:
            writer.writerow({
                "question": r.question,
                "answer": r.answer,
                "num_contexts": r.num_contexts,
                "faithfulness": r.faithfulness,
                "answer_relevancy": r.answer_relevancy,
                "context_precision": r.context_precision,
                "context_recall": r.context_recall,
                "overall_score": r.overall_score,
                "rag_latency_ms": round(r.rag_latency_ms, 1),
                "eval_latency_ms": round(r.eval_latency_ms, 1),
                "total_latency_ms": round(r.total_latency_ms, 1),
                "success": r.success,
                "error": r.error or "",
            })

    # Summary
    summary_path = output_dir / "summary.txt"
    lines = [
        f"═══════════════════════════════════════════════════════",
        f"  RAGAS Evaluation — {summary.experiment_name}",
        f"═══════════════════════════════════════════════════════",
        f"",
        f"时间：{summary.timestamp}",
        f"耗时：{summary.duration_seconds:.1f}s",
        f"",
        f"───────────────────────────────────────────────────────",
        f"  评测统计",
        f"───────────────────────────────────────────────────────",
        f"  总样本数  ：{summary.total_samples}",
        f"  成功      ：{summary.success_count}",
        f"  失败      ：{summary.failure_count}",
        f"",
        f"───────────────────────────────────────────────────────",
        f"  平均指标得分",
        f"───────────────────────────────────────────────────────",
    ]

    scores = summary.average_scores
    for name, label in [
        ("faithfulness",     "Faithfulness（忠实度）"),
        ("answer_relevancy", "Answer Relevancy（相关度）"),
        ("context_precision","Context Precision（精确度）"),
        ("context_recall",   "Context Recall（召回率）"),
        ("overall_score",    "Overall（综合得分）"),
    ]:
        val = scores.get(name)
        if val is not None:
            bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
            lines.append(f"  {label:<30} {val:.3f}  [{bar}]")
        else:
            lines.append(f"  {label:<30}   N/A")

    lines += [
        "",
        f"───────────────────────────────────────────────────────",
        f"  详细结果 → {csv_path}",
        f"───────────────────────────────────────────────────────",
    ]

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return csv_path, summary_path


# ─── CLI 入口 ──────────────────────────────────────────────────────────

def load_test_data(path: Optional[str]) -> list[EvalSample]:
    """从 CSV/JSON 文件加载测试数据，或返回默认数据集。"""
    if path is None:
        return [EvalSample(**d) for d in DEFAULT_TEST_DATA]

    p = Path(path)
    if not p.exists():
        print(f"[ERROR] 测试数据文件不存在: {path}")
        sys.exit(1)

    samples = []
    if p.suffix == ".csv":
        with open(p, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                samples.append(EvalSample(
                    question=row.get("question", row.get("question", "")),
                    ground_truth=row.get("ground_truth") or None,
                    category=row.get("category", "general"),
                ))
    elif p.suffix == ".json":
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            samples.append(EvalSample(
                question=item["question"],
                ground_truth=item.get("ground_truth"),
                category=item.get("category", "general"),
            ))
    else:
        print(f"[ERROR] 仅支持 .csv 或 .json 格式: {path}")
        sys.exit(1)

    return samples


def run(args):
    """执行评测实验。"""
    # ── 加载 .env 配置 ──────────────────────────────────────────
    dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        from dotenv import load_dotenv
        load_dotenv(dotenv_path)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("[ERROR] .env 中未找到 OPENAI_API_KEY")
        sys.exit(1)

    model = os.getenv("OPENAI_MODEL", "qwen3.6-plus-2026-04-02")
    base_url = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # 设置实验名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiment_name = args.name or f"rag_eval_{timestamp}"
    output_dir = Path("results") / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*56}")
    print(f"  RAGAS Evaluation — {experiment_name}")
    print(f"{'='*56}")
    print(f"  输出目录：{output_dir}")
    print(f"{'='*56}\n")

    # ── 加载数据 ───────────────────────────────────────────────
    samples = load_test_data(args.data)
    if args.limit:
        samples = samples[:args.limit]

    print(f"[INFO] 加载了 {len(samples)} 条测试数据\n")

    # ── 初始化评测器 ───────────────────────────────────────────
    from eval.ragas_evaluator import RAGASEvaluator

    evaluator = RAGASEvaluator(
        user_avatar=experiment_name,
        evaluation_llm_model=model,
    )
    # 直接注入已初始化的 LLM（避免 ragas_evaluator 内部再次读取 env）
    from langchain_openai import ChatOpenAI
    evaluator._eval_llm = ChatOpenAI(
        model=model,
        temperature=0.0,
        openai_api_key=api_key,
        base_url=base_url,
        max_retries=5,
        timeout=120.0,
    )
    evaluator._initialized = True

    # ── 执行评测 ───────────────────────────────────────────────
    results: list[EvalRowResult] = []
    start = time.perf_counter()

    for i, sample in enumerate(samples, 1):
        print(f"[{i}/{len(samples)}] Q: {sample.question[:50]}...")
        if args.verbose:
            print(f"    ground_truth: {sample.ground_truth[:80] if sample.ground_truth else 'N/A'}...")

        result = asyncio.run(run_single_eval(sample, evaluator, verbose=args.verbose))
        results.append(result)

        status = "✓" if result.success else "✗"
        score_str = f"{result.overall_score:.3f}" if result.success else "FAIL"
        print(f"    → {status} overall={score_str}, "
              f"rag={result.rag_latency_ms:.0f}ms, "
              f"eval={result.eval_latency_ms:.0f}ms")

        if result.error and args.verbose:
            print(f"    [ERROR] {result.error}")

    total_duration = time.perf_counter() - start

    # ── 生成报告 ───────────────────────────────────────────────
    summary = compute_summary(results, experiment_name, total_duration)
    csv_path, summary_path = save_results(summary, output_dir)

    # ── 打印汇总 ───────────────────────────────────────────────
    print(f"\n{'='*56}")
    print(f"  评测完成！耗时 {total_duration:.1f}s")
    print(f"{'='*56}")
    print()

    scores = summary.average_scores
    for name, label in [
        ("faithfulness",     "Faithfulness（忠实度）"),
        ("answer_relevancy", "Answer Relevancy（相关度）"),
        ("context_precision","Context Precision（精确度）"),
        ("context_recall",   "Context Recall（召回率）"),
        ("overall_score",    "Overall（综合得分）"),
    ]:
        val = scores.get(name)
        if val is not None:
            bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
            print(f"  {label:<30} {val:.3f}  [{bar}]")
        else:
            print(f"  {label:<30}   N/A")

    print()
    print(f"  详细结果 → {csv_path}")
    print(f"  汇总报告 → {summary_path}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="RAGAS RAG 质量评测实验运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python eval/rag_eval.py                    # 使用 .env 中的配置
  python eval/rag_eval.py --limit 3 --verbose
  python eval/rag_eval.py --data eval/examples/test_data.csv --name my_eval
        """,
    )
    parser.add_argument("--data", "-d", help="测试数据文件路径 (.csv 或 .json)")
    parser.add_argument("--name", "-n", help="实验名称（默认: rag_eval_<timestamp>）")
    parser.add_argument("--limit", "-l", type=int, help="最多评测 N 条数据（快速验证）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细输出")

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
