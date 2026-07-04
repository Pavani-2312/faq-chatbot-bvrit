"""
app.py
------
Streamlit UI for the BVRIT FAQ Chatbot.

Two tabs (per build brief §4 and Architecture.md §11):

  🎓 Chat       — conversational interface with citations, refusal badges,
                  conflict flags, injection-blocked alerts

  📊 Dashboard  — full evaluation report:
                  summary stats, 4×2 dimension cards with pass/fail,
                  failed-test drill-downs (question/expected/actual/root cause/fix),
                  weakest-dimension recommendation, RAGAS metric bars + diagnosis

Sidebar:
  - Knowledge base status (doc name, chunk count, index status)
  - Retrieval settings (top-k slider, section filter)
  - RAGAS score bars (from last evaluation report)
  - Per-query latency

Run: streamlit run app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

# Add src/ to path so we can import our modules
SRC_DIR = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_DIR))

from config import (
    APP_ICON,
    APP_TITLE,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CITATION_COLOR,
    CONFLICT_BADGE,
    EVAL_REPORT_PATH,
    FALLBACK_CONTACT,
    REFUSED_BADGE,
    TOP_K,
    TOP_K_MAX,
    RAGAS_FAITHFULNESS_TARGET,
    RAGAS_ANSWER_RELEVANCY_TARGET,
    RAGAS_CONTEXT_PRECISION_TARGET,
    RAGAS_CONTEXT_RECALL_TARGET,
)
from chatbot import BVRITChatbot
from memory import ConversationMemory
from retriever import retriever

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
if "memory" not in st.session_state:
    st.session_state.memory = ConversationMemory()

if "chatbot" not in st.session_state:
    st.session_state.chatbot = None

if "retriever_loaded" not in st.session_state:
    st.session_state.retriever_loaded = False

if "retriever_error" not in st.session_state:
    st.session_state.retriever_error = None

if "sections" not in st.session_state:
    st.session_state.sections = []


# ---------------------------------------------------------------------------
# Load retriever once (cached at session level)
# ---------------------------------------------------------------------------
import re as _re
_IMAGE_MD = _re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
_IMAGES_ROOT = Path(__file__).resolve().parent / "scaper" / "output" / "images"

def _render_answer(answer: str) -> None:
    """
    Render the answer text in Streamlit, displaying any images inline.
    Splits the answer on image markdown tokens, renders text via st.markdown
    and images via st.image() using the absolute local file path.
    """
    parts = _IMAGE_MD.split(answer)
    # split() with a capturing group returns: [text, alt, path, text, alt, path, ...]
    i = 0
    while i < len(parts):
        text_chunk = parts[i]
        if text_chunk.strip():
            st.markdown(text_chunk)
        i += 1
        if i + 1 < len(parts):
            alt  = parts[i]       # captured group 1: alt text
            path = parts[i + 1]   # captured group 2: image path
            i += 2
            # Strip leading "scaper/output/images/" or "app/static/images/" prefix
            rel = _re.sub(r'^(scaper/output/images/|app/static/images/)', '', path)
            abs_path = _IMAGES_ROOT / rel
            if abs_path.exists():
                st.image(str(abs_path), caption=alt if alt else None)
            else:
                st.markdown(f"_(Image not found: {rel})_")


def load_retriever_once() -> None:
    if st.session_state.retriever_loaded:
        return
    try:
        retriever.load()
        st.session_state.retriever_loaded = True
        st.session_state.retriever_error = None
        st.session_state.sections = retriever.get_available_sections()
        st.session_state.chatbot = BVRITChatbot(retriever=retriever)
    except RuntimeError as e:
        st.session_state.retriever_error = str(e)
        st.session_state.retriever_loaded = False


load_retriever_once()


# ---------------------------------------------------------------------------
# Helper: load evaluation report (cached so it doesn't re-read on every rerun)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def load_report() -> dict | None:
    if not EVAL_REPORT_PATH.exists():
        return None
    try:
        return json.loads(EVAL_REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title(f"{APP_ICON} {APP_TITLE}")
    st.markdown("---")

    # --- Index Status ---
    st.subheader("📦 Knowledge Base")
    if st.session_state.retriever_loaded:
        status = retriever.status()
        st.success("● LIVE — Index loaded ✅")
        st.metric("Chunks indexed", status["chunk_count"])
        st.caption(f"Collection: `{status['collection']}`")
        st.caption(f"Embed model: `{status['embedding_model']}`")
    elif st.session_state.retriever_error:
        st.error("Index not found ❌")
        st.caption(st.session_state.retriever_error)
        st.info("Run `python src/ingest.py` to build the index first.")
    else:
        st.warning("Loading…")

    st.markdown("---")

    # --- Retrieval config ---
    st.subheader("⚙️ Retrieval Settings")
    top_k = st.slider(
        "Top-k chunks",
        min_value=1,
        max_value=TOP_K_MAX,
        value=TOP_K,
        help="Number of knowledge base chunks retrieved per query.",
    )

    section_options = ["(All sections)"] + st.session_state.sections
    section_choice = st.selectbox(
        "Section filter",
        options=section_options,
        index=0,
        help="Restrict retrieval to a single KB section.",
    )
    section_filter = None if section_choice == "(All sections)" else section_choice
    st.caption(f"Chunk size: ~{CHUNK_SIZE} chars | Overlap: ~{CHUNK_OVERLAP} chars")

    st.markdown("---")

    # --- RAGAS Score Bars (from last evaluation report) ---
    report = load_report()
    if report and report.get("ragas_scores"):
        st.subheader("📈 RAGAS Scores")
        ragas = report["ragas_scores"]
        targets = {
            "faithfulness": RAGAS_FAITHFULNESS_TARGET,
            "answer_relevancy": RAGAS_ANSWER_RELEVANCY_TARGET,
            "context_precision": RAGAS_CONTEXT_PRECISION_TARGET,
            "context_recall": RAGAS_CONTEXT_RECALL_TARGET,
        }
        labels = {
            "faithfulness": "Faithfulness",
            "answer_relevancy": "Answer Relevancy",
            "context_precision": "Context Precision",
            "context_recall": "Context Recall",
        }
        for key, label in labels.items():
            if key in ragas:
                score = ragas[key].get("score", 0)
                target = targets.get(key, 0.75)
                passed = score >= target
                icon = "✅" if passed else "❌"
                st.caption(f"{icon} {label}: **{score:.2f}** (target ≥ {target})")
                st.progress(min(score, 1.0))
        st.markdown("---")
    elif report:
        st.subheader("📈 RAGAS Scores")
        st.caption("Run `ragas_eval.py` to compute scores.")
        st.markdown("---")

    # --- Session info ---
    if st.button("🗑️ New Chat", use_container_width=True):
        st.session_state.memory.clear()
        st.rerun()
    st.caption(f"Turns this session: {st.session_state.memory.turn_count}")


# ---------------------------------------------------------------------------
# Fix hints for dashboard drill-down panel (must be defined before tab renders)
# ---------------------------------------------------------------------------
FIX_RECOMMENDATIONS_SHORT = {
    "01-Functional": "Increase top-k or fix chunk boundaries so all list items are retrieved together.",
    "02-Quality": "Verify specific facts are verbatim in the KB; reduce chunk size if needed.",
    "03-Safety": "Strengthen safety clause in system prompt; ensure hedging language is used.",
    "04-Security": "Expand injection-defence clause and INJECTION_PATTERNS in config.py.",
    "05-Robustness": "Add pre-retrieval input validation for empty/gibberish inputs in chatbot.py.",
    "06-Performance": "Profile retrieval vs. generation bottleneck; reduce MAX_TOKENS if needed.",
    "07-Context": "Increase MAX_HISTORY_TURNS; verify conversation history is injected into prompt.",
    "08-RAGAS": "See RAGAS diagnosis above for the specific metric that needs attention.",
}

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------
tab_chat, tab_dashboard = st.tabs(["🎓 Chat", "📊 Evaluation Dashboard"])


# ============================================================
# TAB 1: CHAT
# ============================================================
with tab_chat:
    st.header(f"{APP_ICON} BVRIT College FAQ Assistant")
    st.caption(
        "Ask anything about admissions, fees, placements, departments, or campus facilities. "
        "Every answer is grounded in the official BVRIT knowledge base with citations."
    )

    # -- Render existing conversation history --
    for msg in st.session_state.memory.get_display_messages():
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                _render_answer(msg["content"])
            else:
                st.markdown(msg["content"])

    # -- Index not ready: show warning --
    if not st.session_state.retriever_loaded:
        st.warning(
            "⚠️ The knowledge base index is not loaded. "
            "Please run `python src/ingest.py` to build it, then refresh this page."
        )
        st.stop()

    # -- Chat input --
    if prompt := st.chat_input("Ask a question about BVRIT…"):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.memory.add_user(prompt)

        history = st.session_state.memory.get_history(exclude_last_user=True)

        with st.chat_message("assistant"):
            with st.spinner("Searching knowledge base…"):
                response = st.session_state.chatbot.ask(
                    question=prompt,
                    history=history,
                    k=top_k,
                    section_filter=section_filter,
                )

            # Badges
            badges = []
            if response.refused:
                badges.append(f"**{REFUSED_BADGE}**")
            if response.has_conflict:
                badges.append(f"**{CONFLICT_BADGE}**")
            if response.was_injected:
                badges.append("**🚫 INJECTION BLOCKED**")
            if badges:
                st.markdown(" ".join(badges))

            _render_answer(response.answer)

            # Citations expander
            if response.citations:
                with st.expander(f"📎 {len(response.citations)} source(s)"):
                    for cite in response.citations:
                        st.markdown(
                            f"<span style='color:{CITATION_COLOR}'>📄 {cite}</span>",
                            unsafe_allow_html=True,
                        )

            # Retrieved chunks debug expander
            if response.retrieved_chunks:
                with st.expander(
                    f"🔍 Retrieved chunks ({len(response.retrieved_chunks)})",
                    expanded=False,
                ):
                    for i, chunk in enumerate(response.retrieved_chunks, 1):
                        meta = chunk.get("metadata", {})
                        score = chunk.get("score", "?")
                        section = meta.get("section", "?")
                        page = meta.get("page_number", "?")
                        content_preview = chunk.get("content", "")[:300]
                        st.markdown(
                            f"**[{i}]** `{section}` | Page {page} | Score: `{score}`\n\n"
                            f"{content_preview}"
                            f"{'…' if len(chunk.get('content', '')) > 300 else ''}"
                        )
                        st.markdown("---")

            st.caption(f"⏱ {response.latency_sec:.2f}s")

        st.session_state.memory.add_assistant(response.answer)


# ============================================================
# TAB 2: EVALUATION DASHBOARD
# ============================================================
with tab_dashboard:
    st.header("📊 Evaluation Dashboard")

    report = load_report()

    if report is None:
        st.info(
            "No evaluation report found yet.\n\n"
            "Run the full evaluation pipeline:\n"
            "```bash\n"
            "python src/eval/test_generator.py\n"
            "python src/eval/test_runner.py\n"
            "python src/eval/judge.py\n"
            "python src/eval/ragas_eval.py   # optional\n"
            "python src/eval/report.py\n"
            "```"
        )
        st.stop()

    summary = report.get("summary", {})

    # ---- Overall summary banner ----------------------------------------
    col1, col2, col3, col4 = st.columns(4)
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    rate = summary.get("pass_rate", 0)
    pct = round(rate * 100, 1)

    col1.metric("Total Cases", total)
    col2.metric("✅ Passed", passed)
    col3.metric("❌ Failed", failed)
    col4.metric(
        "Overall Pass Rate",
        f"{pct}%",
        delta=f"{pct - 80:.1f}% vs 80% target",
        delta_color="normal",
    )
    st.caption(f"Report generated: {report.get('generated_at', 'N/A')}")
    st.markdown("---")

    # ---- Weakest dimension + recommendation ----------------------------
    st.subheader("⚠️ Weakest Dimension")
    weakest = report.get("weakest_dimension", "N/A")
    rec = report.get("recommendation", "")
    st.error(f"**{weakest}**")
    st.info(f"💡 **Recommended fix:** {rec}")
    st.markdown("---")

    # ---- Per-dimension breakdown with drill-downs ----------------------
    st.subheader("📐 Results by Dimension")
    dim_data: dict = report.get("per_dimension", {})

    for dim_name, data in dim_data.items():
        if data["total"] == 0:
            continue

        pass_rate = data.get("pass_rate", 0)
        dim_pct = round(pass_rate * 100, 1)
        icon = "🟢" if dim_pct >= 80 else ("🟡" if dim_pct >= 50 else "🔴")

        with st.expander(
            f"{icon} **{dim_name}** — {data['passed']}/{data['total']} passed ({dim_pct}%)",
            expanded=False,
        ):
            st.progress(pass_rate)

            # Separate passed and failed cases
            failed_cases = [c for c in data.get("cases", []) if c.get("passed") is False]
            passed_cases = [c for c in data.get("cases", []) if c.get("passed") is True]
            pending_cases = [c for c in data.get("cases", []) if c.get("passed") is None]

            # Show failed cases first with full drill-down
            if failed_cases:
                st.markdown("##### ❌ Failed Tests — Drill-down")
                for case in failed_cases:
                    latency = (
                        f" | ⏱ {case['latency_sec']:.2f}s"
                        if case.get("latency_sec") else ""
                    )
                    with st.container():
                        st.markdown(
                            f"**{case['test_id']}** — {case['question']}{latency}"
                        )
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown("**Expected:**")
                            st.code(
                                case.get("expected_answer", "—")[:400],
                                language=None,
                            )
                        with col_b:
                            st.markdown("**Actual:**")
                            st.code(
                                case.get("actual_answer", "—")[:400],
                                language=None,
                            )
                        reason = case.get("judge_reason", "")
                        if reason:
                            st.markdown(f"🔍 **Root cause:** _{reason}_")
                        fix = FIX_RECOMMENDATIONS_SHORT.get(dim_name, "")
                        if fix:
                            st.markdown(f"🔧 **Fix:** {fix}")
                        st.markdown("---")

            # Show passed cases compactly
            if passed_cases:
                st.markdown("##### ✅ Passed Tests")
                for case in passed_cases:
                    latency = (
                        f" | ⏱ {case['latency_sec']:.2f}s"
                        if case.get("latency_sec") else ""
                    )
                    reason = case.get("judge_reason", "")
                    st.markdown(
                        f"✅ **{case['test_id']}** — {case['question']}  \n"
                        f"&nbsp;&nbsp;&nbsp;&nbsp;_{reason}_{latency}"
                    )

            if pending_cases:
                st.markdown("##### ❓ Not yet judged")
                for case in pending_cases:
                    st.markdown(f"❓ **{case['test_id']}** — {case['question']}")

    st.markdown("---")

    # ---- RAGAS metric bars ---------------------------------------------
    ragas = report.get("ragas_scores", {})
    if ragas:
        st.subheader("📈 RAGAS Metrics (08)")
        ragas_targets = {
            "faithfulness": RAGAS_FAITHFULNESS_TARGET,
            "answer_relevancy": RAGAS_ANSWER_RELEVANCY_TARGET,
            "context_precision": RAGAS_CONTEXT_PRECISION_TARGET,
            "context_recall": RAGAS_CONTEXT_RECALL_TARGET,
        }
        cols = st.columns(len(ragas))
        for col, (metric, info) in zip(cols, ragas.items()):
            score = info.get("score", 0)
            target = info.get("target", ragas_targets.get(metric, 0.75))
            passed_m = info.get("passed", score >= target)
            delta_val = round(score - target, 3)
            col.metric(
                label=metric.replace("_", " ").title(),
                value=f"{score:.3f}",
                delta=f"{delta_val:+.3f} vs {target} target",
                delta_color="normal" if passed_m else "inverse",
            )
            col.progress(min(score, 1.0))

        diagnosis = report.get("ragas_diagnosis", "")
        if diagnosis:
            st.info(f"🔬 **RAGAS Diagnosis:** {diagnosis}")
        st.markdown("---")

    # ---- Error cases ---------------------------------------------------
    errors = report.get("error_cases", [])
    if errors:
        st.subheader("🚨 Errored Test Cases")
        for ec in errors:
            st.error(f"**{ec['test_id']}**: {ec['error']}")


