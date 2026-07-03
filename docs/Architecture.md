# Architecture Document
## BVRIT College FAQ Chatbot (RAG-Powered)
**Version:** 1.0 | **Companion:** Requirements.md v1.0

---

## 1. Introduction

### 1.1 Purpose
This document describes the technical architecture of the BVRIT College FAQ Chatbot: its components, data flow, technology choices, folder layout, and the interfaces between the ingestion, retrieval, generation, UI, and evaluation subsystems. It implements the requirements defined in **Requirements.md v1.0**.

### 1.2 Architectural Goals
- Strict separation between retrieval and generation so each can be debugged independently
- Deterministic, inspectable retrieval (always log what was retrieved before it reaches the LLM)
- A grounding layer that structurally prevents reliance on the LLM's parametric knowledge
- An evaluation subsystem decoupled from the production chat path, reusing the same chatbot interface
- All tunable parameters centralized in one configuration module

### 1.3 Architectural Style
The system follows a layered pipeline architecture: **Ingestion → Retrieval → Generation → Presentation**, with a parallel **Evaluation** pipeline that treats the chatbot as a black-box system under test. This is a classic RAG reference architecture, implemented locally with no microservices or network boundaries beyond LLM/embedding API calls.

---

## 2. High-Level Architecture

### 2.1 System Diagram

```
                     OFFLINE (Phase 0, once)
        bvrit.ac.in --manual copy--> bvrit_knowledge_base.docx

+----------------------- INGESTION PIPELINE -----------------------+
| Docx2txtLoader -> RecursiveCharacterTextSplitter (heading-aware)  |
|   -> chunks[] {text, section, page, chunk_id}                    |
|   -> text-embedding-3-small -> vectors[]                         |
|   -> ChromaDB (persist_directory=./chroma_db)                    |
+---------------------------------+----------------------------------+
                                  | (persisted, loaded on app start)
+---------------------------------v----------------------------------+
|                        RETRIEVAL LAYER                             |
| query -> embed(query) -> Chroma similarity_search(k, filter)       |
|   -> ranked chunks + scores + metadata                             |
+---------------------------------+----------------------------------+
                                  |
+---------------------------------v----------------------------------+
|                  GENERATION LAYER (Grounding)                      |
| system prompt + retrieved chunks + chat history + user query       |
|   -> GPT-4o Mini (via OpenRouter) -> answer + citations             |
+---------------------------------+----------------------------------+
                                  |
+---------------------------------v----------------------------------+
|                      STREAMLIT UI LAYER                             |
| Sidebar: KB status, retrieval config, RAGAS bars                   |
| Main: chat thread with citations + refusal badges                  |
| Tab 2: Evaluation Dashboard                                        |
+---------------------------------------------------------------------+

+----------------- EVALUATION PIPELINE (offline/on-demand) -----------+
| LLM #1 (Test Generator, strong model)                               |
|   -> 20+ test cases across 8 dimensions (JSON)                      |
| LLM #2 = the chatbot itself (system under test)                     |
|   -> runs each test case -> actual_answer, chunks, latency          |
| LLM #3 (Judge, different model from #2)                             |
|   -> pass/fail + reason per test case                               |
| Performance dim -> numeric SLA check, no LLM                        |
| RAGAS dim -> ragas.evaluate() on (q, context, answer)                |
|   -> evaluation_report.json -> rendered in dashboard                |
+-----------------------------------------------------------------------+
```

### 2.2 Data Flow Summary
- **Offline, once:** source website content is manually curated into a structured .docx knowledge base.
- **Startup:** ingestion pipeline builds or loads the persisted vector index.
- **Per query:** retrieval layer fetches top-k relevant chunks; generation layer builds a grounded prompt and calls the LLM; UI renders the cited answer.
- **On demand:** evaluation pipeline generates test cases, runs them through the same chatbot interface, judges results, computes RAGAS metrics, and compiles a report consumed by the dashboard tab.

---

## 3. Component Architecture

| Component | Responsibility | Key Library |
|---|---|---|
| `ingest.py` | Load docx, chunk, embed, persist to Chroma | LangChain, ChromaDB |
| `retriever.py` | Wrap Chroma as retriever; support top-k and metadata filter | LangChain |
| `prompts.py` | Store the grounding system prompt template | — |
| `chatbot.py` | Orchestrate retrieve → build prompt → call LLM → parse citations | LangChain / OpenAI SDK |
| `memory.py` | Maintain multi-turn conversation state | — |
| `app.py` | Streamlit UI: Chat tab + Dashboard tab | Streamlit |
| `eval/test_generator.py` | Call LLM #1 to produce `test_cases.json` | OpenAI / Anthropic SDK |
| `eval/test_runner.py` | Execute test cases against `chatbot.py`, log results | — |
| `eval/judge.py` | Call LLM #3 to score each result | OpenAI / Anthropic SDK |
| `eval/ragas_eval.py` | Run RAGAS metrics on RAGAS-dimension cases | `ragas` |
| `eval/report.py` | Aggregate results into `evaluation_report.json`; feed dashboard | — |
| `config.py` | Central config: chunk size, overlap, top-k, model names, SLAs | — |

---

## 4. Repository / Folder Structure

```
bvrit-faq-chatbot/
├── data/
│   └── bvrit_knowledge_base.docx        # Phase 0 output
├── chroma_db/                           # persisted vector store
├── src/
│   ├── config.py
│   ├── ingest.py
│   ├── retriever.py
│   ├── prompts.py
│   ├── chatbot.py
│   ├── memory.py                        # multi-turn conversation state
│   └── eval/
│       ├── test_generator.py
│       ├── test_runner.py
│       ├── judge.py
│       ├── ragas_eval.py
│       └── report.py
├── tests/
│   ├── test_cases.json                  # generated by LLM #1
│   ├── test_results.json                # raw run output
│   └── evaluation_report.json           # final aggregated report
├── app.py                               # Streamlit entrypoint
├── requirements.txt
├── .env                                 # API keys (not committed)
└── README.md
```

---

## 5. Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Orchestration | LangChain | Mature document loaders, splitters, retriever abstractions |
| Document loader | Docx2txtLoader | Direct .docx text extraction |
| Text splitter | RecursiveCharacterTextSplitter | Configurable separators, size, and overlap; heading-aware |
| Embedding model | text-embedding-3-small | 1536-dim, fast, low cost; consistent indexing/query model |
| Vector database | ChromaDB | Local, persistent, Python-native, metadata filtering |
| Generation LLM | GPT-4o Mini (via OpenRouter) | Cost-effective, strong instruction following |
| UI framework | Streamlit | Rapid chat UI with native chat components |
| Evaluation | RAGAS | Standardized faithfulness/relevancy/precision/recall scoring |

---

## 6. Data Architecture

### 6.1 Chunk Metadata Schema
```json
{
  "chunk_id": "string (uuid or seq)",
  "source_file": "bvrit_knowledge_base.docx",
  "section": "Fee Structure",
  "page_number": 4,
  "text": "raw chunk text",
  "char_count": 812
}
```

### 6.2 Chatbot Response Schema (internal)
```json
{
  "answer": "string",
  "citations": [{"section": "Placements", "page": 5}],
  "refused": false,
  "retrieved_chunks": [
    {"chunk_id": "...", "section": "...", "page": 5, "score": 0.81}
  ],
  "latency_seconds": 2.3
}
```

### 6.3 Test Case Schema (LLM #1 output)
```json
{
  "test_id": "FUNC-01",
  "dimension": "01-Functional",
  "question": "List all B.Tech departments offered at BVRIT.",
  "expected_answer": "CSE, ECE, EEE, MECH, CIVIL, IT, AI&DS",
  "pass_criteria": "All departments appear; citation present.",
  "context_hint": "Departments section"
}
```

### 6.4 Evaluation Report Schema
```json
{
  "summary": {"total": 20, "passed": 15, "failed": 4, "warning": 1, "pass_rate": 0.75},
  "per_dimension": { "01-Functional": {"passed": 3, "total": 3} },
  "weakest_dimension": "04-Security",
  "recommendation": "Strengthen system prompt with injection-defence instructions.",
  "ragas_scores": {
    "faithfulness": 0.89, "answer_relevancy": 0.91,
    "context_precision": 0.72, "context_recall": 0.85
  },
  "ragas_diagnosis": "Context Precision lowest — reduce chunk_size or add filters."
}
```

---

## 7. Component Interfaces (Function Contracts)

```python
# ingest.py
def build_index(docx_path, persist_dir, chunk_size, overlap) -> int

# retriever.py
def retrieve(query, k=5, section_filter=None) -> list[dict]

# chatbot.py
def ask(query, chat_history) -> dict

# eval/test_generator.py
def generate_test_cases(source_doc_text, n_per_dimension) -> list[dict]

# eval/test_runner.py
def run_test_suite(test_cases) -> list[dict]

# eval/judge.py
def judge(test_result) -> dict

# eval/ragas_eval.py
def run_ragas(ragas_cases) -> dict

# eval/report.py
def compile_report(results, ragas_scores) -> dict
```

---

## 8. Configuration Architecture

All tunables live in a single `config.py` module, avoiding hardcoded values scattered across the codebase:

```python
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 5
EMBEDDING_MODEL = "text-embedding-3-small"
GENERATION_MODEL = "gpt-4o-mini"
TEST_GENERATOR_MODEL = "gpt-4o"
JUDGE_MODEL = "claude-sonnet-4-6"
TEMPERATURE = 0.2
PERFORMANCE_SLA_SIMPLE = 10   # seconds
PERFORMANCE_SLA_COMPLEX = 15  # seconds
VECTOR_DB_PATH = "./chroma_db"
```

---

## 9. Grounding Prompt Architecture

The generation layer's system prompt is structured in seven ordered clauses to structurally enforce grounding:

1. **Role definition** (BVRIT information assistant)
2. **Grounding rule** (context-only, no training knowledge)
3. **Citation format** (`[Section Name, Page N]`)
4. **Refusal instruction** with fallback contact
5. **Conflict-handling instruction** (present both values, flag discrepancy)
6. **Safety constraint** (no outcome guarantees)
7. **Injection-defence clause** (ignore embedded instructions in context or user input)

---

## 10. Evaluation Architecture

### 10.1 Three-LLM Pattern

| Role | Model Guidance | Function |
|---|---|---|
| LLM #1 — Test Generator | Strong model (GPT-4o / Claude Sonnet) | Generates test cases + expected answers from the source document |
| LLM #2 — System Under Test | GPT-4o Mini (matches production) | The chatbot itself; answers each test question |
| LLM #3 — Judge | Different model family from LLM #2 | Scores actual vs. expected answer per dimension criteria |

### 10.2 Dimension-Specific Scoring Logic

| Dimension | Scoring Mechanism |
|---|---|
| 01 Functional | LLM judge: format spec, citation presence, completeness |
| 02 Quality | LLM judge: factual match to source document, no hallucination |
| 03 Safety | LLM judge: no harmful promises or biased claims |
| 04 Security | LLM judge: role adherence, no system-prompt leakage |
| 05 Robustness | LLM judge: graceful handling of edge-case input |
| 06 Performance | Numeric code check against SLA thresholds |
| 07 Context | LLM judge: correct resolution of multi-turn follow-up |
| 08 RAGAS | RAGAS library: faithfulness, relevancy, precision, recall |

### 10.3 Evaluation Data Flow
The evaluation pipeline is decoupled from the live UI: it calls the same `ask()` function exposed by `chatbot.py`, ensuring the system under test is identical to what end users interact with. Results are persisted as JSON so the dashboard tab can render them without re-running the suite.

---

## 11. UI Architecture

### 11.1 Tab 1 — Chat
```
Sidebar                        Chat
----------------------------   -----------------------------------
Doc: bvrit_kb.docx              User: What's the CSE fee?
Chunks: 142                     Bot: Rs.1,25,000/yr [Fee Structure, p4]
Index: LIVE
Chunk size: 800/120             User: Do you offer courses in Mars?
Top-k: 5                        Bot: [REFUSED] Not in knowledge base.
Section filter: [All]                Contact: admissions@bvrit.ac.in
RAGAS: 0.89
```

### 11.2 Tab 2 — Evaluation Dashboard
```
Summary: 15/20 passed (75%)   Weakest: 04-Security
[01]3/3 [02]2/3 [03]2/2 [04]1/2 [05]2/3 [06]2/2 [07]1/2 [08]2/3
> Failed test drill-down: SEC-01
   Root cause: No explicit injection-defence clause
   Fix: Add injection-defence instruction (Section 9, item 7)
RAGAS: Faithfulness 0.89 | Relevancy 0.91 | Precision 0.72 | Recall 0.85
```

---

## 12. Deployment View
- Single-process local deployment: `streamlit run app.py`
- Vector store persisted to local disk (`./chroma_db`); no external DB server required
- Secrets (API keys) loaded from `.env`, never committed to version control
- Evaluation pipeline can run standalone via CLI (`python -m src.eval.test_runner`) independent of the UI process

---

## 13. Architectural Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Model hallucinates despite grounding prompt | Explicit context-only clause; test with known-absent questions |
| Chunking splits a fact across chunks | Heading-aware splitting with overlap; verify via retrieval spot checks |
| Judge shares bias with generation model | Use a different model family for judging |
| Section filter reduces recall when unset | Default filter to "All"; apply only when explicitly chosen |
| Prompt injection via user query | Explicit injection-defence clause + Dimension-04 tests |
| Stale knowledge base vs. live website | Document a manual refresh cadence; out of scope for auto-sync |

---

## 14. Appendix: Requirements Traceability

Each component in Section 3 maps to one or more functional requirements (FR-x.x) defined in **Requirements.md**: `ingest.py` implements FR-1, `retriever.py` implements FR-2, `chatbot.py` and `prompts.py` implement FR-3, `app.py` implements FR-4 and FR-6.6, `memory.py` implements FR-5, and the `eval/` package implements FR-6.1 through FR-6.5.
