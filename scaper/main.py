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
import logging
import signal
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

from crawler import Crawler
from extractor import extract_page, download_image, ExtractedImage
from chunker import chunk_markdown


# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


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
        # Skip large HTML files — BeautifulSoup + recursive markdown conversion
        # can hang for minutes on deeply-nested Elementor pages (200KB+ of divs).
        # These pages rarely contain dense prose useful for RAG anyway.
        file_size = html_path.stat().st_size
        if file_size > 500_000:  # 500 KB limit — pages larger than this are usually
            # giant data-dump tables (patents list etc.) with no useful prose
            logger.warning(f"[SKIP-SIZE] {html_path.name} ({file_size // 1024}KB) - exceeds 500KB limit")
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        yield html_path, meta


def build_knowledge_base(args) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    kb_path = output_dir / "knowledge_base.jsonl"
    errors_path = output_dir / "extraction_errors.jsonl"

    session = requests.Session()
    scraped_at_default = datetime.now(timezone.utc).isoformat()

    total_text_chunks = 0
    total_images = 0
    skipped_pages = 0
    
    # Track errors for aggregation
    extraction_errors = []

    # Collect all HTML files first to show progress bar
    html_files = list(iter_saved_html(output_dir))
    
    with open(kb_path, "w", encoding="utf-8") as kb_file:
        # Progress bar showing page processing
        for html_path, meta in tqdm(html_files, desc="Processing pages", unit="page"):
            url = meta.get("url", "")
            scraped_at = meta.get("fetched_at", scraped_at_default)

            html = html_path.read_text(encoding="utf-8", errors="ignore")
            try:
                # Hard 30-second timeout per page — deeply-nested Elementor div
                # trees can cause the recursive markdown converter to stall.
                def _timeout_handler(signum, frame):
                    raise TimeoutError(f"extraction timed out after 30s")
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(30)
                try:
                    page = extract_page(html, url)
                finally:
                    signal.alarm(0)  # cancel alarm
            except TimeoutError as exc:
                logger.warning(f"[SKIP-TIMEOUT] {html_path.name} — {exc}")
                skipped_pages += 1
                extraction_errors.append({
                    "url": url,
                    "error": str(exc),
                    "error_type": "TimeoutError",
                    "html_file": str(html_path),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                continue
            except Exception as exc:
                logger.error(f"[SKIP-ERROR] {html_path.name} — {exc}")
                skipped_pages += 1
                # Aggregate error info
                extraction_errors.append({
                    "url": url,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "html_file": str(html_path),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
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

    logger.info(f"Knowledge base written to: {kb_path}")
    logger.info(f"  Text chunks: {total_text_chunks}")
    logger.info(f"  Images: {total_images}")
    logger.info(f"  Pages skipped (extraction errors): {skipped_pages}")
    
    # Write extraction errors to file for investigation
    if extraction_errors:
        with open(errors_path, "w", encoding="utf-8") as errors_file:
            for error in extraction_errors:
                errors_file.write(json.dumps(error, ensure_ascii=False) + "\n")
        logger.warning(f"Extraction errors logged to: {errors_path}")
    else:
        logger.info("No extraction errors occurred")


def _image_context_text(image: ExtractedImage) -> str:
    parts = []
    if image.alt:
        parts.append(f"Alt text: {image.alt}")
    if image.caption:
        parts.append(f"Caption/context: {image.caption}")
    if not parts:
        parts.append("(no alt text or caption available)")
    return " | ".join(parts)


def validate_knowledge_base(kb_path: Path) -> dict:
    """Validate the knowledge_base.jsonl file for completeness and correctness.
    
    Returns:
        dict with validation results including errors, warnings, and stats
    """
    errors = []
    warnings = []
    stats = {
        "total_records": 0,
        "text_chunks": 0,
        "images": 0,
        "categories": {},
    }
    seen_ids = set()
    
    required_fields = {"id", "type", "content", "category", "source_url", "page_title", "scraped_at"}
    valid_types = {"text", "image"}
    valid_categories = {"faculty", "admission_info", "placement_stat", "department", "news", "facility", "general"}
    
    if not kb_path.exists():
        errors.append(f"Knowledge base file not found: {kb_path}")
        return {"errors": errors, "warnings": warnings, "stats": stats}
    
    line_num = 0
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            for line in f:
                line_num += 1
                line = line.strip()
                if not line:
                    continue
                
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_num}: Invalid JSON - {e}")
                    continue
                
                stats["total_records"] += 1
                
                # Check required fields
                missing_fields = required_fields - set(record.keys())
                if missing_fields:
                    errors.append(f"Line {line_num}: Missing required fields: {missing_fields}")
                
                # Check for duplicate IDs
                record_id = record.get("id")
                if record_id:
                    if record_id in seen_ids:
                        errors.append(f"Line {line_num}: Duplicate ID: {record_id}")
                    seen_ids.add(record_id)
                
                # Validate type
                record_type = record.get("type")
                if record_type not in valid_types:
                    errors.append(f"Line {line_num}: Invalid type '{record_type}', must be one of {valid_types}")
                elif record_type == "text":
                    stats["text_chunks"] += 1
                elif record_type == "image":
                    stats["images"] += 1
                
                # Validate category
                category = record.get("category")
                if category not in valid_categories:
                    warnings.append(f"Line {line_num}: Unknown category '{category}'")
                stats["categories"][category] = stats["categories"].get(category, 0) + 1
                
                # Check content is not empty
                content = record.get("content", "").strip()
                if not content:
                    warnings.append(f"Line {line_num}: Empty content field")
                
                # Check source URL is present
                source_url = record.get("source_url", "").strip()
                if not source_url:
                    warnings.append(f"Line {line_num}: Empty source_url")
    
    except Exception as e:
        errors.append(f"Fatal error reading file: {e}")
    
    return {
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
    }


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
        logger.info("Starting crawl...")
        run_crawl(args)
    else:
        logger.info("Skipping crawl, reusing existing raw_html/")

    logger.info("Extracting + chunking + building knowledge_base.jsonl ...")
    build_knowledge_base(args)
    
    # Validate the output
    logger.info("Validating knowledge_base.jsonl ...")
    kb_path = Path(args.output_dir) / "knowledge_base.jsonl"
    validation_results = validate_knowledge_base(kb_path)
    
    # Print validation results
    print(f"\n{'='*70}")
    print("VALIDATION RESULTS")
    print(f"{'='*70}")
    print(f"Total records: {validation_results['stats']['total_records']}")
    print(f"  Text chunks: {validation_results['stats']['text_chunks']}")
    print(f"  Images: {validation_results['stats']['images']}")
    print(f"\nCategory breakdown:")
    for cat, count in sorted(validation_results['stats']['categories'].items()):
        print(f"  {cat}: {count}")
    
    if validation_results['errors']:
        print(f"\n❌ ERRORS ({len(validation_results['errors'])}):")
        for error in validation_results['errors'][:10]:  # Show first 10
            print(f"  - {error}")
        if len(validation_results['errors']) > 10:
            print(f"  ... and {len(validation_results['errors']) - 10} more")
    else:
        print("\n✓ No errors found")
    
    if validation_results['warnings']:
        print(f"\n⚠ WARNINGS ({len(validation_results['warnings'])}):")
        for warning in validation_results['warnings'][:10]:  # Show first 10
            print(f"  - {warning}")
        if len(validation_results['warnings']) > 10:
            print(f"  ... and {len(validation_results['warnings']) - 10} more")
    else:
        print("✓ No warnings")
    
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
