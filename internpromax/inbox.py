"""Email → application status suggestions (paste flow + IMAP polling)."""

from __future__ import annotations

import email
import hashlib
import imaplib
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from email import policy
from email.utils import parsedate_to_datetime

from . import ai, db, emails, postings, tracker

log = logging.getLogger(__name__)


def analyze(conn, sender: str, subject: str, body: str, use_ai: bool = True) -> dict:
    apps = tracker.list_all(conn)
    cls = emails.classify(subject, body)
    app, match_score, why = emails.match_application(sender, subject, body, apps)
    method = "rules"
    settings = db.get_settings(conn)
    if use_ai and (cls["status"] is None or cls["confidence"] < 0.7 or app is None) and cls["job_related"] and ai.available(settings):
        try:
            out = ai.classify_email(settings, sender, subject, body, [a["company"] for a in apps])
            if out["status"] != "none":
                cls = {"status": out["status"], "confidence": float(out["confidence"]), "reasons": [out["reason"]], "job_related": True}
                method = "ai"
            if app is None and out.get("company"):
                app = next((a for a in apps if emails.norm_company(a["company"]) == emails.norm_company(out["company"])), None)
                if app:
                    match_score, why = 0.75, "AI matched the company"
        except (ai.AIUnavailable, ai.AIError) as exc:
            log.info("AI email classification skipped: %s", exc)
    advance = bool(app and cls["status"] and tracker.is_advance(app["status"], cls["status"]))
    return {
        "status": cls["status"],
        "confidence": round(cls["confidence"] * (match_score if app else 0.6), 2),
        "status_confidence": cls["confidence"],
        "reasons": cls["reasons"],
        "job_related": cls["job_related"],
        "application": app,
        "match_score": match_score,
        "match_reason": why,
        "would_advance": advance,
        "method": method,
    }


def apply_update(conn, app_id: int, status: str, sender: str = "", subject: str = "", snippet: str = "",
                 only_forward: bool = False) -> dict:
    app = tracker.set_status(conn, app_id, status, source="email", only_forward=only_forward,
                             detail={"from": sender, "subject": subject, "snippet": snippet[:300]})
    tracker.add_event(conn, app_id, "email", None, None, {"from": sender, "subject": subject, "snippet": snippet[:300]})
    return app


def create_suggestion(conn, key: str, sender: str, subject: str, body: str, received_at: int | None, result: dict) -> int | None:
    snippet = re.sub(r"\s+", " ", body).strip()[:400]
    try:
        cur = conn.execute(
            """INSERT INTO email_suggestions(message_key, sender, subject, snippet, received_at, application_id,
               suggested_status, confidence, reasons, state, created_at) VALUES(?,?,?,?,?,?,?,?,?, 'pending', ?)""",
            (key, sender, subject, snippet, received_at, (result.get("application") or {}).get("id"),
             result["status"], result["confidence"], json.dumps(result["reasons"]), db.now()),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:  # duplicate message_key: already processed
        return None


def list_suggestions(conn, state: str = "pending") -> list[dict]:
    rows = conn.execute(
        """SELECT s.*, a.company AS app_company, a.title AS app_title, a.status AS app_status
           FROM email_suggestions s LEFT JOIN applications a ON a.id = s.application_id
           WHERE s.state=? ORDER BY coalesce(s.received_at, s.created_at) DESC""", (state,)).fetchall()
    return [db.row_to_dict(r, ("reasons",)) for r in rows]


def accept(conn, sid: int, status: str | None = None, app_id: int | None = None) -> dict:
    row = conn.execute("SELECT * FROM email_suggestions WHERE id=?", (sid,)).fetchone()
    if not row:
        raise KeyError(sid)
    target = app_id or row["application_id"]
    if not target:
        raise ValueError("Pick which application this email is about")
    app = apply_update(conn, target, status or row["suggested_status"], row["sender"] or "", row["subject"] or "", row["snippet"] or "")
    conn.execute("UPDATE email_suggestions SET state='accepted', application_id=? WHERE id=?", (target, sid))
    return app


def dismiss(conn, sid: int) -> None:
    conn.execute("UPDATE email_suggestions SET state='dismissed' WHERE id=?", (sid,))


def ingest_message(conn, key: str, sender: str, subject: str, body: str, received_at: int | None, settings: dict) -> str:
    """Classify one message and record a suggestion (or auto-apply). Returns what happened."""
    if conn.execute("SELECT 1 FROM email_suggestions WHERE message_key=?", (key,)).fetchone():
        return "seen"
    result = analyze(conn, sender, subject, body)
    if not result["status"] or not result["job_related"]:
        return "ignored"
    sid = create_suggestion(conn, key, sender, subject, body, received_at, result)
    app = result.get("application")
    if (sid and app and settings.get("email_auto_apply") and result["would_advance"]
            and result["confidence"] >= float(settings.get("email_auto_apply_min_confidence", 0.85))):
        accept(conn, sid)
        return "applied"
    return "suggested"


# ------------------------------------------------------------------ IMAP

def _body_text(msg: email.message.EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", "replace")
    return postings.html_to_text(content) if part.get_content_type() == "text/html" else content


def imap_sync(max_messages: int = 300) -> dict:
    with db.session() as conn:
        settings = db.get_settings(conn)
    cfg = settings.get("imap") or {}
    if not (cfg.get("host") and cfg.get("username") and cfg.get("password")):
        raise ValueError("Fill in IMAP host, username and app password in Settings first")
    since = (datetime.now(timezone.utc) - timedelta(days=int(cfg.get("lookback_days") or 14))).strftime("%d-%b-%Y")
    counts = {"checked": 0, "suggested": 0, "applied": 0, "ignored": 0, "seen": 0}
    box = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port") or 993))
    try:
        box.login(cfg["username"], cfg["password"])
        box.select(cfg.get("folder") or "INBOX", readonly=True)
        typ, data = box.search(None, "SINCE", since)
        ids = (data[0] or b"").split()[-max_messages:]
        for num in reversed(ids):
            typ, msg_data = box.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
            sender, subject = str(msg.get("From", "")), str(msg.get("Subject", ""))
            try:
                received = int(parsedate_to_datetime(msg.get("Date")).timestamp())
            except (TypeError, ValueError):
                received = None
            key = str(msg.get("Message-ID") or hashlib.sha1(f"{sender}{subject}{received}".encode()).hexdigest())
            body = _body_text(msg)
            counts["checked"] += 1
            with db.session() as conn:
                outcome = ingest_message(conn, key, sender, subject, body, received, settings)
            counts[outcome] = counts.get(outcome, 0) + 1
    finally:
        try:
            box.logout()
        except Exception:
            pass
    with db.session() as conn:
        db.kv_set(conn, "imap_last", {"at": db.now(), **counts})
    return counts
