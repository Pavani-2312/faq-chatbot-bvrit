"""
eval/report.py
--------------
Aggregates test results + RAGAS scores into a structured evaluation report
saved to tests/evaluation_report.json.

The report is consumed by the Dashboard tab in app.py.

Report structure:
{
  "generated_at":     ISO timestamp,
  "total_cases":      int,
  "overall_pass":     int,
  "overall_fail":     int,
  "overall_rate":     float (0–1),
  "weakest_dimension": str,
  "fix_recommendation": str,
  "dimensions": {
    "D01_functional_completeness": {
      "total": int, "passed": int, "failed": int, "pass_rate": float,
      "cases": [...]
    },
    ...
  },
  "ragas": {
    "faithfulness":      {"score": float, "target": float, "passed": bool},
    "answer_relevancy":  {...},
    "context_precision": {...},
    "context_recall":    {...}
  },
  "error_cases": [...]
}
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    EVAL_DIMENSIONS,
    EVAL_REPORT_PATH,
    TEST_RESULTS_PATH,
    TESTS_DIR,
)

RAGAS_SCORES_PATH = TESTS_DIR / "ragas_scores.json"

# ---------------------------------------------------------------------------
# Fix recommendations per dimension (surfaced when dimension fails)
# ---------------------------------------------------------------------------
FIX_RECOMMENDATIONS = {
    "D01_functional_completeness": (
        "Increase top-k retrieval or ensure all-branch/all-department content is well chunked. "
        "Check that list-type pages (e.g., Intake of Courses) are not split across chunk boundaries."
    ),
    "D02_factual_accuracy": (
        "Verify that specific figures (fees, packages) are present verbatim in the knowledge base. "
        "Consider reducing chunk size so precise numbers aren't buried mid-chunk."
    ),
    "D03_grounding_no_hallucination": (
        "Strengthen the system prompt grounding rules. Consider lowering generation temperature "
        "further (toward 0). Add a post-generation check that flags answers not grounded in retrieved context."
    ),
    "D04_citation_quality": (
        "Reinforce citation instructions in the system prompt. "
        "Add a post-processing step that warns if no [Section] pattern is found in the response."
    ),
    "D05_graceful_refusal": (
        "Review refusal detection phrases in chatbot.py. "
        "Ensure the fallback contact is always appended when the model refuses."
    ),
    "D06_performance_latency": (
        "Profile which step is slow: retrieval vs. LLM generation. "
        "For retrieval: verify ChromaDB is using ANN (not exact) search for large collections. "
        "For generation: reduce MAX_TOKENS or switch to a faster model for simple queries."
    ),
    "D07_conflict_handling": (
        "Check that conflicting chunks are being retrieved together (top-k may need to be higher). "
        "Strengthen the conflict-handling instruction in the system prompt with explicit examples."
    ),
    "D08_ragas_metrics": (
        "Low faithfulness → model is hallucinating beyond retrieved context; tighten grounding prompt. "
        "Low relevancy → retrieval is returning off-topic chunks; improve embedding model or chunk boundaries. "
        "Low precision → too many irrelevant chunks retrieved; reduce top-k or add section filtering. "
        "Low recall → relevant chunks not being retrieved; check chunk size and overlap."
    ),
}


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
    dim_data: dict[str, dict] = {}
    for dim in EVAL_DIMENSIONS:
        dim_data[dim] = {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0, "cases": []}

    error_cases = []

    for r in results:
        dim = r.get("dimension", "unknown")
        if dim not in dim_data:
            dim_data[dim] = {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0, "cases": []}

        dim_data[dim]["total"] += 1
        dim_data[dim]["cases"].append(
            {
                "id": r["id"],
                "question": r["question"],
                "passed": r.get("passed"),
                "judge_reason": r.get("judge_reason", ""),
                "latency_sec": r.get("latency_sec"),
                "is_refusal": r.get("is_refusal", False),
                "has_conflict": r.get("has_conflict", False),
            }
        )

        if r.get("error"):
            error_cases.append({"id": r["id"], "error": r["error"]})

        if r.get("passed") is True:
            dim_data[dim]["passed"] += 1
        elif r.get("passed") is False:
            dim_data[dim]["failed"] += 1

    # Compute pass rates
    for dim, data in dim_data.items():
        if data["total"] > 0:
            data["pass_rate"] = round(data["passed"] / data["total"], 4)

    # ---- Overall stats --------------------------------------------------
    judged = [r for r in results if r.get("passed") is not None]
    overall_pass = sum(1 for r in judged if r["passed"])
    overall_fail = sum(1 for r in judged if not r["passed"])
    overall_rate = round(overall_pass / len(judged), 4) if judged else 0.0

    # ---- Weakest dimension ----------------------------------------------
    scored_dims = {
        dim: data for dim, data in dim_data.items()
        if data["total"] > 0 and dim != "D08_ragas_metrics"
    }
    weakest_dim = (
        min(scored_dims, key=lambda d: scored_dims[d]["pass_rate"])
        if scored_dims else "N/A"
    )

    # For D08, use the lowest RAGAS metric score
    if ragas_summary:
        lowest_ragas = min(ragas_summary.items(), key=lambda x: x[1]["score"])
        if not scored_dims or lowest_ragas[1]["score"] < scored_dims.get(weakest_dim, {}).get("pass_rate", 1.0):
            weakest_dim = f"D08_ragas_metrics ({lowest_ragas[0]})"

    fix_rec = FIX_RECOMMENDATIONS.get(
        weakest_dim.split(" ")[0],
        "Review the failing test cases and examine retrieved chunks for that dimension.",
    )

    # ---- Assemble report ------------------------------------------------
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(results),
        "overall_pass": overall_pass,
        "overall_fail": overall_fail,
        "overall_rate": overall_rate,
        "weakest_dimension": weakest_dim,
        "fix_recommendation": fix_rec,
        "dimensions": dim_data,
        "ragas": ragas_summary,
        "error_cases": error_cases,
    }

    # ---- Save -----------------------------------------------------------
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[report] Evaluation report saved → {output_path}")
    print(f"[report] Overall: {overall_pass}/{len(judged)} passed ({100*overall_rate:.1f}%)")
    print(f"[report] Weakest dimension: {weakest_dim}")
    print(f"[report] Fix recommendation: {fix_rec[:100]}...")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_report()
