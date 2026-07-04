#!/usr/bin/env python3
"""
validate_kb.py
--------------
Quick validation script to check knowledge_base.jsonl quality.
Provides detailed analysis of the extracted data.

Usage:
    python validate_kb.py ./output/knowledge_base.jsonl
"""

import json
import sys
from pathlib import Path
from collections import Counter


def analyze_kb(kb_path: Path):
    """Analyze knowledge base for quality metrics."""
    
    if not kb_path.exists():
        print(f"❌ File not found: {kb_path}")
        sys.exit(1)
    
    stats = {
        "total_records": 0,
        "text_chunks": 0,
        "images": 0,
        "categories": Counter(),
        "sources": set(),
        "content_lengths": [],
        "empty_content": 0,
        "missing_fields": 0,
        "duplicate_ids": set(),
    }
    
    seen_ids = set()
    sample_chunks = []
    
    with open(kb_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"❌ Line {line_num}: Invalid JSON - {e}")
                continue
            
            stats["total_records"] += 1
            
            # Check required fields
            required = {"id", "type", "content", "category", "source_url", "page_title"}
            if not required.issubset(record.keys()):
                stats["missing_fields"] += 1
            
            # Track type
            if record.get("type") == "text":
                stats["text_chunks"] += 1
            elif record.get("type") == "image":
                stats["images"] += 1
            
            # Track category
            stats["categories"][record.get("category", "unknown")] += 1
            
            # Track source
            stats["sources"].add(record.get("source_url"))
            
            # Content length
            content = record.get("content", "")
            stats["content_lengths"].append(len(content))
            if not content.strip():
                stats["empty_content"] += 1
            
            # Check duplicate IDs
            record_id = record.get("id")
            if record_id in seen_ids:
                stats["duplicate_ids"].add(record_id)
            seen_ids.add(record_id)
            
            # Collect samples
            if len(sample_chunks) < 5 and record.get("type") == "text":
                sample_chunks.append((record.get("page_title"), content[:200]))
    
    # Calculate statistics
    avg_length = sum(stats["content_lengths"]) / len(stats["content_lengths"]) if stats["content_lengths"] else 0
    
    # Print report
    print("\n" + "="*70)
    print("KNOWLEDGE BASE ANALYSIS")
    print("="*70)
    
    print(f"\n📊 OVERVIEW")
    print(f"  Total records: {stats['total_records']:,}")
    print(f"  Text chunks: {stats['text_chunks']:,}")
    print(f"  Images: {stats['images']:,}")
    print(f"  Unique source pages: {len(stats['sources']):,}")
    
    print(f"\n📝 CONTENT QUALITY")
    print(f"  Avg content length: {avg_length:.0f} chars")
    print(f"  Min length: {min(stats['content_lengths']) if stats['content_lengths'] else 0}")
    print(f"  Max length: {max(stats['content_lengths']) if stats['content_lengths'] else 0}")
    print(f"  Empty content records: {stats['empty_content']}")
    
    print(f"\n🏷️  CATEGORY DISTRIBUTION")
    for cat, count in stats["categories"].most_common():
        pct = (count / stats['total_records']) * 100
        print(f"  {cat:20s}: {count:5,} ({pct:5.1f}%)")
    
    print(f"\n⚠️  DATA QUALITY ISSUES")
    issues = 0
    if stats["missing_fields"] > 0:
        print(f"  ❌ Records with missing fields: {stats['missing_fields']}")
        issues += 1
    if stats["duplicate_ids"]:
        print(f"  ❌ Duplicate IDs found: {len(stats['duplicate_ids'])}")
        issues += 1
    if stats["empty_content"] > 0:
        print(f"  ⚠️  Records with empty content: {stats['empty_content']}")
        issues += 1
    
    if issues == 0:
        print(f"  ✅ No critical issues found!")
    
    print(f"\n📋 SAMPLE TEXT CHUNKS (first 200 chars)")
    for i, (title, content) in enumerate(sample_chunks[:3], 1):
        print(f"\n  {i}. {title}")
        print(f"     {content}...")
    
    print("\n" + "="*70)
    
    # Return summary for programmatic use
    return {
        "total": stats["total_records"],
        "text": stats["text_chunks"],
        "images": stats["images"],
        "issues": issues,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_kb.py <knowledge_base.jsonl>")
        sys.exit(1)
    
    kb_path = Path(sys.argv[1])
    results = analyze_kb(kb_path)
    
    # Exit with error code if issues found
    sys.exit(1 if results["issues"] > 0 else 0)
