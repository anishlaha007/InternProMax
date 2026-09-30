"""Seed a fresh InternProMax database for the browser end-to-end test."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from internpromax import db, ingest, profile  # noqa: E402


def main(site: str) -> None:
    now = int(time.time())
    base = {"source": "Simplify", "active": True, "is_visible": True, "terms": ["Summer 2027"], "sponsorship": "Other",
            "degrees": ["Bachelor's"], "date_posted": now - 3600, "date_updated": now - 3600, "company_url": ""}
    listings = [
        {**base, "id": "e2e-greenhouse", "company_name": "Acme Robotics", "title": "Software Engineer Intern",
         "category": "Software", "locations": ["San Francisco, CA"], "url": f"{site}/greenhouse.html"},
        {**base, "id": "e2e-lever", "company_name": "Globex", "title": "Data Engineering Intern",
         "category": "AI/ML/Data", "locations": ["NYC"], "url": f"{site}/lever.html"},
        {**base, "id": "e2e-workday", "company_name": "Initech", "title": "Software Development Co-op",
         "category": "Software", "locations": ["Remote in USA"], "url": f"{site}/workday.html"},
    ]
    prof = json.loads((ROOT / "tests" / "fixtures" / "profile.json").read_text())
    with db.session() as conn:
        ingest.upsert_listings(conn, listings, "e2e")
        profile.save(conn, prof)
        db.save_settings(conn, {"sources": [], "auto_analyze_on_apply": True, "auto_tailor_on_apply": True,
                                "use_tailored_resume": True, "autofill_on_load": True})
    print("seeded", len(listings), "jobs")


if __name__ == "__main__":
    main(sys.argv[1])
