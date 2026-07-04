"""
retriever.py
------------
Wrapper around ChromaDB that provides semantic retrieval for the BVRIT FAQ chatbot.

Embeddings use ChromaDB's built-in sentence-transformers function (local, no API key).
The same model must be used at ingest time (ingest.py) and query time (here).

Responsibilities:
  - Load the persisted ChromaDB collection (built by ingest.py)
  - Embed a query using the local sentence-transformers model
  - Return top-k most similar chunks with text, metadata, and similarity score
  - Support optional metadata filtering by section name
  - Expose index status for the UI sidebar
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chromadb
from chromadb.utils import embedding_functions

from config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_DIR,
    EMBEDDING_MODEL,
    TOP_K,
)


class Retriever:
    """
    Semantic retriever backed by a persistent ChromaDB collection.

    Usage:
        retriever = Retriever()
        chunks = retriever.retrieve("What is the CSE fee?", k=5)
    """

    def __init__(self) -> None:
        self._client: chromadb.PersistentClient | None = None
        self._collection = None
        self._embedding_fn = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Connect to the persisted ChromaDB collection.
        Uses local sentence-transformers for embedding (no API key needed).
        Raises RuntimeError if the collection does not exist yet (ingest.py not run).
        """
        # Local embedding via sentence-transformers — downloads model on first use (~80MB)
        self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )

        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))

        existing = [c.name for c in self._client.list_collections()]
        if CHROMA_COLLECTION_NAME not in existing:
            raise RuntimeError(
                f"ChromaDB collection '{CHROMA_COLLECTION_NAME}' not found at {CHROMA_DIR}. "
                "Run `python src/ingest.py` first to build the index."
            )

        self._collection = self._client.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=self._embedding_fn,
        )
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def chunk_count(self) -> int:
        if not self._loaded:
            return 0
        return self._collection.count()

    def retrieve(
        self,
        query: str,
        k: int = TOP_K,
        section_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Retrieve top-k chunks most similar to `query`.

        Args:
            query:          Natural-language question.
            k:              Number of chunks to return.
            section_filter: If set, restrict results to chunks in this section.

        Returns:
            List of dicts:
            {
                "id":       str,
                "content":  str,
                "metadata": {"section": ..., "page_number": ..., "source_file": ..., "chunk_id": ...},
                "score":    float,   # L2 distance — lower = more similar
            }
        """
        if not self._loaded:
            raise RuntimeError("Retriever not loaded. Call retriever.load() first.")

        where_filter = None
        if section_filter:
            where_filter = {"section": {"$eq": section_filter}}

        n = min(k, self.chunk_count) if self.chunk_count > 0 else k

        results = self._collection.query(
            query_texts=[query],
            n_results=n,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for cid, doc, meta, dist in zip(ids, documents, metadatas, distances):
            chunks.append(
                {
                    "id": cid,
                    "content": doc,
                    "metadata": meta or {},
                    "score": round(dist, 4),
                }
            )

        return chunks

    def get_available_sections(self) -> list[str]:
        """Return sorted list of unique section names (for the sidebar filter dropdown)."""
        if not self._loaded:
            return []
        result = self._collection.get(limit=1000, include=["metadatas"])
        sections = set()
        for meta in result.get("metadatas", []):
            if meta and meta.get("section"):
                sections.add(meta["section"])
        return sorted(sections)

    def status(self) -> dict:
        return {
            "loaded": self._loaded,
            "collection": CHROMA_COLLECTION_NAME,
            "chunk_count": self.chunk_count,
            "chroma_dir": str(CHROMA_DIR),
            "embedding_model": EMBEDDING_MODEL,
            "embedding_provider": "local (sentence-transformers)",
        }


# ---------------------------------------------------------------------------
# Singleton — import this in other modules
# ---------------------------------------------------------------------------
retriever = Retriever()


# ---------------------------------------------------------------------------
# Quick smoke-test: python retriever.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Loading retriever...")
    retriever.load()
    print(f"Status: {retriever.status()}")
    sections = retriever.get_available_sections()
    print(f"Sections ({len(sections)}): {sections}")
    query = "What is the CSE tuition fee?"
    print(f"\nQuery: {query}")
    for r in retriever.retrieve(query, k=3):
        print(f"  [{r['score']:.4f}] {r['metadata'].get('section','?')} | {r['content'][:120]}...")
