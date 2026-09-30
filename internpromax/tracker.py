"""Applications, the status machine and the event timeline."""

from __future__ import annotations

import json
import re
import sqlite3

from . import ats, db

STATUSES = ["saved", "applied", "oa", "interviewing", "offer", "rejected", "withdrawn", "ghosted"]
STATUS_LABELS = {
    "saved": "Saved", "applied": "Applied", "oa": "Online assessment", "interviewing": "Interviewing",
    "offer": "Offer", "rejected": "Rejected", "withdrawn": "Withdrawn", "ghosted": "Ghosted",
}
RANK = {"saved": 0, "applied": 1, "oa": 2, "interviewing": 3, "offer": 4}
TERMINAL = {"rejected", "withdrawn", "ghosted"}
STALE_DAYS = 30


def is_advance(current: str, new: str) -> bool:
    """Would an automatic update (email/extension) move this application forward?"""
    if current == new:
        return False
    if current in ("rejected", "withdrawn"):
        return False
    if current == "ghosted":
        return new in ("oa", "interviewing", "offer", "rejected")
    if new in TERMINAL:
        return current != "offer"
    return RANK.get(new, -1) > RANK.get(current, -1)


def _app(conn: sqlite3.Connection, app_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    return dict(row) if row else None


def add_event(conn, app_id: int, type_: str, from_status=None, to_status=None, detail=None) -> None:
    conn.execute(
        "INSERT INTO events(application_id, ts, type, from_status, to_status, detail) VALUES(?,?,?,?,?,?)",
        (app_id, db.now(), type_, from_status, to_status, json.dumps(detail) if detail is not None else None),
    )


def find(conn, job_id: str | None = None, url: str | None = None, company: str | None = None,
         title: str | None = None) -> dict | None:
    if job_id:
        row = conn.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
        if row:
            return dict(row)
    if url:
        key = ats.url_key(url)
        akey = ats.parse(url).get("key")
        for row in conn.execute("SELECT * FROM applications WHERE url IS NOT NULL"):
            if (key and ats.url_key(row["url"]) == key) or (akey and ats.parse(row["url"]).get("key") == akey):
                return dict(row)
    if company and title:
        row = conn.execute(
            "SELECT * FROM applications WHERE lower(company)=lower(?) AND lower(title)=lower(?) ORDER BY id DESC",
            (company.strip(), title.strip()),
        ).fetchone()
        if row:
            return dict(row)
    return None


def create(conn, *, company: str, title: str = "", url: str | None = None, job_id: str | None = None,
           status: str = "saved", source: str = "manual", location: str | None = None, notes: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    ts = db.now()
    cur = conn.execute(
        "INSERT INTO applications(job_id, company, title, url, location, status, applied_at, created_at, updated_at, source, ats, notes)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, company.strip() or "Unknown company", (title or "").strip(), url, location, status,
         ts if status not in ("saved",) else None, ts, ts, source, ats.parse(url).get("ats") if url else None, notes or ""),
    )
    app_id = cur.lastrowid
    add_event(conn, app_id, "created", None, status, {"source": source})
    return _app(conn, app_id)


def create_for_job(conn, job: dict, status: str, source: str) -> dict:
    return create(conn, company=job["company"], title=job["title"], url=job.get("url"), job_id=job["id"],
                  status=status, source=source, location=", ".join(job.get("locations") or [])[:200])


def set_status(conn, app_id: int, status: str, source: str = "manual", detail: dict | None = None,
               only_forward: bool = False) -> dict:
    app = _app(conn, app_id)
    if not app:
        raise KeyError(app_id)
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    if app["status"] == status or (only_forward and not is_advance(app["status"], status)):
        return app
    ts = db.now()
    applied_at = app["applied_at"]
    if status != "saved" and not applied_at:
        applied_at = ts
    conn.execute("UPDATE applications SET status=?, applied_at=?, updated_at=? WHERE id=?", (status, applied_at, ts, app_id))
    add_event(conn, app_id, "status", app["status"], status, {"source": source, **(detail or {})})
    return _app(conn, app_id)


def update(conn, app_id: int, fields: dict) -> dict:
    app = _app(conn, app_id)
    if not app:
        raise KeyError(app_id)
    allowed = {k: v for k, v in fields.items() if k in ("company", "title", "url", "notes", "location") and v is not None}
    if allowed:
        sets = ", ".join(f"{k}=?" for k in allowed)
        conn.execute(f"UPDATE applications SET {sets}, updated_at=? WHERE id=?", (*allowed.values(), db.now(), app_id))
        if "notes" in allowed and allowed["notes"] != app["notes"]:
            add_event(conn, app_id, "note", detail={"notes": allowed["notes"][:500]})
    if fields.get("status"):
        set_status(conn, app_id, fields["status"], source="manual")
    return _app(conn, app_id)


def mark_applied(conn, *, job: dict | None = None, url: str | None = None, company: str | None = None,
                 title: str | None = None, source: str = "extension", detail: dict | None = None) -> dict:
    """Called when a submission is detected. Creates the application if needed; never moves it backwards."""
    app = find(conn, job_id=job["id"] if job else None, url=url, company=company, title=title)
    if app is None:
        if job:
            app = create_for_job(conn, job, "applied", source)
        else:
            app = create(conn, company=company or _company_from_url(url), title=title or "", url=url,
                         status="applied", source=source)
        add_event(conn, app["id"], "submitted", None, "applied", {"source": source, **(detail or {})})
        return app
    if app["status"] == "saved":
        app = set_status(conn, app["id"], "applied", source=source, detail=detail)
    add_event(conn, app["id"], "submitted", None, None, {"source": source, **(detail or {})})
    return app


def _company_from_url(url: str | None) -> str:
    info = ats.parse(url)
    for k in ("board", "company", "org", "tenant"):
        if info.get(k):
            return re.sub(r"[-_]+", " ", info[k]).title()
    host = (ats.url_key(url) or "unknown").split("/")[0]
    parts = host.split(".")
    return (parts[-2] if len(parts) >= 2 else parts[0]).title()


def list_all(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT a.*, (SELECT max(ts) FROM events e WHERE e.application_id=a.id) AS last_event
           FROM applications a ORDER BY a.updated_at DESC"""
    ).fetchall()
    now = db.now()
    out = []
    for r in rows:
        d = dict(r)
        d["stale"] = bool(d["status"] == "applied" and d["applied_at"] and now - (d["last_event"] or d["applied_at"]) > STALE_DAYS * 86400)
        out.append(d)
    return out


def get(conn, app_id: int) -> dict | None:
    app = _app(conn, app_id)
    if not app:
        return None
    app["events"] = [db.row_to_dict(r, ("detail",)) for r in
                     conn.execute("SELECT * FROM events WHERE application_id=? ORDER BY ts DESC, id DESC", (app_id,))]
    return app


def delete(conn, app_id: int) -> None:
    conn.execute("DELETE FROM applications WHERE id=?", (app_id,))


def stats(conn) -> dict:
    counts = {s: 0 for s in STATUSES}
    for r in conn.execute("SELECT status, count(*) AS n FROM applications GROUP BY status"):
        counts[r["status"]] = r["n"]
    submitted = sum(v for k, v in counts.items() if k != "saved")
    responded = counts["oa"] + counts["interviewing"] + counts["offer"] + counts["rejected"]
    weeks = []
    now = db.now()
    for i in range(7, -1, -1):
        start, end = now - (i + 1) * 7 * 86400, now - i * 7 * 86400
        n = conn.execute("SELECT count(*) FROM applications WHERE applied_at>? AND applied_at<=?", (start, end)).fetchone()[0]
        weeks.append({"start": start, "count": n})
    return {
        "counts": counts,
        "submitted": submitted,
        "response_rate": round(responded / submitted, 3) if submitted else 0.0,
        "interview_rate": round((counts["interviewing"] + counts["offer"]) / submitted, 3) if submitted else 0.0,
        "weekly": weeks,
    }
