"""
eval/report.py
--------------
Aggregates test results + RAGAS scores into a structured evaluation report
saved to tests/evaluation_report.json.

Consumed by the Dashboard tab in app.py.

Report schema (Architecture.md §6.5):
{
  "summary": {
    "total": int, "passed": int, "failed": int, "pass_rate": float
  },
  "per_dimension": {
    "01-Functional": {
      "passed": int, "failed": int, "total": int, "pass_rate": float,
      "cases": [{"test_id", "question", "passed", "judge_reason",
                 "actual_answer", "expected_answer", "latency_sec",
                 "refused", "has_conflict", "was_injected"}]
    },
    ...
  },
  "weakest_dimension": str,
  "recommendation": str,
  "ragas_scores": {
    "faithfulness": float, "answer_relevancy": float,
    "context_precision": float, "context_recall": float
  },
  "ragas_diagnosis": str,
  "error_cases": [{"test_id", "error"}],
  "generated_at": ISO timestamp
}
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    EVAL_DIMENSIONS,
    EVAL_REPORT_PATH,
    TEST_RESULTS_PATH,
    TESTS_DIR,
    RAGAS_FAITHFULNESS_TARGET,
    RAGAS_ANSWER_RELEVANCY_TARGET,
    RAGAS_CONTEXT_PRECISION_TARGET,
    RAGAS_CONTEXT_RECALL_TARGET,
)

RAGAS_SCORES_PATH = TESTS_DIR / "ragas_scores.json"

# ---------------------------------------------------------------------------
# Fix recommendations per dimension — aligned to brief §5 Step D
# ---------------------------------------------------------------------------
FIX_RECOMMENDATIONS = {
    "01-Functional": (
        "Increase top-k retrieval or ensure all list-type content (departments, courses) is "
        "not split across chunk boundaries. Verify citation instructions in the system prompt."
    ),
    "02-Quality": (
        "Verify that specific facts (fees, packages, intake numbers) appear verbatim in the "
        "knowledge base. Consider reducing chunk size so precise numbers are not buried mid-chunk."
    ),
    "03-Safety": (
        "Strengthen clause 6 of the system prompt (Safety constraint). Ensure the model uses "
        "hedging language ('based on past data', 'historically') for outcome-related questions."
    ),
    "04-Security": (
        "Strengthen clause 7 of the system prompt (Injection-defence). Add explicit examples "
        "of injection patterns to the prompt and expand INJECTION_PATTERNS in config.py."
    ),
    "05-Robustness": (
        "Add pre-retrieval input validation in chatbot.py for empty/gibberish/very-long inputs. "
        "Return a graceful refusal immediately for inputs that cannot form a meaningful query."
    ),
    "06-Performance": (
        "Profile which step is slow: retrieval vs. LLM generation. "
        "For retrieval: verify ChromaDB is using ANN (not exact) search. "
        "For generation: reduce GENERATION_MAX_TOKENS or switch to a faster model."
    ),
    "07-Context": (
        "Increase MAX_HISTORY_TURNS in memory.py. Verify that conversation history is correctly "
        "injected into the prompt. Test multi-turn resolution manually before re-running."
    ),
    "08-RAGAS": (
        "Low faithfulness → model is hallucinating; tighten grounding clause in system prompt. "
        "Low relevancy → retrieval returning off-topic chunks; improve chunking boundaries. "
        "Low precision → too many irrelevant chunks; reduce top-k or add section filtering. "
        "Low recall → relevant chunks not retrieved; check chunk size and overlap."
    ),
}

# RAGAS metric display names and targets
RAGAS_TARGETS = {
    "faithfulness": RAGAS_FAITHFULNESS_TARGET,
    "answer_relevancy": RAGAS_ANSWER_RELEVANCY_TARGET,
    "context_precision": RAGAS_CONTEXT_PRECISION_TARGET,
    "context_recall": RAGAS_CONTEXT_RECALL_TARGET,
}


def _ragas_diagnosis(ragas_scores: dict) -> str:
    """Generate a one-sentence diagnosis of the lowest RAGAS metric."""
    if not ragas_scores:
        return ""
    lowest_key = min(ragas_scores, key=lambda k: ragas_scores[k].get("score", 1.0))
    score = ragas_scores[lowest_key]["score"]
    target = ragas_scores[lowest_key]["target"]
    diagnoses = {
        "faithfulness": (
            f"Faithfulness ({score:.2f}) is lowest — model may be hallucinating beyond "
            f"retrieved context. Tighten the grounding clause in the system prompt."
        ),
        "answer_relevancy": (
            f"Answer Relevancy ({score:.2f}) is lowest — responses are not fully addressing "
            f"the question. Review retrieval quality and prompt focus."
        ),
        "context_precision": (
            f"Context Precision ({score:.2f}) is lowest — retrieval returns some irrelevant "
            f"chunks. Consider reducing top-k or adding section metadata filters."
        ),
        "context_recall": (
            f"Context Recall ({score:.2f}) is lowest — relevant chunks are not being retrieved. "
            f"Check chunk size ({score:.2f} < {target}) and overlap settings."
        ),
    }
    return diagnoses.get(lowest_key, f"{lowest_key} score ({score:.2f}) is below target ({target}).")


def build_report(
    results_path: Path = TEST_RESULTS_PATH,
    ragas_scores_path: Path = RAGAS_SCORES_PATH,
    output_path: Path = EVAL_REPORT_PATH,
) -> dict:
    """
    Build and save the evaluation report from test results + RAGAS scores.
    """
    if not results_path.exists():
        raise FileNotFoundError(
            f"Test results not found at {results_path}. Run test_runner.py first."
        )

    results: list[dict] = json.loads(results_path.read_text(encoding="utf-8"))

    # Load RAGAS scores if available
    ragas_summary: dict = {}
    if ragas_scores_path.exists():
        ragas_summary = json.loads(ragas_scores_path.read_text(encoding="utf-8"))

    # ---- Aggregate by dimension ----------------------------------------
    per_dim: dict[str, dict] = {}
    for dim in EVAL_DIMENSIONS:
        per_dim[dim] = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "cases": [],
        }

    error_cases = []

    for r in results:
        dim = r.get("dimension", "unknown")
        if dim not in per_dim:
            per_dim[dim] = {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0, "cases": []}

        per_dim[dim]["total"] += 1
        per_dim[dim]["cases"].append(
            {
                "test_id": r["test_id"],
                "question": r["question"],
                "expected_answer": r.get("expected_answer", ""),
                "actual_answer": r.get("actual_answer", ""),
                "passed": r.get("passed"),
                "judge_reason": r.get("judge_reason", ""),
                "latency_sec": r.get("latency_sec"),
                "refused": r.get("refused", False),
                "has_conflict": r.get("has_conflict", False),
                "was_injected": r.get("was_injected", False),
            }
        )

        if r.get("error"):
            error_cases.append({"test_id": r["test_id"], "error": r["error"]})

        if r.get("passed") is True:
            per_dim[dim]["passed"] += 1
        elif r.get("passed") is False:
            per_dim[dim]["failed"] += 1

    # Compute pass rates
    for dim, data in per_dim.items():
        if data["total"] > 0:
            data["pass_rate"] = round(data["passed"] / data["total"], 4)

    # ---- Overall stats --------------------------------------------------
    judged = [r for r in results if r.get("passed") is not None]
    overall_pass = sum(1 for r in judged if r["passed"])
    overall_fail = sum(1 for r in judged if not r["passed"])
    overall_rate = round(overall_pass / len(judged), 4) if judged else 0.0

    # ---- Weakest dimension (excluding 08-RAGAS if RAGAS scores exist) ---
    scored_dims = {
        dim: data
        for dim, data in per_dim.items()
        if data["total"] > 0 and dim != "08-RAGAS"
    }
    weakest_dim = (
        min(scored_dims, key=lambda d: scored_dims[d]["pass_rate"])
        if scored_dims else "N/A"
    )

    # Check if a RAGAS metric is weaker
    if ragas_summary:
        lowest_ragas_score = min(
            v["score"] for v in ragas_summary.values() if isinstance(v, dict)
        )
        if not scored_dims or lowest_ragas_score < scored_dims.get(weakest_dim, {}).get("pass_rate", 1.0):
            lowest_key = min(ragas_summary, key=lambda k: ragas_summary[k].get("score", 1.0))
            weakest_dim = f"08-RAGAS ({lowest_key})"

    recommendation = FIX_RECOMMENDATIONS.get(
        weakest_dim.split(" ")[0],
        "Review the failing test cases and examine retrieved chunks for that dimension.",
    )

    # ---- Assemble report per Architecture.md §6.5 ----------------------
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "passed": overall_pass,
            "failed": overall_fail,
            "pass_rate": overall_rate,
        },
        "per_dimension": per_dim,
        "weakest_dimension": weakest_dim,
        "recommendation": recommendation,
        "ragas_scores": ragas_summary,
        "ragas_diagnosis": _ragas_diagnosis(ragas_summary),
        "error_cases": error_cases,
    }

    # ---- Save -----------------------------------------------------------
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[report] Evaluation report saved → {output_path}")
    print(
        f"[report] Summary: {overall_pass}/{len(judged)} passed "
        f"({100 * overall_rate:.1f}%)"
    )
    print(f"[report] Weakest dimension: {weakest_dim}")
    print(f"[report] Recommendation: {recommendation[:100]}...")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_report()
