# BVRIT HYDERABAD College of Engineering for Women — RAG Knowledge Base

**Source:** https://bvrithyderabad.edu.in/ (manually browsed and compiled)
**Compiled:** July 2026
**Files in this set:**

1. `01_About_BVRITH.md`
2. `02_Departments.md`
3. `03_Admissions.md`
4. `04_Fee_Structure.md`
5. `05_Placements.md`
6. `06_Campus_Facilities.md`
7. `07_Faculty.md`
8. `08_Contact.md`

## How to use this set

- Each file corresponds to one of the 8 required top-level sections and should be given a Word **Heading 1** for its title if merged into a single .docx, with **Heading 2** for each sub-topic (each department, each batch, etc.), consistent with the chunking requirements in your Knowledge Base Content Requirements spec.
- Every factual claim carries an inline `(Source: /path)` tag referencing the specific page on bvrithyderabad.edu.in it came from, so it can be fact-checked quickly.
- Wherever the site published conflicting figures for the same fact, **both** figures are shown together with a ⚠️ flag — none were silently resolved.
- Wherever a required field had no information located in the pages reviewed, it is explicitly marked **"Not published on website in the pages reviewed"** rather than omitted or guessed.

## Important scope caveat — read before using in production

This compilation was built from a **representative but non-exhaustive** crawl of the site: the homepage, About, Admissions (process/fees/intake/documents/hostel), one full department page (CSE), Placements (Placement Details), Library, and Contact were reviewed in depth. Several linked subpages referenced throughout these files were **not** individually visited, including:

- The five other departments' full "About the Department" / "About HOD" / "Faculty" / "Laboratories" pages (ECE, EEE, IT, CSE-AI&ML, BS&H)
- The Transportation, B-Category, and EAMCET Ranks admissions pages
- Gym, Temple, Security, PCS Facilities, and Food & Cafeteria campus pages
- The NIRF page and the individual NAAC/AICTE/NBA approval PDFs
- The Internships, Training & Placement Process/Cell/Team, and Testimonials placement pages

Before this document set is used to build a production RAG knowledge base, a second pass visiting these remaining pages is recommended to fill the "Not published on website in the pages reviewed" gaps — many of these are likely to have real answers on the site that simply weren't captured in this pass, as distinct from facts that are genuinely absent from the site.
