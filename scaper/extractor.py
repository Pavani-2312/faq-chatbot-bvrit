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
# IMPORTANT: Use specific selectors, not broad substring matches — this site adds
# utility classes like "has-breadcrumbs" to <body> itself, so "[class*='breadcrumb']"
# would nuke the entire page. Similarly "[class*='menu']" matches menu-item children.
STRIP_SELECTORS = [
    "nav",
    "header",
    "footer",
    # Cookie banners (specific names, not substring match on body class)
    "#cookie-notice", "#cookie-bar", ".cookie-notice", ".cookie-bar",
    # WordPress sidebars — scoped, not the bare [class*='widget'] which kills Elementor content
    "aside.widget-area", "aside.sidebar",
    "[id='sidebar']", "[id='sidebar-primary']",
    ".elementor-widget-sidebar",
    # Elementor chrome: remove header/footer/popup templates embedded alongside wp-page content
    ".elementor-location-header", ".elementor-location-footer",
    "[data-elementor-type='popup']",
    "[data-elementor-type='header']",
    "[data-elementor-type='footer']",
    "[data-elementor-type='loop-item']",
    "[data-elementor-type='loop-header']",
    # Strictly scoped breadcrumb containers (not body class selectors)
    ".site-breadcrumbs", ".breadcrumbs", ".breadcrumb-trail",
    # Misc chrome
    ".back-to-top", "#back-to-top",
    ".social-icons", ".social-share",
    "script", "style", "noscript", "iframe",
]

# Best-effort selectors for the "main content" region, tried in order.
# Elementor pages: [data-elementor-type="wp-page"] is the page body (excludes header/footer)
# Then fall back to classic WordPress content containers and finally to main/body
CONTENT_SELECTORS = [
    '[data-elementor-type="wp-page"]',
    '[data-elementor-type="single"]',
    "#main",
    "main",
    "article",
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


def _escape_markdown(text: str) -> str:
    """Escape special Markdown characters to prevent formatting issues."""
    # Escape common Markdown special characters
    # Be careful not to escape already-escaped characters
    escape_chars = {
        '\\': '\\\\',
        '*': '\\*',
        '_': '\\_',
        '[': '\\[',
        ']': '\\]',
        '`': '\\`',
        '#': '\\#',
    }
    result = text
    for char, escaped in escape_chars.items():
        # Only escape if not already escaped
        result = re.sub(f'(?<!\\\\){re.escape(char)}', escaped, result)
    return result


def classify_text(text: str, title: str = "", headings: list = None) -> str:
    """Improved keyword-based categorizer with position weighting and confidence thresholds.
    
    Args:
        text: Main content text
        title: Page title (weighted more heavily)
        headings: List of (level, heading_text) tuples (weighted more heavily)
    
    Returns:
        Category string or "general" if no strong match
    """
    if headings is None:
        headings = []
    
    # Lowercase everything for matching
    text_lower = text.lower()
    title_lower = title.lower()
    heading_texts = [h[1].lower() for h in headings]
    
    # Score with position-based weights:
    # - Title: 5x weight (most indicative)
    # - Headings: 3x weight (very indicative)
    # - Body text: 1x weight (baseline)
    scores = {cat: 0 for cat in CATEGORY_KEYWORDS}
    
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            # Check title (highest weight)
            if kw in title_lower:
                scores[cat] += 5
            
            # Check headings (high weight)
            for heading_text in heading_texts:
                if kw in heading_text:
                    scores[cat] += 3
            
            # Check body text (normal weight)
            # Count occurrences but cap at 5 to prevent spam from dominating
            body_count = min(text_lower.count(kw), 5)
            scores[cat] += body_count
    
    # Find best category
    best_cat = max(scores, key=scores.get)
    best_score = scores[best_cat]
    
    # Confidence threshold: require at least a score of 3 to avoid false positives
    # (e.g., a single keyword mention in body text isn't enough)
    CONFIDENCE_THRESHOLD = 3
    
    if best_score < CONFIDENCE_THRESHOLD:
        return "general"
    
    # If there's a close second category (within 20% of best score), 
    # prefer more specific categories in this order:
    # faculty > placement_stat > admission_info > department > facility > news > general
    category_specificity = {
        "faculty": 6,
        "placement_stat": 5,
        "admission_info": 4,
        "department": 3,
        "facility": 2,
        "news": 1,
        "general": 0,
    }
    
    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_cats) > 1:
        second_best_score = sorted_cats[1][1]
        if second_best_score >= best_score * 0.8:  # Within 20%
            # There's ambiguity - prefer more specific category
            top_candidates = [cat for cat, score in sorted_cats if score >= best_score * 0.8]
            best_cat = max(top_candidates, key=lambda c: category_specificity.get(c, 0))
    
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


def html_to_markdown(content_root: Tag) -> str:
    """Convert a BeautifulSoup content root to Markdown using a fast iterative
    flat-scan strategy.

    Instead of recursing through every wrapper div (Elementor pages can have
    100+ nested container divs around a single paragraph), we use find_all to
    pull out only the meaningful leaf elements — headings, paragraphs, lists,
    tables — in document order, then render each one directly.  Container divs
    are completely ignored, which makes this O(n_meaningful_nodes) rather than
    O(n_total_nodes) and avoids Python stack overflows on deeply nested markup.
    """
    CONTENT_TAGS = re.compile(r"^(h[1-6]|p|ul|ol|table)$")
    parts = []
    # Track nodes already consumed as part of a list/table so we don't emit
    # their children again as bare paragraphs.
    consumed: set = set()

    for node in content_root.find_all(CONTENT_TAGS):
        if id(node) in consumed:
            continue

        # Skip nodes that are nested inside a list or table we'll render whole
        ancestor_names = {a.name for a in node.parents if isinstance(a, Tag)}
        if ancestor_names & {"li", "td", "th"}:
            continue

        name = node.name.lower()

        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(name[1])
            text = node.get_text(" ", strip=True)
            if text:
                parts.append(f"\n{'#' * level} {_escape_markdown(text)}\n")

        elif name == "p":
            text = node.get_text(" ", strip=True)
            if text:
                parts.append(f"\n{_escape_markdown(text)}\n")

        elif name in ("ul", "ol"):
            lines = []
            for i, li in enumerate(node.find_all("li", recursive=False), start=1):
                text = li.get_text(" ", strip=True)
                if not text:
                    continue
                prefix = f"{i}." if name == "ol" else "-"
                lines.append(f"{prefix} {_escape_markdown(text)}")
            if lines:
                parts.append("\n" + "\n".join(lines) + "\n")
            # mark all descendant tags as consumed
            for desc in node.find_all(CONTENT_TAGS):
                consumed.add(id(desc))

        elif name == "table":
            rows = node.find_all("tr")
            if rows:
                table_lines = []
                for idx, row in enumerate(rows):
                    cells = row.find_all(["td", "th"])
                    cell_texts = [_escape_markdown(c.get_text(" ", strip=True)) for c in cells]
                    table_lines.append("| " + " | ".join(cell_texts) + " |")
                    if idx == 0:
                        table_lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
                parts.append("\n" + "\n".join(table_lines) + "\n")
            for desc in node.find_all(CONTENT_TAGS):
                consumed.add(id(desc))

    raw = "".join(parts)
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
        
        # If no figcaption, look for caption in nearby text within the same container
        if not caption:
            # Limit search to the immediate parent container (not the whole page)
            parent = img.find_parent(["div", "section", "article"])
            if parent:
                # Find the next <p> sibling within the same parent
                for sibling in img.next_siblings:
                    if isinstance(sibling, Tag) and sibling.name == "p":
                        caption = sibling.get_text(" ", strip=True)[:300]
                        break
                    # Stop if we hit another structural element
                    if isinstance(sibling, Tag) and sibling.name in ("div", "section", "h1", "h2", "h3", "h4", "h5", "h6"):
                        break

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

    # Classify with position weighting: title and headings are weighted more heavily
    category = classify_text(markdown[:2000], title=title, headings=headings)

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
        # Use (connect_timeout, read_timeout) tuple — connect must succeed within 5s,
        # each read chunk within 10s. This prevents hanging on servers that accept
        # the TCP connection but never send data.
        resp = session.get(image.src, headers=headers, timeout=(5, 10), stream=True)
        if resp.status_code != 200:
            return False
        
        # Check Content-Length header to avoid downloading huge files
        # (prevents DoS from accidentally downloading multi-GB images)
        MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
        content_length = resp.headers.get('Content-Length')
        if content_length and int(content_length) > MAX_IMAGE_SIZE:
            print(f"[skip] Image too large: {image.src} ({int(content_length) / (1024*1024):.1f} MB)")
            return False
        
        # Download with size checking even if Content-Length is missing
        downloaded_size = 0
        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                downloaded_size += len(chunk)
                if downloaded_size > MAX_IMAGE_SIZE:
                    print(f"[skip] Image exceeded size limit during download: {image.src}")
                    # Clean up partial download
                    target_path.unlink(missing_ok=True)
                    return False
                f.write(chunk)
        
        image.local_path = str(target_path)
        return True
    except requests.RequestException:
        return False