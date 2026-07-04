"""
eval/test_runner.py
-------------------
Executes every test case from tests/test_cases.json against the live chatbot
and saves raw results to tests/test_results.json.

Each result record:
{
  "id":               "TC_001",
  "dimension":        "D01_functional_completeness",
  "question":         "...",
  "expected":         "...",
  "pass_criteria":    "...",
  "actual_answer":    "...",
  "retrieved_chunks": [...],    // metadata only, not full content
  "citations":        [...],
  "latency_sec":      2.34,
  "is_refusal":       false,
  "has_conflict":     false,
  "error":            null,
  "judge_score":      null,     // filled in by judge.py later
  "judge_reason":     null,
  "passed":           null
}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    SLA_COMPLEX_QUERY_SEC,
    SLA_SIMPLE_QUERY_SEC,
    TEST_CASES_PATH,
    TEST_RESULTS_PATH,
    TESTS_DIR,
    TOP_K,
)
from chatbot import BVRITChatbot
from retriever import retriever


def _chunk_summary(chunks: list[dict]) -> list[dict]:
    """Return lightweight chunk summaries (no full content) to keep results.json small."""
    return [
        {
            "id": c.get("id", ""),
            "section": c.get("metadata", {}).get("section", ""),
            "page_number": c.get("metadata", {}).get("page_number", ""),
            "score": c.get("score", 0),
            "content_preview": c.get("content", "")[:150],
        }
        for c in chunks
    ]


def run_all(test_cases_path: Path = TEST_CASES_PATH) -> list[dict]:
    """
    Load test cases, run each through the chatbot, and return result records.
    Also writes results to TEST_RESULTS_PATH.
    """
    # -- Load test cases --------------------------------------------------
    if not test_cases_path.exists():
        raise FileNotFoundError(
            f"Test cases not found at {test_cases_path}. "
            "Run eval/test_generator.py first."
        )
    test_cases: list[dict] = json.loads(test_cases_path.read_text(encoding="utf-8"))
    print(f"[test_runner] Loaded {len(test_cases)} test cases from {test_cases_path}")

    # -- Load retriever & chatbot -----------------------------------------
    print("[test_runner] Loading retriever...")
    retriever.load()
    chatbot = BVRITChatbot(retriever=retriever)
    print(f"[test_runner] Retriever ready. Chunks: {retriever.chunk_count}")

    # -- Run each test case -----------------------------------------------
    results = []
    for i, tc in enumerate(test_cases, start=1):
        tc_id = tc.get("id", f"TC_{i:03d}")
        question = tc["question"]
        dimension = tc["dimension"]
        section_hint = tc.get("section_hint", None)
        is_complex = tc.get("is_complex", False)

        print(f"[{i:02d}/{len(test_cases)}] {tc_id} | {dimension}")

        response = chatbot.ask(
            question=question,
            history=[],   # each test case is independent (no prior context)
            k=TOP_K,
            section_filter=section_hint,
        )

        # D06: numeric SLA check (no judge needed)
        passed = None
        judge_score = None
        judge_reason = None

        if dimension == "D06_performance_latency":
            sla = SLA_COMPLEX_QUERY_SEC if is_complex else SLA_SIMPLE_QUERY_SEC
            passed = response.latency_sec <= sla
            judge_score = 1 if passed else 0
            judge_reason = (
                f"Latency {response.latency_sec:.2f}s vs SLA {sla}s → "
                f"{'PASS' if passed else 'FAIL'}"
            )

        result = {
            "id": tc_id,
            "dimension": dimension,
            "question": question,
            "expected": tc.get("expected", ""),
            "pass_criteria": tc.get("pass_criteria", ""),
            "actual_answer": response.answer,
            "retrieved_chunks": _chunk_summary(response.retrieved_chunks),
            "citations": response.citations,
            "latency_sec": response.latency_sec,
            "is_refusal": response.is_refusal,
            "has_conflict": response.has_conflict,
            "error": response.error,
            "judge_score": judge_score,
            "judge_reason": judge_reason,
            "passed": passed,
        }
        results.append(result)

        # Brief status line
        status = "ERROR" if response.error else ("REFUSAL" if response.is_refusal else "OK")
        print(f"       {status} | {response.latency_sec:.2f}s | {len(response.citations)} citations")

    # -- Save results -----------------------------------------------------
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    TEST_RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[test_runner] Results saved → {TEST_RESULTS_PATH}")

    # Summary
    errors = sum(1 for r in results if r["error"])
    d06_passed = sum(1 for r in results if r["dimension"] == "D06_performance_latency" and r["passed"])
    d06_total = sum(1 for r in results if r["dimension"] == "D06_performance_latency")
    print(f"[test_runner] Errors: {errors} | D06 (latency): {d06_passed}/{d06_total} passed")

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_all()
