#!/usr/bin/env python3
"""
embed.py (optional)
--------------------
Reads knowledge_base.jsonl and generates embeddings, storing them in a
local vector DB (Chroma by default, FAISS as an alternative) so a RAG
chatbot can query the knowledge base.

This script only embeds "text" records by default (image records carry
alt-text/caption content and can optionally be embedded too via
--include-images, since that text is often useful for retrieval).

Requires an embedding model. Two options are supported out of the box:

  1. --provider local   -> sentence-transformers (all-MiniLM-L6-v2), fully
                            offline, no API key needed. Recommended default.
  2. --provider openai   -> OpenAI text-embedding-3-small via the `openai`
                            package. Requires OPENAI_API_KEY env var.

Usage:
    python embed.py --input ./output/knowledge_base.jsonl \
                     --db chroma --db-path ./output/chroma_db \
                     --provider local

    python embed.py --input ./output/knowledge_base.jsonl \
                     --db faiss --db-path ./output/faiss_index \
                     --provider local
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed knowledge_base.jsonl into a vector DB")
    parser.add_argument("--input", type=str, default="./output/knowledge_base.jsonl")
    parser.add_argument("--db", choices=["chroma", "faiss"], default="chroma")
    parser.add_argument("--db-path", type=str, default="./output/vector_db")
    parser.add_argument("--provider", choices=["local", "openai"], default="local")
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override embedding model name (default: all-MiniLM-L6-v2 for local, "
        "text-embedding-3-small for openai)",
    )
    parser.add_argument(
        "--include-images",
        action="store_true",
        help="Also embed image records (using their alt text/caption content)",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


def load_records(path: Path, include_images: bool):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("type") == "image" and not include_images:
                continue
            if not rec.get("content"):
                continue
            records.append(rec)
    return records


def get_local_embedder(model_name: str):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def embed(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, show_progress_bar=False).tolist()

    return embed


def get_openai_embedder(model_name: str):
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def embed(texts: list[str]) -> list[list[float]]:
        resp = client.embeddings.create(model=model_name, input=texts)
        return [item.embedding for item in resp.data]

    return embed


def store_chroma(records, embed_fn, db_path: str, batch_size: int) -> None:
    import chromadb

    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection("bvrit_knowledge_base")

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        texts = [r["content"] for r in batch]
        embeddings = embed_fn(texts)
        collection.add(
            ids=[r["id"] for r in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "type": r.get("type", "text"),
                    "category": r.get("category", "general"),
                    "source_url": r.get("source_url", ""),
                    "page_title": r.get("page_title", ""),
                    "image_path": r.get("image_path") or "",
                    "scraped_at": r.get("scraped_at", ""),
                }
                for r in batch
            ],
        )
        print(f"[info] embedded {min(i + batch_size, len(records))}/{len(records)} records")

    print(f"[info] Chroma collection persisted at {db_path}")


def store_faiss(records, embed_fn, db_path: str, batch_size: int) -> None:
    import faiss
    import numpy as np

    all_embeddings = []
    metadata_store = []

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        texts = [r["content"] for r in batch]
        embeddings = embed_fn(texts)
        all_embeddings.extend(embeddings)
        metadata_store.extend(batch)
        print(f"[info] embedded {min(i + batch_size, len(records))}/{len(records)} records")

    matrix = np.array(all_embeddings, dtype="float32")
    dim = matrix.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(matrix)

    db_dir = Path(db_path)
    db_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(db_dir / "index.faiss"))

    with open(db_dir / "metadata.jsonl", "w", encoding="utf-8") as f:
        for rec in metadata_store:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[info] FAISS index + metadata persisted at {db_dir}")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"knowledge base file not found: {input_path}")

    records = load_records(input_path, include_images=args.include_images)
    if not records:
        raise SystemExit("no embeddable records found in knowledge base")

    if args.provider == "local":
        model_name = args.model or "all-MiniLM-L6-v2"
        embed_fn = get_local_embedder(model_name)
    else:
        model_name = args.model or "text-embedding-3-small"
        embed_fn = get_openai_embedder(model_name)

    print(f"[info] embedding {len(records)} records with provider={args.provider} model={model_name}")

    if args.db == "chroma":
        store_chroma(records, embed_fn, args.db_path, args.batch_size)
    else:
        store_faiss(records, embed_fn, args.db_path, args.batch_size)


if __name__ == "__main__":
    main()
