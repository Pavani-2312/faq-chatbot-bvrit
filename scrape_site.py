"""
Website text scraper for building a RAG knowledge base.

What it does:
- Starts at a seed URL
- Crawls every internal link on the same domain (breadth-first)
- Extracts clean, readable text from each page (removes nav/script/style/footer clutter)
- Saves each page as a separate .txt file AND one combined .txt file
- Writes a manifest.csv mapping url -> filename -> char count (handy for RAG chunking/citations)

Usage:
    python scrape_site.py https://bvrithyderabad.edu.in/ --max-pages 200 --delay 0.5

Output:
    ./scraped_site/pages/*.txt        (one file per page)
    ./scraped_site/combined.txt       (everything concatenated, with source markers)
    ./scraped_site/manifest.csv       (url, filename, num_chars)
"""

import argparse
import csv
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RAGKnowledgeBaseBot/1.0; +for-college-chatbot)"
}

# Tags that never contain useful body text
STRIP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form"]


def is_same_domain(url: str, base_netloc: str) -> bool:
    return urlparse(url).netloc in ("", base_netloc)


def normalize_url(base: str, link: str) -> str | None:
    if not link:
        return None
    link = link.strip()
    if link.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    full = urljoin(base, link)
    full, _ = urldefrag(full)  # drop #fragment
    # Skip obvious non-HTML assets
    if re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|zip|rar|mp4|mp3|docx?|xlsx?|pptx?)$", full, re.I):
        return None
    return full


def extract_text(html: str) -> tuple[str, str]:
    """Returns (title, cleaned_text) from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(STRIP_TAGS):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""

    # get_text with a separator keeps block-level elements from
    # smashing together into one giant unreadable line
    text = soup.get_text(separator="\n")

    # Collapse excessive blank lines/whitespace
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    cleaned = "\n".join(lines)

    return title, cleaned


def safe_filename(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        path = "home"
    name = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_")
    return (name or "page")[:150] + ".txt"


def crawl(seed_url: str, max_pages: int, delay: float, out_dir: Path):
    base_netloc = urlparse(seed_url).netloc
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    visited = set()
    queue = deque([seed_url])
    manifest_rows = []
    combined_parts = []

    session = requests.Session()
    session.headers.update(HEADERS)

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                continue
        except requests.RequestException as e:
            print(f"[skip] {url} -> {e}")
            continue

        title, text = extract_text(resp.text)
        if len(text) < 20:  # near-empty page, skip saving but still crawl its links
            print(f"[thin] {url} ({len(text)} chars)")
        else:
            fname = safe_filename(url)
            # avoid filename collisions
            i = 1
            candidate = fname
            while (pages_dir / candidate).exists():
                candidate = fname.replace(".txt", f"_{i}.txt")
                i += 1
            fname = candidate

            (pages_dir / fname).write_text(
                f"URL: {url}\nTITLE: {title}\n\n{text}", encoding="utf-8"
            )
            manifest_rows.append((url, fname, len(text)))
            combined_parts.append(f"\n\n===== SOURCE: {url} =====\nTITLE: {title}\n\n{text}")
            print(f"[ok]   {url}  ({len(text)} chars)")

        # queue internal links
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            link = normalize_url(url, a["href"])
            if link and is_same_domain(link, base_netloc) and link not in visited:
                queue.append(link)

        time.sleep(delay)  # be polite to the server

    # Write combined file
    (out_dir / "combined.txt").write_text("".join(combined_parts), encoding="utf-8")

    # Write manifest
    with open(out_dir / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "filename", "num_chars"])
        writer.writerows(manifest_rows)

    print(f"\nDone. Crawled {len(visited)} URLs, saved {len(manifest_rows)} pages with text.")
    print(f"Output folder: {out_dir.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl a website and extract text for a RAG knowledge base.")
    parser.add_argument("url", help="Seed URL to start crawling from")
    parser.add_argument("--max-pages", type=int, default=200, help="Max number of pages to crawl")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay (seconds) between requests")
    parser.add_argument("--out", type=str, default="scraped_site", help="Output directory")
    args = parser.parse_args()

    crawl(args.url, args.max_pages, args.delay, Path(args.out))