"""
eval/test_runner.py
-------------------
Executes every test case from tests/test_cases.json against the live chatbot
and saves raw results to tests/test_results.json.

Handles the 07-Context dimension by injecting turn_1 as prior history before
running the follow-up question, simulating a real multi-turn conversation.

Each result record (Architecture.md §6.4):
{
  "test_id":          "FUNC-01",
  "dimension":        "01-Functional",
  "question":         "...",
  "expected_answer":  "...",
  "pass_criteria":    "...",
  "actual_answer":    "...",
  "retrieved_chunks": [...],    // lightweight summaries
  "citations":        [...],
  "latency_sec":      2.34,
  "refused":          false,
  "has_conflict":     false,
  "was_injected":     false,
  "error":            null,
  "judge_score":      null,     // filled in by judge.py
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
    Writes results to TEST_RESULTS_PATH.
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
        tc_id = tc.get("test_id", f"TC_{i:03d}")
        question = tc["question"]
        dimension = tc["dimension"]
        section_hint = tc.get("context_hint", None)
        is_complex = tc.get("is_complex", False)

        print(f"[{i:02d}/{len(test_cases)}] {tc_id} | {dimension}")

        # 07-Context: inject turn_1 as prior history before the follow-up
        history = []
        if dimension == "07-Context" and tc.get("turn_1"):
            turn_1_q = tc["turn_1"]
            # Run turn_1 silently to get a real chatbot answer as prior context
            turn_1_resp = chatbot.ask(question=turn_1_q, history=[], k=TOP_K)
            history = [
                {"role": "user", "content": turn_1_q},
                {"role": "assistant", "content": turn_1_resp.answer},
            ]

        response = chatbot.ask(
            question=question,
            history=history,
            k=TOP_K,
            section_filter=section_hint,
        )

        # 06-Performance: numeric SLA check (no judge needed)
        passed = None
        judge_score = None
        judge_reason = None

        if dimension == "06-Performance":
            sla = SLA_COMPLEX_QUERY_SEC if is_complex else SLA_SIMPLE_QUERY_SEC
            passed = response.latency_sec <= sla
            judge_score = 1 if passed else 0
            judge_reason = (
                f"Latency {response.latency_sec:.2f}s vs SLA {sla}s → "
                f"{'PASS' if passed else 'FAIL'}"
            )

        result = {
            "test_id": tc_id,
            "dimension": dimension,
            "question": question,
            "expected_answer": tc.get("expected_answer", ""),
            "pass_criteria": tc.get("pass_criteria", ""),
            "actual_answer": response.answer,
            "retrieved_chunks": _chunk_summary(response.retrieved_chunks),
            "citations": response.citations,
            "latency_sec": response.latency_sec,
            "refused": response.refused,
            "has_conflict": response.has_conflict,
            "was_injected": response.was_injected,
            "error": response.error,
            "judge_score": judge_score,
            "judge_reason": judge_reason,
            "passed": passed,
            # preserve turn_1 for reference in dashboard drill-downs
            "turn_1": tc.get("turn_1"),
        }
        results.append(result)

        # Brief status line
        status = "ERROR" if response.error else ("REFUSED" if response.refused else "OK")
        print(f"       {status} | {response.latency_sec:.2f}s | {len(response.citations)} citations")

    # -- Save results -----------------------------------------------------
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    TEST_RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[test_runner] Results saved → {TEST_RESULTS_PATH}")

    # Summary
    errors = sum(1 for r in results if r["error"])
    d06_results = [r for r in results if r["dimension"] == "06-Performance"]
    d06_passed = sum(1 for r in d06_results if r["passed"])
    print(
        f"[test_runner] Errors: {errors} | "
        f"06-Performance: {d06_passed}/{len(d06_results)} passed"
    )

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_all()
