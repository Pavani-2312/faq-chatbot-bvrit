#!/usr/bin/env python3
"""Re-scrape missing/weak pages from BVRIT website."""

import requests
from bs4 import BeautifulSoup
import time

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

def fetch_text(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for tag in soup.find_all(['script', 'style', 'noscript', 'header', 'footer']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 3]
        return '\n'.join(lines)
    except Exception as e:
        return f"ERROR: {e}"

targets = {
    "05_Placements": [
        "https://bvrithyderabad.edu.in/placements/",
        "https://bvrithyderabad.edu.in/information/placement-details/",
    ],
    "08_Contact": [
        "https://bvrithyderabad.edu.in/contact-us/",
    ],
    "01_About_BVRIT": [
        "https://bvrithyderabad.edu.in/information/vision-mission/",
        "https://bvrithyderabad.edu.in/information/leadership/",
        "https://bvrithyderabad.edu.in/information/awards/",
    ],
    "04_Fee_Structure": [
        "https://bvrithyderabad.edu.in/admission/fee-details/",
    ],
}

all_output = {}

for section, urls in targets.items():
    section_texts = []
    for url in urls:
        print(f"Fetching: {url}")
        content = fetch_text(url)
        if content and "ERROR" not in content[:20]:
            section_texts.append(f"=== {url.split('/')[-2] or url.split('/')[-1]} ===\n{content}")
        time.sleep(1)
    all_output[section] = '\n\n'.join(section_texts)
    print(f"[{section}] {len(all_output[section])} chars")

# Print results
for section, content in all_output.items():
    print(f"\n{'='*60}")
    print(f"SECTION: {section} ({len(content)} chars)")
    print(f"{'='*60}")
    # Show first 2000 chars
    print(content[:2000])
    if len(content) > 2000:
        print(f"\n... [truncated, total {len(content)} chars]")