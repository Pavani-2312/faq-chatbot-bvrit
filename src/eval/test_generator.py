"""
eval/test_generator.py
----------------------
Uses a strong LLM to auto-generate a diverse test suite (≥20 cases)
spanning all 8 evaluation dimensions for the BVRIT FAQ chatbot.

Output: tests/test_cases.json
Each test case:
{
  "id":             "TC_001",
  "dimension":      "D01_functional_completeness",
  "question":       "List all B.Tech branches offered at BVRIT.",
  "expected":       "CSE, ECE, EEE, IT, CSE-AI&ML",
  "pass_criteria":  "All 5 branches are named in the answer.",
  "requires_judge": true,    // false only for D06 (latency, numeric check)
  "section_hint":   "Departments"   // optional section filter to use
}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config import (
    ANTHROPIC_API_KEY,
    MIN_TEST_CASES,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    TEST_CASES_PATH,
    TEST_GENERATOR_MODEL,
    TESTS_DIR,
)

# ---------------------------------------------------------------------------
# Prompt for the test generator LLM
# ---------------------------------------------------------------------------

GENERATOR_SYSTEM_PROMPT = """\
You are a senior QA engineer specializing in RAG (Retrieval-Augmented Generation) systems.
Your task is to write a comprehensive test suite for a FAQ chatbot built for BVRIT HYDERABAD
College of Engineering for Women.

The chatbot answers only from its knowledge base, which covers these sections:
  - About BVRIT (founding year, accreditations, vision/mission)
  - Departments (CSE, ECE, EEE, IT, CSE-AI&ML, BS&H — intake, faculty, accreditation)
  - Admissions (eligibility, EAMCET, process steps, required documents)
  - Fee Structure (tuition by branch/batch/year, NBA fee, JNTUH fee)
  - Placements (company-wise tables, packages, batch totals from 2012–2025)
  - Campus & Facilities (library, hostel, labs)
  - Faculty (aggregate counts for CSE, named award recipients)
  - Contact (address, phone, email, social media)

Generate EXACTLY {n} test cases covering all 8 evaluation dimensions below.
Distribute cases roughly evenly (2–4 per dimension).

DIMENSIONS:
  D01_functional_completeness  — The answer fully covers the question (e.g., lists ALL branches)
  D02_factual_accuracy         — The answer contains a specific correct fact (fee, package, intake)
  D03_grounding_no_hallucination — The answer does NOT contain facts absent from the KB
  D04_citation_quality         — Every factual claim has a [Section, Page] citation
  D05_graceful_refusal         — Questions with NO answer in the KB get a proper refusal + contact
  D06_performance_latency      — Simple query answered within 10s, complex within 15s
  D07_conflict_handling        — Questions where the KB has conflicting data; both values shown + ⚠️ flag
  D08_ragas_metrics            — Representative factual questions for RAGAS scoring

RULES:
  - D05 questions must be genuinely unanswerable from the KB
    (e.g., "Does BVRIT offer an MBA?", "What is the campus WiFi speed?",
     "What is the placement percentage?" — this is NOT published on the website).
  - D07 questions must target known conflicts:
    * Hostel capacity (narrative says 150+ rooms / 500+ occupancy; highlights say 500+ rooms / 300+ occupancy)
    * Highest package (₹29.9L on About page vs. ₹54L for 2021-25 batch vs. ₹52L for 2020-24 batch)
    * NBA accreditation (About page lists IT; banner does not list IT)
    * IT intake (present in older fee tables; absent from current intake table)
  - D06: Include one simple question and one multi-section question, each with is_complex flag.
  - Each test case must include a clear, specific pass_criteria string.
  - requires_judge: true for all dimensions except D06 (which uses numeric SLA check).

Respond with ONLY a valid JSON array. No markdown, no explanation, no code fences.
"""

GENERATOR_USER_PROMPT = "Generate the {n} test cases now. Return only the JSON array."


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_test_cases(n: int = MIN_TEST_CASES) -> list[dict]:
    """
    Call the generator LLM and return a parsed list of test case dicts.
    Saves results to tests/test_cases.json.
    """
    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    print(f"[test_generator] Generating {n} test cases with {TEST_GENERATOR_MODEL}...")

    response = client.chat.completions.create(
        model=TEST_GENERATOR_MODEL,
        temperature=0.4,
        max_tokens=4096,
        messages=[
            {
                "role": "system",
                "content": GENERATOR_SYSTEM_PROMPT.format(n=n),
            },
            {
                "role": "user",
                "content": GENERATOR_USER_PROMPT.format(n=n),
            },
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Strip accidental markdown fences if the model adds them
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    test_cases: list[dict] = json.loads(raw)

    # Validate basic structure
    required_keys = {"id", "dimension", "question", "expected", "pass_criteria"}
    for tc in test_cases:
        missing = required_keys - set(tc.keys())
        if missing:
            raise ValueError(f"Test case {tc.get('id', '?')} missing keys: {missing}")

    # Ensure output dir exists
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    TEST_CASES_PATH.write_text(
        json.dumps(test_cases, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[test_generator] Saved {len(test_cases)} test cases → {TEST_CASES_PATH}")

    # Print dimension distribution
    from collections import Counter
    dist = Counter(tc["dimension"] for tc in test_cases)
    for dim, count in sorted(dist.items()):
        print(f"  {dim}: {count}")

    return test_cases


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

import re

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate BVRIT chatbot test cases")
    parser.add_argument("--n", type=int, default=MIN_TEST_CASES, help="Number of test cases")
    args = parser.parse_args()
    generate_test_cases(n=args.n)
