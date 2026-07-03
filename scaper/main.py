#!/usr/bin/env python3
"""
main.py
-------
CLI entry point that runs the full pipeline:
  1. Crawl bvrithyderabad.edu.in (crawler.py)
  2. Extract cleaned text + images from saved HTML (extractor.py)
  3. Chunk text into ~500-700 token pieces with overlap (chunker.py)
  4. Write everything out to a single knowledge_base.jsonl

Usage:
    python main.py --max-depth 4 --max-pages 800 --output-dir ./output --concurrency 5
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from crawler import Crawler
from extractor import extract_page, download_image, ExtractedImage
from chunker import chunk_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl bvrithyderabad.edu.in and build a RAG knowledge base."
    )
    parser.add_argument("--max-depth", type=int, default=4, help="Max BFS crawl depth")
    parser.add_argument("--max-pages", type=int, default=800, help="Max pages to crawl")
    parser.add_argument(
        "--output-dir", type=str, default="./output", help="Directory for all outputs"
    )
    parser.add_argument(
        "--concurrency", type=int, default=5, help="Max concurrent requests (capped at 5)"
    )
    parser.add_argument(
        "--skip-crawl",
        action="store_true",
        help="Skip crawling and reuse previously saved raw_html/ (useful for re-running "
        "extraction/chunking only)",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Skip downloading images (text-only knowledge base)",
    )
    return parser.parse_args()


def run_crawl(args) -> list[Path]:
    crawler = Crawler(
        output_dir=args.output_dir,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        concurrency=args.concurrency,
    )
    return crawler.crawl()


def iter_saved_html(output_dir: Path):
    raw_dir = output_dir / "raw_html"
    for html_path in sorted(raw_dir.glob("*.html")):
        meta_path = raw_dir / f"{html_path.stem}.meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        yield html_path, meta


def build_knowledge_base(args) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    kb_path = output_dir / "knowledge_base.jsonl"

    session = requests.Session()
    scraped_at_default = datetime.now(timezone.utc).isoformat()

    total_text_chunks = 0
    total_images = 0
    skipped_pages = 0

    with open(kb_path, "w", encoding="utf-8") as kb_file:
        for html_path, meta in iter_saved_html(output_dir):
            url = meta.get("url", "")
            scraped_at = meta.get("fetched_at", scraped_at_default)

            html = html_path.read_text(encoding="utf-8", errors="ignore")
            try:
                page = extract_page(html, url)
            except Exception as exc:
                print(f"[warn] failed to extract {url}: {exc}")
                skipped_pages += 1
                continue

            if not page.markdown or len(page.markdown.strip()) < 30:
                # near-empty page (e.g. redirect stub, gallery-only page) -- still
                # process images below, but skip text chunking
                pass
            else:
                chunks = chunk_markdown(
                    markdown=page.markdown,
                    source_url=page.url,
                    page_title=page.title,
                    category=page.category,
                    scraped_at=scraped_at,
                )
                for chunk in chunks:
                    record = {
                        "id": chunk.id,
                        "type": "text",
                        "content": chunk.content,
                        "category": chunk.category,
                        "source_url": chunk.source_url,
                        "page_title": chunk.page_title,
                        "image_path": None,
                        "scraped_at": chunk.scraped_at,
                    }
                    kb_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total_text_chunks += 1

            if not args.skip_images:
                for image in page.images:
                    ok = download_image(image, images_dir, session=session)
                    if not ok:
                        continue
                    record = {
                        "id": str(uuid.uuid4()),
                        "type": "image",
                        "content": _image_context_text(image),
                        "category": page.category,
                        "source_url": page.url,
                        "page_title": page.title,
                        "image_path": image.local_path,
                        "scraped_at": scraped_at,
                    }
                    kb_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total_images += 1

    print(
        f"[info] knowledge base written: {kb_path}\n"
        f"       text chunks: {total_text_chunks}\n"
        f"       images: {total_images}\n"
        f"       pages skipped (extraction errors): {skipped_pages}"
    )


def _image_context_text(image: ExtractedImage) -> str:
    parts = []
    if image.alt:
        parts.append(f"Alt text: {image.alt}")
    if image.caption:
        parts.append(f"Caption/context: {image.caption}")
    if not parts:
        parts.append("(no alt text or caption available)")
    return " | ".join(parts)


def main() -> None:
    args = parse_args()

    if not args.skip_crawl:
        print("[info] starting crawl...")
        run_crawl(args)
    else:
        print("[info] skipping crawl, reusing existing raw_html/")

    print("[info] extracting + chunking + building knowledge_base.jsonl ...")
    build_knowledge_base(args)


if __name__ == "__main__":
    main()
