"""
app.py
------
Streamlit UI for the BVRIT FAQ Chatbot.

Two tabs:
  🎓 Chat     — main conversational interface with citations + refusal badges
  📊 Dashboard — evaluation report viewer (pass rates, RAGAS metrics, per-case detail)

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
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title(f"{APP_ICON} {APP_TITLE}")
    st.markdown("---")

    # --- Index Status ---
    st.subheader("📦 Knowledge Base")
    if st.session_state.retriever_loaded:
        status = retriever.status()
        st.success("Index loaded ✅")
        st.metric("Chunks", status["chunk_count"])
        st.caption(f"Collection: `{status['collection']}`")
        st.caption(f"Embed model: `{status['embedding_model']}`")
    elif st.session_state.retriever_error:
        st.error("Index not found ❌")
        st.caption(st.session_state.retriever_error)
        st.info("Run `python src/ingest.py` to build the index first.")
    else:
        st.warning("Loading...")

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
        "Filter by section",
        options=section_options,
        index=0,
        help="Restrict retrieval to a single KB section.",
    )
    section_filter = None if section_choice == "(All sections)" else section_choice

    st.caption(f"Chunk size: ~{CHUNK_SIZE} tokens | Overlap: ~{CHUNK_OVERLAP} tokens")

    st.markdown("---")

    # --- New Chat ---
    if st.button("🗑️ New Chat", use_container_width=True):
        st.session_state.memory.clear()
        st.rerun()

    st.caption(f"Turns this session: {st.session_state.memory.turn_count}")


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
        "Ask anything about admissions, fees, placements, departments, or campus facilities."
    )

    # -- Render existing conversation history --
    for msg in st.session_state.memory.get_display_messages():
        with st.chat_message(msg["role"]):
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
        # Render user message immediately
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.memory.add_user(prompt)

        # Get history excluding the message we just added
        history = st.session_state.memory.get_history(exclude_last_user=True)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Searching knowledge base…"):
                response = st.session_state.chatbot.ask(
                    question=prompt,
                    history=history,
                    k=top_k,
                    section_filter=section_filter,
                )

            # Build display
            answer_text = response.answer

            # Badges row
            badges = []
            if response.is_refusal:
                badges.append(f"**{REFUSED_BADGE}**")
            if response.has_conflict:
                badges.append(f"**{CONFLICT_BADGE}**")
            if response.was_injected:
                badges.append("**🚫 INJECTION BLOCKED**")
            if badges:
                st.markdown(" ".join(badges))

            # Main answer
            st.markdown(answer_text)

            # Citations expander
            if response.citations:
                with st.expander(f"📎 {len(response.citations)} source(s)"):
                    for cite in response.citations:
                        st.markdown(
                            f"<span style='color:{CITATION_COLOR}'>📄 {cite}</span>",
                            unsafe_allow_html=True,
                        )

            # Debug expander: retrieved chunks
            if response.retrieved_chunks:
                with st.expander(f"🔍 Retrieved chunks ({len(response.retrieved_chunks)})", expanded=False):
                    for i, chunk in enumerate(response.retrieved_chunks, 1):
                        meta = chunk.get("metadata", {})
                        score = chunk.get("score", "?")
                        section = meta.get("section", "?")
                        page = meta.get("page_number", "?")
                        content_preview = chunk.get("content", "")[:300]
                        st.markdown(
                            f"**[{i}]** `{section}` | Page {page} | Score: `{score}`\n\n"
                            f"{content_preview}{'…' if len(chunk.get('content','')) > 300 else ''}"
                        )
                        st.markdown("---")

            # Latency
            st.caption(f"⏱ {response.latency_sec:.2f}s")

        # Store assistant message
        st.session_state.memory.add_assistant(response.answer)


# ============================================================
# TAB 2: EVALUATION DASHBOARD
# ============================================================
with tab_dashboard:
    st.header("📊 Evaluation Dashboard")

    if not EVAL_REPORT_PATH.exists():
        st.info(
            "No evaluation report found yet.\n\n"
            "Run the full evaluation pipeline to generate it:\n"
            "```bash\n"
            "python src/eval/test_generator.py\n"
            "python src/eval/test_runner.py\n"
            "python src/eval/judge.py\n"
            "python src/eval/ragas_eval.py   # optional\n"
            "python src/eval/report.py\n"
            "```"
        )
        st.stop()

    report: dict = json.loads(EVAL_REPORT_PATH.read_text(encoding="utf-8"))

    # ---- Overall summary ------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Cases", report["total_cases"])
    col2.metric("Passed", report["overall_pass"])
    col3.metric("Failed", report["overall_fail"])
    overall_pct = round(report["overall_rate"] * 100, 1)
    col4.metric(
        "Overall Pass Rate",
        f"{overall_pct}%",
        delta=f"{overall_pct - 80:.1f}% vs 80% target",
        delta_color="normal",
    )

    st.caption(f"Report generated: {report.get('generated_at', 'N/A')}")
    st.markdown("---")

    # ---- Weakest dimension + fix ----------------------------------------
    st.subheader("⚠️ Weakest Dimension")
    st.error(f"**{report.get('weakest_dimension', 'N/A')}**")
    st.info(f"💡 **Recommendation:** {report.get('fix_recommendation', '')}")
    st.markdown("---")

    # ---- Per-dimension breakdown ----------------------------------------
    st.subheader("📐 Results by Dimension")

    dim_data: dict = report.get("dimensions", {})
    for dim_name, data in dim_data.items():
        if data["total"] == 0:
            continue

        pass_rate = data.get("pass_rate", 0)
        pct = round(pass_rate * 100, 1)
        label_color = "🟢" if pct >= 80 else ("🟡" if pct >= 50 else "🔴")

        with st.expander(
            f"{label_color} **{dim_name}** — {data['passed']}/{data['total']} passed ({pct}%)",
            expanded=False,
        ):
            st.progress(pass_rate)

            for case in data.get("cases", []):
                verdict = "✅" if case.get("passed") else ("❓" if case.get("passed") is None else "❌")
                latency = f"⏱ {case['latency_sec']:.2f}s" if case.get("latency_sec") else ""
                st.markdown(
                    f"{verdict} **{case['id']}** — {case['question']}  \n"
                    f"&nbsp;&nbsp;&nbsp;&nbsp;_{case.get('judge_reason', '')}_ {latency}"
                )

    st.markdown("---")

    # ---- RAGAS metrics --------------------------------------------------
    ragas: dict = report.get("ragas", {})
    if ragas:
        st.subheader("📈 RAGAS Metrics (D08)")
        targets = {
            "faithfulness": RAGAS_FAITHFULNESS_TARGET,
            "answer_relevancy": RAGAS_ANSWER_RELEVANCY_TARGET,
            "context_precision": RAGAS_CONTEXT_PRECISION_TARGET,
            "context_recall": RAGAS_CONTEXT_RECALL_TARGET,
        }
        cols = st.columns(len(ragas))
        for col, (metric, info) in zip(cols, ragas.items()):
            score = info["score"]
            target = info["target"]
            passed = info["passed"]
            delta_val = round(score - target, 3)
            col.metric(
                label=metric.replace("_", " ").title(),
                value=f"{score:.3f}",
                delta=f"{delta_val:+.3f} vs {target} target",
                delta_color="normal" if passed else "inverse",
            )
        st.markdown("---")

    # ---- Error cases ----------------------------------------------------
    errors = report.get("error_cases", [])
    if errors:
        st.subheader("🚨 Errored Test Cases")
        for ec in errors:
            st.error(f"**{ec['id']}**: {ec['error']}")
