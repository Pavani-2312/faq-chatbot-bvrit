"""
ingest.py
---------
Ingestion pipeline for the BVRIT FAQ Chatbot.

Reads all Markdown files from kb_formatted/, chunks them, embeds them with a
local sentence-transformers model, and persists the vectors to ChromaDB.

Run once (or re-run after updating the knowledge base):
    python src/ingest.py

What it does:
  1. Scans KB_MD_DIR for all .md files (skips _image_index.md)
  2. Parses the front-matter of each file:
       - Title     → from the first `# Heading` line
       - Section   → from the `**Category:**` field
       - Source    → from the `**Source:**` field
  3. Splits each file's content into overlapping character chunks
       (CHUNK_SIZE / CHUNK_OVERLAP from config.py)
  4. Assigns stable chunk IDs: <filename_stem>_chunk_<N>
  5. Stores each chunk in ChromaDB with metadata:
       {section, page_number, source_file, source_url, chunk_id, title}
  6. Prints a summary: files processed, chunks stored, time taken

Re-running is safe — the collection is deleted and rebuilt from scratch.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

# Ensure src/ is on the path when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chromadb
from chromadb.utils import embedding_functions

from config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_MODEL,
    KB_MD_DIR,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Files to skip during ingestion
SKIP_FILES = {"_image_index.md"}

# Front-matter patterns
_RE_TITLE    = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_RE_SOURCE   = re.compile(r"\*\*Source:\*\*\s*(.+?)(?:\n|$)")
_RE_CATEGORY = re.compile(r"\*\*Category:\*\*\s*(.+?)(?:\n|$)")

# Strip HTML-style comments (scraper artefacts)
_RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_front_matter(text: str) -> tuple[str, str, str]:
    """
    Extract title, section (category), and source URL from file text.

    Returns:
        (title, section, source_url) — all strings, empty string if missing.
    """
    title_match    = _RE_TITLE.search(text)
    source_match   = _RE_SOURCE.search(text)
    category_match = _RE_CATEGORY.search(text)

    title      = title_match.group(1).strip()    if title_match    else ""
    source_url = source_match.group(1).strip()   if source_match   else ""
    section    = category_match.group(1).strip() if category_match else "General"

    return title, section, source_url


def _clean_text(text: str) -> str:
    """
    Remove noise from markdown text before chunking:
      - HTML comments (scraper artefacts)
      - Collapse 3+ blank lines into 2

    NOTE: The ## Related Images section and all image markdown (![alt](path))
    are intentionally KEPT so the LLM can retrieve and render images in answers.
    """
    # Drop HTML comments only
    text = _RE_HTML_COMMENT.sub("", text)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Heading-aware section splitter
# ---------------------------------------------------------------------------

_RE_HEADING = re.compile(r"^(#{1,3} .+)$", re.MULTILINE)


def _split_by_headings(text: str, max_section_size: int) -> list[str]:
    """
    Split markdown text on ## / ### headings so that each logical section
    (Vision, Mission, Core Values, etc.) becomes its own unit before
    character-level chunking.

    Sections smaller than min_section_size are merged with the next section
    so their embeddings are not too sparse (e.g. a one-line Vision statement
    alone would score poorly against 'what is BVRIT's vision?').

    Sections larger than max_section_size are passed through unchanged —
    the character chunker will further split them.
    """
    MIN_SECTION = 200   # merge sections shorter than this into the next one

    boundaries = [m.start() for m in _RE_HEADING.finditer(text)]

    if len(boundaries) <= 1:
        return [text]

    raw_sections: list[str] = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        section = text[start:end].strip()
        if section:
            raw_sections.append(section)

    # Merge short sections forward into the next one
    merged: list[str] = []
    buf = ""
    for sec in raw_sections:
        if buf:
            buf = buf + "\n\n" + sec
        else:
            buf = sec
        if len(buf) >= MIN_SECTION:
            merged.append(buf)
            buf = ""
    if buf:
        if merged:
            merged[-1] = merged[-1] + "\n\n" + buf   # append leftover to last
        else:
            merged.append(buf)

    return merged if merged else [text]


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

# Minimum content length for a chunk to be kept (filters out degenerate fragments)
_MIN_CHUNK_LEN = 100


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Split `text` into overlapping character-level chunks.

    Strategy:
      - Prefer splitting at paragraph boundaries (\n\n) within the window.
      - Fall back to splitting at sentence boundaries (. ? !) if no paragraph.
      - Hard-split if no natural boundary found.

    Returns a list of non-empty chunk strings.
    """
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            # Try to split at a paragraph boundary within the last 20% of the window
            search_from = start + int(chunk_size * 0.8)
            para_pos = text.rfind("\n\n", search_from, end)
            if para_pos != -1:
                end = para_pos + 2  # include the blank line
            else:
                # Try sentence boundary
                for sep in (". ", "? ", "! ", "\n"):
                    sent_pos = text.rfind(sep, search_from, end)
                    if sent_pos != -1:
                        end = sent_pos + len(sep)
                        break

        chunk = text[start:end].strip()
        if len(chunk) >= _MIN_CHUNK_LEN:
            chunks.append(chunk)

        # Finished reading the file — break to prevent generating
        # degenerate overlapping tail fragments.
        if end == text_len:
            break

        # Advance start with overlap
        next_start = end - overlap
        if next_start <= start:
            next_start = start + 1  # prevent infinite loop on tiny texts
        start = next_start

    return chunks


# ---------------------------------------------------------------------------
# Main ingestion pipeline
# ---------------------------------------------------------------------------

def ingest(
    kb_dir: Path = KB_MD_DIR,
    chroma_dir: Path = CHROMA_DIR,
    collection_name: str = CHROMA_COLLECTION_NAME,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    verbose: bool = True,
) -> dict:
    """
    Full ingestion pipeline: read → parse → chunk → embed → persist.

    Returns a summary dict with stats.
    """
    t0 = time.perf_counter()

    # ---- Validate KB directory ----------------------------------------
    if not kb_dir.exists():
        raise FileNotFoundError(
            f"Knowledge base directory not found: {kb_dir}\n"
            "Set KB_MD_DIR in config.py to the correct path."
        )

    md_files = sorted(
        f for f in kb_dir.glob("*.md")
        if f.name not in SKIP_FILES
    )

    if not md_files:
        raise ValueError(f"No .md files found in {kb_dir}")

    if verbose:
        print(f"[ingest] Knowledge base: {kb_dir}")
        print(f"[ingest] Found {len(md_files)} markdown files")
        print(f"[ingest] Chunk size: {chunk_size} chars | Overlap: {overlap} chars")
        print(f"[ingest] Embedding model: {EMBEDDING_MODEL} (local)")
        print()

    # ---- Set up ChromaDB ----------------------------------------------
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))

    # Delete existing collection so re-runs are idempotent
    existing = [c.name for c in client.list_collections()]
    if collection_name in existing:
        client.delete_collection(collection_name)
        if verbose:
            print(f"[ingest] Deleted existing collection: {collection_name!r}")

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    collection = client.create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "l2"},  # L2 distance (matches retriever expectations)
    )

    if verbose:
        print(f"[ingest] Created collection: {collection_name!r}")
        print()

    # ---- Process each file --------------------------------------------
    all_ids:       list[str]  = []
    all_documents: list[str]  = []
    all_metadatas: list[dict] = []

    files_processed = 0
    files_skipped   = 0

    for md_file in md_files:
        raw = md_file.read_text(encoding="utf-8")
        if not raw.strip():
            files_skipped += 1
            continue

        title, section, source_url = _parse_front_matter(raw)
        clean = _clean_text(raw)

        if not clean:
            files_skipped += 1
            continue

        chunks = []
        for section in _split_by_headings(clean, chunk_size):
            chunks.extend(_chunk_text(section, chunk_size, overlap))
        if not chunks:
            files_skipped += 1
            continue

        stem = md_file.stem  # filename without .md extension

        for chunk_idx, chunk_text in enumerate(chunks):
            chunk_id = f"{stem}_chunk_{chunk_idx:04d}"

            # page_number: use chunk_idx + 1 as a synthetic "page"
            # (the knowledge base has no real page numbers)
            page_number = chunk_idx + 1

            all_ids.append(chunk_id)
            all_documents.append(chunk_text)
            all_metadatas.append({
                "section":     section,
                "title":       title,
                "page_number": page_number,
                "source_file": md_file.name,
                "source_url":  source_url,
                "chunk_id":    chunk_id,
            })

        files_processed += 1
        if verbose:
            print(f"  ✓ {md_file.name:<70}  {len(chunks):>3} chunks  [{section}]")

    if not all_ids:
        raise ValueError("No chunks were produced — check your markdown files.")

    # ---- Batch upsert into ChromaDB -----------------------------------
    # ChromaDB handles embedding internally via the embedding_function
    BATCH_SIZE = 100
    total = len(all_ids)

    if verbose:
        print(f"\n[ingest] Storing {total} chunks in ChromaDB (batch size {BATCH_SIZE})...")

    for batch_start in range(0, total, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total)
        collection.add(
            ids=all_ids[batch_start:batch_end],
            documents=all_documents[batch_start:batch_end],
            metadatas=all_metadatas[batch_start:batch_end],
        )
        if verbose:
            print(f"  → stored chunks {batch_start + 1}–{batch_end} / {total}")

    elapsed = time.perf_counter() - t0

    # ---- Summary -------------------------------------------------------
    summary = {
        "files_found":     len(md_files),
        "files_processed": files_processed,
        "files_skipped":   files_skipped,
        "chunks_stored":   total,
        "collection":      collection_name,
        "chroma_dir":      str(chroma_dir),
        "elapsed_sec":     round(elapsed, 2),
    }

    if verbose:
        print()
        print("=" * 60)
        print(f"  Ingestion complete!")
        print(f"  Files processed : {files_processed}")
        print(f"  Files skipped   : {files_skipped}")
        print(f"  Chunks stored   : {total}")
        print(f"  Collection      : {collection_name!r}")
        print(f"  ChromaDB path   : {chroma_dir}")
        print(f"  Time taken      : {elapsed:.2f}s")
        print("=" * 60)

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ingest()
