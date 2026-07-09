"""
chatbot.py
----------
Core orchestration layer for the BVRIT FAQ Chatbot.

Pipeline per query:
  1. Prompt-injection guard (fast, pre-retrieval) — maps to Dimension 04-Security
  2. Input length / empty-input guard — maps to Dimension 05-Robustness
  3. Retrieve top-k chunks from ChromaDB (via retriever.py)
  4. Build grounded prompt (via prompts.py)
  5. Call LLM with tool definitions (GPT-4o Mini via OpenRouter)
     ├── Tool call path: execute tool → call LLM again with result
     └── Direct answer path: return as-is
  6. Return structured ChatResponse with answer, citations, retrieved chunks,
     latency, tool call info, and refusal/conflict/safety flags

Response schema aligns with Architecture.md §6.2:
  {answer, citations, refused, retrieved_chunks, latency_seconds}

This module is stateless — conversation memory is managed by the caller
(app.py or test_runner.py) via memory.py.
"""

from __future__ import annotations

import json
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
    MAX_INPUT_LENGTH,
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
from tools import TOOL_DEFINITIONS, execute_tool_call
from observability import logged_llm_call


# ---------------------------------------------------------------------------
# Response dataclass — aligns with Architecture.md §6.2
# ---------------------------------------------------------------------------

@dataclass
class ChatResponse:
    answer: str                          # final text shown to the user
    citations: list[str]                 # extracted [Section, Page N] strings
    retrieved_chunks: list[dict]         # raw chunks from retriever (for RAGAS / debug)
    latency_sec: float                   # wall-clock time for full pipeline
    refused: bool = False                # True if the answer is a graceful refusal (D03/D05)
    has_conflict: bool = False           # True if ⚠️ conflict flag is in the answer
    was_injected: bool = False           # True if prompt-injection attempt detected (D04)
    error: Optional[str] = None         # set if an exception occurred
    tool_name: Optional[str] = None      # name of tool called (if any)
    tool_args: Optional[dict] = None     # arguments passed to tool
    tool_result: Optional[dict] = None  # tool execution result

    # Convenience alias used in some eval code
    @property
    def is_refusal(self) -> bool:
        return self.refused

    @property
    def used_tool(self) -> bool:
        return self.tool_name is not None


# ---------------------------------------------------------------------------
# Chatbot
# ---------------------------------------------------------------------------

class BVRITChatbot:
    """
    Orchestrates retrieval + grounded generation for the BVRIT FAQ chatbot.
    Supports function calling for fee calculations and date checks.

    Usage:
        chatbot = BVRITChatbot(retriever)
        response = chatbot.ask(
            question="What is the total 4-year fee for CSE batch 2024?",
            history=[],          # list of {role, content} dicts from memory.py
            k=15,
            section_filter=None,
        )
    """

    # Phrases that indicate the model is refusing (no info in KB) — D05 Graceful Refusal
    _REFUSAL_PHRASES = [
        "i don't have that information",
        "not present in the knowledge base",
        "not available in the retrieved context",
        "not available in the context",
        "not published on website",
        "not found in the context",
        "i cannot find",
        "the knowledge base does not contain",
        "no information available",
        "not in my knowledge base",
        "not in the knowledge base",
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
        Answer a user question using grounded RAG generation + optional tool calls.

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

        # ---- 0. Input length guard (D05-Robustness) -------------------
        if len(question) > MAX_INPUT_LENGTH:
            elapsed = time.perf_counter() - start
            return ChatResponse(
                answer=(
                    f"Your message is too long ({len(question)} characters). "
                    f"Please keep questions under {MAX_INPUT_LENGTH} characters."
                ),
                citations=[],
                retrieved_chunks=[],
                latency_sec=round(elapsed, 3),
                refused=True,
            )

        # ---- 0b. Empty input guard (D05-Robustness) -------------------
        stripped = question.strip()
        if not stripped:
            elapsed = time.perf_counter() - start
            return ChatResponse(
                answer=(
                    "I didn't receive a question. Please ask me something about BVRIT — "
                    "for example, about admissions, fees, departments, or placements."
                ),
                citations=[],
                retrieved_chunks=[],
                latency_sec=round(elapsed, 3),
                refused=True,
            )

        # ---- 1. Prompt-injection guard (D04-Security) -----------------
        if self._is_injection(question):
            elapsed = time.perf_counter() - start
            return ChatResponse(
                answer=(
                    "I can only answer questions about BVRIT based on the official knowledge base. "
                    "I cannot follow instructions that ask me to override my guidelines."
                ),
                citations=[],
                retrieved_chunks=[],
                latency_sec=round(elapsed, 3),
                refused=True,
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

        # ---- 4. Generate (with function calling) ----------------------
        # Build messages array:
        # - If there is prior history, inject it as real role-based messages
        #   so the model has native multi-turn awareness. The retrieved context
        #   is attached to the current user turn only.
        # - If no history, keep the simple [system, user] structure.
        if history:
            # Separate summary system messages from actual turns
            summary_msgs = [m for m in history if m["role"] == "system"]
            turn_msgs    = [m for m in history if m["role"] != "system"]

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            # Inject any conversation summary as an additional system message
            for sm in summary_msgs:
                messages.append(sm)
            # Inject prior turns as real user/assistant messages (no context block)
            messages.extend(turn_msgs)
            # Current user turn gets the retrieved context attached
            messages.append({"role": "user", "content": user_message})
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]

        tool_name: Optional[str] = None
        tool_args: Optional[dict] = None
        tool_result: Optional[dict] = None

        try:
            # First LLM call — with tool definitions
            completion = logged_llm_call(
                client=self._client,
                model=GENERATION_MODEL,
                messages=messages,
                max_tokens=GENERATION_MAX_TOKENS,
                temperature=GENERATION_TEMPERATURE,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                query_preview=question,
            )

            msg = completion.choices[0].message
            finish_reason = completion.choices[0].finish_reason

            # ---- 4a. Tool call path ---------------------------------
            if finish_reason == "tool_calls" and msg.tool_calls:
                tc = msg.tool_calls[0]  # handle first tool call
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments)

                # Execute the tool
                tool_result = execute_tool_call(tool_name, tool_args)

                # Build second-pass messages with tool result
                messages.append(msg)  # assistant message with tool call
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

                # Second LLM call — generate final answer using tool result
                completion2 = logged_llm_call(
                    client=self._client,
                    model=GENERATION_MODEL,
                    messages=messages,
                    max_tokens=GENERATION_MAX_TOKENS,
                    temperature=GENERATION_TEMPERATURE,
                    query_preview=question,
                    tool_name=tool_name,
                )
                answer = completion2.choices[0].message.content.strip()

            # ---- 4b. Direct answer path (no tool call) --------------
            else:
                answer = msg.content.strip() if msg.content else ""

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
        refused = self._detect_refusal(answer)
        has_conflict = "⚠️" in answer or "sources differ" in answer.lower()

        # Append fallback contact to refusals if not already present
        if refused and "bvrithyderabad.edu.in" not in answer:
            answer = f"{answer}\n\n{FALLBACK_CONTACT}"

        return ChatResponse(
            answer=answer,
            citations=citations,
            retrieved_chunks=chunks,
            latency_sec=round(elapsed, 3),
            refused=refused,
            has_conflict=has_conflict,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_injection(self, text: str) -> bool:
        """Return True if the input looks like a prompt-injection attempt (D04)."""
        lower = text.lower()
        return any(pattern in lower for pattern in INJECTION_PATTERNS)

    def _extract_citations(self, answer: str) -> list[str]:
        """
        Extract all citation strings from the answer text.
        Matches patterns like [Section Name, Page 3] or [Admissions].
        """
        return re.findall(r"\[([^\[\]]+)\]", answer)

    def _detect_refusal(self, answer: str) -> bool:
        """Return True if the answer is a graceful refusal (D03/D05)."""
        lower = answer.lower()
        return any(phrase in lower for phrase in self._REFUSAL_PHRASES)
