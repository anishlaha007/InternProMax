"""Unit tests: URL parsing, skills, ingestion, matching, posting text extraction."""

import json
import time

import httpx

from internpromax import ats, db, ingest, matching, postings, skills

from .conftest import listing


# ------------------------------------------------------------------ ats

def test_parse_known_ats_urls():
    gh = ats.parse("https://job-boards.greenhouse.io/aquaticcapitalmanagement/jobs/8489186002")
    assert gh["ats"] == "greenhouse" and gh["board"] == "aquaticcapitalmanagement" and gh["key"] == "gh:8489186002"
    assert ats.parse("https://careers.example.com/jobs?gh_jid=42")["key"] == "gh:42"
    lever = ats.parse("https://jobs.lever.co/palantir/d5486403-c050-4920-b2e0-91b69b61ebb2/apply")
    assert lever["company"] == "palantir" and lever["key"] == "lever:d5486403-c050-4920-b2e0-91b69b61ebb2"
    ashby = ats.parse("https://jobs.ashbyhq.com/mercor/de3025e5-10ca-4d55-b688-eff0e647ac8d/application")
    assert ashby["org"] == "mercor" and ashby["key"].startswith("ashby:")
    wd = ats.parse("https://geaerospace.wd5.myworkdayjobs.com/en-US/ge_externalsite/job/Evendale/Engines-Co-op_R5029619-1")
    assert wd["tenant"] == "geaerospace" and wd["site"] == "ge_externalsite" and wd["key"] == "wd:geaerospace:r5029619"
    assert ats.parse("https://jobs.smartrecruiters.com/Visa/744000077777777-intern")["key"] == "sr:744000077777777"


def test_url_key_ignores_query_and_apply_suffix():
    a = ats.url_key("https://www.jobs.lever.co/acme/abc/apply?lever-source=x")
    assert a == ats.url_key("https://jobs.lever.co/acme/abc/") == "jobs.lever.co/acme/abc"


# ------------------------------------------------------------------ skills

def test_skill_extraction_handles_tricky_names():
    text = "Proficiency in Python, Go, and C/C++. Familiar with Node.js, REST APIs and R. You will excel in a team. Spark and Excel."
    found = skills.extract(text)
    for s in ["Python", "Go", "C", "C++", "Node.js", "REST APIs", "R", "Spark", "Excel"]:
        assert s in found, s
    assert "Excel" not in skills.extract("You will excel in a fast-paced team.")
    assert "Go" not in skills.extract("We go to great lengths for customers.")
    assert "REST APIs" not in skills.extract("The rest of the team uses Java.")


def test_title_matching_uses_word_boundaries():
    assert skills.title_has("ML Engineer Intern", "ml")
    assert not skills.title_has("HTML Developer Intern", "ml")
    assert skills.title_has("Full-Stack Engineer", "full stack")


# ------------------------------------------------------------------ ingest

def test_upsert_normalizes_and_tracks_removals():
    with db.session() as conn:
        stats = ingest.upsert_listings(conn, [listing(), listing(id="job-2", category="AI/ML/Data")], "src")
        assert stats == {"total": 2, "added": 2, "removed": 0}
        row = conn.execute("SELECT * FROM jobs WHERE id='job-2'").fetchone()
        assert row["category"] == "Data Science, AI & ML" and row["ats_key"] == "gh:123456"
        stats = ingest.upsert_listings(conn, [listing()], "src")
        assert stats["removed"] == 1
        assert conn.execute("SELECT visible FROM jobs WHERE id='job-2'").fetchone()[0] == 0


def test_sync_uses_etag(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json=[listing()], headers={"etag": '"v1"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with db.session() as conn:
        db.save_settings(conn, {"sources": [{"name": "t", "url": "https://example.test/listings.json", "enabled": True}]})
    first = ingest.sync_all(client=client)
    second = ingest.sync_all(client=client)
    assert first["results"][0]["added"] == 1 and first["results"][0]["changed"]
    assert second["results"][0]["changed"] is False
    assert calls == [None, '"v1"']


def test_sync_reports_errors_without_raising():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with db.session() as conn:
        db.save_settings(conn, {"sources": [{"name": "t", "url": "https://example.test/x.json", "enabled": True}]})
    out = ingest.sync_all(client=client)
    assert "error" in out["results"][0]


# ------------------------------------------------------------------ matching

def _job(**kw):
    return matching.job_from_row({**{k: (json.dumps(v) if isinstance(v, list) else v) for k, v in {
        "id": "x", "company": "Acme", "title": "Software Engineer Intern", "category": "Software Engineering",
        "terms": ["Summer 2027"], "locations": ["San Francisco, CA"], "sponsorship": "Other", "degrees": ["Bachelor's"],
        "active": 1, "date_posted": int(time.time()) - 3600, "url": "u", "ats": None}.items()}, **kw})


def test_hard_filters(profile_data):
    m = matching.Matcher(profile_data)
    assert m.hard_filters(_job()) == []
    assert "Closed" in m.hard_filters(_job(active=0))
    assert any(f.startswith("Term") for f in m.hard_filters(_job(terms=json.dumps(["Fall 2026"]))))
    assert any(f.startswith("Degree") for f in m.hard_filters(_job(degrees=json.dumps(["PhD"]))))
    profile_data["work_auth"].update(needs_sponsorship=True, us_citizen=False)
    m = matching.Matcher(profile_data)
    assert "No visa sponsorship" in m.hard_filters(_job(sponsorship="Does Not Offer Sponsorship"))
    assert "Requires U.S. citizenship" in m.hard_filters(_job(sponsorship="U.S. Citizenship is Required"))


def test_location_matching():
    loc = matching.parse_location
    assert matching.location_matches("Bay Area", loc("Palo Alto, CA"))
    assert matching.location_matches("NYC", loc("NYC"))
    assert matching.location_matches("new york", loc("NYC"))
    assert matching.location_matches("CA", loc("San Jose, CA"))
    assert matching.location_matches("California", loc("San Jose, CA"))
    assert matching.location_matches("Remote", loc("Remote in USA"))
    assert matching.location_matches("USA", loc("Austin, TX"))
    assert matching.location_matches("Canada", loc("Toronto, ON, Canada"))
    assert not matching.location_matches("Seattle", loc("San Francisco, CA"))


def test_scoring_prefers_interests_location_and_dream_companies(profile_data):
    m = matching.Matcher(profile_data)
    strong = m.score(_job(company="Stripe", title="Backend Software Engineer Intern"))
    weak = m.score(_job(company="Other", title="Mechanical Engineering Intern", locations=json.dumps(["Houston, TX"]),
                        category="Hardware Engineering", date_posted=int(time.time()) - 60 * 86400))
    assert strong.score > weak.score
    kinds = {r["kind"] for r in strong.reasons}
    assert {"category", "title", "location", "company"} <= kinds
    phd = m.score(_job(title="PhD Research Intern, Machine Learning"))
    assert any(r["kind"] == "penalty" for r in phd.reasons)
    assert m.score(_job(), ai_fit=100).score > m.score(_job(), ai_fit=0).score


# ------------------------------------------------------------------ postings

def test_html_to_text_keeps_structure():
    text = postings.html_to_text("<h2>What you'll do</h2><ul><li>Build APIs</li><li>Ship code</li></ul><script>x()</script>")
    assert "What you'll do" in text and "• Build APIs" in text and "x()" not in text


def test_extract_prefers_json_ld():
    desc = "<p>" + "Build distributed systems in Go. " * 20 + "</p>"
    html = f'<html><script type="application/ld+json">{json.dumps({"@type": "JobPosting", "title": "SWE Intern", "description": desc})}</script><body>menu</body></html>'
    text, method = postings.extract_from_html(html)
    assert method == "json-ld" and text.startswith("SWE Intern") and "distributed systems" in text


def test_fetch_uses_ats_apis():
    long = "<p>" + "Work on Kubernetes and Python services. " * 15 + "</p>"

    def handler(request):
        host, path = request.url.host, request.url.path
        if host == "boards-api.greenhouse.io":
            assert path == "/v1/boards/acme/jobs/123"
            return httpx.Response(200, json={"content": long.replace("<", "&lt;").replace(">", "&gt;")})
        if host == "api.lever.co":
            return httpx.Response(200, json={"descriptionPlain": "Intro " * 60, "lists": [{"text": "Requirements", "content": "<li>Python</li>"}]})
        if host == "acme.wd5.myworkdayjobs.com" and path.startswith("/wday/cxs/acme/careers/job/"):
            return httpx.Response(200, json={"jobPostingInfo": {"jobDescription": long}})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gh = postings.fetch("https://job-boards.greenhouse.io/acme/jobs/123", client)
    assert gh["method"] == "greenhouse-api" and "Kubernetes" in gh["text"]
    lv = postings.fetch("https://jobs.lever.co/acme/d5486403-c050-4920-b2e0-91b69b61ebb2", client)
    assert lv["method"] == "lever-api" and "Requirements" in lv["text"]
    wd = postings.fetch("https://acme.wd5.myworkdayjobs.com/careers/job/Remote/SWE-Intern_R123", client)
    assert wd["method"] == "workday-api"


def test_fetch_reports_js_only_pages():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html><body><div id=root></div></body></html>", headers={"content-type": "text/html"})))
    out = postings.fetch("https://careers.example.com/job/1", client)
    assert out["text"] is None and "extension" in out["error"]
