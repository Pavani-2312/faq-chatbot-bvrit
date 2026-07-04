"""
eval/ragas_eval.py
------------------
Computes RAGAS metrics (faithfulness, answer_relevancy, context_precision,
context_recall) for the 08-RAGAS dimension test cases.

Uses the `ragas` library with OpenAI as the LLM/embedding backend.

Appends RAGAS metric scores to the result records and saves a summary
to tests/ragas_scores.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    OPENAI_API_KEY,
    RAGAS_ANSWER_RELEVANCY_TARGET,
    RAGAS_CONTEXT_PRECISION_TARGET,
    RAGAS_CONTEXT_RECALL_TARGET,
    RAGAS_FAITHFULNESS_TARGET,
    TEST_RESULTS_PATH,
    TESTS_DIR,
)

RAGAS_SCORES_PATH = TESTS_DIR / "ragas_scores.json"

# ---------------------------------------------------------------------------
# Targets map (for pass/fail per metric)
# ---------------------------------------------------------------------------
METRIC_TARGETS = {
    "faithfulness": RAGAS_FAITHFULNESS_TARGET,
    "answer_relevancy": RAGAS_ANSWER_RELEVANCY_TARGET,
    "context_precision": RAGAS_CONTEXT_PRECISION_TARGET,
    "context_recall": RAGAS_CONTEXT_RECALL_TARGET,
}


def run_ragas_eval(results_path: Path = TEST_RESULTS_PATH) -> dict:
    """
    Run RAGAS evaluation on D08 test cases.

    Returns a dict with per-metric scores and pass/fail flags.
    """
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
    except ImportError as e:
        print(f"[ragas_eval] Missing dependency: {e}")
        print("[ragas_eval] Install with: pip install ragas langchain-openai datasets")
        return {}

    if not results_path.exists():
        raise FileNotFoundError(
            f"Test results not found at {results_path}. Run test_runner.py first."
        )

    results: list[dict] = json.loads(results_path.read_text(encoding="utf-8"))

    # Filter D08 cases that have real answers (no errors)
    d08_cases = [
        r for r in results
        if r["dimension"] == "08-RAGAS" and not r.get("error")
    ]

    if not d08_cases:
        print("[ragas_eval] No D08 test cases found in results.")
        return {}

    print(f"[ragas_eval] Running RAGAS on {len(d08_cases)} D08 cases...")

    # Build RAGAS dataset
    questions = []
    answers = []
    contexts = []
    ground_truths = []

    for r in d08_cases:
        questions.append(r["question"])
        answers.append(r["actual_answer"])
        # Build context list from retrieved chunk previews
        ctx = [
            chunk.get("content_preview", "")
            for chunk in r.get("retrieved_chunks", [])
            if chunk.get("content_preview")
        ]
        contexts.append(ctx if ctx else [""])
        ground_truths.append(r["expected_answer"])

    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
    )

    # Configure RAGAS to use OpenAI
    import os
    os.environ.setdefault("OPENAI_API_KEY", OPENAI_API_KEY)

    llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini", temperature=0))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))

    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
    for metric in metrics:
        metric.llm = llm
        if hasattr(metric, "embeddings"):
            metric.embeddings = embeddings

    result = evaluate(dataset, metrics=metrics)
    scores_df = result.to_pandas()

    # Aggregate per metric (mean across all D08 cases)
    metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    summary: dict = {}
    for key in metric_keys:
        if key in scores_df.columns:
            mean_score = float(scores_df[key].mean())
            target = METRIC_TARGETS.get(key, 0.75)
            summary[key] = {
                "score": round(mean_score, 4),
                "target": target,
                "passed": mean_score >= target,
            }

    # Annotate individual D08 results with per-row RAGAS scores
    for i, r in enumerate(d08_cases):
        ragas_row = {}
        for key in metric_keys:
            if key in scores_df.columns:
                ragas_row[key] = round(float(scores_df[key].iloc[i]), 4)
        r["ragas_scores"] = ragas_row

    # Save updated results
    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Save RAGAS summary
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    RAGAS_SCORES_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"[ragas_eval] RAGAS scores saved → {RAGAS_SCORES_PATH}")
    for metric, info in summary.items():
        verdict = "✅ PASS" if info["passed"] else "❌ FAIL"
        print(f"  {metric}: {info['score']:.3f} (target ≥ {info['target']}) {verdict}")

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_ragas_eval()
