import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPM_NO_BACKGROUND", "1")

from internpromax import db  # noqa: E402
from internpromax import profile as profile_mod  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr("internpromax.config.DATA_DIR", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db.set_db_path(tmp_path / "test.db")
    yield tmp_path


@pytest.fixture
def profile_data():
    return db.deep_merge(profile_mod.DEFAULT_PROFILE, json.loads((FIXTURES / "profile.json").read_text()))


@pytest.fixture
def posting_text():
    return (FIXTURES / "posting_backend.txt").read_text()


def listing(**kw):
    base = {
        "source": "Simplify", "category": "Software", "company_name": "Acme", "id": "job-1",
        "title": "Software Engineer Intern", "active": True, "terms": ["Summer 2027"], "date_updated": 1790000000,
        "date_posted": 1790000000, "url": "https://job-boards.greenhouse.io/acme/jobs/123456", "locations": ["San Francisco, CA"],
        "company_url": "", "is_visible": True, "sponsorship": "Other", "degrees": ["Bachelor's"],
    }
    base.update(kw)
    return base
