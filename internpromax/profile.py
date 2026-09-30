"""The user's profile: autofill data, preferences, master resume and answer bank."""

from __future__ import annotations

import sqlite3
import uuid

from . import db, skills

DEFAULT_PROFILE: dict = {
    "personal": {
        "first_name": "",
        "last_name": "",
        "preferred_name": "",
        "pronouns": "",
        "email": "",
        "phone": "",
        "linkedin": "",
        "github": "",
        "website": "",
        "address": "",
        "city": "",
        "state": "",
        "zip": "",
        "country": "United States",
    },
    "education": [
        {
            "school": "",
            "degree": "Bachelor of Science",
            "degree_level": "Bachelor's",
            "major": "",
            "minor": "",
            "gpa": "",
            "start_month": "",
            "start_year": "",
            "grad_month": "",
            "grad_year": "",
            "location": "",
            "coursework": [],
            "highlights": [],
        }
    ],
    "work_auth": {
        "authorized_us": True,
        "needs_sponsorship": False,
        "us_citizen": False,
        "over_18": True,
        "willing_to_relocate": True,
    },
    "eeo": {
        "gender": "Decline to self-identify",
        "race": "Decline to self-identify",
        "hispanic": "Decline to self-identify",
        "veteran": "I don't wish to answer",
        "disability": "I don't wish to answer",
        "lgbtq": "Decline to self-identify",
    },
    "application": {
        "how_heard": "Online job board",
        "earliest_start": "",
        "salary_expectation": "",
        "previously_employed": False,
        "current_company": "",
        "current_title": "",
    },
    "preferences": {
        "terms": ["Summer 2027", "Winter 2027", "Spring 2027", "Fall 2027"],
        "categories": ["Software Engineering"],
        "interests": ["Software Engineering"],
        "locations": [],
        "remote_ok": True,
        "strict_location": False,
        "include_keywords": [],
        "exclude_keywords": [],
        "dream_companies": [],
        "excluded_companies": [],
        "ignore_degree_filter": False,
        "hide_closed": True,
    },
    "resume": {
        "summary": "",
        "experience": [],
        "projects": [],
        "activities": [],
        "skills": [],
        "awards": [],
    },
    "answers": [
        {"question": "Why are you interested in this role?", "answer": ""},
        {"question": "How did you hear about this position?", "answer": "Online job board"},
    ],
}


def get(conn: sqlite3.Connection) -> dict:
    return db.deep_merge(DEFAULT_PROFILE, db.kv_get(conn, "profile", {}))


def save(conn: sqlite3.Connection, profile: dict) -> dict:
    merged = db.deep_merge(DEFAULT_PROFILE, profile)
    ensure_ids(merged)
    db.kv_set(conn, "profile", merged)
    return merged


def ensure_ids(profile: dict) -> None:
    """Give every resume entry a stable id so tailored versions can reference it."""
    res = profile.setdefault("resume", {})
    for kind in ("experience", "projects", "activities"):
        seen: set[str] = set()
        for entry in res.get(kind) or []:
            if not entry.get("id") or entry["id"] in seen:
                entry["id"] = f"{kind[:3]}-{uuid.uuid4().hex[:8]}"
            seen.add(entry["id"])


def primary_education(profile: dict) -> dict:
    edu = profile.get("education") or []
    return edu[0] if edu else {}


def all_skills(profile: dict) -> list[str]:
    """Every skill the user can legitimately claim: listed skills + those evidenced in resume text."""
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        c = skills.canonical(s)
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)

    res = profile.get("resume") or {}
    for group in res.get("skills") or []:
        for item in group.get("items") or []:
            add(item)
    for s in skills.extract(resume_text(profile)):
        add(s)
    return out


def resume_text(profile: dict) -> str:
    """Flatten the master resume into text (used for evidence checks and AI prompts)."""
    res = profile.get("resume") or {}
    parts: list[str] = [res.get("summary") or ""]
    for e in (res.get("experience") or []) + (res.get("activities") or []):
        parts += [e.get("title", ""), e.get("company", "")] + list(e.get("bullets") or []) + list(e.get("skills") or [])
    for p in res.get("projects") or []:
        parts += [p.get("name", ""), p.get("role", "")] + list(p.get("tech") or []) + list(p.get("bullets") or [])
    for g in res.get("skills") or []:
        parts += list(g.get("items") or [])
    for a in res.get("awards") or []:
        parts += [a.get("title", ""), a.get("detail", "")]
    for ed in profile.get("education") or []:
        parts += [ed.get("major", ""), ed.get("minor", "")] + list(ed.get("coursework") or []) + list(ed.get("highlights") or [])
    return "\n".join(p for p in parts if p)


def completeness(profile: dict) -> dict:
    """What's missing for good autofill + tailoring."""
    p = profile["personal"]
    edu = primary_education(profile)
    res = profile["resume"]
    checks = {
        "name": bool(p.get("first_name") and p.get("last_name")),
        "email": bool(p.get("email")),
        "phone": bool(p.get("phone")),
        "school": bool(edu.get("school")),
        "graduation": bool(edu.get("grad_year")),
        "resume_entries": bool(res.get("experience") or res.get("projects")),
        "skills": bool(res.get("skills")),
        "preferences": bool(profile["preferences"].get("terms")),
    }
    return {"checks": checks, "score": round(100 * sum(checks.values()) / len(checks))}
