"""
extractor.py
------------
Turns raw saved HTML pages into cleaned Markdown + structured metadata,
and extracts qualifying images with their contextual captions/alt text.

Strategy:
  - Strip nav/header/footer/cookie-banner/sidebar/Elementor chrome
  - Keep only the main content area (best-effort heuristics for
    WordPress/Elementor markup: .elementor, article, main, #content, .entry-content)
  - Extract title, meta description, heading hierarchy, body text, lists/tables
  - Lightly classify content chunks by "category" using keyword heuristics
    (faculty, admission_info, placement_stat, department, news, facility, general)
  - Convert cleaned content into Markdown preserving lists/tables
  - Extract <img> tags from wp-content/uploads, filter by size, skip
    logos/icons/spacers, and download them locally
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

USER_AGENT = (
    "BVRIT-KB-Bot/1.0 (+educational RAG knowledge-base crawler; "
    "contact: kb-crawler@example.local; respects robots.txt)"
)

# Tags/selectors that constitute chrome we should strip before extracting content.
STRIP_SELECTORS = [
    "nav", "header", "footer",
    "[class*='cookie']", "[id*='cookie']",
    "[class*='sidebar']", "[id*='sidebar']",
    "[class*='widget']",
    "[class*='menu']:not([class*='menu-item'] p)",
    "script", "style", "noscript", "iframe",
    ".elementor-location-header", ".elementor-location-footer",
    ".elementor-widget-sidebar",
    "[class*='breadcrumb']",
    "[class*='popup']", "[class*='modal']",
    "[class*='back-to-top']",
    "[class*='social-icons']", "[class*='social-share']",
]

# Best-effort selectors for the "main content" region, tried in order.
CONTENT_SELECTORS = [
    "article",
    "main",
    "#content",
    ".entry-content",
    ".elementor-widget-theme-post-content",
    ".site-content",
    "#primary",
    "body",
]

MIN_IMAGE_DIM = 50  # px, skip anything smaller in either dimension when known
LOGO_ICON_PATTERNS = re.compile(
    r"(logo|icon|favicon|spacer|placeholder|sprite|avatar-default)", re.IGNORECASE
)
UPLOADS_PATH_HINT = "/wp-content/uploads/"

CATEGORY_KEYWORDS = {
    "faculty": [
        "professor", "assistant professor", "associate professor", "hod",
        "head of department", "faculty", "ph.d", "phd", "qualification",
        "designation",
    ],
    "admission_info": [
        "admission", "eligibility", "eamcet", "ecet", "counseling", "counselling",
        "fee structure", "intake", "how to apply", "entrance exam",
    ],
    "placement_stat": [
        "placement", "placed", "package", "ctc", "lpa", "recruiter",
        "highest package", "average package", "campus drive",
    ],
    "department": [
        "department of", "curriculum", "syllabus", "b.tech", "btech",
        "program outcomes", "vision and mission", "course outcomes",
    ],
    "news": [
        "news", "event", "workshop", "seminar", "conference", "announcement",
        "notification", "circular",
    ],
    "facility": [
        "hostel", "library", "laboratory", "lab facilities", "sports",
        "canteen", "transport", "infrastructure", "auditorium",
    ],
}


def classify_text(text: str) -> str:
    """Very lightweight keyword-based categorizer."""
    lowered = text.lower()
    scores = {cat: 0 for cat in CATEGORY_KEYWORDS}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in lowered:
                scores[cat] += 1
    best_cat = max(scores, key=scores.get)
    if scores[best_cat] == 0:
        return "general"
    return best_cat


@dataclass
class ExtractedImage:
    src: str
    alt: str
    caption: str
    width: Optional[int]
    height: Optional[int]
    page_url: str
    page_slug: str
    local_path: Optional[str] = None


@dataclass
class ExtractedPage:
    url: str
    title: str
    meta_description: str
    markdown: str
    headings: list = field(default_factory=list)  # list of (level, text)
    category: str = "general"
    images: list = field(default_factory=list)  # list[ExtractedImage]


def _remove_chrome(soup: BeautifulSoup) -> None:
    for selector in STRIP_SELECTORS:
        try:
            for el in soup.select(selector):
                el.decompose()
        except Exception:
            # some malformed pseudo-selectors above are best-effort; ignore failures
            continue


def _find_content_root(soup: BeautifulSoup) -> Tag:
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 80:
            return el
    return soup.body or soup


def _node_to_markdown(node) -> str:
    """Recursively render a BeautifulSoup node to Markdown, preserving
    heading hierarchy, lists, and simple tables."""
    if isinstance(node, NavigableString):
        text = str(node).strip()
        return text

    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()

    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        text = node.get_text(" ", strip=True)
        return f"\n{'#' * level} {text}\n" if text else ""

    if name == "p":
        text = node.get_text(" ", strip=True)
        return f"\n{text}\n" if text else ""

    if name in ("ul", "ol"):
        lines = []
        for i, li in enumerate(node.find_all("li", recursive=False), start=1):
            text = li.get_text(" ", strip=True)
            if not text:
                continue
            prefix = f"{i}." if name == "ol" else "-"
            lines.append(f"{prefix} {text}")
        return "\n" + "\n".join(lines) + "\n" if lines else ""

    if name == "table":
        rows = node.find_all("tr")
        if not rows:
            return ""
        table_lines = []
        for idx, row in enumerate(rows):
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(" ", strip=True) for c in cells]
            table_lines.append("| " + " | ".join(cell_texts) + " |")
            if idx == 0:
                table_lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
        return "\n" + "\n".join(table_lines) + "\n"

    if name in ("br",):
        return "\n"

    if name in ("div", "section", "span", "article", "main", "figure"):
        parts = [_node_to_markdown(child) for child in node.children]
        return "".join(parts)

    # fallback: plain text
    text = node.get_text(" ", strip=True)
    return text


def html_to_markdown(content_root: Tag) -> str:
    parts = [_node_to_markdown(child) for child in content_root.children]
    raw = "".join(parts)
    # collapse excessive blank lines
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def extract_headings(content_root: Tag) -> list[tuple[int, str]]:
    headings = []
    for tag in content_root.find_all(re.compile(r"^h[1-6]$")):
        level = int(tag.name[1])
        text = tag.get_text(" ", strip=True)
        if text:
            headings.append((level, text))
    return headings


def _looks_like_logo_or_icon(
    img: Tag, resolved_src: str, width: Optional[int], height: Optional[int]
) -> bool:
    cls = " ".join(img.get("class", []))
    alt = img.get("alt", "")
    combined = f"{resolved_src} {cls} {alt}"
    if LOGO_ICON_PATTERNS.search(combined):
        return True
    if width is not None and height is not None:
        if width < MIN_IMAGE_DIM or height < MIN_IMAGE_DIM:
            return True
    return False


def extract_images(
    content_root: Tag,
    page_url: str,
    page_slug: str,
) -> list[ExtractedImage]:
    results = []
    for img in content_root.find_all("img"):
        raw_src = (img.get("src") or "").strip()
        lazy_src = (img.get("data-src") or img.get("data-lazy-src") or "").strip()

        # Lazy-loading plugins (lazysizes, WP Rocket, etc.) put a throwaway
        # base64/blank placeholder in `src` and the real URL in a data-*
        # attribute. Prefer the real one whenever `src` isn't an actual URL.
        if lazy_src and (not raw_src or raw_src.startswith("data:")):
            src = lazy_src
        else:
            src = raw_src or lazy_src

        if not src:
            continue
        absolute_src = urljoin(page_url, src)

        if UPLOADS_PATH_HINT not in absolute_src:
            # not a media-library asset (likely theme chrome/icon sprite) -> skip
            continue

        width = _to_int(img.get("width"))
        height = _to_int(img.get("height"))

        if _looks_like_logo_or_icon(img, absolute_src, width, height):
            continue

        alt = (img.get("alt") or "").strip()

        caption = ""
        figure_parent = img.find_parent("figure")
        if figure_parent:
            figcaption = figure_parent.find("figcaption")
            if figcaption:
                caption = figcaption.get_text(" ", strip=True)
        if not caption:
            # fall back to a nearby paragraph as context
            next_p = img.find_next("p")
            if next_p:
                caption = next_p.get_text(" ", strip=True)[:300]

        results.append(
            ExtractedImage(
                src=absolute_src,
                alt=alt,
                caption=caption,
                width=width,
                height=height,
                page_url=page_url,
                page_slug=page_slug,
            )
        )
    return results


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_page(html: str, url: str) -> ExtractedPage:
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    _remove_chrome(soup)
    content_root = _find_content_root(soup)

    markdown = html_to_markdown(content_root)
    headings = extract_headings(content_root)

    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", urlparse(url).path.strip("/") or "home")[:150]
    images = extract_images(content_root, url, slug)

    category = classify_text(f"{title} {markdown[:2000]}")

    return ExtractedPage(
        url=url,
        title=title,
        meta_description=meta_desc,
        markdown=markdown,
        headings=headings,
        category=category,
        images=images,
    )


def download_image(image: ExtractedImage, images_dir: Path, session: Optional[requests.Session] = None) -> bool:
    """Download an image to /images/<page-slug>/<filename>. Returns True on success."""
    session = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}

    parsed = urlparse(image.src)
    filename = Path(parsed.path).name or "image.jpg"
    filename = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename)

    target_dir = images_dir / image.page_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if target_path.exists():
        image.local_path = str(target_path)
        return True

    try:
        resp = session.get(image.src, headers=headers, timeout=20, stream=True)
        if resp.status_code != 200:
            return False
        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        image.local_path = str(target_path)
        return True
    except requests.RequestException:
        return False
