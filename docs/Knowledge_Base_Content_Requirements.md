# Knowledge Base Content Requirements
## What must go into `bvrit_knowledge_base.docx`

**Version:** 1.0 | **Source:** bvrit.ac.in (manual curation, Phase 0) | **Companion:** Requirements.md, Architecture.md

---

## 0. Ground Rules

- **One fact, one source.** Only include information you can point to on bvrit.ac.in. If a page is ambiguous or outdated, note it or omit it — do not infer or estimate.
- **Use real Word heading styles** (Heading 1 for each of the 8 sections, Heading 2 for sub-topics within a section). The chunker splits on these — plain bold text will not work as a boundary.
- **Write facts, not marketing copy.** "B.Tech CSE tuition fee: ₹1,25,000/year" beats "Our stellar CSE program offers unmatched value."
- **Keep each fact atomic and self-contained** within its paragraph/bullet so a single chunk boundary doesn't split a number from its label.
- **Date-stamp anything that changes yearly** (fees, cutoffs, placement stats) with the academic year it applies to, e.g. "AY 2025–26."
- **If a fact isn't on the site, leave it out.** A gap here becomes a graceful refusal later — that's correct behavior, not a defect.

---

## 1. About BVRIT — required fields

| Field | Detail needed |
|---|---|
| Full institution name & founding year | Exact legal/registered name, year established |
| Affiliating university | e.g., JNTUH or applicable university |
| Vision statement | Verbatim or closely paraphrased from the official page |
| Mission statement | Verbatim or closely paraphrased |
| Accreditations | NAAC grade (with cycle/year if stated), NBA-accredited programs (list which branches) |
| Approvals | AICTE approval status, UGC recognition if stated |
| Campus location | City, state, approximate size/area if published |
| Institution type | Autonomous / affiliated, private/deemed, etc. |
| Notable rankings | NIRF or other published rankings, with year |

---

## 2. Departments — required fields

For **each** B.Tech branch offered, capture:

| Field | Detail needed |
|---|---|
| Branch name & short code | e.g., Computer Science and Engineering (CSE) |
| Intake capacity | Number of seats per year, if published |
| Specializations / electives | e.g., AI & ML, Data Science, Cybersecurity tracks under CSE |
| Year established | If the department page states it |
| Faculty count | Total faculty, and split by designation if available (Professor / Associate / Assistant) |
| HOD name | Current Head of Department, if listed |
| Department-level accreditation | NBA status specific to that branch, if different from institution-wide |
| Labs specific to the department | Named labs, if listed on the department page |

List **every** branch the college currently offers — do not summarize or truncate the list, since Dimension-01 (Functional) test cases specifically check that every department appears in list-type answers.

---

## 3. Admissions — required fields

| Field | Detail needed |
|---|---|
| Eligibility criteria | Minimum qualifying exam, minimum marks/percentage |
| Entrance exams accepted | EAMCET/EAPCET, JEE Main, management quota criteria, lateral entry (ECET) if applicable |
| Application process steps | Step-by-step, in the order published |
| Important dates | Application open/close, counseling dates, academic year start — with the year they apply to |
| Reservation / category quota info | If published (SC/ST/OBC/EWS/management seats) |
| Required documents | List exactly as stated on the admissions page |
| Lateral entry details | If BVRIT admits diploma holders directly into 2nd year |
| Management/NRI quota | Separate fee or eligibility rules, if published |

---

## 4. Fee Structure — required fields

**This section needs the most precision — fee questions are high-frequency and highly fact-checkable by RAGAS.**

| Field | Detail needed |
|---|---|
| Tuition fee per branch, per year | Exact amount, with academic year stated |
| Fee category variants | Convener quota vs. management quota, if both exist and differ |
| Hostel fees | Per year, split by room type (if applicable: AC/non-AC, sharing) |
| Mess/food charges | If separate from hostel fee |
| Transport fees | If published, by route/zone |
| One-time charges | Admission fee, caution deposit, ID card, etc. |
| Other recurring charges | Exam fee, library fee, lab fee, if itemized separately |
| Scholarships available | Name, eligibility, and amount/percentage for each scholarship program listed |
| Fee payment schedule | Installments, due dates, late fee penalty if stated |
| Refund policy | If published |

If the website gives a range or "starting from" figure rather than an exact number, record it as a range — do not average it into a single number.

---

## 5. Placements — required fields

| Field | Detail needed |
|---|---|
| Placement percentage | Most recent year's overall placement %, with year stated |
| Highest package (CTC) | Exact figure, year, and company if named |
| Average package (CTC) | Exact figure, year |
| Median package | If published separately from average |
| Top recruiters | Full list of named companies, not "and many more" |
| Branch-wise placement stats | If published separately per department |
| Placement cell details | Name/contact of Training & Placement Officer if listed |
| Internship program details | Stipend ranges, partner companies, if published |
| Year-over-year trend | If multiple years of data are published, capture each year distinctly (this matters for "compare this year vs last year" test questions) |

**Do not** phrase this section in a way that could be read as a guarantee (e.g., avoid "students will get placed") — capture only historical, dated statistics.

---

## 6. Campus & Facilities — required fields

| Field | Detail needed |
|---|---|
| Library | Book count, digital resources (e-journals/IEEE/Springer access), seating capacity, working hours if listed |
| Laboratories | Named labs per department, key equipment if listed |
| Hostel | Separate boys'/girls' hostel details, room types, capacity, curfew/rules if published |
| Sports facilities | Named facilities (indoor/outdoor), any notable sports achievements |
| WiFi / IT infrastructure | Campus-wide WiFi, computer labs, bandwidth if stated |
| Transport | Bus routes, number of buses, areas covered |
| Medical facilities | On-campus health center, tie-ups with hospitals if listed |
| Canteen / food courts | If described |
| Auditoriums / seminar halls | Capacity, notable events hosted |
| Other named amenities | Bank/ATM on campus, bookstore, etc. |

---

## 7. Faculty — required fields

| Field | Detail needed |
|---|---|
| Key faculty per department | Name, designation, highest qualification (Ph.D./M.Tech, university) |
| Research areas | As listed on faculty profile pages |
| Notable publications/patents | If explicitly listed and attributable |
| Faculty-student ratio | If published institution-wide or per department |
| Distinguished/visiting faculty | If the site names any |
| Faculty achievements/awards | If listed |

Note: only include named individuals whose information is publicly published on the official site — do not fabricate faculty members or credentials.

---

## 8. Contact — required fields

| Field | Detail needed |
|---|---|
| Full postal address | Complete, as published |
| Phone number(s) | Main office, admissions helpline if separate |
| Email address(es) | General inquiries, admissions-specific if separate |
| Official website URL | bvrit.ac.in |
| Social media handles | Facebook, Instagram, LinkedIn, X/Twitter, YouTube — whichever are linked |
| Office hours | If published |
| Map/landmark reference | If given, for directions |

**This section doubles as the fallback contact used in refusal messages (FR-3.3)** — it must be complete and accurate, since every "I don't have that information" response will point here.

---

## Document Formatting Checklist (before handing off to ingestion)

- [ ] Each of the 8 sections above starts with a Word **Heading 1**
- [ ] Sub-topics within a section (e.g., each department, each scholarship) use **Heading 2** or bolded sub-labels consistently
- [ ] No marketing language — facts only, in plain declarative sentences or bullet lists
- [ ] Every number has its unit and academic year attached in the same sentence/bullet (never a bare number with the year in a different paragraph)
- [ ] Every department, recruiter, and scholarship is listed individually — no "etc." or "and more" truncation
- [ ] Contact section is complete and would work as a real fallback if quoted verbatim in a refusal message
- [ ] Final pass: read the whole document once and flag any sentence you can't personally verify against bvrit.ac.in — either verify it or delete it

---

## Suggested Verification Pass

Once drafted, do a quick self-audit against the eventual test suite:
1. Pick 3 "Quality" dimension–style questions (e.g., "What is the CSE tuition fee?") and confirm the exact figure is unambiguous in the document.
2. Pick 1 question you know is **not** covered (e.g., "Does BVRIT have a study-abroad program?") and confirm the document genuinely has no answer — this is your refusal-path test case.
3. Check the Fee Structure and Placements sections for any numbers that might conflict if quoted at two different points (year mismatches) — this is your conflict-handling test case.
