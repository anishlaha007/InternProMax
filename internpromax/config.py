"""Paths, network settings and defaults."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("IPM_DATA_DIR", ROOT / "data")).resolve()
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = os.environ.get("IPM_HOST", "127.0.0.1")
PORT = int(os.environ.get("IPM_PORT", "8420"))

USER_AGENT = "InternProMax/0.1 (+local job tracker)"

SIMPLIFY_RAW = "https://raw.githubusercontent.com/SimplifyJobs/{repo}/dev/.github/scripts/listings.json"

DEFAULT_SOURCES = [
    {
        "name": "SimplifyJobs · Summer 2027 Internships (+ off-season / co-ops)",
        "url": SIMPLIFY_RAW.format(repo="Summer2027-Internships"),
        "enabled": True,
    },
    {
        "name": "SimplifyJobs · New Grad Positions",
        "url": SIMPLIFY_RAW.format(repo="New-Grad-Positions"),
        "enabled": False,
    },
]

DEFAULT_SETTINGS = {
    "sources": DEFAULT_SOURCES,
    "sync_interval_hours": 6,
    "auto_analyze_on_apply": True,
    "auto_tailor_on_apply": True,
    "use_tailored_resume": True,
    "autofill_on_load": True,
    "ai_model": "claude-opus-5-5",
    "ai_effort": "medium",
    "anthropic_api_key": "",
    "imap": {
        "enabled": False,
        "host": "imap.gmail.com",
        "port": 993,
        "username": "",
        "password": "",
        "folder": "INBOX",
        "lookback_days": 14,
        "interval_minutes": 30,
    },
    "email_auto_apply": False,
    "email_auto_apply_min_confidence": 0.85,
}


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "files").mkdir(exist_ok=True)
    return DATA_DIR
