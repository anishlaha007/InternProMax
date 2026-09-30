"""FastAPI app: REST API for the dashboard + extension, static dashboard, background scheduler."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, ai, ats, config, db, inbox, ingest, pipeline, resume_pdf, skills, tailor, tracker
from . import profile as profile_mod
from .matching import DEGREE_LEVELS, Matcher, job_from_row

log = logging.getLogger("internpromax")

# ------------------------------------------------------------------ background scheduler

_sync_lock = threading.Lock()
_sync_state = {"running": False, "last": None, "error": None}


def run_sync(force: bool = False) -> dict:
    if not _sync_lock.acquire(blocking=False):
        return {"running": True}
    _sync_state.update(running=True, error=None)
    try:
        result = ingest.sync_all(force=force)
        _sync_state["last"] = result
        return result
    except Exception as exc:
        _sync_state["error"] = str(exc)
        raise
    finally:
        _sync_state["running"] = False
        _sync_lock.release()


def _scheduler(stop: threading.Event) -> None:
    last_imap = 0.0
    while not stop.is_set():
        try:
            with db.session() as conn:
                settings = db.get_settings(conn)
                last = (db.kv_get(conn, "last_sync", {}) or {}).get("at", 0)
            if time.time() - last > float(settings.get("sync_interval_hours") or 6) * 3600:
                run_sync()
            imap = settings.get("imap") or {}
            if imap.get("enabled") and time.time() - last_imap > float(imap.get("interval_minutes") or 30) * 60:
                last_imap = time.time()
                try:
                    inbox.imap_sync()
                except Exception as exc:
                    log.warning("IMAP sync failed: %s", exc)
        except Exception:
            log.exception("scheduler tick failed")
        stop.wait(60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = threading.Event()
    if not os.environ.get("IPM_NO_BACKGROUND"):
        threading.Thread(target=_scheduler, args=(stop,), daemon=True, name="ipm-scheduler").start()
    yield
    stop.set()


app = FastAPI(title="InternProMax", version=__version__, lifespan=lifespan)

# ------------------------------------------------------------------ security

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = (request.headers.get("host") or "").lower()
    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    if hostname not in _LOCAL_HOSTS and hostname != "testserver":
        return JSONResponse({"detail": "InternProMax only answers on localhost"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        ok = origin.startswith("chrome-extension://") or re.fullmatch(
            r"https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?", origin) is not None
        if not ok:
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    return await call_next(request)


# ------------------------------------------------------------------ helpers

def _job_or_404(conn, job_id: str) -> dict:
    job = pipeline.get_job(conn, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _masked_settings(settings: dict) -> dict:
    s = json.loads(json.dumps(settings))
    s["anthropic_api_key_set"] = bool(settings.get("anthropic_api_key")) or bool(os.environ.get("ANTHROPIC_API_KEY"))
    s["anthropic_api_key_from_env"] = not settings.get("anthropic_api_key") and bool(os.environ.get("ANTHROPIC_API_KEY"))
    s["anthropic_api_key"] = ""
    s["imap"]["password_set"] = bool(settings.get("imap", {}).get("password"))
    s["imap"]["password"] = ""
    return s


def _resume_file_meta(conn) -> dict | None:
    meta = db.kv_get(conn, "resume_file")
    if meta and (config.DATA_DIR / "files" / meta["stored_as"]).exists():
        return meta
    return None


def _display_name(profile: dict) -> str:
    p = profile["personal"]
    name = "_".join(x for x in (p.get("first_name"), p.get("last_name")) if x) or "Resume"
    return re.sub(r"[^A-Za-z0-9_\-]", "", name) + "_Resume"


# ------------------------------------------------------------------ meta / health

@app.get("/api/health")
def health():
    with db.session() as conn:
        settings = db.get_settings(conn)
        n = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
        last = db.kv_get(conn, "last_sync")
    return {"ok": True, "app": "internpromax", "version": __version__, "ai": ai.available(settings),
            "jobs": n, "last_sync": last, "sync_running": _sync_state["running"]}


@app.get("/api/meta")
def meta():
    with db.session() as conn:
        terms: dict[str, int] = {}
        for r in conn.execute("SELECT terms FROM jobs WHERE active=1 AND visible=1"):
            for t in json.loads(r["terms"]):
                terms[t] = terms.get(t, 0) + 1
    order = {"Spring": 0, "Summer": 1, "Fall": 2, "Winter": 3}

    def term_key(t: str):
        m = re.match(r"(\w+) (\d{4})", t)
        return (int(m.group(2)), order.get(m.group(1), 9)) if m else (9999, 9)

    return {
        "categories": ingest.CATEGORIES,
        "terms": [{"term": t, "count": terms[t]} for t in sorted(terms, key=term_key)],
        "statuses": [{"id": s, "label": tracker.STATUS_LABELS[s]} for s in tracker.STATUSES],
        "interests": list(skills.ROLE_FAMILIES),
        "degree_levels": DEGREE_LEVELS,
        "ai_models": ai.MODEL_CHOICES,
        "skill_names": sorted(skills.SKILLS),
    }


# ------------------------------------------------------------------ profile

@app.get("/api/profile")
def get_profile():
    with db.session() as conn:
        p = profile_mod.get(conn)
        settings = db.get_settings(conn)
        return {"profile": p, "completeness": profile_mod.completeness(p), "resume_file": _resume_file_meta(conn),
                "skills": profile_mod.all_skills(p), "ai": ai.available(settings),
                "flags": {k: settings.get(k) for k in ("use_tailored_resume", "autofill_on_load", "auto_tailor_on_apply", "auto_analyze_on_apply")}}


@app.put("/api/profile")
def put_profile(payload: dict = Body(...)):
    with db.session() as conn:
        saved = profile_mod.save(conn, payload.get("profile", payload))
        return {"profile": saved, "completeness": profile_mod.completeness(saved)}


@app.post("/api/profile/resume-file")
async def upload_resume(file: UploadFile = File(...)):
    ext = Path(file.filename or "resume.pdf").suffix.lower()
    if ext not in (".pdf", ".docx", ".doc"):
        raise HTTPException(400, "Upload a PDF or Word resume")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Resume must be under 8 MB")
    config.ensure_data_dir()
    stored = f"resume{ext}"
    for old in (config.DATA_DIR / "files").glob("resume.*"):
        old.unlink()
    (config.DATA_DIR / "files" / stored).write_bytes(data)
    text = ""
    if ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception as exc:
            log.info("could not extract resume text: %s", exc)
    meta = {"name": file.filename, "stored_as": stored, "size": len(data), "uploaded_at": db.now(),
            "content_type": file.content_type or ("application/pdf" if ext == ".pdf" else "application/octet-stream")}
    with db.session() as conn:
        db.kv_set(conn, "resume_file", meta)
        db.kv_set(conn, "resume_text", text)
    return {"file": meta, "text_preview": text[:3000], "skills_found": skills.extract(text)}


@app.get("/api/profile/resume-file")
def download_resume_file():
    with db.session() as conn:
        meta = _resume_file_meta(conn)
        name = _display_name(profile_mod.get(conn))
    if not meta:
        raise HTTPException(404, "No resume uploaded")
    ext = Path(meta["stored_as"]).suffix
    return FileResponse(config.DATA_DIR / "files" / meta["stored_as"], media_type=meta["content_type"], filename=f"{name}{ext}")


@app.post("/api/profile/import-resume")
def import_resume():
    """Turn the uploaded resume into structured profile fields (AI when available)."""
    with db.session() as conn:
        text = db.kv_get(conn, "resume_text", "")
        settings = db.get_settings(conn)
    if not text.strip():
        raise HTTPException(400, "Upload a text-based PDF resume first")
    if ai.available(settings):
        try:
            return {"method": "ai", "proposal": ai.parse_resume(settings, text)}
        except ai.AIError as exc:
            note = f"AI import failed ({exc}); only skills were detected."
    else:
        note = "Add an Anthropic API key to import every section automatically; skills were detected with the built-in parser."
    found = skills.extract(text)
    groups: dict[str, list[str]] = {}
    for s in found:
        groups.setdefault(skills.category_of(s), []).append(s)
    return {"method": "rules", "note": note,
            "proposal": {"skills": [{"category": k, "items": v} for k, v in groups.items()]}}


# ------------------------------------------------------------------ settings + sync

@app.get("/api/settings")
def get_settings():
    with db.session() as conn:
        s = db.get_settings(conn)
        out = _masked_settings(s)
        out["source_meta"] = db.kv_get(conn, "source_meta", {})
        out["last_sync"] = db.kv_get(conn, "last_sync")
        out["imap_last"] = db.kv_get(conn, "imap_last")
        return out


@app.put("/api/settings")
def put_settings(patch: dict = Body(...)):
    patch = {k: v for k, v in patch.items() if k in config.DEFAULT_SETTINGS}
    if "imap" in patch and not patch["imap"].get("password"):
        patch["imap"].pop("password", None)
    if patch.get("anthropic_api_key") is None:
        patch.pop("anthropic_api_key", None)
    with db.session() as conn:
        return _masked_settings(db.save_settings(conn, patch))


@app.post("/api/settings/clear-secret")
def clear_secret(payload: dict = Body(...)):
    with db.session() as conn:
        if payload.get("name") == "anthropic_api_key":
            db.save_settings(conn, {"anthropic_api_key": ""})
        elif payload.get("name") == "imap_password":
            db.save_settings(conn, {"imap": {"password": ""}})
        return _masked_settings(db.get_settings(conn))


@app.post("/api/sync")
def sync(payload: dict = Body(default={})):
    if payload.get("wait"):
        return run_sync(force=bool(payload.get("force")))
    if _sync_state["running"]:
        return {"started": False, "running": True}
    threading.Thread(target=run_sync, kwargs={"force": bool(payload.get("force"))}, daemon=True).start()
    return {"started": True}


@app.get("/api/sync/status")
def sync_status():
    with db.session() as conn:
        return {"running": _sync_state["running"], "error": _sync_state["error"], "last": db.kv_get(conn, "last_sync")}


# ------------------------------------------------------------------ jobs feed

JOB_QUERY = """
SELECT j.*, coalesce(s.hidden, 0) AS hidden, s.opened_at, d.status AS details_status,
       json_extract(d.analysis, '$.fit_score') AS fit, a.id AS app_id, a.status AS app_status
FROM jobs j
LEFT JOIN job_state s ON s.job_id = j.id
LEFT JOIN job_details d ON d.job_id = j.id
LEFT JOIN applications a ON a.job_id = j.id
WHERE j.visible = 1
"""


def _card(job: dict, row, scored, filtered: list[str], seen_at: int) -> dict:
    return {
        "id": job["id"], "company": job["company"], "title": job["title"], "category": job["category"],
        "terms": job["terms"], "locations": job["locations"], "url": job["url"], "ats": job["ats"],
        "sponsorship": job["sponsorship"], "degrees": job["degrees"], "active": bool(job["active"]),
        "date_posted": job["date_posted"], "first_seen": job["first_seen"],
        "score": scored.score if scored else None, "reasons": scored.reasons if scored else [],
        "filtered": filtered, "hidden": bool(row["hidden"]), "opened_at": row["opened_at"],
        "app_id": row["app_id"], "app_status": row["app_status"], "details_status": row["details_status"],
        "fit": row["fit"], "is_new": bool(seen_at and job["first_seen"] > seen_at),
    }


@app.get("/api/jobs")
def list_jobs(view: str = "matches", q: str = "", term: str = "", category: str = "", sort: str = "score",
              limit: int = 100, offset: int = 0, new_only: bool = False, include_applied: bool = False):
    with db.session() as conn:
        profile = profile_mod.get(conn)
        seen_at = db.kv_get(conn, "feed_seen_at", 0)
        rows = conn.execute(JOB_QUERY).fetchall()
    m = Matcher(profile)
    ql = q.strip().lower()
    counts = {"matches": 0, "filtered": 0, "hidden": 0, "saved": 0, "applied": 0, "new": 0}
    items = []
    dedupe: set[tuple] = set()
    for row in rows:
        job = job_from_row(row)
        if ql and ql not in f"{job['company']} {job['title']} {' '.join(job['locations'])}".lower():
            continue
        if term and term not in job["terms"]:
            continue
        if category and job["category"] != category:
            continue
        filtered = m.hard_filters(job)
        hidden = bool(row["hidden"])
        app_status = row["app_status"]
        applied = app_status not in (None, "saved")
        if hidden:
            bucket = "hidden"
        elif app_status == "saved":
            bucket = "saved"
        elif applied:
            bucket = "applied"
        elif filtered:
            bucket = "filtered"
        else:
            bucket = "matches"
        is_new = bool(seen_at and job["first_seen"] > seen_at)
        key = (job["company"].lower(), job["title"].lower(), tuple(sorted(job["locations"])))
        if bucket == "matches":
            if key in dedupe:
                continue
            dedupe.add(key)
            if is_new:
                counts["new"] += 1
        counts[bucket] += 1
        wanted = {
            "matches": bucket == "matches" or (include_applied and bucket in ("applied", "saved") and not filtered),
            "filtered": bucket == "filtered",
            "hidden": bucket == "hidden",
            "saved": bucket == "saved",
            "applied": bucket == "applied",
            "all": True,
        }.get(view, False)
        if not wanted or (new_only and not is_new):
            continue
        scored = m.score(job, ai_fit=row["fit"])
        items.append(_card(job, row, scored, filtered, seen_at))
    if sort == "newest":
        items.sort(key=lambda x: -(x["date_posted"] or 0))
    else:
        items.sort(key=lambda x: (-(x["score"] or 0), -(x["date_posted"] or 0)))
    return {"total": len(items), "counts": counts, "items": items[offset: offset + limit], "seen_at": seen_at}


@app.post("/api/jobs/mark-seen")
def mark_seen():
    with db.session() as conn:
        db.kv_set(conn, "feed_seen_at", db.now())
    return {"ok": True}


@app.get("/api/jobs/lookup")
def lookup(url: str):
    key, akey = ats.url_key(url), ats.parse(url).get("key")
    with db.session() as conn:
        row = None
        if akey:
            row = conn.execute("SELECT * FROM jobs WHERE ats_key=? ORDER BY active DESC, date_posted DESC LIMIT 1", (akey,)).fetchone()
        if not row and key:
            row = conn.execute("SELECT * FROM jobs WHERE url_key=? ORDER BY active DESC, date_posted DESC LIMIT 1", (key,)).fetchone()
        job = job_from_row(row) if row else None
        app_row = tracker.find(conn, job_id=job["id"] if job else None, url=url)
    return {"job": job, "application": app_row}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    with db.session() as conn:
        job = _job_or_404(conn, job_id)
        profile = profile_mod.get(conn)
        details = pipeline.get_details(conn, job_id)
        state = conn.execute("SELECT * FROM job_state WHERE job_id=?", (job_id,)).fetchone()
        app_row = tracker.find(conn, job_id=job_id)
        resume = pipeline.latest_resume(conn, job_id)
    fit = (details.get("analysis") or {}).get("fit_score")
    scored = Matcher(profile).score(job, ai_fit=fit)
    return {"job": job, "score": scored.score, "reasons": scored.reasons, "filtered": Matcher(profile).hard_filters(job),
            "state": dict(state) if state else None, "details": details, "application": app_row,
            "resume": resume, "busy": pipeline.busy(job_id)}


@app.post("/api/jobs/{job_id}/hide")
def hide_job(job_id: str, payload: dict = Body(default={})):
    hidden = 1 if payload.get("hidden", True) else 0
    with db.session() as conn:
        _job_or_404(conn, job_id)
        conn.execute("INSERT INTO job_state(job_id, hidden) VALUES(?, ?) ON CONFLICT(job_id) DO UPDATE SET hidden=excluded.hidden",
                     (job_id, hidden))
    return {"ok": True, "hidden": bool(hidden)}


@app.post("/api/jobs/{job_id}/save")
def save_job(job_id: str):
    with db.session() as conn:
        job = _job_or_404(conn, job_id)
        app_row = tracker.find(conn, job_id=job_id) or tracker.create_for_job(conn, job, "saved", "dashboard")
        settings = db.get_settings(conn)
    if settings.get("auto_analyze_on_apply"):
        pipeline.queue(job_id, "analyze")
    return {"application": app_row}


@app.post("/api/jobs/{job_id}/open")
def open_job(job_id: str):
    """Called when you click Apply: remember it and prepare analysis + tailored resume in the background."""
    with db.session() as conn:
        job = _job_or_404(conn, job_id)
        conn.execute("INSERT INTO job_state(job_id, opened_at) VALUES(?, ?) ON CONFLICT(job_id) DO UPDATE SET opened_at=excluded.opened_at",
                     (job_id, db.now()))
        settings = db.get_settings(conn)
    queued = []
    if settings.get("auto_tailor_on_apply"):
        pipeline.queue(job_id, "tailor")
        queued.append("tailor")
    elif settings.get("auto_analyze_on_apply"):
        pipeline.queue(job_id, "analyze")
        queued.append("analyze")
    return {"job": job, "queued": queued}


@app.post("/api/jobs/{job_id}/description")
def capture_description(job_id: str, payload: dict = Body(...)):
    text = (payload.get("text") or "").strip()
    if len(text) < 200:
        raise HTTPException(400, "That doesn't look like a full job description")
    with db.session() as conn:
        _job_or_404(conn, job_id)
        details = pipeline.get_details(conn, job_id)
    if details.get("description") and not payload.get("force") and details.get("status") not in ("needs_capture", "error"):
        return {"stored": False, "reason": "already have the description"}
    pipeline.store_description(job_id, text, payload.get("source") or "captured")
    pipeline.queue(job_id, "analyze", force=True)
    return {"stored": True}


@app.post("/api/jobs/{job_id}/analyze")
def analyze_job(job_id: str, payload: dict = Body(default={})):
    with db.session() as conn:
        _job_or_404(conn, job_id)
    force = bool(payload.get("force"))
    if payload.get("wait"):
        return {"details": pipeline.analyze_job(job_id, force=force)}
    return {"queued": pipeline.queue(job_id, "analyze", force=force)}


@app.post("/api/jobs/{job_id}/tailor")
def tailor_job(job_id: str, payload: dict = Body(default={})):
    with db.session() as conn:
        _job_or_404(conn, job_id)
    force = bool(payload.get("force"))
    if payload.get("wait"):
        return {"resume": pipeline.tailor_job(job_id, force=force)}
    return {"queued": pipeline.queue(job_id, "tailor", force=force)}


@app.get("/api/jobs/{job_id}/resume-status")
def resume_status(job_id: str):
    with db.session() as conn:
        r = pipeline.latest_resume(conn, job_id)
        settings = db.get_settings(conn)
        has_file = _resume_file_meta(conn) is not None
        p = profile_mod.get(conn)
    has_master = bool(p["resume"].get("experience") or p["resume"].get("projects"))
    return {"tailored": r["status"] if r else "none", "use_tailored": bool(settings.get("use_tailored_resume")),
            "has_base_file": has_file, "has_master": has_master, "error": r.get("error") if r else None}


@app.get("/api/jobs/{job_id}/resume.pdf")
def job_resume_pdf(job_id: str, variant: str = "auto"):
    with db.session() as conn:
        _job_or_404(conn, job_id)
        r = pipeline.latest_resume(conn, job_id)
        settings = db.get_settings(conn)
        p = profile_mod.get(conn)
        meta = _resume_file_meta(conn)
    name = _display_name(p)
    tailored_ok = r and r["status"] == "ready" and r.get("data")
    if variant == "tailored" or (variant == "auto" and tailored_ok and settings.get("use_tailored_resume")):
        if not tailored_ok:
            raise HTTPException(404, "No tailored resume yet")
        return Response(resume_pdf.render(r["data"]), media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{name}.pdf"', "X-Resume-Variant": "tailored"})
    if meta and variant in ("auto", "base"):
        return FileResponse(config.DATA_DIR / "files" / meta["stored_as"], media_type=meta["content_type"],
                            filename=f"{name}{Path(meta['stored_as']).suffix}", headers={"X-Resume-Variant": "uploaded"})
    if p["resume"].get("experience") or p["resume"].get("projects"):
        return Response(resume_pdf.render(tailor.base_resume(p)), media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{name}.pdf"', "X-Resume-Variant": "master"})
    raise HTTPException(404, "Upload a resume or fill in your master resume first")


@app.get("/api/resume/master.pdf")
def master_pdf():
    with db.session() as conn:
        p = profile_mod.get(conn)
    return Response(resume_pdf.render(tailor.base_resume(p)), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_display_name(p)}.pdf"'})


@app.post("/api/resume/preview.pdf")
def preview_pdf(resume: dict = Body(...)):
    return Response(resume_pdf.render(resume), media_type="application/pdf")


@app.put("/api/jobs/{job_id}/resume")
def edit_tailored(job_id: str, payload: dict = Body(...)):
    """Save your manual edits to a tailored resume."""
    with db.session() as conn:
        _job_or_404(conn, job_id)
        conn.execute("INSERT INTO resumes(job_id, data, changes, warnings, method, status, created_at) VALUES(?,?,?,?, 'edited', 'ready', ?)",
                     (job_id, json.dumps(payload["data"]), json.dumps(payload.get("changes") or ["Edited by you"]), "[]", db.now()))
        return {"resume": pipeline.latest_resume(conn, job_id)}


# ------------------------------------------------------------------ applications

@app.get("/api/applications")
def applications():
    with db.session() as conn:
        return {"items": tracker.list_all(conn), "stats": tracker.stats(conn)}


@app.post("/api/applications")
def add_application(payload: dict = Body(...)):
    if not (payload.get("company") or "").strip():
        raise HTTPException(400, "Company is required")
    with db.session() as conn:
        job = pipeline.get_job(conn, payload["job_id"]) if payload.get("job_id") else None
        if job:
            existing = tracker.find(conn, job_id=job["id"])
            if existing:
                return tracker.set_status(conn, existing["id"], payload.get("status") or existing["status"])
            return tracker.create_for_job(conn, job, payload.get("status") or "saved", "manual")
        return tracker.create(conn, company=payload["company"], title=payload.get("title") or "", url=payload.get("url"),
                              status=payload.get("status") or "applied", source="manual", notes=payload.get("notes") or "")


@app.post("/api/applications/applied")
def applied(payload: dict = Body(...)):
    """The extension calls this when it detects a submitted application."""
    found = lookup(payload["url"])["job"] if payload.get("url") and not payload.get("job_id") else None
    with db.session() as conn:
        job = pipeline.get_job(conn, payload["job_id"]) if payload.get("job_id") else found
        app_row = tracker.mark_applied(conn, job=job, url=payload.get("url"), company=payload.get("company"),
                                       title=payload.get("title"), source=payload.get("source") or "extension",
                                       detail={k: payload.get(k) for k in ("ats", "page_title", "trigger") if payload.get(k)})
        return {"application": tracker.get(conn, app_row["id"])}


@app.get("/api/applications/{app_id}")
def application(app_id: int):
    with db.session() as conn:
        a = tracker.get(conn, app_id)
    if not a:
        raise HTTPException(404, "Application not found")
    return a


@app.patch("/api/applications/{app_id}")
def patch_application(app_id: int, payload: dict = Body(...)):
    with db.session() as conn:
        try:
            tracker.update(conn, app_id, payload)
        except KeyError:
            raise HTTPException(404, "Application not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return tracker.get(conn, app_id)


@app.delete("/api/applications/{app_id}")
def delete_application(app_id: int):
    with db.session() as conn:
        tracker.delete(conn, app_id)
    return {"ok": True}


@app.get("/api/stats")
def stats():
    with db.session() as conn:
        s = tracker.stats(conn)
        s["pending_emails"] = conn.execute("SELECT count(*) FROM email_suggestions WHERE state='pending'").fetchone()[0]
    feed = list_jobs(limit=0)
    s["matches"] = feed["counts"]["matches"]
    s["new_matches"] = feed["counts"]["new"]
    return s


# ------------------------------------------------------------------ email

@app.post("/api/email/analyze")
def email_analyze(payload: dict = Body(...)):
    with db.session() as conn:
        return inbox.analyze(conn, payload.get("from") or "", payload.get("subject") or "", payload.get("body") or "")


@app.post("/api/email/apply")
def email_apply(payload: dict = Body(...)):
    if not payload.get("application_id") or not payload.get("status"):
        raise HTTPException(400, "application_id and status are required")
    with db.session() as conn:
        try:
            inbox.apply_update(conn, int(payload["application_id"]), payload["status"], payload.get("from") or "",
                               payload.get("subject") or "", payload.get("body") or "")
        except KeyError:
            raise HTTPException(404, "Application not found")
        return tracker.get(conn, int(payload["application_id"]))


@app.get("/api/email/suggestions")
def email_suggestions(state: str = "pending"):
    with db.session() as conn:
        return {"items": inbox.list_suggestions(conn, state)}


@app.post("/api/email/suggestions/{sid}/accept")
def accept_suggestion(sid: int, payload: dict = Body(default={})):
    with db.session() as conn:
        try:
            return inbox.accept(conn, sid, payload.get("status"), payload.get("application_id"))
        except KeyError:
            raise HTTPException(404, "Suggestion not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))


@app.post("/api/email/suggestions/{sid}/dismiss")
def dismiss_suggestion(sid: int):
    with db.session() as conn:
        inbox.dismiss(conn, sid)
    return {"ok": True}


@app.post("/api/email/imap-sync")
def imap_sync_now():
    try:
        return inbox.imap_sync()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"IMAP sync failed: {exc}")


# ------------------------------------------------------------------ AI helpers

@app.post("/api/ai/answer")
def ai_answer(payload: dict = Body(...)):
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    with db.session() as conn:
        settings = db.get_settings(conn)
        p = profile_mod.get(conn)
        job = pipeline.get_job(conn, payload["job_id"]) if payload.get("job_id") else None
        analysis = (pipeline.get_details(conn, job["id"]).get("analysis") if job else None)
    job = job or {"company": payload.get("company") or "", "title": payload.get("title") or ""}
    try:
        answer = ai.draft_answer(settings, question, job, analysis, pipeline.candidate_brief(p), int(payload.get("max_words") or 150))
    except ai.AIUnavailable as exc:
        raise HTTPException(400, str(exc))
    except ai.AIError as exc:
        raise HTTPException(502, str(exc))
    return {"answer": answer}


# ------------------------------------------------------------------ export

@app.get("/api/export")
def export():
    with db.session() as conn:
        p = profile_mod.get(conn)
        apps = [tracker.get(conn, a["id"]) for a in tracker.list_all(conn)]
    return JSONResponse({"exported_at": db.now(), "profile": p, "applications": apps},
                        headers={"Content-Disposition": 'attachment; filename="internpromax-export.json"'})


@app.get("/api/export/applications.csv")
def export_csv():
    with db.session() as conn:
        apps = tracker.list_all(conn)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "title", "status", "applied_at", "url", "location", "source", "notes"])
    for a in apps:
        applied_at = time.strftime("%Y-%m-%d", time.localtime(a["applied_at"])) if a["applied_at"] else ""
        w.writerow([a["company"], a["title"], a["status"], applied_at, a["url"] or "", a["location"] or "", a["source"] or "", a["notes"]])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="applications.csv"'})


# ------------------------------------------------------------------ static dashboard

app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="dashboard")
