"""Per-job pipeline: fetch posting -> analyze -> tailor resume. Runs inline or in a small thread pool."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from . import ai, analysis, db, postings, tailor
from . import profile as profile_mod
from .matching import job_from_row

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ipm-pipeline")
_inflight: set[tuple[str, str]] = set()
_lock = threading.Lock()


def get_job(conn, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return job_from_row(row) if row else None


def get_details(conn, job_id: str) -> dict:
    row = conn.execute("SELECT * FROM job_details WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return {"job_id": job_id, "status": "none", "description": None, "analysis": None}
    return db.row_to_dict(row, ("analysis",))


def set_details(conn, job_id: str, **fields) -> None:
    if "analysis" in fields and not isinstance(fields["analysis"], (str, type(None))):
        fields["analysis"] = json.dumps(fields["analysis"])
    conn.execute("INSERT OR IGNORE INTO job_details(job_id) VALUES(?)", (job_id,))
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE job_details SET {sets} WHERE job_id=?", (*fields.values(), job_id))


def latest_resume(conn, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM resumes WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    return db.row_to_dict(row, ("data", "changes", "warnings"))


def candidate_brief(profile: dict) -> str:
    """What the model sees about the candidate (no contact details)."""
    edu = profile_mod.primary_education(profile)
    auth = profile.get("work_auth") or {}
    lines = [
        f"Education: {edu.get('degree_level', '')} {edu.get('degree', '')} in {edu.get('major', '')} at {edu.get('school', '')}, "
        f"graduating {edu.get('grad_month', '')} {edu.get('grad_year', '')}, GPA {edu.get('gpa') or 'n/a'}",
        f"Work authorization: {'needs sponsorship' if auth.get('needs_sponsorship') else 'no sponsorship needed'}"
        f"{', U.S. citizen' if auth.get('us_citizen') else ''}",
        "Skills: " + ", ".join(profile_mod.all_skills(profile)),
        "Interests: " + ", ".join((profile.get("preferences") or {}).get("interests") or []),
        "",
        json.dumps(tailor.master_for_prompt(profile), indent=1),
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ steps

def store_description(job_id: str, text: str, method: str) -> None:
    text = postings.clean_text(text or "")
    with db.session() as conn:
        set_details(conn, job_id, description=text[:60000], fetch_method=method, fetched_at=db.now(),
                    status="fetched", error=None)


def analyze_job(job_id: str, force: bool = False) -> dict:
    with db.session() as conn:
        job = get_job(conn, job_id)
        if not job:
            raise KeyError(job_id)
        details = get_details(conn, job_id)
        settings = db.get_settings(conn)
        profile = profile_mod.get(conn)
    if details.get("analysis") and not force:
        return details

    text = details.get("description")
    if not text:
        with db.session() as conn:
            set_details(conn, job_id, status="fetching", error=None)
        result = postings.fetch(job.get("url") or "") if job.get("url") else {"text": None, "error": "no URL"}
        if not result.get("text"):
            with db.session() as conn:
                set_details(conn, job_id, status="needs_capture", error=result.get("error"))
                return get_details(conn, job_id)
        text = result["text"]
        store_description(job_id, text, result["method"])

    with db.session() as conn:
        set_details(conn, job_id, status="analyzing", error=None)
    note = None
    try:
        if not ai.available(settings):
            raise ai.AIUnavailable("no key")
        result = ai.analyze_posting(settings, job, text, candidate_brief(profile))
        if not result.get("resume_focus"):
            result["resume_focus"] = [r["name"] for r in tailor.rank_entries(profile, result)]
        method = "ai"
    except (ai.AIUnavailable, ai.AIError) as exc:
        if isinstance(exc, ai.AIError):
            note = f"AI analysis failed ({exc}); used the built-in analyzer"
        result = analysis.analyze(text, profile, job)
        method = "rules"
    with db.session() as conn:
        set_details(conn, job_id, analysis=result, analysis_method=method, analyzed_at=db.now(),
                    status="ready", error=note)
        return get_details(conn, job_id)


def tailor_job(job_id: str, force: bool = False) -> dict:
    with db.session() as conn:
        existing = latest_resume(conn, job_id)
        if existing and existing["status"] == "ready" and not force:
            return existing
    details = analyze_job(job_id)
    with db.session() as conn:
        job = get_job(conn, job_id)
        settings = db.get_settings(conn)
        profile = profile_mod.get(conn)
        if existing and existing["status"] == "queued":
            rid = existing["id"]
            conn.execute("UPDATE resumes SET status='running' WHERE id=?", (rid,))
        else:
            cur = conn.execute("INSERT INTO resumes(job_id, status, created_at) VALUES(?, 'running', ?)", (job_id, db.now()))
            rid = cur.lastrowid
    if not details.get("analysis"):
        with db.session() as conn:
            conn.execute("UPDATE resumes SET status='error', error=? WHERE id=?",
                         ("Need the posting text first: open the job in Chrome with the extension, or paste it in.", rid))
            return latest_resume(conn, job_id)
    if not ((profile.get("resume") or {}).get("experience") or (profile.get("resume") or {}).get("projects")):
        with db.session() as conn:
            conn.execute("UPDATE resumes SET status='error', error=? WHERE id=?",
                         ("Add your experience/projects in Profile → Master resume first.", rid))
            return latest_resume(conn, job_id)

    an = details["analysis"]
    warnings: list[str] = []
    try:
        if not ai.available(settings):
            raise ai.AIUnavailable("no key")
        raw = ai.tailor_resume(settings, job, an, tailor.master_for_prompt(profile))
        data, changes, warnings = tailor.assemble_ai(profile, raw)
        method = "ai"
    except (ai.AIUnavailable, ai.AIError) as exc:
        if isinstance(exc, ai.AIError):
            warnings.append(f"AI tailoring failed ({exc}); used the built-in tailoring")
        data, changes, w2 = tailor.tailor_rules(profile, an)
        warnings += w2
        method = "rules"
    with db.session() as conn:
        conn.execute("UPDATE resumes SET data=?, changes=?, warnings=?, method=?, status='ready' WHERE id=?",
                     (json.dumps(data), json.dumps(changes), json.dumps(warnings), method, rid))
        return latest_resume(conn, job_id)


# ------------------------------------------------------------------ background

def _run(kind: str, job_id: str, force: bool) -> None:
    try:
        if kind == "tailor":
            tailor_job(job_id, force=force)
        else:
            analyze_job(job_id, force=force)
    except Exception as exc:  # never let a background task die silently
        log.exception("pipeline %s failed for %s", kind, job_id)
        with db.session() as conn:
            if kind == "tailor":
                conn.execute("UPDATE resumes SET status='error', error=? WHERE job_id=? AND status='running'",
                             (str(exc), job_id))
            else:
                set_details(conn, job_id, status="error", error=str(exc))
    finally:
        with _lock:
            _inflight.discard((kind, job_id))


def queue(job_id: str, kind: str = "analyze", force: bool = False) -> bool:
    """Queue analyze/tailor for a job. Returns False if it's already running."""
    key = (kind, job_id)
    with _lock:
        if key in _inflight:
            return False
        _inflight.add(key)
    if kind == "tailor":
        with db.session() as conn:
            existing = latest_resume(conn, job_id)
            if not (existing and existing["status"] == "ready" and not force):
                conn.execute("INSERT INTO resumes(job_id, status, created_at) VALUES(?, 'queued', ?)", (job_id, db.now()))
    else:
        with db.session() as conn:
            if force or not get_details(conn, job_id).get("analysis"):
                set_details(conn, job_id, status="queued", error=None)
    _executor.submit(_run, kind, job_id, force)
    return True


def busy(job_id: str) -> dict:
    with _lock:
        return {"analyze": ("analyze", job_id) in _inflight, "tailor": ("tailor", job_id) in _inflight}
