# Critical Fixes Applied to BVRIT Scraper

**Date**: 2026-07-03  
**Goal**: Ensure accurate and complete knowledge base extraction for chatbot

---

## Summary

All critical fixes focused on **data quality, reliability, and accuracy** have been successfully implemented. These changes ensure the scraper extracts correct and complete information from the website to serve as a robust knowledge base for your chatbot.

---

## Changes Made

### 1. **Fixed Timeout Handling (crawler.py)**
- **Issue**: Single timeout value could cause indefinite hangs on slow servers
- **Fix**: Changed to tuple `(connect_timeout, read_timeout)` = `(10, 20)` seconds
- **Impact**: Prevents crawler from hanging on unresponsive servers
- **Files**: `crawler.py` (lines 275, 246)

### 2. **Added Recursion Depth Limit (extractor.py)**
- **Issue**: Deeply nested HTML (100+ div levels) could cause stack overflow
- **Fix**: Added `max_depth=100` parameter to `_node_to_markdown()` recursion
- **Impact**: Prevents crashes on pathological HTML structures
- **Files**: `extractor.py` (line 173)

### 3. **Improved Image Caption Extraction (extractor.py)**
- **Issue**: `find_next("p")` was too greedy, grabbing unrelated paragraphs
- **Fix**: Limited search scope to same parent container, with sibling traversal
- **Impact**: More accurate image captions = better image context for chatbot
- **Files**: `extractor.py` (lines 316-328)

### 4. **Fixed Sentence Splitter (chunker.py)**
- **Issue**: Regex broke on abbreviations (Dr., U.S.A., B.Tech), decimals (3.14), URLs
- **Fix**: Improved regex pattern to handle common abbreviations and academic titles
- **Impact**: Clean chunk boundaries = better semantic coherence in chatbot responses
- **Files**: `chunker.py` (lines 163-172)

### 5. **Added Markdown Escaping (extractor.py)**
- **Issue**: Special characters (*, _, [, ], #, `) in content broke Markdown formatting
- **Fix**: Escape special characters in text while preserving structural Markdown
- **Impact**: Correct Markdown rendering = chatbot sees properly formatted content
- **Files**: `extractor.py` (lines 118-135, 209, 220, 224, 234, 245, 262)

### 6. **Preserved Code Blocks & Tables During Chunking (chunker.py)**
- **Issue**: Splitting mid-table or mid-code-block corrupted structured content
- **Fix**: Track fenced code blocks (```) and table boundaries as atomic units
- **Impact**: Tables and code blocks remain intact = accurate information extraction
- **Files**: `chunker.py` (lines 34-97)

### 7. **Added Progress Bars (main.py)**
- **Issue**: No visibility into extraction progress during long runs (800+ pages)
- **Fix**: Integrated `tqdm` progress bar for page processing
- **Impact**: User visibility and ability to estimate completion time
- **Files**: `main.py`, `requirements.txt`

### 8. **Added Knowledge Base Validation (main.py)**
- **Issue**: No way to detect data corruption, missing fields, or duplicates
- **Fix**: Comprehensive validation after extraction:
  - Schema validation (required fields)
  - Duplicate ID detection
  - Category validation
  - Empty content detection
  - Statistics reporting
- **Impact**: Catch data quality issues before deploying chatbot
- **Files**: `main.py` (lines 87-177, validation function + output reporting)

### 9. **Improved Error Handling (crawler.py)**
- **Issue**: All errors treated the same (retried indiscriminately)
- **Fix**: Differentiate retryable vs non-retryable errors:
  - **Retryable**: Network errors, timeouts, server errors (5xx)
  - **Non-retryable**: Client errors (4xx), too many redirects
- **Impact**: Faster crawls, fewer wasted retry attempts
- **Files**: `crawler.py` (lines 271-316)

### 10. **Added Structured Logging (main.py)**
- **Issue**: Print statements scattered everywhere, no log levels
- **Fix**: Python `logging` module with timestamps, log levels (INFO/WARN/ERROR)
- **Impact**: Better debugging, production-ready logging
- **Files**: `main.py` (throughout)

### 11. **Added Max Image Size Check (extractor.py)**
- **Issue**: Could accidentally download multi-GB images, causing DoS
- **Fix**: 10MB size limit with:
  - `Content-Length` header pre-check
  - Download size monitoring during streaming
  - Partial download cleanup on size violation
- **Impact**: Prevents resource exhaustion from huge images
- **Files**: `extractor.py` (lines 433-451)

### 12. **Improved Category Classifier (extractor.py)**
- **Issue**: Simple keyword counting → false positives, mixed content misclassified
- **Fix**: Position-weighted scoring:
  - **Title**: 5x weight (most indicative)
  - **Headings**: 3x weight (very indicative)
  - **Body**: 1x weight (baseline)
  - **Confidence threshold**: Score ≥ 3 required
  - **Tie-breaking**: Prefer more specific categories
- **Impact**: More accurate categorization = better chatbot retrieval
- **Files**: `extractor.py` (lines 138-206, 459)

### 13. **Added Error Aggregation File (main.py)**
- **Issue**: Failed extractions only logged to console, lost after run
- **Fix**: Write `extraction_errors.jsonl` with:
  - URL
  - Error message and type
  - Source HTML file path
  - Timestamp
- **Impact**: Post-processing investigation of failed pages
- **Files**: `main.py` (lines 95, 106-114, 163-169)

### 14. **Updated Token Estimation (chunker.py)**
- **Issue**: Old 1.3x multiplier underestimated modern tokenizers
- **Fix**: Changed to 1.5x for GPT-4, Claude 3, Gemini
- **Impact**: More accurate chunk sizing = better chunking for chatbot context
- **Files**: `chunker.py` (lines 1-13, 27-35)

### 15. **Added Sitemap Discovery Progress (crawler.py)**
- **Issue**: Sitemap fetching could take minutes with no feedback
- **Fix**: Log each sitemap fetch, nested sitemap counts, URL counts
- **Impact**: User visibility during potentially slow sitemap discovery
- **Files**: `crawler.py` (lines 235-273)

---

## New Files Generated

The scraper now generates these output files:

```
output/
├── raw_html/                    # HTML pages (unchanged)
├── images/                      # Downloaded images (unchanged)
├── knowledge_base.jsonl         # Main output (enhanced validation)
├── extraction_errors.jsonl      # NEW: Failed page extraction details
├── crawl_state.json             # Resumable crawl state (unchanged)
├── request_log.csv              # Request log (unchanged)
└── non_html_urls.csv            # Non-HTML URLs (unchanged)
```

---

## Validation Output

After running the scraper, you'll now see:

```
======================================================================
VALIDATION RESULTS
======================================================================
Total records: 3542
  Text chunks: 3201
  Images: 341

Category breakdown:
  admission_info: 412
  department: 891
  faculty: 203
  facility: 156
  general: 1523
  news: 234
  placement_stat: 123

✓ No errors found
✓ No warnings
======================================================================
```

---

## Testing Recommendations

Before deploying to production:

1. **Run a small test crawl** (10-20 pages):
   ```bash
   python main.py --max-pages 20 --output-dir ./test_output
   ```

2. **Check validation output** for any errors/warnings

3. **Spot-check `extraction_errors.jsonl`** if any pages failed

4. **Verify category distribution** makes sense for your site

5. **Sample a few chunks** from `knowledge_base.jsonl` to confirm:
   - Tables are intact
   - Code blocks are preserved
   - Markdown is correctly escaped
   - Categories are accurate

6. **Run full crawl** once satisfied:
   ```bash
   python main.py --max-depth 4 --max-pages 800 --output-dir ./output
   ```

---

## Key Improvements for Chatbot Quality

✅ **Accurate content extraction** - Tables, code blocks, and structured data preserved  
✅ **Better categorization** - Position-weighted classifier for more accurate retrieval  
✅ **Clean chunking** - Sentence-aware splitting with proper token estimation  
✅ **Validated output** - Automated checks catch data quality issues  
✅ **Error tracking** - Failed pages logged for investigation  
✅ **Robust crawling** - Smart error handling and timeouts prevent hangs  
✅ **Complete data** - Improved image captions and context extraction  

---

## Remaining Recommendations (Optional)

For future enhancements (not critical for current goal):

1. **Testing suite** - Unit tests for extraction, chunking, classification
2. **Multiprocessing** - Speed up extraction with parallel processing
3. **Caching** - Skip re-parsing unchanged HTML
4. **PDF extraction** - Process the logged non-HTML documents
5. **Configuration file** - Move hardcoded constants to config.yaml

---

## Questions or Issues?

If you encounter any problems or unexpected behavior:

1. Check `extraction_errors.jsonl` for failed pages
2. Review validation output for data quality issues
3. Inspect logs for error patterns
4. Spot-check a few problematic pages manually

All fixes prioritize **data accuracy and completeness** to ensure your chatbot has a reliable, high-quality knowledge base.
