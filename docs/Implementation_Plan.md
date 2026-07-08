# BVRIT FAQ Chatbot — Implementation Plan
**Author:** Kiro AI  
**Date:** 2026-07-08  
**Status:** In Progress

---

## Context

The BVRIT FAQ Chatbot is a RAG-based Streamlit application that answers questions about BVRIT HYDERABAD College of Engineering for Women. The core pipeline (ingest → retrieve → generate → UI) is working. The evaluation suite runs but passes only 5/20 test cases (25%).

This plan covers all remaining work to bring the chatbot to production quality, guided by:
- `references/CollegeFAQ_Chatbot_Build_Brief (3).docx` — core evaluation requirements
- `references/HandsOn_FunctionCalling_Questions (1).docx` — tool calling exercises
- `references/HandsOn_Observability_Questions.docx` — observability exercises
- `references/HandsOn_Memory_Questions.docx` — memory improvement exercises
- `references/HandsOn_Governance_Questions (1).docx` — governance context

---

## Current State

| Component | Status |
|-----------|--------|
| `src/ingest.py` | ✅ Working — 490 chunks in ChromaDB |
| `src/retriever.py` | ✅ Working — local sentence-transformers |
| `src/chatbot.py` | ✅ Working — RAG generation via OpenRouter |
| `src/prompts.py` | ✅ Working — 7-clause grounding prompt |
| `src/memory.py` | ✅ Basic — MAX_HISTORY_TURNS=10, no summarisation |
| `src/eval/test_generator.py` | ✅ Working |
| `src/eval/test_runner.py` | ✅ Working |
| `src/eval/judge.py` | ✅ Working |
| `src/eval/ragas_eval.py` | ✅ Working |
| `src/eval/report.py` | ✅ Working |
| `app.py` | ✅ Basic UI — no observability, no tool display |
| Evaluation pass rate | ❌ 25% (5/20) |
| Function calling tools | ❌ Not implemented |
| Observability | ❌ Not implemented |
| Memory summarisation | ❌ Not implemented |

---

## Task 1 — Fix Evaluation Pipeline

**Goal:** Bring pass rate from 25% to ≥ 70%.

### Root cause analysis of low pass rate (from tests/evaluation_report.json)

The current test cases are poorly formed — many fail because:
1. Test generator uses wrong expected answers (not grounded in actual KB content)  
2. Judge criteria are too strict for the available KB data  
3. Some dimensions (D04-Security, D03-Safety) were likely passing in previous run

### Fix Strategy

1. **Regenerate test cases** with a fresh call to `test_generator.py`. The generator system prompt already has good instructions — we need fresh cases that match actual KB content.

2. **Fix D02-Quality**: Expected answers must match what's in `kb_formatted/` files. Key facts:
   - CSE: 360 seats, intake varies by batch
   - Fees: from `kb_formatted/admission_fee_details.md`
   - Placements: from `kb_formatted/placements_placement_details.md`

3. **Fix D04-Security**: The injection guard in `chatbot.py` is pre-retrieval. Test cases must trigger the guard AND the judge must recognise that `was_injected=True` means the chatbot blocked it correctly.

4. **Fix D06-Performance**: SLA check is numeric — latency ≤ 10s for simple, ≤ 15s for complex. Current response time is ~6.7s (OK for simple). Complex queries may be slower.

5. **Fix D05-Robustness**: Add input length validation in `chatbot.py` (>2000 chars → reject).

### Files to modify
- `src/eval/test_generator.py` — no changes needed, just re-run
- `src/chatbot.py` — add input length validation
- `src/config.py` — add `MAX_INPUT_LENGTH = 2000`

---

## Task 2 — Function Calling Tools

**Goal:** Implement `fee_calculator` and `date_checker` tools wired into the chatbot.

### Tool Definitions

#### `fee_calculator`
Handles queries requiring fee computation across years, branches, or scholarship combinations that pure RAG cannot compute reliably.

```json
{
  "name": "fee_calculator",
  "description": "Calculate total fees for a BVRIT student given branch, batch year, scholarship percentage, and number of years. Use this when the user asks for total cost, fee with scholarship, or multi-year fee calculations that require arithmetic beyond what the document states directly.",
  "parameters": {
    "branch": "string — one of: CSE, ECE, EEE, IT, CSE-AIML (required)",
    "batch_year": "integer — admission year e.g. 2023 (required)",
    "years": "integer — number of years to calculate for, 1-4 (optional, default 4)",
    "scholarship_percent": "number — scholarship discount percentage 0-100 (optional, default 0)",
    "include_hostel": "boolean — include hostel fees (optional, default false)"
  }
}
```

#### `date_checker`
Handles deadline/date comparison queries. Students ask "has the admission deadline passed?" or "how many days until classes start?".

```json
{
  "name": "date_checker",
  "description": "Check whether a specific BVRIT deadline, event, or academic date has passed relative to today's date. Use this when a student asks whether they can still apply, how many days until an event, or if a deadline has passed. Do NOT use this for general date questions unrelated to BVRIT.",
  "parameters": {
    "event_name": "string — name of the event or deadline (required)",
    "event_date": "string — ISO date YYYY-MM-DD (required)",
    "query_type": "string — one of: 'has_passed', 'days_until', 'days_since' (required)"
  }
}
```

### Integration Architecture

The tool-calling flow replaces the current single-step generation:

```
User query
  ↓
Injection guard (existing)
  ↓
Retrieve chunks (existing)
  ↓
Build prompt WITH tool definitions
  ↓
LLM call #1 — model decides: tool call OR direct answer
  ├── Tool call → execute function → inject result
  │       ↓
  │   LLM call #2 — generate final answer using tool result + context
  └── Direct answer → existing flow
```

### Files to create/modify
- `src/tools.py` — NEW: tool definitions + implementations
- `src/chatbot.py` — add `_call_with_tools()` method, update `ask()`
- `src/config.py` — add fee data constants (branch fees by year)
- `src/prompts.py` — no changes needed (tools are injected at API call time)

---

## Task 3 — Observability

**Goal:** Log every LLM call with 7 fields; display session stats in Streamlit sidebar.

### logged_llm_call() wrapper

Log fields per call:
1. `timestamp` — ISO datetime
2. `model` — model name (gpt-4o-mini, etc.)
3. `input_tokens` — from API response usage
4. `output_tokens` — from API response usage
5. `latency_sec` — wall clock
6. `cost_usd` — estimated from token counts × model pricing
7. `status` — "success" | "error"

Storage: in-memory list for session + append to `logs/llm_calls.jsonl`

### Session Stats Panel (Streamlit sidebar)

Metrics to display (using `st.metric()` with delta):
- Total queries this session
- Average latency (s)
- P95 latency (s) — needs numpy percentile
- Total cost (USD)
- Total tokens (input + output)
- Error count

### Alert thresholds
- Latency > 10s → `st.warning("⚠️ Response was slow (>10s)")`
- Cost per query > $0.10 → `st.warning("⚠️ Query was expensive")`
- Error rate > 5% (rolling last 20) → `st.error("🚨 High error rate")`

### Input length validator
- Max 2000 characters
- Reject with friendly message, log attempt

### Files to create/modify
- `src/observability.py` — NEW: `LLMCallLogger` class with `logged_llm_call()`
- `src/chatbot.py` — replace raw `client.chat.completions.create()` with wrapper
- `app.py` — add Session Stats panel to sidebar
- `logs/` — new directory for JSONL logs

---

## Task 4 — Memory Improvements

**Goal:** Implement summarisation after every 10 turns to prevent context window overflow.

### Summarisation Strategy

After every 10 user-assistant turn pairs:
1. Take the oldest 10 turns (20 messages)
2. Call LLM to summarise them into a concise paragraph (~100 words)
3. Replace those 20 messages with a single system message: `[SUMMARY: ...]`
4. Keep the most recent 10 turns verbatim

This keeps token usage bounded while preserving conversational context.

### Implementation in memory.py

```python
class ConversationMemory:
    def maybe_summarise(self, llm_client, model) -> bool:
        """Called after each turn. Returns True if summarisation was performed."""
        if self.turn_count > 0 and self.turn_count % 10 == 0:
            # summarise oldest turns
            ...
```

The summarisation is triggered in `app.py` after each response is added.

### Files to modify
- `src/memory.py` — add `summarise_older_turns()` and `maybe_summarise()` methods
- `app.py` — call `memory.maybe_summarise()` after each turn

---

## Task 5 — app.py Updates

**Goal:** Wire all new features into the Streamlit UI.

### Sidebar additions
- **Session Stats panel**: metrics with delta indicators
- **Observability toggle**: enable/disable detailed logging
- **Memory status**: current turn count, whether summarisation is active

### Chat area additions
- **Tool call display**: when a tool was called, show `🔧 Tool used: fee_calculator(branch=CSE, years=4) → ₹4,80,000` in an expandable section
- **Threshold alerts**: inline warnings after slow/expensive queries

### Dashboard tab
- Already implemented in existing `app.py`
- Add RAGAS score bars (currently referenced but may not display if no scores file)

---

## Task 6 — Full Evaluation Re-Run

**Goal:** Demonstrate improved pass rate ≥ 70%.

### Pipeline

```bash
# 1. Generate fresh test cases
python src/eval/test_generator.py --n 20

# 2. Run all test cases through chatbot
python src/eval/test_runner.py

# 3. LLM-as-judge scoring
python src/eval/judge.py

# 4. RAGAS metrics (needs OPENAI_API_KEY - optional)
# python src/eval/ragas_eval.py

# 5. Compile report
python src/eval/report.py
```

### Expected improvements after fixes
- D04-Security: should pass all 2 cases (injection guard is working)
- D03-Safety: should pass both cases (refusal logic is correct)
- D05-Robustness: should pass with input validation added
- D06-Performance: should pass (latency ~6-7s < 10s SLA)
- D01-Functional: should improve with better test case grounding
- D02-Quality: will depend on KB coverage

---

## File Map

```
src/
├── config.py              MODIFY — add fee data, tool constants, MAX_INPUT_LENGTH
├── chatbot.py             MODIFY — tool routing, input length check, observability
├── memory.py              MODIFY — add summarisation methods
├── tools.py               CREATE — fee_calculator, date_checker implementations
├── observability.py       CREATE — LLMCallLogger, logged_llm_call()
├── prompts.py             No changes
├── retriever.py           No changes
├── ingest.py              No changes
└── eval/                  No changes needed

app.py                     MODIFY — session stats, tool display, observability panel
docs/
└── Implementation_Plan.md CREATE ← this file

logs/
└── llm_calls.jsonl        CREATE (at runtime)
```

---

## Success Criteria

| Criterion | Target |
|-----------|--------|
| Evaluation pass rate | ≥ 70% (14/20) |
| fee_calculator tool works | "What's the total 4-year fee for CSE?" gives computed answer |
| date_checker tool works | "Has the admission deadline passed?" gives correct answer |
| LLM call logging | Every call logged to logs/llm_calls.jsonl |
| Session stats visible | Sidebar shows total queries, latency, cost after each turn |
| Memory summarisation | Long sessions (>10 turns) summarise automatically |
| Input validation | Input >2000 chars rejected gracefully |
