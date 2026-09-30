# InternProMax — Scope & Design

An end-to-end, local-first internship/co-op pipeline:

**find → rank for you → understand the posting → tailor your resume → autofill the application → track it → update from email.**

---

## 1. Goals

| # | Goal | How |
|---|------|-----|
| G1 | Pull every listing from the SimplifyJobs lists (default: `Summer2027-Internships`, which also carries the off-season / co-op terms) and any other list in the same format you point it at | Ingest the machine-readable `.github/scripts/listings.json` that powers those READMEs (≈17k rows, all terms), with ETag caching and a background re-sync |
| G2 | Only surface jobs that fit *you* | Profile-driven hard filters (term, sponsorship, citizenship, degree, excluded companies/keywords) + an explainable 0-100 score (category, title keywords vs. your skills/interests, location, dream companies, freshness) |
| G3 | For every job you pursue: what are they asking for? | Fetch the full posting (Greenhouse / Lever / Ashby / Workday / SmartRecruiters APIs, JSON-LD, or the page text captured by the extension) and extract required skills, preferred skills, responsibilities, the *kinds of projects/experience* they want, grad-date/GPA/degree/auth constraints, and your matched vs. missing skills |
| G4 | A resume tailored to that posting | From your structured "master resume", pick & order the most relevant experience/projects, rewrite bullets to foreground what they want (**never inventing experience** — enforced by post-validation), reorder skills, render an ATS-friendly PDF |
| G5 | Fill the application form for you | Chrome extension (MV3) detects the ATS, fills contact/education/links/work-auth/EEO/common questions from your profile + answer bank, uploads the tailored resume (or your base resume), and drafts free-text answers with AI on request |
| G6 | Auto-track: submitting the form marks it Applied | The extension watches for the submit + the confirmation page ("Thank you for applying", `/confirmation`, …) and marks the application **Applied** with a timestamp |
| G7 | Update statuses from email | Paste an email (or connect IMAP, e.g. Gmail with an app password) → classifier detects *rejected / OA / interview / offer / received*, matches it to the application, and proposes (or auto-applies) the status change |

## 2. Non-goals (deliberately out of scope)

* **Auto-submitting applications.** You always click Submit. This keeps accuracy high and avoids ToS problems.
* Solving CAPTCHAs, creating/logging into ATS accounts (e.g. Workday sign-up) on your behalf.
* LinkedIn Easy Apply automation or scraping LinkedIn/Indeed.
* Hosting: it runs on your machine; your data never leaves it except (optionally) the text you send to the Claude API.

## 3. User flow

```
 ┌───────────── Dashboard (http://127.0.0.1:8420) ─────────────┐
 │ Jobs feed (ranked for you) ─► Job detail                    │
 │    • score + why                                            │
 │    • "Analyze posting"  → requirements, skills ✓/✗, themes   │
 │    • "Tailor resume"    → preview, changes, PDF              │
 │    • "Apply"  ─────────────────────────────┐                │
 └────────────────────────────────────────────┼────────────────┘
                                              ▼
            Chrome tab opened by the extension (tab ↔ job remembered)
                 • panel: "Stripe — SWE Intern · Autofill"
                 • fills fields, uploads tailored resume
                 • you review & click Submit
                 • confirmation detected ─► POST /api/applications/applied
                                              ▼
 Tracker (kanban): Saved → Applied → OA → Interviewing → Offer / Rejected
                                              ▲
     Inbox: paste email / IMAP sync ─► classifier ─► suggested status change
```

## 4. Architecture

```
internpromax/            Python 3.10+ backend (FastAPI + SQLite, runs on 127.0.0.1)
  ingest.py              listings.json fetch (ETag) + normalize + upsert
  matching.py            hard filters + explainable scoring
  skills.py              skills taxonomy (aliases, categories) used everywhere
  postings.py            fetch full job descriptions per ATS + HTML→text
  analysis.py            rule-based posting analysis (+ AI via ai.py)
  tailor.py              resume tailoring (rules + AI) with no-fabrication guardrails
  resume_pdf.py          ATS-friendly PDF renderer (fpdf2)
  tracker.py             applications, status machine, event timeline
  emails.py              email classifier + company matcher
  imap_sync.py           optional IMAP polling → suggestions
  ai.py                  Claude API wrapper (optional; structured JSON outputs)
  server.py              REST API + static dashboard + background sync/tasks
  static/                dashboard (vanilla JS, no build step)
extension/               Chrome MV3 extension (load unpacked)
  background.js          API relay, tab↔job association, badge, alarms
  content/fields.js      field detection dictionary (label → profile key)
  content/autofill.js    fill inputs/selects/radios/comboboxes, file upload
  content/content.js     ATS detection, panel UI, submit/confirmation detection
  bridge.js              lets the dashboard open jobs through the extension
  popup.*, options.*
tests/                   pytest (unit + API) and Playwright e2e (real extension, mock ATS pages)
```

Why a local backend + extension (vs. extension-only): SQLite is durable and exportable, the backend can sync on a schedule, fetch postings without CORS limits, poll IMAP, render PDFs, and keep your API key out of web pages.

## 5. Data model (SQLite, `data/internpromax.db`)

| table | purpose |
|---|---|
| `jobs` | normalized listings (id, source, company, title, category, terms[], locations[], url, sponsorship, degrees[], active, posted/updated, first_seen/last_seen) |
| `job_state` | your per-job state: hidden, opened_at, notes |
| `job_details` | fetched description text, fetch method, analysis JSON (rules/AI), status |
| `resumes` | tailored resumes per job (structured JSON + changes + method) |
| `applications` | one per job/app: company, title, url, status, applied_at, source (extension/manual/dashboard) |
| `events` | timeline: status changes, submissions detected, emails, notes |
| `email_suggestions` | classified emails awaiting accept/dismiss |
| `kv` | profile JSON, settings, sync metadata |

Application statuses: `saved → applied → oa → interviewing → offer`, plus terminal `rejected`, `withdrawn`, `ghosted`. Email-driven updates never move an application *backwards* (a late "we received your application" won't undo "interviewing").

## 6. Matching (G2)

Hard filters (job hidden unless you toggle "show filtered"): inactive/closed, term not in your target terms, needs-sponsorship vs. "Does Not Offer Sponsorship", non-citizen vs. "U.S. Citizenship is Required", your degree level not accepted (e.g. PhD-only), excluded companies, excluded title keywords, (optional) strict location.

Score (0-100, each component shown as a reason chip):
* category preference (up to 25)
* title ↔ your interests/skills/keywords (up to 30)
* location preference incl. remote (up to 15)
* dream companies (15)
* freshness: ≤3d / ≤7d / ≤14d (up to 10)
* sponsorship explicitly offered when you need it (5)
* penalties: advanced-degree-only titles when you're undergrad, etc.
* If an AI fit score exists for the job (from posting analysis), final = 50/50 blend.

## 7. Posting analysis & tailored resume (G3, G4)

**Fetch order:** ATS JSON API (Greenhouse `boards-api`, Lever `api.lever.co/v0/postings`, Ashby `posting-api`, Workday `wday/cxs/...`, SmartRecruiters `api.smartrecruiters.com`) → schema.org `JobPosting` JSON-LD → readable page text. If the site needs JavaScript, the extension captures the posting text from the open tab.

**Analysis output:** summary, required skills, preferred skills, responsibilities, *project/experience themes they look for*, keywords, constraints (grad window, GPA, degree, work auth), matched vs. missing skills against your profile, fit score + reasons, suggestions for gaps.
* Rules engine (free, offline): skills taxonomy + section detection ("Minimum qualifications", "Nice to have", "What you'll do"...).
* Claude (optional, `ANTHROPIC_API_KEY`): structured-JSON analysis that also understands prose like "you've shipped a side project with real users".

**Tailoring:** input = master resume (all your experience/projects/skills) + analysis.
* Rules: rank experience bullets and projects by overlap with what they want, keep the best N projects, put matched skills first.
* Claude: selects/reorders and rewrites bullets to mirror the posting's language **only where truthful**.
* Guardrails (both paths): output entries must exist in the master resume (unknown companies/projects are dropped), skills must appear somewhere in the master resume, metrics/numbers not present in the original bullet are flagged, and every change is listed for your review.
* Output: preview in the dashboard, PDF download, and the extension uploads the tailored PDF automatically when you apply.

"For every application": clicking **Apply** (or Save) queues analysis + tailoring in the background (setting-controlled); the extension waits up to ~90s for the tailored PDF before falling back to your base resume.

## 8. Chrome extension (G5, G6)

* **Tab ↔ job association:** the dashboard opens jobs *through* the extension, so the extension knows which job a tab (and its iframes, redirects, and child tabs) belongs to. Direct visits are matched by URL/ATS job id via `/api/jobs/lookup`.
* **Field detection:** for every input/select/textarea/radio group/combobox, build a label from `<label for>`, `aria-label(ledby)`, placeholder, name/id, Workday `data-automation-id`, fieldset legends and nearby text; match against a prioritized dictionary (first/last/full/preferred name, email, phone, address, city/state/zip/country, location, LinkedIn/GitHub/portfolio, school, degree, major, GPA, graduation month/year, current company/title, work authorization, sponsorship, 18+, relocation, previous employment, how-did-you-hear, pronouns, EEO gender/race/hispanic/veteran/disability, salary) then fall back to your answer bank (fuzzy question match).
* **Filling:** React/Vue-safe value setting + input/change/blur events, `<select>` best-option matching, yes/no radios, custom comboboxes (react-select, Workday listboxes) best-effort, resume upload via `DataTransfer`. Never overwrites something you typed.
* **Submit detection:** capture-phase `submit` + clicks on "Submit (application)" buttons record an attempt; confirmation is detected by URL (`/confirmation`, `/thanks`, `/submitted`…) or text ("Thank you for applying", "Application submitted", "We've received your application") within 2 minutes → marked Applied. Attempt without confirmation → the panel asks "Did it go through?". Manual "Mark applied" is always available.
* Panel lives in a Shadow DOM (no style clashes), top frame only; autofill runs in every frame (embedded Greenhouse iframes).

## 9. Email → status (G7)

* Rules classifier (priority offer > rejected > interview > OA > received) using phrase lists ("unfortunately… not moving forward", "HackerRank/CodeSignal", "schedule an interview", "pleased to offer"…), with confidence.
* Company matching: sender domain, display name, subject/body mentions vs. your applications (normalized names, "Inc/LLC" stripped, ATS senders like `no-reply@greenhouse.io` handled via body text).
* Paste flow in the Inbox tab, or IMAP sync (Gmail/Outlook/any, app password) that polls recent mail, keeps only job-related messages and creates suggestions. Optional auto-apply for high-confidence matches.
* Optional Claude fallback for low-confidence classification.

## 10. Security & privacy

* Binds to `127.0.0.1` only; `Host` header must be localhost (blocks DNS rebinding); state-changing requests from any web origin other than the dashboard or a `chrome-extension://` origin are rejected (blocks CSRF from random sites); no permissive CORS, so other sites can't read your profile.
* All data in `./data/` (gitignored). IMAP password / API key stored locally in SQLite or read from env vars.
* Only posting text + your resume/profile are sent to Claude, and only when you configure a key.

## 11. Milestones

1. Backend core: ingestion, profile, matching, API, dashboard jobs feed
2. Posting fetch + analysis, master resume editor, tailoring + PDF
3. Extension: association, detection, autofill, resume upload, submit detection
4. Tracker + email classifier + IMAP
5. Tests: unit, API, e2e (real Chromium + unpacked extension against mock Greenhouse/Lever/Workday-style forms)

## 12. Known limits / future work

* Some ATSs (Workday multi-step with account creation, Oracle Cloud, iCIMS) have custom widgets; autofill is best-effort there and the panel reports which fields it couldn't fill.
* Title-only matching for jobs you haven't analyzed (the list has no descriptions); analyze/AI-rank the top of your feed for better signal.
* Direct Gmail API (OAuth) could replace IMAP later.
