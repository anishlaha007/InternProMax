# InternProMax

Find internships and co-ops that fit you, understand what each posting wants, send a resume tailored to it, autofill the application, and keep every application's status up to date. It all runs on your computer.

```
SimplifyJobs list ─► ranked for you ─► posting analysis ─► tailored resume ─► Chrome autofill ─► you click Submit
                                                                                                        │
                        tracker (Saved → Applied → OA → Interviewing → Offer/Rejected) ◄──── auto-marked Applied
                                                  ▲
                                   recruiter emails (paste or IMAP) ─► status updates
```

The design and scope are in [docs/SCOPE.md](docs/SCOPE.md).

## What it does

| | |
|---|---|
| **Pulls listings** | Syncs [SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships) from its machine-readable `listings.json`. That file also covers the off-season terms (Winter/Spring/Fall 2027), which is where the co-ops are. You can add any other list in the same format (New Grad is built in, off by default). Re-syncs every few hours. |
| **Ranks for you** | Filters out what you can't or won't take (term, sponsorship, citizenship, degree level, companies/keywords you excluded, optional strict location). Then it scores the rest on category, role interests matched against the title, your skills, location, dream companies and freshness. Every score shows its reasons. |
| **Reads the posting** | For each job you pursue it pulls the full description (Greenhouse, Lever, Ashby, Workday and SmartRecruiters APIs, schema.org data, or the page itself via the extension). It extracts required vs. nice-to-have skills, what you'd work on, **the kinds of projects/experience they want**, hard requirements (graduation window, GPA, work authorization), your matched and missing skills, and a fit score. |
| **Tailors your resume** | Starts from your "master resume" (everything you've done). It leads with the most relevant experience and projects, rewrites bullets toward what the posting asks for, puts matching skills first, and renders a clean one-page, ATS-friendly PDF. It **never invents anything**: entries are rebuilt from your master copy, rewritten bullets that add numbers you never wrote are reverted, and skills you don't list are dropped. Every change is listed for you. |
| **Autofills applications** | The Chrome extension fills name, contact, links, address, school/degree/major/GPA/graduation, current employer, work authorization, sponsorship, 18+, relocation, "how did you hear", EEO questions and saved answers. It attaches the tailored PDF and drafts free-text answers with AI if you want. It works on Greenhouse, Lever, Ashby and Workday-style forms, plus generic forms. It never overwrites what you typed, and **you** click Submit. |
| **Tracks automatically** | When you submit and the confirmation page appears ("Thank you for applying", `/confirmation`, …), the application is marked **Applied** with a timestamp. "Mark applied" is always one click away. |
| **Email → status** | Paste a recruiter email, or connect your inbox over IMAP (Gmail app passwords work). It detects rejections, online assessments, interview invites, offers and "application received" emails, then matches each to the right application. It suggests the status change, or applies it automatically if you opt in, and never moves an application backwards. |

## Quick start

Requirements: **Python 3.10+** and **Google Chrome** (or any Chromium browser).

```bash
git clone <this repo> && cd InternProMax
./run.sh            # macOS/Linux: creates .venv, installs deps, starts the app
# or: run.bat       # Windows
# or manually:
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python -m internpromax
```

The dashboard opens at **http://127.0.0.1:8420** and pulls the listings on first launch.

### Install the Chrome extension

1. Go to `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and pick the `extension/` folder.
3. Reload the dashboard. The sidebar should say **● Extension connected**.

Chrome will say the extension can "read and change data on all websites". It needs that because application forms live on many different domains. It only acts on pages that look like application forms or that you opened with **Apply**, and it only talks to your local server.

### Set up your profile (≈15 minutes, once)

**Profile** tab:
- **Basics / Education / Authorization & EEO**: used for autofill and filtering. EEO answers default to "decline".
- **Job preferences**: terms (Summer 2027 + the 2027 off-season terms for co-ops are on by default), categories, role interests, locations ("Bay Area", "NYC", "CA", "Remote", "Canada"…), keywords to boost or exclude, dream companies.
- **Master resume**: upload your PDF (it's attached when there's no tailored version) and click **Import into profile** (full import with AI, skills-only without). Then list *all* your experience, projects, activities and skills. Tailored resumes pick from this and never add to it.
- **Application answers**: common answers plus an answer bank for recurring questions.

### Daily flow

1. **Jobs**: new matches first, best score on top. Click a job to see *why* it matched, **Analyze posting**, and **Tailor my resume** (preview, edit text, download PDF).
2. **Apply**: opens the posting in a tab the extension links to the job. The posting is analyzed and your tailored resume generated in the background. The form is filled and the tailored PDF attached.
3. Answer what's left (the panel lists the questions that need you) and click **Submit**. The job moves to **Applied**.
4. **Inbox**: paste recruiter emails, or let IMAP sync find them, and accept the suggested status changes.
5. **Tracker**: board or list view with response rate, interviews and offers. Drag cards between stages and keep notes and a timeline per application.

## Optional: AI (Claude)

Everything works without AI: built-in analyzers handle posting analysis, tailoring and email classification. To add Claude, put an Anthropic API key in **Settings → AI**, or set the `ANTHROPIC_API_KEY` environment variable. With a key it:

- reads postings like a recruiter (catches prose such as "you've shipped a side project with real users"),
- rewrites resume bullets toward each posting (with the no-fabrication checks above),
- drafts answers to free-text application questions (✨ buttons next to text boxes),
- classifies unclear emails and imports your resume PDF into the profile editor.

The default model is `claude-opus-5-5` at medium effort (switchable in Settings). Only posting text and your resume content go to the API; contact details don't.

## Optional: email via IMAP

In **Settings → Email updates**: host `imap.gmail.com`, your address, and an [app password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification). The inbox is opened read-only and checked every 30 minutes. Only job-related messages become suggestions. Turn on auto-apply to let high-confidence updates go through without asking.

## CLI

```bash
python -m internpromax                 # dashboard + API (default port 8420; IPM_PORT to change)
python -m internpromax sync --force    # pull listings now
python -m internpromax analyze JOB_ID  # fetch + analyze one posting
python -m internpromax import file.json
```

Data lives in `./data/` (SQLite + your resume file). Set `IPM_DATA_DIR` to put it elsewhere. **Settings → Your data** exports everything as JSON, or your applications as CSV.

## Privacy & security

- The server binds to `127.0.0.1` only. It rejects requests whose `Host` isn't localhost (blocks DNS rebinding) and rejects state-changing requests from other websites (blocks CSRF). It sends no CORS headers, so other sites can't read your data.
- The extension only talks to your local server, and only switches to a different local address after checking that it really is InternProMax.
- The Anthropic key and IMAP password are stored in your local database and never shown back in the UI.

## Development

```
internpromax/   FastAPI backend: ingest, matching, postings, analysis, tailor, resume_pdf, tracker, emails, inbox, ai, server
internpromax/static/   dashboard (vanilla JS modules, no build step)
extension/      Chrome MV3 extension: background.js, bridge.js, content/{fields,fill,panel,content}.js, popup, options
tests/          pytest suite + tests/e2e (real Chromium + unpacked extension + mock Greenhouse/Lever/Workday forms)
```

```bash
pip install -r requirements-dev.txt && pytest          # unit + API tests
npm install && npm run e2e                             # browser end-to-end test (Playwright + Chromium)
```

## Limits

- Workday flows that need an account, Oracle Cloud and iCIMS use custom widgets. Autofill there is best effort, and the panel lists anything it couldn't fill.
- Until you analyze a job, matching only sees its title, company, location and category (the list has no descriptions). Analyzing adds the real fit score.
- It never submits for you or solves CAPTCHAs, by design.
