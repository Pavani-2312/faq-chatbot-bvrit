"""
eval/judge.py
-------------
Uses a second LLM (different from the generation model, per FR-6.3) to score
each non-D06 test result pass/fail with a reason.

The judge reads:
  - question
  - expected answer / pass_criteria
  - actual_answer
  - citations found in the answer
  - is_refusal / has_conflict flags

It returns:
  - score:  1 (pass) | 0 (fail)
  - reason: one-sentence explanation

Updates tests/test_results.json in-place.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config import (
    JUDGE_MODEL,
    JUDGE_TEMPERATURE,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    TEST_RESULTS_PATH,
)


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """\
You are an impartial evaluator for a RAG-based FAQ chatbot built for BVRIT College.
You will be given a test case and the chatbot's actual response.
Your job is to determine whether the response passes or fails the stated pass_criteria.

Rules:
- Score 1 = PASS, 0 = FAIL. No partial scores.
- Base your decision ONLY on the pass_criteria, not on your own knowledge of BVRIT.
- For citation questions: check that citations are present and formatted as [Section, Page N] or [Section].
- For refusal questions: PASS if the response refuses AND provides a fallback contact (phone/email/website).
- For conflict questions: PASS only if BOTH conflicting values are shown AND a ⚠️ flag or "conflict" mention is present.
- For accuracy questions: PASS only if the specific expected fact appears in the actual answer.
- For completeness questions: PASS only if all required items in expected are present in actual.
- For grounding questions: PASS if the answer stays within the retrieved knowledge base (no invented facts).

Respond with ONLY a JSON object: {"score": 0 or 1, "reason": "one-sentence explanation"}
"""

JUDGE_USER_TEMPLATE = """\
DIMENSION: {dimension}

QUESTION: {question}

EXPECTED / PASS CRITERIA:
{pass_criteria}

ACTUAL ANSWER:
{actual_answer}

CITATIONS FOUND: {citations}
IS REFUSAL: {is_refusal}
HAS CONFLICT FLAG: {has_conflict}
"""


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

def judge_result(client: OpenAI, result: dict) -> tuple[int, str]:
    """
    Score a single test result using the judge LLM.

    Returns (score: int, reason: str).
    """
    prompt = JUDGE_USER_TEMPLATE.format(
        dimension=result.get("dimension", ""),
        question=result.get("question", ""),
        pass_criteria=result.get("pass_criteria", ""),
        actual_answer=result.get("actual_answer", ""),
        citations=result.get("citations", []),
        is_refusal=result.get("is_refusal", False),
        has_conflict=result.get("has_conflict", False),
    )

    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=JUDGE_TEMPERATURE,
        max_tokens=256,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Strip accidental markdown fences
    import re
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    parsed = json.loads(raw)
    score = int(parsed.get("score", 0))
    reason = str(parsed.get("reason", ""))
    return score, reason


def run_judging(results_path: Path = TEST_RESULTS_PATH) -> list[dict]:
    """
    Load test results, judge each non-D06 result, update and save.
    """
    if not results_path.exists():
        raise FileNotFoundError(
            f"Test results not found at {results_path}. Run test_runner.py first."
        )

    results: list[dict] = json.loads(results_path.read_text(encoding="utf-8"))
    to_judge = [r for r in results if r["dimension"] != "D06_performance_latency"
                and r.get("judge_score") is None
                and not r.get("error")]

    if not to_judge:
        print("[judge] No results to judge (all already scored or D06-only).")
        return results

    print(f"[judge] Judging {len(to_judge)} results with {JUDGE_MODEL}...")

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    judged = 0
    for result in results:
        if result["dimension"] == "D06_performance_latency":
            continue  # already scored numerically by test_runner
        if result.get("error"):
            result["judge_score"] = 0
            result["judge_reason"] = f"Test errored: {result['error']}"
            result["passed"] = False
            continue
        if result.get("judge_score") is not None:
            continue  # already judged

        try:
            score, reason = judge_result(client, result)
        except Exception as exc:
            score = 0
            reason = f"Judge error: {exc}"

        result["judge_score"] = score
        result["judge_reason"] = reason
        result["passed"] = bool(score)
        judged += 1

        verdict = "PASS" if score else "FAIL"
        print(f"  [{verdict}] {result['id']} | {reason[:80]}")

    # Save updated results
    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[judge] Judged {judged} results → {results_path}")

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    print(f"[judge] Overall: {passed}/{total} passed ({100*passed//total}%)")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_judging()
