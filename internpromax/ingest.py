"""Pull SimplifyJobs-format listings.json files and upsert them into SQLite."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from typing import Any, Iterable

import httpx

from . import ats, config, db

log = logging.getLogger(__name__)

CATEGORY_MAP = {
    "software": "Software Engineering",
    "software engineering": "Software Engineering",
    "ai/ml/data": "Data Science, AI & ML",
    "data science, ai & machine learning": "Data Science, AI & ML",
    "hardware": "Hardware Engineering",
    "hardware engineering": "Hardware Engineering",
    "product": "Product Management",
    "product management": "Product Management",
    "quant": "Quantitative Finance",
    "quantitative finance": "Quantitative Finance",
}

CATEGORIES = [
    "Software Engineering",
    "Data Science, AI & ML",
    "Hardware Engineering",
    "Quantitative Finance",
    "Product Management",
    "Other",
]


def normalize_category(raw: str | None) -> str:
    if not raw:
        return "Other"
    return CATEGORY_MAP.get(raw.strip().lower(), raw.strip())


def normalize(item: dict, source_url: str) -> dict | None:
    job_id = item.get("id")
    company = (item.get("company_name") or "").strip()
    title = (item.get("title") or "").strip()
    if not job_id or not company or not title:
        return None
    url = (item.get("url") or "").strip() or None
    parsed = ats.parse(url)
    terms = [t for t in (item.get("terms") or []) if t]
    return {
        "id": str(job_id),
        "source": source_url,
        "list_source": item.get("source"),
        "company": company,
        "title": title,
        "category": normalize_category(item.get("category")),
        "terms": json.dumps(terms),
        "locations": json.dumps([loc for loc in (item.get("locations") or []) if loc]),
        "url": url,
        "url_key": ats.url_key(url),
        "ats": parsed.get("ats"),
        "ats_key": parsed.get("key"),
        "company_url": item.get("company_url"),
        "sponsorship": item.get("sponsorship") or "Other",
        "degrees": json.dumps(item.get("degrees") or []),
        "active": 1 if item.get("active", True) else 0,
        "visible": 1 if item.get("is_visible", True) else 0,
        "date_posted": int(item.get("date_posted") or 0) or None,
        "date_updated": int(item.get("date_updated") or 0) or None,
    }


UPSERT = """
INSERT INTO jobs (id, source, list_source, company, title, category, terms, locations, url, url_key,
                  ats, ats_key, company_url, sponsorship, degrees, active, visible, date_posted,
                  date_updated, first_seen, last_seen)
VALUES (:id, :source, :list_source, :company, :title, :category, :terms, :locations, :url, :url_key,
        :ats, :ats_key, :company_url, :sponsorship, :degrees, :active, :visible, :date_posted,
        :date_updated, :now, :now)
ON CONFLICT(id) DO UPDATE SET
    source=excluded.source, list_source=excluded.list_source, company=excluded.company,
    title=excluded.title, category=excluded.category, terms=excluded.terms,
    locations=excluded.locations, url=excluded.url, url_key=excluded.url_key, ats=excluded.ats,
    ats_key=excluded.ats_key, company_url=excluded.company_url, sponsorship=excluded.sponsorship,
    degrees=excluded.degrees, active=excluded.active, visible=excluded.visible,
    date_posted=excluded.date_posted, date_updated=excluded.date_updated, last_seen=excluded.last_seen
"""


def upsert_listings(conn: sqlite3.Connection, items: Iterable[dict], source_url: str) -> dict:
    ts = db.now()
    existing = {r["id"] for r in conn.execute("SELECT id FROM jobs WHERE source=?", (source_url,))}
    seen: set[str] = set()
    added = 0
    rows = []
    for item in items:
        row = normalize(item, source_url)
        if row is None or row["id"] in seen:
            continue
        seen.add(row["id"])
        if row["id"] not in existing:
            added += 1
        row["now"] = ts
        rows.append(row)
    conn.executemany(UPSERT, rows)
    removed = existing - seen
    if removed:
        conn.executemany("UPDATE jobs SET visible=0 WHERE id=?", [(r,) for r in removed])
    return {"total": len(rows), "added": added, "removed": len(removed)}


def fetch_source(url: str, etag: str | None = None, client: httpx.Client | None = None) -> tuple[Any, str | None, bool]:
    """Returns (items or None, etag, changed)."""
    headers = {"User-Agent": config.USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    own = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        resp = client.get(url, headers=headers)
        if resp.status_code == 304:
            return None, etag, False
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise ValueError("listings file is not a JSON array")
        return items, resp.headers.get("etag"), True
    finally:
        if own:
            client.close()


def sync_all(force: bool = False, client: httpx.Client | None = None) -> dict:
    """Sync every enabled source. Safe to call from a background thread."""
    results = []
    with db.session() as conn:
        settings = db.get_settings(conn)
        meta = db.kv_get(conn, "source_meta", {})
    for src in settings.get("sources", []):
        if not src.get("enabled"):
            continue
        url = src["url"]
        m = meta.get(url, {})
        entry = {"name": src.get("name") or url, "url": url}
        try:
            items, etag, changed = fetch_source(url, None if force else m.get("etag"), client)
            if changed:
                with db.session() as conn:
                    stats = upsert_listings(conn, items, url)
                entry.update(stats, changed=True)
            else:
                entry.update(changed=False, total=m.get("total", 0), added=0, removed=0)
            m = {"etag": etag, "synced_at": db.now(), "total": entry.get("total", 0), "error": None}
        except Exception as exc:  # network, JSON, HTTP errors are all reported, not raised
            log.warning("sync failed for %s: %s", url, exc)
            entry.update(error=str(exc))
            m = {**m, "error": str(exc), "attempted_at": db.now()}
        meta[url] = m
        results.append(entry)
    with db.session() as conn:
        db.kv_set(conn, "source_meta", meta)
        db.kv_set(conn, "last_sync", {"at": db.now(), "results": results})
    return {"at": db.now(), "results": results}


EXTERNAL_SOURCE = "extension"

_CATEGORY_HINTS = [
    ("Data Science, AI & ML", r"data scien|machine learning|\bml\b|\bai\b|analytics|data analyst|data engineer"),
    ("Quantitative Finance", r"\bquant|trading|trader"),
    ("Product Management", r"product manag|\bapm\b|program manag"),
    ("Software Engineering", r"software|developer|full.?stack|back.?end|front.?end|\bweb\b|mobile|devops|\bsre\b"),
    ("Hardware Engineering", r"hardware|electrical|mechanical|aerospace|propulsion|avionics|embedded|firmware|robot|test|manufactur|thermal|structur|systems engineer|design engineer|controls"),
]


def guess_category(title: str) -> str:
    low = (title or "").lower()
    for cat, pat in _CATEGORY_HINTS:
        if re.search(pat, low):
            return cat
    return "Other"


def add_external(conn: sqlite3.Connection, *, url: str, company: str, title: str, location: str = "") -> dict:
    """Create a job for a posting you found anywhere (not on a synced list)."""
    parsed = ats.parse(url)
    key = parsed.get("key") or ats.url_key(url) or url
    job_id = "ext-" + hashlib.sha1(key.encode()).hexdigest()[:12]
    ts = db.now()
    row = {
        "id": job_id, "source": EXTERNAL_SOURCE, "list_source": EXTERNAL_SOURCE,
        "company": (company or "").strip()[:120] or "Unknown company", "title": (title or "").strip()[:200] or "Application",
        "category": guess_category(title), "terms": "[]", "locations": json.dumps([location] if location else []),
        "url": url, "url_key": ats.url_key(url), "ats": parsed.get("ats"), "ats_key": parsed.get("key"), "company_url": None,
        "sponsorship": "Other", "degrees": "[]", "active": 1, "visible": 1, "date_posted": ts, "date_updated": ts, "now": ts,
    }
    conn.execute(UPSERT.replace("company=excluded.company,", "").replace("title=excluded.title,", ""), row)
    return dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def import_file(path: str, source_url: str = "local-file") -> dict:
    with open(path, encoding="utf-8") as fh:
        items = json.load(fh)
    with db.session() as conn:
        return upsert_listings(conn, items, source_url)
