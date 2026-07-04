"""
config.py
---------
Central configuration for the BVRIT FAQ Chatbot.
All tunable parameters live here — nothing is hardcoded across other modules.

API setup:
  - LLM calls (chatbot, judge, test generator) → OpenRouter (one key needed)
  - Embeddings → local sentence-transformers (no API key needed)
  - RAGAS evaluation → OpenAI API key required
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

# Knowledge base source — folder of .md files ingested by ingest.py
KB_MD_DIR = ROOT_DIR / "kb_formatted"

# Legacy docx path (kept for reference — not used by current ingest.py)
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
# Rationale: 800 chars (~150-200 words) keeps one sub-topic per chunk without
# splitting facts; 120-char overlap prevents losing context at boundaries.
# ---------------------------------------------------------------------------
CHUNK_SIZE = 800           # target characters per chunk
CHUNK_OVERLAP = 120        # ~15% overlap to preserve cross-boundary context
CHUNK_SIZE_TOKENS = 200    # approximate token count (1 token ≈ 4 chars)
CHUNK_OVERLAP_TOKENS = 30

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
TOP_K = 5                  # default number of chunks returned per query
TOP_K_MAX = 10             # upper bound for sidebar slider

# ---------------------------------------------------------------------------
# Generation — all LLM calls go through OpenRouter
# ---------------------------------------------------------------------------
GENERATION_MODEL = "openai/gpt-4o-mini"              # chatbot (fast, low-cost)
GENERATION_TEMPERATURE = 0.2
GENERATION_MAX_TOKENS = 1024

# ---------------------------------------------------------------------------
# Evaluation LLMs (also via OpenRouter)
# Using different model families avoids self-evaluation bias (per brief §5)
# ---------------------------------------------------------------------------
TEST_GENERATOR_MODEL = "openai/gpt-4o-mini"   # cheap, sufficient for test generation
JUDGE_MODEL = "openai/gpt-4o-mini"           # cheap judge model
JUDGE_TEMPERATURE = 0.0

MIN_TEST_CASES = 20

# ---------------------------------------------------------------------------
# Evaluation dimensions — aligned to build brief §3 (Phase 5)
# ---------------------------------------------------------------------------
EVAL_DIMENSIONS = [
    "01-Functional",
    "02-Quality",
    "03-Safety",
    "04-Security",
    "05-Robustness",
    "06-Performance",
    "07-Context",
    "08-RAGAS",
]

# Cases per dimension (used by test_generator)
CASES_PER_DIMENSION = {
    "01-Functional":  3,
    "02-Quality":     3,
    "03-Safety":      2,
    "04-Security":    2,
    "05-Robustness":  3,
    "06-Performance": 2,
    "07-Context":     2,
    "08-RAGAS":       3,
}

# Performance SLAs (seconds) for 06-Performance
SLA_SIMPLE_QUERY_SEC = 10.0
SLA_COMPLEX_QUERY_SEC = 15.0

# RAGAS target thresholds for 08-RAGAS
RAGAS_FAITHFULNESS_TARGET = 0.85
RAGAS_ANSWER_RELEVANCY_TARGET = 0.80
RAGAS_CONTEXT_PRECISION_TARGET = 0.75
RAGAS_CONTEXT_RECALL_TARGET = 0.75

# ---------------------------------------------------------------------------
# API keys — read from .env, never hardcoded
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")        # used by RAGAS
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")  # optional direct Anthropic

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
    "show me your prompt",
    "you are now",
    "forget you are",
    "act as",
    "disregard",
    "bypass",
    "dump the document",
    "list all documents",
    "what are your instructions",
    "override your",
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
