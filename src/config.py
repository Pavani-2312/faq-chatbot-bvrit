"""
config.py
---------
Central configuration for the BVRIT FAQ Chatbot.
All tunable parameters live here — nothing is hardcoded across other modules.

API setup:
  - LLM calls (chatbot, judge, test generator) → OpenRouter (one key needed)
  - Embeddings → local sentence-transformers (no API key needed)
  - Vector DB → ChromaDB (local persistent, no server needed)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level up from src/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CHROMA_DIR = ROOT_DIR / "chroma_db"
TESTS_DIR = ROOT_DIR / "tests"

# Knowledge base source (docx ingested offline by ingest.py)
KB_DOCX_PATH = DATA_DIR / "bvrit_knowledge_base.docx"

# Evaluation outputs
TEST_CASES_PATH = TESTS_DIR / "test_cases.json"
TEST_RESULTS_PATH = TESTS_DIR / "test_results.json"
EVAL_REPORT_PATH = TESTS_DIR / "evaluation_report.json"

# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------
CHROMA_COLLECTION_NAME = "bvrit_knowledge_base"

# ---------------------------------------------------------------------------
# Embeddings — local sentence-transformers (no API key required)
# ChromaDB uses this model directly via its built-in embedding function.
# Must be identical at ingest time and query time.
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # local, ~80MB download on first run
EMBEDDING_PROVIDER = "local"

# ---------------------------------------------------------------------------
# Chunking (used by ingest.py — kept here for reference / UI display)
# ---------------------------------------------------------------------------
CHUNK_SIZE = 600           # target tokens per chunk
CHUNK_OVERLAP = 90         # ~15% overlap
CHUNK_SIZE_CHARS = 2400    # approximate character count (1 token ≈ 4 chars)
CHUNK_OVERLAP_CHARS = 360

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
TOP_K = 5                  # default number of chunks returned per query
TOP_K_MAX = 10             # upper bound for sidebar slider

# ---------------------------------------------------------------------------
# Generation — all LLM calls go through OpenRouter
# ---------------------------------------------------------------------------
GENERATION_MODEL = "openai/gpt-4o-mini"              # chatbot (fast, low-cost)
GENERATION_TEMPERATURE = 0.1
GENERATION_MAX_TOKENS = 1024

# ---------------------------------------------------------------------------
# Evaluation LLMs (also via OpenRouter)
# ---------------------------------------------------------------------------
TEST_GENERATOR_MODEL = "anthropic/claude-3-5-sonnet"  # strong model for test generation
JUDGE_MODEL = "openai/gpt-4o"                          # different from generation model
JUDGE_TEMPERATURE = 0.0

MIN_TEST_CASES = 20

# ---------------------------------------------------------------------------
# Evaluation dimensions
# ---------------------------------------------------------------------------
EVAL_DIMENSIONS = [
    "D01_functional_completeness",
    "D02_factual_accuracy",
    "D03_grounding_no_hallucination",
    "D04_citation_quality",
    "D05_graceful_refusal",
    "D06_performance_latency",
    "D07_conflict_handling",
    "D08_ragas_metrics",
]

# Performance SLAs (seconds) for D06
SLA_SIMPLE_QUERY_SEC = 10.0
SLA_COMPLEX_QUERY_SEC = 15.0

# RAGAS target thresholds
RAGAS_FAITHFULNESS_TARGET = 0.85
RAGAS_ANSWER_RELEVANCY_TARGET = 0.80
RAGAS_CONTEXT_PRECISION_TARGET = 0.75
RAGAS_CONTEXT_RECALL_TARGET = 0.75

# ---------------------------------------------------------------------------
# API keys — read from .env, never hardcoded
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# OpenRouter base URL (OpenAI-compatible API)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ---------------------------------------------------------------------------
# Prompt-injection guard strings (checked pre-retrieval in chatbot.py)
# ---------------------------------------------------------------------------
INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all instructions",
    "reveal your system prompt",
    "print your prompt",
    "you are now",
    "forget you are",
    "act as",
    "disregard",
    "bypass",
    "dump the document",
]

# ---------------------------------------------------------------------------
# UI constants
# ---------------------------------------------------------------------------
APP_TITLE = "BVRIT College FAQ Chatbot"
APP_ICON = "🎓"
REFUSED_BADGE = "⛔ REFUSED"
CONFLICT_BADGE = "⚠️ CONFLICT"
CITATION_COLOR = "#2563eb"

# Fallback contact shown in every refusal message (FR-3.3)
FALLBACK_CONTACT = (
    "For more information, please contact BVRIT directly:\n"
    "📞 +91 40 4241 7773\n"
    "📧 info@bvrithyderabad.edu.in\n"
    "🌐 https://bvrithyderabad.edu.in"
)
