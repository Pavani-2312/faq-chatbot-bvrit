"""
chatbot.py
----------
Core orchestration layer for the BVRIT FAQ Chatbot.

Pipeline per query:
  1. Prompt-injection guard (fast, pre-retrieval)
  2. Retrieve top-k chunks from ChromaDB (via retriever.py)
  3. Build grounded prompt (via prompts.py)
  4. Call LLM (GPT-4o Mini via OpenRouter)
  5. Return structured ChatResponse with answer, citations, retrieved chunks,
     latency, and refusal/conflict flags

This module is stateless — conversation memory is managed by the caller
(app.py or test_runner.py) via memory.py.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

from config import (
    FALLBACK_CONTACT,
    GENERATION_MAX_TOKENS,
    GENERATION_MODEL,
    GENERATION_TEMPERATURE,
    INJECTION_PATTERNS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    TOP_K,
)

if not OPENROUTER_API_KEY:
    raise EnvironmentError(
        "OPENROUTER_API_KEY is not set. "
        "Add it to your .env file: OPENROUTER_API_KEY=sk-or-v1-..."
    )
from prompts import SYSTEM_PROMPT, build_user_message
from retriever import Retriever


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChatResponse:
    answer: str                          # final text shown to the user
    citations: list[str]                 # extracted [Section, Page N] strings
    retrieved_chunks: list[dict]         # raw chunks from retriever (for RAGAS / debug)
    latency_sec: float                   # wall-clock time for full pipeline
    is_refusal: bool = False             # True if the answer is a graceful refusal
    has_conflict: bool = False           # True if ⚠️ conflict flag is in the answer
    was_injected: bool = False           # True if prompt-injection attempt detected
    error: Optional[str] = None         # set if an exception occurred


# ---------------------------------------------------------------------------
# Chatbot
# ---------------------------------------------------------------------------

class BVRITChatbot:
    """
    Orchestrates retrieval + grounded generation for the BVRIT FAQ chatbot.

    Usage:
        chatbot = BVRITChatbot(retriever)
        response = chatbot.ask(
            question="What is the CSE placement percentage?",
            history=[],          # list of {role, content} dicts from memory.py
            k=5,
            section_filter=None,
        )
    """

    # Phrases that indicate the model is refusing (no info in KB)
    _REFUSAL_PHRASES = [
        "i don't have that information",
        "not present in the knowledge base",
        "not available in the retrieved context",
        "not published on website",
        "not found in the context",
        "i cannot find",
        "the knowledge base does not contain",
        "no information available",
    ]

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever
        self._client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        history: list[dict] | None = None,
        k: int = TOP_K,
        section_filter: str | None = None,
    ) -> ChatResponse:
        """
        Answer a user question using grounded RAG generation.

        Args:
            question:       The user's natural-language question.
            history:        Prior conversation turns [{role, content}, ...].
                            Pass memory.get_history(exclude_last_user=True).
            k:              Number of chunks to retrieve.
            section_filter: Optional section name to restrict retrieval.

        Returns:
            ChatResponse with answer, citations, chunks, latency, flags.
        """
        history = history or []
        start = time.perf_counter()

        # ---- 1. Prompt-injection guard --------------------------------
        if self._is_injection(question):
            elapsed = time.perf_counter() - start
            answer = (
                "I can only answer questions about BVRIT based on the official knowledge base. "
                "I cannot follow instructions that ask me to override my guidelines."
            )
            return ChatResponse(
                answer=answer,
                citations=[],
                retrieved_chunks=[],
                latency_sec=round(elapsed, 3),
                is_refusal=True,
                was_injected=True,
            )

        # ---- 2. Retrieve ----------------------------------------------
        try:
            chunks = self._retriever.retrieve(
                query=question, k=k, section_filter=section_filter
            )
        except Exception as exc:
            elapsed = time.perf_counter() - start
            return ChatResponse(
                answer=f"Retrieval error: {exc}",
                citations=[],
                retrieved_chunks=[],
                latency_sec=round(elapsed, 3),
                error=str(exc),
            )

        # ---- 3. Build prompt ------------------------------------------
        user_message = build_user_message(
            chunks=chunks,
            history=history,
            question=question,
        )

        # ---- 4. Generate ----------------------------------------------
        try:
            completion = self._client.chat.completions.create(
                model=GENERATION_MODEL,
                temperature=GENERATION_TEMPERATURE,
                max_tokens=GENERATION_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            answer = completion.choices[0].message.content.strip()
        except Exception as exc:
            elapsed = time.perf_counter() - start
            return ChatResponse(
                answer=f"Generation error: {exc}",
                citations=[],
                retrieved_chunks=chunks,
                latency_sec=round(elapsed, 3),
                error=str(exc),
            )

        elapsed = time.perf_counter() - start

        # ---- 5. Post-process ------------------------------------------
        citations = self._extract_citations(answer)
        is_refusal = self._detect_refusal(answer)
        has_conflict = "⚠️" in answer or "conflicting information" in answer.lower()

        # Append fallback contact to refusals if not already present
        if is_refusal and "bvrithyderabad.edu.in" not in answer:
            answer = f"{answer}\n\n{FALLBACK_CONTACT}"

        return ChatResponse(
            answer=answer,
            citations=citations,
            retrieved_chunks=chunks,
            latency_sec=round(elapsed, 3),
            is_refusal=is_refusal,
            has_conflict=has_conflict,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_injection(self, text: str) -> bool:
        """Return True if the input looks like a prompt-injection attempt."""
        lower = text.lower()
        return any(pattern in lower for pattern in INJECTION_PATTERNS)

    def _extract_citations(self, answer: str) -> list[str]:
        """
        Extract all citation strings from the answer text.
        Matches patterns like [Section Name, Page 3] or [Admissions].
        """
        return re.findall(r"\[([^\[\]]+)\]", answer)

    def _detect_refusal(self, answer: str) -> bool:
        """Return True if the answer is a graceful refusal."""
        lower = answer.lower()
        return any(phrase in lower for phrase in self._REFUSAL_PHRASES)
