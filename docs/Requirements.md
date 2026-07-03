# Software Requirements Specification
## BVRIT College FAQ Chatbot (RAG-Powered)
**Version:** 1.0 | **Companion:** Architecture.md v1.0 | **Status:** Draft for Implementation

---

## 1. Introduction

### 1.1 Purpose
This document specifies the functional and non-functional requirements for the BVRIT College FAQ Chatbot, a Retrieval-Augmented Generation (RAG) system that answers questions about BVRIT using a curated internal document as its sole knowledge source. It guides implementation and forms the basis for acceptance testing and evaluation.

### 1.2 Scope
The system ingests a single Word document derived from bvrit.ac.in, indexes it in a vector database, retrieves relevant content per user query, generates a grounded and cited answer, presents it through a Streamlit chat interface, and is validated by an automated eight-dimension evaluation suite including RAGAS metrics.

**In scope:**
- Single-document knowledge base ingestion and indexing
- Semantic retrieval with optional metadata filtering
- Grounded, cited answer generation with graceful refusal
- Streamlit chat UI with sidebar diagnostics
- Automated 8-dimension test suite and RAGAS-based evaluation report

**Out of scope:**
- Multi-college / multi-tenant support
- User authentication or personalization
- Live, runtime scraping of the college website
- Voice interfaces or production-grade deployment infrastructure

### 1.3 Definitions, Acronyms, Abbreviations

| Term | Definition |
|---|---|
| RAG | Retrieval-Augmented Generation — generation grounded in retrieved documents |
| Chunk | A segment of the source document stored with metadata for retrieval |
| Top-k | The number of chunks returned by the retriever per query |
| RAGAS | Retrieval-Augmented Generation Assessment — automated RAG evaluation library |
| SLA | Service Level Agreement — maximum acceptable response latency |
| Judge (LLM-as-judge) | A separate LLM used to score chatbot output against expected answers |

### 1.4 References
- Lab brief: "GenAI & Agentic AI Engineering — Day 4 Afternoon Lab: College FAQ Chatbot"
- Architecture.md v1.0 (companion document)
- Knowledge_Base_Content_Requirements.md (companion document)
- Source website: bvrit.ac.in

---

## 2. Overall Description

### 2.1 Product Perspective
The chatbot is a standalone lab deliverable, not integrated with any existing BVRIT IT system. It reads from a static, manually curated document rather than a live database or CMS. It is a self-contained Streamlit application with a local, persistent vector store.

### 2.2 User Classes and Characteristics

| User Class | Characteristics | Primary Needs |
|---|---|---|
| Prospective student / parent | Non-technical, first-time user | Fast, trustworthy answers on admissions, fees, placements |
| Current student | Occasional user | Facility, faculty, contact information |
| Lab instructor / peer reviewer | Technical evaluator | Verifiable evaluation report, correct refusals, live demo |
| Developer | Technical, builds and maintains the system | Debuggable pipeline, clear logs, configurable parameters |

### 2.3 Operating Environment
- Python 3.x runtime, Streamlit web application (local or hosted)
- ChromaDB local persistent vector store (no external server required)
- LLM and embedding calls via OpenAI-compatible API (OpenRouter) and/or Anthropic API

### 2.4 Design and Implementation Constraints
- Must use the same embedding model for indexing and querying
- Must not hardcode configuration values across multiple files — centralize in one config module
- Judge LLM must differ from the generation LLM to avoid self-evaluation bias

### 2.5 Assumptions and Dependencies
- The curated knowledge-base document is accurate and complete as of the date it was compiled
- API access (OpenAI/OpenRouter/Anthropic) is available and within rate/cost limits for the lab
- The lab environment allows local persistence to disk (Chroma index and JSON result files)

---

## 3. Functional Requirements

### 3.1 Knowledge Base Ingestion (FR-1)

| ID | Requirement | Priority |
|---|---|---|
| FR-1.1 | The system shall load a single .docx file as the sole knowledge source. | Must |
| FR-1.2 | The system shall split the document into chunks aligned to section headings. | Must |
| FR-1.3 | Each chunk shall carry metadata: source_file, section, page_number, chunk_id. | Must |
| FR-1.4 | The system shall embed all chunks with a single fixed embedding model and persist vectors to a vector database. | Must |
| FR-1.5 | The system shall reload the persisted index without re-embedding on restart. | Must |

### 3.2 Retrieval (FR-2)

| ID | Requirement | Priority |
|---|---|---|
| FR-2.1 | Given a query, the system shall return the top-k most similar chunks (default k=5, configurable). | Must |
| FR-2.2 | The system shall support optional metadata filtering by section. | Should |
| FR-2.3 | The system shall expose retrieved chunks (text, metadata, score) for logging and RAGAS evaluation. | Must |

### 3.3 Grounded Generation (FR-3)

| ID | Requirement | Priority |
|---|---|---|
| FR-3.1 | The system shall answer only from retrieved context, never from the LLM's own training knowledge. | Must |
| FR-3.2 | Every substantive answer shall include a citation in the form `[Section Name, Page N]`. | Must |
| FR-3.3 | If the answer is absent from context, the system shall refuse gracefully and provide a fallback contact. | Must |
| FR-3.4 | On conflicting information across chunks, the system shall present both values and flag the discrepancy. | Must |
| FR-3.5 | The system shall never guarantee individual outcomes (e.g., placement, admission). | Must |

### 3.4 Chat UI (FR-4)

| ID | Requirement | Priority |
|---|---|---|
| FR-4.1 | The system shall provide a Streamlit chat interface using `st.chat_input` and `st.chat_message`. | Must |
| FR-4.2 | The sidebar shall display document name, chunk count, index status, chunk size/overlap, top-k, and an optional section filter. | Must |
| FR-4.3 | Every bot message shall visibly render its citation(s). | Must |
| FR-4.4 | Refused answers shall be visually distinguished (e.g., a REFUSED badge). | Should |
| FR-4.5 | Conversation history shall persist within the session. | Must |

### 3.5 Multi-turn Context (FR-5)

| ID | Requirement | Priority |
|---|---|---|
| FR-5.1 | Follow-up questions referencing prior turns shall resolve correctly using conversation history. | Should |

### 3.6 Evaluation Suite (FR-6)

| ID | Requirement | Priority |
|---|---|---|
| FR-6.1 | An LLM shall auto-generate at least 20 test cases spanning all 8 evaluation dimensions. | Must |
| FR-6.2 | The system shall execute every test case against the live chatbot and capture question, expected answer, actual answer, retrieved chunks, and latency. | Must |
| FR-6.3 | A second LLM, different from the generation model, shall judge and score each applicable test case pass/fail with a reason. | Must |
| FR-6.4 | The system shall compute RAGAS metrics programmatically for the RAGAS dimension. | Must |
| FR-6.5 | The system shall compile a structured evaluation report including per-dimension results, pass rate, weakest dimension, and a fix recommendation. | Must |
| FR-6.6 | The evaluation report shall be viewable as a dashboard in a separate Streamlit tab. | Must |

---

## 4. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Accuracy | Zero fabricated facts absent from the source document; target Faithfulness ≥ 0.85 |
| Latency | Simple query ≤ 10s; complex multi-section query ≤ 15s |
| Persistence | Vector index survives app restart without re-embedding |
| Traceability | 100% of non-refused answers carry a machine-checkable citation |
| Cost | Low-cost models for the production path; stronger models reserved for test generation and judging |
| Reproducibility | Deterministic retrieval; low generation temperature (0–0.3) |
| Usability | All configuration accessible via sidebar or config file, not embedded in code |
| Security | Resistant to prompt-injection attempts to leak system prompt or bypass role |
| Maintainability | Centralized configuration for chunk size, top-k, and model names |

---

## 5. Data Requirements

### 5.1 Knowledge Base Document Structure
See **Knowledge_Base_Content_Requirements.md** for the full field-level breakdown. Summary of required sections:

1. About BVRIT — history, vision, mission, accreditations (NAAC, NBA)
2. Departments — B.Tech branches, specialisations, faculty count
3. Admissions — eligibility, entrance exams, process, key dates
4. Fee Structure — tuition by branch, hostel fees, other charges, scholarships
5. Placements — top recruiters, average/highest packages, placement percentage
6. Campus & Facilities — library, labs, hostel, sports, WiFi, transport
7. Faculty — key faculty members, qualifications, research areas
8. Contact — address, phone, email, website, social media

Content must be factual and sourced from bvrit.ac.in; no invented facts are permitted. Absence of a fact must produce a graceful refusal, not fabrication.

### 5.2 Chunk Metadata Requirements

| Field | Type | Required | Notes |
|---|---|---|---|
| chunk_id | string | Yes | Unique identifier per chunk |
| source_file | string | Yes | Name of the source .docx |
| section | string | Yes | Section heading the chunk belongs to |
| page_number | integer | Yes | Page or sequence index for citation |
| text | string | Yes | Raw chunk content |

### 5.3 Test Case and Result Data
Test cases, results, and the final evaluation report shall be persisted as JSON artifacts (`test_cases.json`, `test_results.json`, `evaluation_report.json`) to support peer review and reproducibility.

---

## 6. External Interface Requirements

### 6.1 User Interface
- Chat tab: message input, chat history, citations, refusal badges
- Sidebar: knowledge base status, retrieval configuration, optional section filter
- Dashboard tab: summary stats, per-dimension pass/fail cards, failed-test drill-downs, RAGAS score bars

### 6.2 External Services

| Service | Purpose |
|---|---|
| Embedding API (e.g., OpenAI text-embedding-3-small) | Convert chunks and queries into vectors |
| Generation LLM API (e.g., GPT-4o Mini via OpenRouter) | Produce grounded, cited answers |
| Test-generator LLM API (stronger model) | Auto-generate test cases and expected answers |
| Judge LLM API (different family from generation model) | Score actual vs. expected answers |
| RAGAS library | Compute faithfulness, relevancy, precision, recall |

---

## 7. Acceptance Criteria

- [ ] Index persists across restarts with matching chunk count
- [ ] Three known test queries return the correct chunks on manual inspection
- [ ] A query with no document answer triggers a graceful refusal with contact information
- [ ] A contradictory-fact query surfaces both values with a discrepancy note
- [ ] Every non-refused UI answer shows a `[Section, Page]` citation
- [ ] At least 20 auto-generated test cases exist, covering all 8 dimensions
- [ ] The test suite has been run end-to-end with judge verdicts recorded
- [ ] RAGAS scores are computed for all RAGAS-dimension cases
- [ ] An evaluation report is generated with a weakest dimension and a concrete fix
- [ ] The evaluation dashboard renders in a separate Streamlit tab
- [ ] Peer review: three unseen questions are handled correctly or refused appropriately

---

## 8. Appendix

### 8.1 Traceability Note
Each functional requirement (FR-x.x) maps to a corresponding component in **Architecture.md**, Section 3 (Component Architecture), enabling design and code review to be traced back to a specific requirement.
