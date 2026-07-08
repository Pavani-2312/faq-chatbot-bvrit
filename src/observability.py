"""
observability.py
----------------
LLM call logging and session statistics for the BVRIT FAQ Chatbot.

Implements the observability requirements from HandsOn_Observability_Questions.docx:
  - Exercise 1: logged_llm_call() wrapper with 7 fields per call
  - Exercise 2: SessionStats for Streamlit sidebar metrics
  - Exercise 3: Threshold alerts (latency > 10s, cost > $0.10, error rate > 5%)

Seven fields logged per LLM call:
  1. timestamp    — ISO 8601 datetime
  2. model        — model name (e.g., openai/gpt-4o-mini)
  3. input_tokens  — from API response usage.prompt_tokens
  4. output_tokens — from API response usage.completion_tokens
  5. latency_sec   — wall-clock time for the API call
  6. cost_usd      — estimated cost based on model pricing
  7. status        — "success" | "error"

Storage:
  - In-memory: list of LogEntry dicts (cleared on app restart)
  - Persistent: JSON Lines file at logs/llm_calls.jsonl (appended per call)

Cost estimation uses approximate OpenRouter pricing for gpt-4o-mini.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Model pricing table (per 1M tokens, in USD)
# Source: OpenRouter approximate pricing, July 2026
# ---------------------------------------------------------------------------
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini":         {"input": 0.15, "output": 0.60},
    "openai/gpt-4o":       {"input": 5.00, "output": 15.00},
    "anthropic/claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    # Default fallback pricing
    "_default": {"input": 0.15, "output": 0.60},
}

# Alert thresholds (from Exercise 3)
LATENCY_ALERT_SEC = 10.0      # warn if single call > 10s
COST_ALERT_USD = 0.10         # warn if single query > $0.10
ERROR_RATE_ALERT = 0.05       # warn if last 20 calls have > 5% errors
ERROR_RATE_WINDOW = 20        # rolling window for error rate calculation

# Log file path
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOGS_DIR / "llm_calls.jsonl"


# ---------------------------------------------------------------------------
# Log entry schema
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    timestamp: str         # ISO 8601
    model: str
    input_tokens: int
    output_tokens: int
    latency_sec: float
    cost_usd: float
    status: str            # "success" | "error"
    error_message: str = ""
    query_preview: str = ""   # first 100 chars of user query (for debugging)
    tool_name: str = ""        # tool called (if any)

    def to_dict(self) -> dict:
        return asdict(self)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD based on model pricing per 1M tokens."""
    pricing = _MODEL_PRICING.get(model, _MODEL_PRICING["_default"])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Global in-memory log storage
# (In Streamlit this should be stored in st.session_state instead)
# ---------------------------------------------------------------------------
_call_log: list[LogEntry] = []


def get_call_log() -> list[LogEntry]:
    """Return the in-memory call log."""
    return _call_log


def clear_call_log() -> None:
    """Clear the in-memory call log (call on session start)."""
    _call_log.clear()


def _append_to_file(entry: LogEntry) -> None:
    """Append a log entry to the JSONL file."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass  # Don't let logging failure break the chatbot


# ---------------------------------------------------------------------------
# Core logging function
# ---------------------------------------------------------------------------

def log_llm_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_sec: float,
    status: str = "success",
    error_message: str = "",
    query_preview: str = "",
    tool_name: str = "",
) -> LogEntry:
    """
    Record a single LLM call with all 7 required fields.

    This is the core logging function. Use logged_llm_call() as a
    higher-level wrapper that handles the API call automatically.
    """
    entry = LogEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_sec=round(latency_sec, 3),
        cost_usd=_estimate_cost(model, input_tokens, output_tokens),
        status=status,
        error_message=error_message,
        query_preview=query_preview[:100],
        tool_name=tool_name,
    )
    _call_log.append(entry)
    _append_to_file(entry)
    return entry


def logged_llm_call(
    client,
    model: str,
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    tools: Optional[list] = None,
    tool_choice: str = "auto",
    query_preview: str = "",
    tool_name: str = "",
) -> Any:
    """
    Wrapper around OpenAI client.chat.completions.create() that logs the call.

    Drop-in replacement for direct API calls.

    Args:
        client:         OpenAI client instance
        model:          Model name
        messages:       Message list for the API call
        max_tokens:     Max tokens for response
        temperature:    Sampling temperature
        tools:          Tool definitions (optional)
        tool_choice:    Tool choice strategy
        query_preview:  First N chars of user query (for log context)
        tool_name:      Name of tool if this is a tool-result call

    Returns:
        The API response object.

    Raises:
        Exception if the API call fails (after logging the error).
    """
    t0 = time.perf_counter()

    try:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        completion = client.chat.completions.create(**kwargs)
        elapsed = time.perf_counter() - t0

        usage = completion.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        log_llm_call(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_sec=elapsed,
            status="success",
            query_preview=query_preview,
            tool_name=tool_name,
        )

        return completion

    except Exception as exc:
        elapsed = time.perf_counter() - t0
        log_llm_call(
            model=model,
            input_tokens=0,
            output_tokens=0,
            latency_sec=elapsed,
            status="error",
            error_message=str(exc),
            query_preview=query_preview,
            tool_name=tool_name,
        )
        raise  # re-raise so caller handles the error


# ---------------------------------------------------------------------------
# Session stats computation
# ---------------------------------------------------------------------------

@dataclass
class SessionStats:
    """Aggregated statistics for the current session."""
    total_queries: int = 0
    avg_latency_sec: float = 0.0
    p95_latency_sec: float = 0.0
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    error_count: int = 0
    error_rate: float = 0.0    # rolling last 20 calls
    last_latency_sec: float = 0.0
    last_cost_usd: float = 0.0


def compute_session_stats(log: list[LogEntry] | None = None) -> SessionStats:
    """
    Compute session statistics from the call log.

    Args:
        log: Optional explicit log list (uses global log if None).

    Returns:
        SessionStats dataclass.
    """
    if log is None:
        log = _call_log

    if not log:
        return SessionStats()

    stats = SessionStats()
    stats.total_queries = len(log)

    latencies = [e.latency_sec for e in log]
    costs = [e.cost_usd for e in log]
    errors = [e for e in log if e.status == "error"]

    stats.avg_latency_sec = round(sum(latencies) / len(latencies), 3)
    stats.p95_latency_sec = round(float(np.percentile(latencies, 95)), 3)
    stats.total_cost_usd = round(sum(costs), 6)
    stats.total_input_tokens = sum(e.input_tokens for e in log)
    stats.total_output_tokens = sum(e.output_tokens for e in log)
    stats.total_tokens = stats.total_input_tokens + stats.total_output_tokens
    stats.error_count = len(errors)

    # Rolling error rate (last N calls)
    window = log[-ERROR_RATE_WINDOW:]
    window_errors = sum(1 for e in window if e.status == "error")
    stats.error_rate = round(window_errors / len(window), 3) if window else 0.0

    if log:
        stats.last_latency_sec = log[-1].latency_sec
        stats.last_cost_usd = log[-1].cost_usd

    return stats


# ---------------------------------------------------------------------------
# Alert checking
# ---------------------------------------------------------------------------

@dataclass
class AlertStatus:
    latency_alert: bool = False
    cost_alert: bool = False
    error_rate_alert: bool = False
    latency_message: str = ""
    cost_message: str = ""
    error_rate_message: str = ""


def check_alerts(stats: SessionStats, last_entry: Optional[LogEntry] = None) -> AlertStatus:
    """
    Check if any threshold has been breached.

    Args:
        stats:       Current session statistics.
        last_entry:  Most recent log entry (for per-query alerts).

    Returns:
        AlertStatus with flags and messages.
    """
    alert = AlertStatus()

    # Latency alert — based on last query
    if last_entry and last_entry.latency_sec > LATENCY_ALERT_SEC:
        alert.latency_alert = True
        alert.latency_message = (
            f"⚠️ Slow response: {last_entry.latency_sec:.1f}s "
            f"(threshold: {LATENCY_ALERT_SEC}s). "
            "Consider reducing top-k or switching to a faster model."
        )

    # Cost alert — based on last query
    if last_entry and last_entry.cost_usd > COST_ALERT_USD:
        alert.cost_alert = True
        alert.cost_message = (
            f"⚠️ Expensive query: ${last_entry.cost_usd:.4f} "
            f"(threshold: ${COST_ALERT_USD}). "
            "Query may have used many tokens."
        )

    # Error rate alert — rolling window
    if stats.error_rate > ERROR_RATE_ALERT:
        alert.error_rate_alert = True
        alert.error_rate_message = (
            f"🚨 High error rate: {stats.error_rate * 100:.1f}% "
            f"(threshold: {ERROR_RATE_ALERT * 100:.1f}% over last {ERROR_RATE_WINDOW} calls). "
            "Check API key validity and model availability."
        )

    return alert


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Simulate some log entries
    log_llm_call("openai/gpt-4o-mini", 500, 200, 2.3, "success", query_preview="What is the CSE fee?")
    log_llm_call("openai/gpt-4o-mini", 800, 350, 4.1, "success", query_preview="List all departments")
    log_llm_call("openai/gpt-4o-mini", 300, 0, 0.1, "error", error_message="Rate limit", query_preview="test")
    log_llm_call("openai/gpt-4o-mini", 600, 250, 11.2, "success", query_preview="Complex query")

    stats = compute_session_stats()
    print("Session Stats:")
    print(f"  Total queries: {stats.total_queries}")
    print(f"  Avg latency: {stats.avg_latency_sec}s")
    print(f"  P95 latency: {stats.p95_latency_sec}s")
    print(f"  Total cost: ${stats.total_cost_usd}")
    print(f"  Total tokens: {stats.total_tokens}")
    print(f"  Error count: {stats.error_count}")
    print(f"  Error rate: {stats.error_rate}")

    alerts = check_alerts(stats, last_entry=_call_log[-1])
    if alerts.latency_alert:
        print(alerts.latency_message)
    if alerts.error_rate_alert:
        print(alerts.error_rate_message)
