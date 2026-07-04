"""
chunker.py
----------
Splits cleaned Markdown page content into ~500-700 token chunks with
~15% overlap, breaking on paragraph/heading boundaries rather than
mid-sentence. Attaches metadata (source_url, page_title, category,
scraped_at) to every chunk.

Token counting uses a simple whitespace-based approximation (~1.5 tokens
per word for modern tokenizers like GPT-4, Claude 3, Gemini). This
conservative estimate helps prevent oversized chunks while maintaining
consistency.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

TARGET_MIN_TOKENS = 500
TARGET_MAX_TOKENS = 700
OVERLAP_RATIO = 0.15


def approx_token_count(text: str) -> int:
    """Rough token estimate: ~1.5 tokens per whitespace-separated word.
    
    Modern tokenizers (GPT-4, Claude 3, Gemini) typically produce 1.3-1.5 tokens
    per word for English prose. Using 1.5x provides a conservative estimate that
    helps prevent oversized chunks.
    """
    words = text.split()
    return int(len(words) * 1.5)
    return int(len(words) * 1.3)


def split_into_blocks(markdown: str) -> list[str]:
    """Split markdown into paragraph/heading-level blocks (never mid-sentence).
    
    Preserves code blocks (fenced with ```) and tables as atomic units.
    """
    blocks = []
    current_block = []
    in_code_block = False
    in_table = False
    
    lines = markdown.split('\n')
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Track code block boundaries
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            current_block.append(line)
            if not in_code_block:  # End of code block
                blocks.append('\n'.join(current_block).strip())
                current_block = []
            continue
        
        # Inside code block - accumulate everything
        if in_code_block:
            current_block.append(line)
            continue
        
        # Track table boundaries (lines starting with |)
        if stripped.startswith('|'):
            if not in_table:
                # Flush any accumulated non-table content
                if current_block:
                    blocks.append('\n'.join(current_block).strip())
                    current_block = []
                in_table = True
            current_block.append(line)
            continue
        elif in_table:
            # End of table - flush it
            blocks.append('\n'.join(current_block).strip())
            current_block = []
            in_table = False
        
        # Regular content - split on blank lines and headings
        if not stripped:  # Blank line
            if current_block:
                blocks.append('\n'.join(current_block).strip())
                current_block = []
        elif stripped.startswith('#'):  # Heading
            if current_block:
                blocks.append('\n'.join(current_block).strip())
                current_block = []
            current_block.append(line)
        else:
            current_block.append(line)
    
    # Flush remaining content
    if current_block:
        blocks.append('\n'.join(current_block).strip())
    
    # Filter out empty blocks
    return [b for b in blocks if b]


@dataclass
class Chunk:
    id: str
    content: str
    source_url: str
    page_title: str
    category: str
    scraped_at: str
    chunk_index: int
    token_estimate: int


def chunk_markdown(
    markdown: str,
    source_url: str,
    page_title: str,
    category: str,
    scraped_at: Optional[str] = None,
) -> list[Chunk]:
    scraped_at = scraped_at or datetime.now(timezone.utc).isoformat()
    blocks = split_into_blocks(markdown)
    if not blocks:
        return []

    chunks: list[Chunk] = []
    current_blocks: list[str] = []
    current_tokens = 0
    chunk_index = 0

    def flush(next_start_blocks: list[str] = None):
        nonlocal current_blocks, current_tokens, chunk_index
        if not current_blocks:
            return
        content = "\n\n".join(current_blocks).strip()
        chunks.append(
            Chunk(
                id=str(uuid.uuid4()),
                content=content,
                source_url=source_url,
                page_title=page_title,
                category=category,
                scraped_at=scraped_at,
                chunk_index=chunk_index,
                token_estimate=approx_token_count(content),
            )
        )
        chunk_index += 1

    i = 0
    while i < len(blocks):
        block = blocks[i]
        block_tokens = approx_token_count(block)

        # A single block larger than max on its own: hard-split it by sentence.
        if block_tokens > TARGET_MAX_TOKENS:
            if current_blocks:
                flush()
                current_blocks = []
                current_tokens = 0
            sentence_chunks = _split_oversized_block(block)
            for sc in sentence_chunks:
                current_blocks = [sc]
                current_tokens = approx_token_count(sc)
                flush()
            current_blocks = []
            current_tokens = 0
            i += 1
            continue

        if current_tokens + block_tokens > TARGET_MAX_TOKENS and current_tokens >= TARGET_MIN_TOKENS:
            # finalize current chunk, then start new one with overlap
            flush()
            overlap_tokens_target = int(current_tokens * OVERLAP_RATIO)
            overlap_blocks = _take_overlap(current_blocks, overlap_tokens_target)
            current_blocks = overlap_blocks
            current_tokens = sum(approx_token_count(b) for b in current_blocks)
            continue  # re-evaluate this block against the new (overlap-seeded) chunk

        current_blocks.append(block)
        current_tokens += block_tokens
        i += 1

    if current_blocks:
        flush()

    return chunks


def _take_overlap(blocks: list[str], target_tokens: int) -> list[str]:
    """Take trailing blocks from the previous chunk to seed overlap,
    without exceeding target_tokens too much."""
    overlap = []
    total = 0
    for block in reversed(blocks):
        t = approx_token_count(block)
        if total + t > target_tokens and overlap:
            break
        overlap.insert(0, block)
        total += t
        if total >= target_tokens:
            break
    return overlap


def _split_oversized_block(block: str) -> list[str]:
    """Split an oversized single block (e.g. a huge table or long paragraph)
    into sentence-bounded pieces near TARGET_MAX_TOKENS.
    
    Uses a more robust sentence splitter that handles common abbreviations.
    """
    # Split on sentence-ending punctuation followed by space and capital letter
    # This is more reliable than lookbehind patterns with variable width
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', block)
    
    # If no splits happened (no capital letters after periods), fall back to simpler split
    if len(sentences) == 1 and len(block) > TARGET_MAX_TOKENS * 2:
        sentences = re.split(r'(?<=[.!?])\s+', block)
    
    # Post-process to rejoin common abbreviations that got split incorrectly
    # Common academic/professional abbreviations
    abbreviations = ['Dr', 'Mr', 'Mrs', 'Ms', 'Prof', 'Sr', 'Jr', 'vs', 'etc', 
                     'Inc', 'Ltd', 'Corp', 'Ph.D', 'M.D', 'B.Tech', 'M.Tech', 'St']
    
    cleaned_sentences = []
    i = 0
    while i < len(sentences):
        current_sent = sentences[i]
        # Check if this sentence is just an abbreviation
        if i < len(sentences) - 1:
            # If current sentence ends with a common abbreviation, merge with next
            should_merge = False
            for abbr in abbreviations:
                if current_sent.rstrip().endswith(abbr + '.'):
                    should_merge = True
                    break
            
            if should_merge and i + 1 < len(sentences):
                current_sent = current_sent + ' ' + sentences[i + 1]
                i += 2
                cleaned_sentences.append(current_sent)
                continue
        
        cleaned_sentences.append(current_sent)
        i += 1
    
    sentences = cleaned_sentences
    
    pieces = []
    current = []
    current_tokens = 0
    for sentence in sentences:
        st = approx_token_count(sentence)
        if current_tokens + st > TARGET_MAX_TOKENS and current:
            pieces.append(" ".join(current))
            current = []
            current_tokens = 0
        current.append(sentence)
        current_tokens += st
    if current:
        pieces.append(" ".join(current))
    return pieces
