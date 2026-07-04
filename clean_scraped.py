"""
clean_scraped.py — Strips navigation boilerplate from scraped_site/pages/*.txt files
and writes clean versions to scraped_site/pages_clean/*.txt

The scraper output has a fixed structure:
  URL: <url>
  TITLE: <title>
  <nav boilerplate repeated twice>
  <actual page content>
  <footer boilerplate>

The nav always ends after the second occurrence of:
  "Innovation and Entrepreneurship (I & E) Policy"

The footer always starts at:
  "Our Campuses"

Usage:
    python clean_scraped.py
"""

import re
from pathlib import Path

INPUT_DIR  = Path("scraped_site/pages")
OUTPUT_DIR = Path("scraped_site/pages_clean")

# The nav block always ends at the second occurrence of this line.
NAV_END_MARKER = "Innovation and Entrepreneurship (I & E) Policy"

# Footer starts at this line.
FOOTER_START_MARKER = "Our Campuses"

# Lines that are pure boilerplate even inside the content zone — deduplicate them.
BOILERPLATE_LINES = {
    "Skip to content",
    "Close Study",
    "Open Study",
    "Close Discover",
    "Open Discover",
    "Close Research",
    "Open Research",
    "Close Differentiators",
    "Open Differentiators",
    "Close Placements",
    "Open Placements",
    "Close News",
    "Open News",
    "Close Approvals",
    "Open Approvals",
    "#craftedbyreinaphics",
    "© 2023 BVRITH – All rights reserved",
    "website",
}


def clean_file(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()

    # ── Extract URL and TITLE from the first two non-empty lines ────────────
    url, title = "", ""
    content_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("URL:"):
            url = stripped[4:].strip()
        elif stripped.startswith("TITLE:"):
            title = stripped[6:].strip()
            content_start = i + 1
            break

    # ── Skip past the nav boilerplate (two occurrences of the end marker) ───
    nav_end_count = 0
    body_start = content_start
    for i in range(content_start, len(lines)):
        if lines[i].strip() == NAV_END_MARKER:
            nav_end_count += 1
            if nav_end_count == 2:
                body_start = i + 1
                break

    # ── Find where the footer starts ────────────────────────────────────────
    body_end = len(lines)
    for i in range(body_start, len(lines)):
        if lines[i].strip() == FOOTER_START_MARKER:
            body_end = i
            break

    # ── Extract and clean the body lines ────────────────────────────────────
    body_lines = lines[body_start:body_end]

    cleaned = []
    prev_blank = False
    for line in body_lines:
        stripped = line.strip()

        # Drop pure boilerplate lines
        if stripped in BOILERPLATE_LINES:
            continue

        # Collapse consecutive blank lines to one
        if stripped == "":
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False

        cleaned.append(stripped)

    # ── Build the output ─────────────────────────────────────────────────────
    body_text = "\n".join(cleaned).strip()

    output = f"URL: {url}\nTITLE: {title}\n\n{body_text}\n"
    return output


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(INPUT_DIR.glob("*.txt"))
    print(f"Found {len(txt_files)} files in {INPUT_DIR}")

    for path in txt_files:
        try:
            cleaned = clean_file(path)
            out_path = OUTPUT_DIR / path.name
            out_path.write_text(cleaned, encoding="utf-8")
        except Exception as e:
            print(f"  [ERROR] {path.name}: {e}")

    print(f"Done. Clean files written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
