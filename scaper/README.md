# BVRIT Hyderabad Knowledge Base Scraper

## Fixes in this version

- **`extractor.py`** — Removed the bare `[class*='widget']` strip selector.
  Elementor names every content block `elementor-widget-*` (headings, text,
  images, icon-lists — everything), so that selector was deleting almost all
  real page content sitewide, not just sidebars. It's now scoped to actual
  sidebar/widget-area containers only. Verified with a synthetic Elementor
  page: headings, paragraphs, lists, and images with captions all now survive
  extraction while nav/sidebar chrome is still correctly stripped.
- **`crawler.py`** — Fixed the crawl stall: `IMAGE_EXTENSIONS` was defined but
  never actually used, so `<a href="...jpg">` gallery/lightbox links (very
  common in Elementor image widgets) were being enqueued and fetched as if
  they were HTML pages — downloading full image binaries only to discard them
  once the content-type check failed. On a media-heavy site like this one,
  that can flood the frontier with thousands of wasted requests. Image URLs
  are now filtered out at both the sitemap-seeding step and the link-discovery
  step, since `extractor.py` already pulls every qualifying `<img>` directly
  from each page's own HTML — there was never a need to crawl images as
  separate "pages." The frontier was also switched from a `list` (`pop(0)` is
  O(n)) to a `deque` (`popleft()` is O(1)) so this doesn't degrade further as
  the frontier grows on a ~500-800 page crawl. A running count of skipped
  image URLs is now printed at the end of the crawl and saved in
  `crawl_state.json` as `skipped_image_links`.


A polite, resumable crawler + extractor + chunker pipeline that turns
[bvrithyderabad.edu.in](https://bvrithyderabad.edu.in/) (a WordPress/Elementor
site) into a `knowledge_base.jsonl` file suitable for a RAG-based chatbot.

## What it does

1. **`crawler.py`** — Reads `robots.txt` and `sitemap.xml`/`sitemap_index.xml`,
   then does a breadth-first crawl of `bvrithyderabad.edu.in` only, up to a
   configurable depth/page limit. Rate-limited (max 5 concurrent requests,
   1–2.5s randomized delay, exponential backoff on failure), resumable via a
   `crawl_state.json` file, and logs every request to `request_log.csv`.
   Non-HTML files (PDF/DOC/XLS/PPT) are **not** downloaded — their URLs are
   logged separately to `non_html_urls.csv` for an optional follow-up PDF
   extraction pass.

2. **`extractor.py`** — Strips nav/header/footer/sidebar/cookie-banner/Elementor
   chrome from each saved page, keeps only the real content area, and converts
   it to Markdown (preserving heading hierarchy, lists, and tables). It also
   applies a lightweight keyword-based classifier to tag content as
   `faculty`, `admission_info`, `placement_stat`, `department`, `news`,
   `facility`, or `general`. Images are extracted from
   `/wp-content/uploads/`, filtered by size and filename heuristics (skipping
   logos/icons/spacers), and downloaded with their alt text / caption /
   nearby-paragraph context captured.

3. **`chunker.py`** — Splits each page's Markdown into ~500–700 token chunks
   with ~15% overlap, always breaking on paragraph/heading boundaries (never
   mid-sentence). Each chunk carries `source_url`, `page_title`, `category`,
   and `scraped_at` metadata.

4. **`main.py`** — CLI that runs the full pipeline end-to-end and writes a
   single `knowledge_base.jsonl`.

5. **`embed.py`** *(optional)* — Reads `knowledge_base.jsonl` and generates
   embeddings into a local Chroma or FAISS vector store for the chatbot to
   query.

## Output layout

```
output/
├── raw_html/                # saved HTML per page + .meta.json sidecar
├── images/<page-slug>/      # downloaded images, grouped by originating page
├── crawl_state.json         # resumable crawl frontier/visited state
├── request_log.csv          # timestamp, url, status, depth, note
├── non_html_urls.csv        # PDFs/DOCs/etc. discovered but not fetched
├── extraction_errors.jsonl  # pages that failed extraction (for investigation)
└── knowledge_base.jsonl     # final output: one JSON object per line
```

### `knowledge_base.jsonl` record shape

```json
{
  "id": "uuid",
  "type": "text | image",
  "content": "...",
  "category": "faculty | admission_info | placement_stat | department | news | facility | general",
  "source_url": "https://bvrithyderabad.edu.in/...",
  "page_title": "...",
  "image_path": "output/images/<slug>/<file>.jpg | null",
  "scraped_at": "2026-07-03T12:00:00+00:00"
}
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Running

Full pipeline (crawl + extract + chunk):

```bash
python main.py --max-depth 4 --max-pages 800 --output-dir ./output --concurrency 5
```

Re-run extraction/chunking only, reusing previously crawled HTML (useful
after tweaking `extractor.py` or `chunker.py`, or when the crawl was already
completed):

```bash
python main.py --output-dir ./output --skip-crawl
```

Text-only knowledge base (skip image downloads):

```bash
python main.py --output-dir ./output --skip-images
```

If interrupted mid-crawl, just re-run the same command — `crawl_state.json`
lets it resume from where it left off instead of restarting.

### Quick validation

After extraction completes, you can run an additional validation script for
detailed quality analysis:

```bash
python validate_kb.py ./output/knowledge_base.jsonl
```

This provides:
- Category distribution statistics
- Content length analysis
- Data quality checks (missing fields, duplicates, empty content)
- Sample chunk preview

### CLI flags

| Flag             | Default    | Description                                      |
|------------------|------------|---------------------------------------------------|
| `--max-depth`    | `4`        | Max BFS crawl depth from the seed URL              |
| `--max-pages`    | `800`      | Max number of pages to crawl                       |
| `--output-dir`   | `./output` | Directory for all outputs                          |
| `--concurrency`  | `5`        | Max concurrent requests (hard-capped at 5)         |
| `--skip-crawl`   | off        | Reuse existing `raw_html/`, skip crawling           |
| `--skip-images`  | off        | Don't download images                              |

## Optional: generate embeddings

```bash
pip install sentence-transformers chromadb   # for local embeddings + Chroma
python embed.py --input ./output/knowledge_base.jsonl \
                 --db chroma --db-path ./output/chroma_db \
                 --provider local
```

Or with FAISS instead of Chroma:

```bash
pip install sentence-transformers faiss-cpu numpy
python embed.py --input ./output/knowledge_base.jsonl \
                 --db faiss --db-path ./output/faiss_index \
                 --provider local
```

OpenAI embeddings are also supported via `--provider openai` (requires
`pip install openai` and an `OPENAI_API_KEY` environment variable).

## Ethics / scope notes

- The crawler respects `robots.txt`, including any `Crawl-delay` directive.
- Only publicly reachable pages under `bvrithyderabad.edu.in` are crawled —
  `wp-admin`, `wp-login`, `/feed`, `/wp-json`, `xmlrpc.php`, and cart/checkout
  paths are excluded, and no login-gated portals are accessed.
- Only contact details already published on public pages (e.g. official
  department emails/phone numbers) are captured — nothing beyond what the
  site itself displays.
- A descriptive `User-Agent` identifies the bot and its educational,
  RAG-knowledge-base purpose.
- Non-HTML documents (PDF/DOC/XLS/PPT — e.g. NAAC/NBA reports, brochures) are
  intentionally **not** downloaded by this pipeline; their URLs are only
  logged for a separate, explicit follow-up pass if you decide you want them.

## Notes on extraction heuristics

WordPress/Elementor markup varies a lot page to page (this is one reason the
extractor uses a prioritized list of content-root selectors and a chrome-strip
selector list rather than a single fixed CSS path). After a first crawl, it's
worth spot-checking a handful of `output/raw_html/*.html` files against the
corresponding chunks in `knowledge_base.jsonl` and adjusting
`CONTENT_SELECTORS` / `STRIP_SELECTORS` in `extractor.py` if you notice nav
leakage or missing content on particular page templates (e.g. faculty-profile
pages or the placements page, which colleges often build with custom
Elementor widgets that don't match the generic selectors).
