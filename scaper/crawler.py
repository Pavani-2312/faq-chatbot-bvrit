"""
crawler.py
----------
BFS web crawler for bvrithyderabad.edu.in.

Responsibilities:
  - Read /robots.txt and respect its rules + crawl-delay
  - Read /sitemap.xml or /sitemap_index.xml as a primary seed list
  - BFS crawl within the allowed domain, up to max_depth / max_pages
  - Deduplicate by normalized URL
  - Persist visited-URL state to disk (resumable)
  - Skip excluded paths (wp-admin, wp-login, feed, wp-json, xmlrpc.php, cart/checkout)
  - Skip non-HTML file types but log them separately for a later PDF pass
  - Rate-limit with randomized delay + bounded concurrency
  - Exponential backoff retries on failure
  - Log every request to a CSV
"""

from __future__ import annotations

import csv
import json
import random
import re
import time
import urllib.robotparser as robotparser
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

DOMAIN = "bvrithyderabad.edu.in"
SEED_URL = f"https://{DOMAIN}/"

USER_AGENT = (
    "BVRIT-KB-Bot/1.0 (+educational RAG knowledge-base crawler; "
    "contact: kb-crawler@example.local; respects robots.txt)"
)

EXCLUDED_PATH_PATTERNS = [
    r"^/wp-admin",
    r"^/wp-login",
    r"^/feed",
    r"^/wp-json",
    r"^/xmlrpc\.php",
    r"^/cart",
    r"^/checkout",
    r"/cart/",
    r"/checkout/",
]

NON_HTML_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}

MAX_RETRIES = 3
BASE_BACKOFF = 1.5  # seconds, exponential backoff base
MIN_DELAY = 1.0
MAX_DELAY = 2.5


def normalize_url(url: str) -> str:
    """Normalize a URL: strip fragment/query (except when query is meaningful),
    lower-case host, drop trailing slash duplication, sort query params."""
    parsed = urlparse(url)
    scheme = "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    # collapse duplicate slashes
    path = re.sub(r"/{2,}", "/", path)
    # strip trailing slash except for root
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # drop query params and fragment entirely (site is content-driven, not paginated by query)
    query = ""
    normalized = urlunparse((scheme, netloc, path, "", query, ""))
    return normalized


def is_in_scope(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host == DOMAIN


def is_excluded_path(url: str) -> bool:
    path = urlparse(url).path
    for pattern in EXCLUDED_PATH_PATTERNS:
        if re.search(pattern, path, flags=re.IGNORECASE):
            return True
    return False


def get_extension(url: str) -> str:
    path = urlparse(url).path
    return Path(path).suffix.lower()


@dataclass
class CrawlState:
    """Resumable crawl state, persisted to disk as JSON."""
    visited: set = field(default_factory=set)
    queued: set = field(default_factory=set)
    frontier: deque = field(default_factory=deque)  # deque of (url, depth)
    non_html_log: set = field(default_factory=set)
    depth_map: dict = field(default_factory=dict)
    skipped_image_links: int = 0

    @classmethod
    def load(cls, path: Path) -> "CrawlState":
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            state = cls(
                visited=set(data.get("visited", [])),
                queued=set(data.get("queued", [])),
                frontier=deque(tuple(item) for item in data.get("frontier", [])),
                non_html_log=set(data.get("non_html_log", [])),
                depth_map=data.get("depth_map", {}),
                skipped_image_links=data.get("skipped_image_links", 0),
            )
            return state
        return cls(frontier=deque())

    def save(self, path: Path) -> None:
        data = {
            "visited": sorted(self.visited),
            "queued": sorted(self.queued),
            "frontier": [list(item) for item in self.frontier],
            "non_html_log": sorted(self.non_html_log),
            "depth_map": self.depth_map,
            "skipped_image_links": self.skipped_image_links,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class Crawler:
    def __init__(
        self,
        output_dir: str,
        max_depth: int = 4,
        max_pages: int = 800,
        concurrency: int = 5,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.output_dir / "raw_html"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        self.max_depth = max_depth
        self.max_pages = max_pages
        self.concurrency = min(concurrency, 5)  # hard cap at 5 per spec

        self.state_path = self.output_dir / "crawl_state.json"
        self.log_path = self.output_dir / "request_log.csv"
        self.non_html_path = self.output_dir / "non_html_urls.csv"

        self.state = CrawlState.load(self.state_path)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

        self.robots = robotparser.RobotFileParser()
        self.robots_crawl_delay: Optional[float] = None
        self._lock = RLock()

        self._init_log_files()

    def _init_log_files(self) -> None:
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "url", "status", "depth", "note"])
        if not self.non_html_path.exists():
            with open(self.non_html_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["url", "extension", "discovered_on"])

    def _log_request(self, url: str, status, depth: int, note: str = "") -> None:
        with self._lock:
            with open(self.log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [datetime.now(timezone.utc).isoformat(), url, status, depth, note]
                )

    def _log_non_html(self, url: str, discovered_on: str) -> None:
        ext = get_extension(url)
        with self._lock:
            if url in self.state.non_html_log:
                return
            self.state.non_html_log.add(url)
            with open(self.non_html_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([url, ext, discovered_on])

    # ---------------------------------------------------------------
    # robots.txt / sitemap handling
    # ---------------------------------------------------------------
    def load_robots(self) -> None:
        robots_url = urljoin(SEED_URL, "/robots.txt")
        self.robots.set_url(robots_url)
        try:
            self.robots.read()
        except Exception:
            # if robots.txt is unreachable, proceed conservatively (no wp-admin etc,
            # already excluded by EXCLUDED_PATH_PATTERNS) but log the issue
            print(f"[warn] could not read {robots_url}; proceeding with built-in exclusions only")
            return
        try:
            delay = self.robots.crawl_delay(USER_AGENT)
            if delay:
                self.robots_crawl_delay = float(delay)
        except Exception:
            pass

    def can_fetch(self, url: str) -> bool:
        try:
            return self.robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def discover_sitemap_urls(self) -> list[str]:
        """Fetch sitemap.xml / sitemap_index.xml (recursively for index files)."""
        candidates = ["/sitemap.xml", "/sitemap_index.xml"]
        found_urls: list[str] = []
        seen_sitemaps: set[str] = set()
        
        print("[info] Discovering sitemaps...")

        def fetch_sitemap(sm_url: str, depth: int = 0) -> None:
            if sm_url in seen_sitemaps or depth > 2:
                return
            seen_sitemaps.add(sm_url)
            print(f"[info] Fetching sitemap: {sm_url} (depth {depth})")
            try:
                resp = self.session.get(sm_url, timeout=(5, 15))
                if resp.status_code != 200:
                    print(f"[warn] Sitemap {sm_url} returned status {resp.status_code}")
                    return
            except requests.RequestException as e:
                print(f"[warn] Failed to fetch sitemap {sm_url}: {e}")
                return
            soup = BeautifulSoup(resp.content, "xml")
            # sitemap index -> nested sitemaps
            nested_sitemaps = soup.find_all("sitemap")
            if nested_sitemaps:
                print(f"[info] Found {len(nested_sitemaps)} nested sitemap(s) in {sm_url}")
            for sitemap_tag in nested_sitemaps:
                loc = sitemap_tag.find("loc")
                if loc and loc.text:
                    fetch_sitemap(loc.text.strip(), depth + 1)
            # urlset -> actual page urls
            url_entries = soup.find_all("url")
            if url_entries:
                print(f"[info] Found {len(url_entries)} URL(s) in {sm_url}")
            for url_tag in url_entries:
                loc = url_tag.find("loc")
                if loc and loc.text:
                    found_urls.append(loc.text.strip())

        for path in candidates:
            fetch_sitemap(urljoin(SEED_URL, path))
        
        print(f"[info] Sitemap discovery complete: {len(found_urls)} total URLs found")
        return found_urls

    # ---------------------------------------------------------------
    # fetching
    # ---------------------------------------------------------------
    def fetch(self, url: str) -> Optional[requests.Response]:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # (connect_timeout, read_timeout) - prevents hanging on slow servers
                resp = self.session.get(url, timeout=(10, 20), allow_redirects=True)
                if resp.status_code == 200:
                    return resp
                
                # Retryable server errors (temporary)
                if resp.status_code in (429, 500, 502, 503, 504):
                    backoff = BASE_BACKOFF ** attempt + random.uniform(0, 0.5)
                    print(f"[retry] {url} returned {resp.status_code}, retrying in {backoff:.1f}s (attempt {attempt}/{MAX_RETRIES})")
                    time.sleep(backoff)
                    continue
                
                # Client errors (4xx) - no point retrying
                # 404 = not found, 403 = forbidden, 400 = bad request, 401 = unauthorized
                if 400 <= resp.status_code < 500:
                    print(f"[skip] {url} returned {resp.status_code} (client error, not retrying)")
                    return resp
                
                # Other status codes - return as-is
                return resp
                
            except requests.exceptions.ConnectionError as e:
                # Network issues - retryable
                backoff = BASE_BACKOFF ** attempt + random.uniform(0, 0.5)
                print(f"[retry] Connection error for {url}: {e} (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(backoff)
                
            except requests.exceptions.Timeout as e:
                # Timeout - retryable
                backoff = BASE_BACKOFF ** attempt + random.uniform(0, 0.5)
                print(f"[retry] Timeout for {url}: {e} (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(backoff)
                
            except requests.exceptions.TooManyRedirects as e:
                # Too many redirects - not retryable
                print(f"[skip] Too many redirects for {url}: {e} (not retrying)")
                return None
                
            except requests.exceptions.RequestException as e:
                # Generic request exception - retryable as last resort
                backoff = BASE_BACKOFF ** attempt + random.uniform(0, 0.5)
                print(f"[retry] Request error for {url}: {e} (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(backoff)
                
        print(f"[fail] {url} failed after {MAX_RETRIES} attempts")
        return None

    def polite_delay(self) -> None:
        delay = self.robots_crawl_delay if self.robots_crawl_delay else random.uniform(
            MIN_DELAY, MAX_DELAY
        )
        time.sleep(delay)

    def extract_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            absolute = urljoin(base_url, href)
            links.append(absolute)
        return links

    # ---------------------------------------------------------------
    # main crawl loop
    # ---------------------------------------------------------------
    def crawl(self) -> list[Path]:
        """Runs the BFS crawl. Returns list of raw HTML file paths saved."""
        self.load_robots()

        # seed frontier: sitemap urls (depth 1) + the seed url (depth 0), if not resuming
        if not self.state.frontier and not self.state.visited:
            self.state.frontier.append((normalize_url(SEED_URL), 0))
            self.state.queued.add(normalize_url(SEED_URL))

            sitemap_urls = self.discover_sitemap_urls()
            print(f"[info] discovered {len(sitemap_urls)} URLs from sitemap(s)")
            skipped = 0
            for u in sitemap_urls:
                nu = normalize_url(u)
                if get_extension(nu) in IMAGE_EXTENSIONS:
                    # image/media-library URLs sometimes appear in WP media
                    # sitemaps; these are handled by extractor.py from within
                    # page HTML, never as crawl targets in their own right.
                    skipped += 1
                    continue
                if is_in_scope(nu) and nu not in self.state.queued:
                    self.state.frontier.append((nu, 1))
                    self.state.queued.add(nu)
            if skipped:
                self.state.skipped_image_links += skipped
                print(f"[info] skipped {skipped} image URLs found in sitemap(s)")

        saved_files: list[Path] = []

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            while self.state.frontier and len(self.state.visited) < self.max_pages:
                # take a batch up to concurrency size
                batch = []
                while self.state.frontier and len(batch) < self.concurrency:
                    url, depth = self.state.frontier.popleft()
                    if url in self.state.visited:
                        continue
                    if depth > self.max_depth:
                        continue
                    if is_excluded_path(url):
                        continue
                    if not is_in_scope(url):
                        continue
                    ext = get_extension(url)
                    if ext in NON_HTML_EXTENSIONS:
                        self._log_non_html(url, discovered_on="crawl")
                        self.state.visited.add(url)  # mark handled, won't re-queue
                        continue
                    if not self.can_fetch(url):
                        self._log_request(url, "disallowed_by_robots", depth)
                        self.state.visited.add(url)
                        continue
                    batch.append((url, depth))

                if not batch:
                    continue

                futures = {
                    executor.submit(self._process_url, url, depth): (url, depth)
                    for url, depth in batch
                }

                for future in as_completed(futures):
                    url, depth = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        self._log_request(url, f"error:{exc}", depth)
                        result = None

                    with self._lock:
                        self.state.visited.add(url)
                        self.state.depth_map[url] = depth

                    if result is None:
                        continue

                    html_path, new_links = result
                    if html_path:
                        saved_files.append(html_path)

                    with self._lock:
                        for link in new_links:
                            nlink = normalize_url(link)
                            if (
                                nlink not in self.state.visited
                                and nlink not in self.state.queued
                                and is_in_scope(nlink)
                                and not is_excluded_path(nlink)
                            ):
                                ext = get_extension(nlink)
                                if ext in IMAGE_EXTENSIONS:
                                    # <a href="...jpg"> lightbox/gallery links are
                                    # extremely common in Elementor image widgets.
                                    # These are never real pages to crawl - the
                                    # extractor already pulls every qualifying
                                    # <img> straight out of each page's own HTML,
                                    # so fetching these as "pages" only wastes
                                    # bandwidth/time and stalls the frontier.
                                    self.state.queued.add(nlink)
                                    self.state.skipped_image_links += 1
                                    continue
                                if ext in NON_HTML_EXTENSIONS:
                                    self._log_non_html(nlink, discovered_on=url)
                                    self.state.queued.add(nlink)
                                    continue
                                self.state.frontier.append((nlink, depth + 1))
                                self.state.queued.add(nlink)

                    # persist state after every batch for resumability
                    self.state.save(self.state_path)

                self.polite_delay()

        self.state.save(self.state_path)
        print(
            f"[info] crawl complete. pages visited: {len(self.state.visited)} | "
            f"image URLs kept out of page frontier: {self.state.skipped_image_links}"
        )
        return saved_files

    def _process_url(self, url: str, depth: int):
        resp = self.fetch(url)
        if resp is None:
            self._log_request(url, "failed_after_retries", depth)
            return None

        self._log_request(url, resp.status_code, depth)

        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return None

        # save raw html for the extraction stage
        slug = self._slug_for_url(url)
        html_path = self.raw_dir / f"{slug}.html"
        html_path.write_text(resp.text, encoding="utf-8", errors="ignore")

        # write a small sidecar with the source url (slug collisions are possible)
        meta_path = self.raw_dir / f"{slug}.meta.json"
        meta_path.write_text(
            json.dumps({"url": url, "fetched_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )

        links = self.extract_links(resp.text, url)
        return html_path, links

    @staticmethod
    def _slug_for_url(url: str) -> str:
        path = urlparse(url).path.strip("/")
        if not path:
            return "home"
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", path)
        return slug[:150]


if __name__ == "__main__":
    # quick manual smoke test (real entry point is main.py)
    crawler = Crawler(output_dir="./output", max_depth=4, max_pages=800, concurrency=5)
    crawler.crawl()
