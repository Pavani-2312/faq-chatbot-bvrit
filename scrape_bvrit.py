#!/usr/bin/env python3
"""Scrape BVRIT Hyderabad website for FAQ chatbot knowledge base content."""

import requests
from bs4 import BeautifulSoup
import re
import time
import json

BASE_URL = "https://bvrithyderabad.edu.in"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_text(url):
    """Fetch a URL and return visible text content."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        # Remove script, style, nav, header, footer elements
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'noscript']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        # Clean up whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return '\n'.join(lines)
    except Exception as e:
        return f"[ERROR fetching {url}: {e}]"

def extract_page_content(url, name):
    """Fetch a page and extract structured content."""
    print(f"\n--- Fetching: {name} ({url}) ---")
    text = fetch_text(url)
    # Remove common boilerplate
    boilerplate = [
        "Skip to content", "Announcements", "ACCREDITED BY NAAC WITH GRADE",
        "ACCREDITED BY NBA FOR EEE, ECE, CSE", "Study", "Discover", "Research",
        "Differentiators", "Placements", "News", "Alumni", "Approvals",
        "EAMCET", "ECET", "CODE:", "PGECET CODE:", "BVRW", "BVRW1",
        "info@bvrithyderabad.edu.in", "principal@bvrithyderabad.edu.in",
        "+91 40 4241 7773", "Privacy Policy", "Terms of Service",
        "All Rights Reserved", "Designed by", "Powered by",
        "BVRIT HYDERABAD College of Engineering for Women",
    ]
    lines = text.split('\n')
    filtered = []
    for line in lines:
        skip = False
        for b in boilerplate:
            if b.lower() in line.lower():
                skip = True
                break
        if not skip and len(line) > 3:
            filtered.append(line)
    return '\n'.join(filtered)

# Pages to scrape organized by section
pages = {
    "01_About_BVRIT": [
        ("https://bvrithyderabad.edu.in/", "Homepage"),
        ("https://bvrithyderabad.edu.in/about-us/", "About Us"),  # Try this path
        ("https://bvrithyderabad.edu.in/information/vision-mission/", "Vision Mission"),
        ("https://bvrithyderabad.edu.in/information/leadership/", "Leadership"),
    ],
    "02_Departments": [
        ("https://bvrithyderabad.edu.in/computer-science-and-engineering/about-the-department/", "CSE Dept"),
        ("https://bvrithyderabad.edu.in/cse-artificial-intelligence-and-machine-learning/about-the-department/", "AI&ML Dept"),
        ("https://bvrithyderabad.edu.in/electronics-and-communication-engineering/about-the-department/", "ECE Dept"),
        ("https://bvrithyderabad.edu.in/electrical-and-electronics-engineering/about-the-department/", "EEE Dept"),
        ("https://bvrithyderabad.edu.in/information-technology/about-the-department/", "IT Dept"),
        ("https://bvrithyderabad.edu.in/basic-sciences-and-humanities/about-the-department/", "BS&H Dept"),
    ],
    "03_Admissions": [
        ("https://bvrithyderabad.edu.in/admission/admission-process/", "Admission Process"),
        ("https://bvrithyderabad.edu.in/admission/eamcet-ranks/", "EAMCET Ranks"),
        ("https://bvrithyderabad.edu.in/admission/b-category/", "B-Category"),
        ("https://bvrithyderabad.edu.in/admission/intake-of-courses/", "Intake of Courses"),
        ("https://bvrithyderabad.edu.in/admission/documents-to-submit/", "Documents"),
        ("https://bvrithyderabad.edu.in/admission/hostel/", "Hostel Admission"),
        ("https://bvrithyderabad.edu.in/admission/transportation/", "Transportation"),
    ],
    "04_Fee_Structure": [
        ("https://bvrithyderabad.edu.in/admission/fee-details/", "Fee Details"),
    ],
    "05_Placements": [
        ("https://bvrithyderabad.edu.in/placements/", "Placements"),
    ],
    "06_Campus_Facilities": [
        ("https://bvrithyderabad.edu.in/infrastructure/library/", "Library"),
        ("https://bvrithyderabad.edu.in/infrastructure/", "Infrastructure"),
        ("https://bvrithyderabad.edu.in/admission/hostel/", "Hostel"),
        ("https://bvrithyderabad.edu.in/admission/transportation/", "Transport"),
    ],
    "07_Faculty": [
        ("https://bvrithyderabad.edu.in/computer-science-and-engineering/faculty/", "CSE Faculty"),
        ("https://bvrithyderabad.edu.in/cse-artificial-intelligence-and-machine-learning/faculty/", "AI&ML Faculty"),
        ("https://bvrithyderabad.edu.in/electronics-and-communication-engineering/faculty/", "ECE Faculty"),
        ("https://bvrithyderabad.edu.in/electrical-and-electronics-engineering/faculty/", "EEE Faculty"),
        ("https://bvrithyderabad.edu.in/information-technology/faculty/", "IT Faculty"),
    ],
    "08_Contact": [
        ("https://bvrithyderabad.edu.in/contact-us/", "Contact"),
    ],
}

all_content = {}

for section, urls in pages.items():
    section_content = []
    for url, name in urls:
        content = extract_page_content(url, name)
        if content and "[ERROR" not in content[:20]:
            section_content.append(f"=== {name} ===\n{content}")
        # Be polite
        time.sleep(1)
    all_content[section] = '\n\n'.join(section_content)
    print(f"[{section}] Extracted {len(all_content[section])} chars")

# Also try the homepage for About info
print("\n--- Fetching Homepage specific sections ---")
homepage_text = fetch_text(BASE_URL)
print(f"Homepage: {len(homepage_text)} chars")

# Save raw data
with open('scraped_data.json', 'w') as f:
    json.dump(all_content, f, indent=2)

print("\n\n=== SUMMARY ===")
for section, content in all_content.items():
    print(f"{section}: {len(content)} chars")

print("\nDone! Data saved to scraped_data.json")