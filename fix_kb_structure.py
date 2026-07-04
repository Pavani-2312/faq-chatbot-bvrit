"""
fix_kb_structure.py

Fixes the two structural issues in auto-generated kb_formatted/*.md files:
  1. Removes YAML frontmatter block (--- ... ---)
  2. Replaces blockquote Source/Category header with clean bold lines + divider

Only processes files last modified at exactly 08:13 (the auto-gen run).
Manually edited files (08:22 onwards) are untouched.

Usage:
    python3 fix_kb_structure.py           # dry run — shows what would change
    python3 fix_kb_structure.py --apply   # applies changes in place
"""

import re
import sys
from pathlib import Path
from datetime import datetime

KB_DIR = Path("kb_formatted")
DRY_RUN = "--apply" not in sys.argv


def is_unedited(path: Path) -> bool:
    """Files auto-generated at 08:13 have mtime hour=8, minute=13."""
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return mtime.hour == 8 and mtime.minute == 13


def fix_file(path: Path) -> tuple[bool, str]:
    """
    Returns (was_changed, new_content).
    """
    text = path.read_text(encoding="utf-8")
    original = text

    # ── 1. Extract YAML frontmatter values before stripping ──
    source_url = ""
    category   = ""

    yaml_match = re.match(
        r'^---\n(.*?)\n---\n',
        text, re.DOTALL
    )
    if yaml_match:
        yaml_block = yaml_match.group(1)
        url_m  = re.search(r'^source_url:\s*"(.+)"', yaml_block, re.MULTILINE)
        cat_m  = re.search(r'^category:\s*"(.+)"',   yaml_block, re.MULTILINE)
        if url_m:
            source_url = url_m.group(1).strip()
        if cat_m:
            category = cat_m.group(1).strip()
        # Strip the YAML block
        text = text[yaml_match.end():]

    # ── 2. Replace blockquote Source/Category header ──
    # Pattern: optional blank line, then:
    #   > **Source:** [url](url)
    #   > **Category:** CAT
    #   blank line
    bq_pattern = re.compile(
        r'\n?> \*\*Source:\*\* \[.*?\]\(.*?\)\n> \*\*Category:\*\* .+\n',
        re.MULTILINE
    )
    if bq_pattern.search(text):
        # Build the clean replacement header
        clean_header = (
            f"\n**Source:** {source_url}\n"
            f"**Category:** {category}\n\n"
            f"---\n"
        )
        text = bq_pattern.sub(clean_header, text, count=1)

    changed = text != original
    return changed, text


def main():
    files = sorted(KB_DIR.glob("*.md"))
    unedited = [f for f in files if f.name != "_image_index.md" and is_unedited(f)]

    print(f"Found {len(unedited)} unedited files (08:13 timestamp)")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'APPLYING CHANGES'}\n")

    changed_count = 0
    for path in unedited:
        changed, new_text = fix_file(path)
        if changed:
            changed_count += 1
            if DRY_RUN:
                print(f"  [would fix] {path.name}")
            else:
                path.write_text(new_text, encoding="utf-8")
                print(f"  [fixed]     {path.name}")
        else:
            if DRY_RUN:
                print(f"  [no change] {path.name}")

    print(f"\n{'Would fix' if DRY_RUN else 'Fixed'} {changed_count}/{len(unedited)} files.")
    if DRY_RUN:
        print("Run with --apply to write changes.")


if __name__ == "__main__":
    main()
