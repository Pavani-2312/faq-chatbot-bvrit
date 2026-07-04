"""
format_kb.py — Converts cleaned scraped pages into structured, RAG-ready Markdown files.

For each file in scraped_site/pages_clean/*.txt:
  1. Parses the URL, title, and body text
  2. Infers the page category from the filename/URL
  3. Applies category-specific formatting rules to produce clean Markdown sections
  4. Appends an ## Images section with every image found in the matching
     scaper/output/images/<slug>/ folder, formatted as:
       ![alt text](relative/path/to/image.ext)
       *Caption: <human-readable description from filename>*
  5. Writes output to kb_formatted/<slug>.md

Output layout:
  kb_formatted/
    about_bvrith.md
    admission_hostel.md
    library.md
    ...
    _image_index.md     ← master index of all images grouped by category

Usage:
    python3 format_kb.py
"""

import re
from pathlib import Path

CLEAN_DIR  = Path("scraped_site/pages_clean")
IMAGES_DIR = Path("scaper/output/images")
OUT_DIR    = Path("kb_formatted")

# ── Helpers ──────────────────────────────────────────────────────────────────

def slug_to_title(slug: str) -> str:
    """
    'computer_science_and_engineering_about_hod' →
    'Computer Science And Engineering About Hod'
    """
    return slug.replace("_", " ").title()


def filename_to_caption(fname: str) -> str:
    """
    'DrArunaRaoSL_HoD_CSE.jpg' → 'Dr Aruna Rao SL HoD CSE'
    'elcs-lab-1-bsh-bvrit-hyderabad-college-for-engineering-for-women.jpg' →
    'Elcs Lab 1 Bsh'  (strips long college-suffix noise)
    """
    stem = Path(fname).stem
    # Remove common suffix noise
    for noise in [
        "-bvrit-hyderabad-college-for-engineering-for-women",
        "-bvrit-hyderabad-engineering-women-college",
        "-bvrit-hyderabad",
        "-bvrit",
        "-768x1074", "-768x512", "-768x1051", "-768x1039",
        "-768x513", "-768x326", "-768x1086", "-768x1098",
        "-scaled",
    ]:
        stem = stem.replace(noise, "")
    # Replace separators with spaces
    stem = re.sub(r"[-_]+", " ", stem)
    # Remove dimension patterns like 1024x768
    stem = re.sub(r"\b\d+x\d+\b", "", stem)
    return stem.strip().title()


def find_image_folder(slug: str) -> Path | None:
    """
    Given a page slug, try to find the matching images folder.
    The slug uses underscores; image folders use hyphens.
    """
    # Direct match after replacing underscores with hyphens
    candidate = IMAGES_DIR / slug.replace("_", "-")
    if candidate.exists():
        return candidate
    return None


def get_images_for_page(slug: str) -> list[tuple[str, str]]:
    """
    Returns list of (relative_path, caption) for images belonging to this page.
    """
    folder = find_image_folder(slug)
    if not folder:
        return []
    images = []
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in exts:
            rel = f.relative_to(Path("."))
            caption = filename_to_caption(f.name)
            images.append((str(rel), caption))
    return images


def format_image_section(images: list[tuple[str, str]]) -> str:
    if not images:
        return ""
    lines = ["\n## Images\n"]
    for path, caption in images:
        lines.append(f"![{caption}]({path})")
        lines.append(f"*Caption: {caption}*\n")
    return "\n".join(lines)


# ── Body formatting rules ─────────────────────────────────────────────────────

# Lines that are purely sub-navigation (appear in department pages etc.) — drop them
SUBNAV_LINES = {
    "About the Department", "About HOD", "Faculty", "Milestones", "Laboratories",
    "Curriculum", "Course Content", "Course Outcomes", "BH23 Course Outcomes",
    "R22 Course Outcomes", "R18 Course Outcomes", "Academic Calendars",
    "Funded Projects", "Department Placements", "Patents", "Start – Ups",
    "Innovations by Faculty In Teaching and Learning", "News Letter",
    "Training and Placement Process", "Training and Placement Cell",
    "Training and Placement Team", "Employability Skills", "Internships",
    "Placement Details", "Testimonials",
    "About R & D", "Faculty Thrust Area", "Ph. D Awarded", "Publications",
    "Research Projects", "Consultancy Projects", "Funded FDPs/Conferences",
    "Published", "Granted", "Incentive Policy", "R & D Center",
    "Center of Excellence (CoEs)", "Research Advisory Committee",
    "Research Supervisors", "Research Ethics Committee", "IPR Committee",
    "Seed Funding", "IRINS Link", "Plagiarism Tool", "Research Facility",
}

# Lines that look like section headings (ALL CAPS or known heading patterns)
def is_heading(line: str) -> bool:
    if not line:
        return False
    # All caps, at least 4 chars, no trailing punctuation that would make it a sentence
    if line.isupper() and len(line) >= 4 and not line.endswith((".", "?", "!")):
        return True
    # Known heading keywords
    known = [
        "Vision", "Mission", "About ", "Faculty", "Placements",
        "Highlights", "Library automation", "Digital library",
        "Remote access", "Plagiarism Check", "Rare Books", "Library Staff",
        "Library Timings", "Library Catalogue", "e-library", "e resources",
        "Floor Wise", "FLOOR WISE", "GROUND FLOOR", "FIRST FLOOR",
        "SECOND FLOOR", "THIRD FLOOR",
        "Program Outcomes", "PROGRAM OUTCOMES",
        "Undergraduate programmes", "Postgraduate programmes",
        "Sponsored R&D", "Awards", "International / National",
        "Our Core Values",
    ]
    return any(line.startswith(kw) for kw in known)


def format_body(raw_lines: list[str], page_slug: str) -> str:
    """
    Transform raw cleaned body lines into structured Markdown.
    """
    out = []
    prev_blank = False
    table_mode = False
    table_rows: list[list[str]] = []
    table_header_done = False

    def flush_table():
        nonlocal table_rows, table_header_done
        if not table_rows:
            return
        # Try to detect if first row is a header
        if len(table_rows) >= 2:
            header = table_rows[0]
            out.append("| " + " | ".join(header) + " |")
            out.append("| " + " | ".join(["---"] * len(header)) + " |")
            for row in table_rows[1:]:
                # pad row to header width
                while len(row) < len(header):
                    row.append("")
                out.append("| " + " | ".join(row[:len(header)]) + " |")
        else:
            for row in table_rows:
                out.append("| " + " | ".join(row) + " |")
        out.append("")
        table_rows.clear()
        table_header_done = False

    # ── Detect table blocks: lines that appear in groups of consistent
    #    column count. We use a simple heuristic: after a line that looks
    #    like a table header (e.g. "S.No  Company  Package..."), accumulate
    #    until we get a blank line.
    #    For this scraper output, tables are lines of tab/space separated values
    #    — we detect them by looking for lines where splitting gives N>=3 tokens
    #    and most tokens are short.

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()

        # Drop sub-nav lines
        if line in SUBNAV_LINES:
            i += 1
            continue

        # Blank line handling
        if not line:
            if table_mode:
                flush_table()
                table_mode = False
            if not prev_blank:
                out.append("")
            prev_blank = True
            i += 1
            continue
        prev_blank = False

        # ── Section headings ──
        if is_heading(line):
            if table_mode:
                flush_table()
                table_mode = False
            out.append(f"\n## {line}\n")
            i += 1
            continue

        # ── Numbered list items (1, 2, 3... or "1." "2.") ──
        m = re.match(r'^(\d+)\s+(.+)$', line)
        if m and len(m.group(1)) <= 2 and not re.match(r'^\d+\s+\d', line):
            # Could be a numbered list or a table row starting with a number
            # Treat as numbered list only if next line is also a numbered item
            # or line is short (< 60 chars) — otherwise it's likely a table row
            if len(line) < 80:
                out.append(f"{m.group(1)}. {m.group(2)}")
                i += 1
                continue

        # ── Bullet list items ──
        if line.startswith(("- ", "• ", "* ")):
            out.append(line)
            i += 1
            continue

        # ── Table detection ──
        # A table row is a line with multiple short pipe/space-separated tokens
        tokens = re.split(r'\s{2,}|\t', line)
        tokens = [t.strip() for t in tokens if t.strip()]
        if len(tokens) >= 3 and all(len(t) < 60 for t in tokens):
            table_mode = True
            table_rows.append(tokens)
            i += 1
            continue
        else:
            if table_mode:
                flush_table()
                table_mode = False

        # ── Normal paragraph line ──
        out.append(line)
        i += 1

    if table_mode:
        flush_table()

    # Post-process: collapse multiple blank lines
    result = []
    blank_count = 0
    for line in out:
        if line == "":
            blank_count += 1
            if blank_count <= 1:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    return "\n".join(result).strip()


# ── Category metadata ─────────────────────────────────────────────────────────

CATEGORY_MAP = {
    "about": "About BVRIT",
    "admission": "Admissions",
    "placements": "Placements",
    "library": "Campus Facilities",
    "food": "Campus Facilities",
    "gym": "Campus Facilities",
    "temple": "Campus Facilities",
    "security": "Campus Facilities",
    "pcs": "Campus Facilities",
    "hostel": "Campus Facilities",
    "yoga": "Campus Facilities",
    "computer_science": "Departments — CSE",
    "cse_artificial": "Departments — CSE AI&ML",
    "electronics_and_communication": "Departments — ECE",
    "electrical_and_electronics": "Departments — EEE",
    "information_technology": "Departments — IT",
    "basic_sciences": "Departments — BS&H",
    "post_graduate": "Postgraduate Programs",
    "under_graduate": "Undergraduate Programs",
    "research": "Research",
    "differentiators": "Differentiators",
    "student_activities": "Student Activities",
    "committees": "Committees & Governance",
    "governing": "Committees & Governance",
    "contact": "Contact",
    "management": "Management",
    "principal": "Management",
    "organogram": "Management",
    "nirf": "Rankings & Accreditations",
    "naac": "Rankings & Accreditations",
    "alumni": "Alumni",
    "home": "General",
    "sri_vishnu": "About BVRIT",
    "honor_degree": "Academic Programs",
    "downloads": "General",
    "category": "News & Events",
    "faculty_achievement": "Faculty Achievements",
    "dr_": "Faculty Achievements",
    "national_level": "News & Events",
    "one_week": "News & Events",
    "annual": "News & Events",
    "synergia": "News & Events",
    "iot_and_smart": "News & Events",
}


def get_category(slug: str) -> str:
    for key, val in CATEGORY_MAP.items():
        if slug.startswith(key):
            return val
    return "General"


# ── Main processor ────────────────────────────────────────────────────────────

def process_file(txt_path: Path) -> str:
    """Read a cleaned txt file and produce a structured Markdown string."""
    content = txt_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    url, title, body_lines = "", "", []
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("URL:"):
            url = line[4:].strip()
        elif line.startswith("TITLE:"):
            title = line[6:].strip()
            # Strip " – BVRIT HYDERABAD College..." suffix from title
            title = re.sub(r"\s*[–-]\s*BVRIT HYDERABAD.*$", "", title).strip()
            body_start = i + 1
            break

    body_lines = [l.strip() for l in lines[body_start:] if l.strip()]

    slug = txt_path.stem
    category = get_category(slug)

    formatted_body = format_body(body_lines, slug)
    images = get_images_for_page(slug)
    image_section = format_image_section(images)

    md = f"""---
title: "{title}"
source_url: "{url}"
category: "{category}"
slug: "{slug}"
---

# {title}

> **Source:** [{url}]({url})
> **Category:** {category}

{formatted_body}
{image_section}
"""
    return md.strip() + "\n"


def build_image_index() -> str:
    """Build a master Markdown index of all images grouped by category."""
    lines = ["# Image Index — BVRIT Knowledge Base\n",
             "All images scraped from bvrithyderabad.edu.in, grouped by page category.\n",
             "Each entry: image path | caption | source page\n"]

    by_category: dict[str, list[tuple[str, str, str]]] = {}

    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    for folder in sorted(IMAGES_DIR.iterdir()):
        if not folder.is_dir():
            continue
        slug = folder.name.replace("-", "_")
        category = get_category(slug)
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in exts:
                rel = str(f.relative_to(Path(".")))
                caption = filename_to_caption(f.name)
                by_category.setdefault(category, []).append((rel, caption, slug))

    for cat in sorted(by_category):
        lines.append(f"\n## {cat}\n")
        for rel, caption, slug in by_category[cat]:
            lines.append(f"- **{caption}**")
            lines.append(f"  - Path: `{rel}`")
            lines.append(f"  - Page: `{slug}`")
            lines.append(f"  - ![{caption}]({rel})\n")

    return "\n".join(lines)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(CLEAN_DIR.glob("*.txt"))
    print(f"Processing {len(txt_files)} files...")

    for path in txt_files:
        try:
            md = process_file(path)
            out_path = OUT_DIR / (path.stem + ".md")
            out_path.write_text(md, encoding="utf-8")
        except Exception as e:
            print(f"  [ERROR] {path.name}: {e}")

    # Build image index
    print("Building image index...")
    index_md = build_image_index()
    (OUT_DIR / "_image_index.md").write_text(index_md, encoding="utf-8")

    print(f"Done. Output in {OUT_DIR}/")
    print(f"  {len(txt_files)} page .md files")
    print(f"  1 _image_index.md")


if __name__ == "__main__":
    main()
