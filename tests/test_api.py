"""HTTP API tests through FastAPI's TestClient."""

import pytest
from fastapi.testclient import TestClient

from internpromax import db, ingest
from internpromax.server import app

from .conftest import listing

BASE = "http://127.0.0.1:8420"


@pytest.fixture
def client(profile_data):
    c = TestClient(app, base_url=BASE)
    with db.session() as conn:
        ingest.upsert_listings(conn, [
            listing(id="a", company_name="Stripe", title="Backend Software Engineer Intern"),
            listing(id="b", company_name="Globex", title="Mechanical Engineer Intern", category="Hardware",
                    url="https://jobs.lever.co/globex/d5486403-c050-4920-b2e0-91b69b61ebb2"),
            listing(id="c", company_name="Closed Co", active=False),
            listing(id="d", company_name="Phd Co", degrees=["PhD"]),
        ], "test")
    assert c.put("/api/profile", json={"profile": profile_data}).status_code == 200
    return c


def test_feed_ranks_and_buckets(client):
    data = client.get("/api/jobs").json()
    assert [i["id"] for i in data["items"]][0] == "a"
    assert data["counts"]["matches"] == 2 and data["counts"]["filtered"] == 1  # closed job excluded entirely
    filtered = client.get("/api/jobs?view=filtered").json()["items"]
    assert filtered[0]["id"] == "d" and filtered[0]["filtered"][0].startswith("Degree")
    client.post("/api/jobs/b/hide", json={"hidden": True})
    assert client.get("/api/jobs?view=hidden").json()["items"][0]["id"] == "b"
    client.post("/api/jobs/a/save")
    assert client.get("/api/jobs?view=saved").json()["items"][0]["app_status"] == "saved"


def test_lookup_by_url(client):
    out = client.get("/api/jobs/lookup", params={"url": "https://jobs.lever.co/globex/d5486403-c050-4920-b2e0-91b69b61ebb2/apply?src=x"}).json()
    assert out["job"]["id"] == "b"
    assert client.get("/api/jobs/lookup", params={"url": "https://example.com/nothing"}).json()["job"] is None


def test_capture_analyze_tailor_and_pdf(client, posting_text):
    assert client.post("/api/jobs/a/description", json={"text": "too short"}).status_code == 400
    assert client.post("/api/jobs/a/description", json={"text": posting_text}).json()["stored"]
    details = client.post("/api/jobs/a/analyze", json={"wait": True}).json()["details"]
    assert details["status"] == "ready" and details["analysis_method"] == "rules"
    resume = client.post("/api/jobs/a/tailor", json={"wait": True, "force": True}).json()["resume"]
    assert resume["status"] == "ready" and resume["data"]["projects"][0]["name"] == "RaftKV"
    status = client.get("/api/jobs/a/resume-status").json()
    assert status["tailored"] == "ready" and status["use_tailored"]
    pdf = client.get("/api/jobs/a/resume.pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.headers["x-resume-variant"] == "tailored"
    assert 'filename="Alex_Rivera_Resume.pdf"' in pdf.headers["content-disposition"]  # neutral name, no company
    detail = client.get("/api/jobs/a").json()
    assert detail["details"]["analysis"]["fit_score"] > 0 and detail["resume"]["method"] == "rules"


def test_applied_from_extension_and_manual_status(client):
    out = client.post("/api/applications/applied", json={"url": "https://jobs.lever.co/globex/d5486403-c050-4920-b2e0-91b69b61ebb2", "trigger": "confirmation-page"}).json()
    app = out["application"]
    assert app["job_id"] == "b" and app["status"] == "applied"
    patched = client.patch(f"/api/applications/{app['id']}", json={"status": "interviewing", "notes": "Call with Sam on Tue"}).json()
    assert patched["status"] == "interviewing" and patched["notes"].startswith("Call")
    items = client.get("/api/applications").json()
    assert items["stats"]["counts"]["interviewing"] == 1
    csv = client.get("/api/export/applications.csv").text
    assert "Globex" in csv and "interviewing" in csv


def test_email_paste_flow(client):
    app = client.post("/api/applications", json={"company": "Initech", "title": "Co-op", "status": "applied"}).json()
    res = client.post("/api/email/analyze", json={"from": "careers@initech.com", "subject": "Update on your application",
                                                  "body": "Unfortunately we will not be moving forward with your application."}).json()
    assert res["status"] == "rejected" and res["application"]["id"] == app["id"]
    updated = client.post("/api/email/apply", json={"application_id": app["id"], "status": "rejected", "subject": "Update"}).json()
    assert updated["status"] == "rejected" and any(e["type"] == "email" for e in updated["events"])


def test_settings_hide_secrets(client):
    s = client.put("/api/settings", json={"anthropic_api_key": "sk-secret", "imap": {"username": "me@x.com", "password": "pw"}}).json()
    assert s["anthropic_api_key"] == "" and s["anthropic_api_key_set"]
    assert s["imap"]["password"] == "" and s["imap"]["password_set"]
    s = client.put("/api/settings", json={"imap": {"host": "imap.example.com", "password": ""}}).json()
    assert s["imap"]["password_set"]  # blank password in a save keeps the stored one
    with db.session() as conn:
        assert db.get_settings(conn)["anthropic_api_key"] == "sk-secret"


def test_security_rejects_foreign_hosts_and_origins(client):
    assert TestClient(app, base_url="http://evil.example").get("/api/profile").status_code == 403
    assert TestClient(app).get("/api/profile").status_code == 403  # "testserver" is not localhost
    assert client.post("/api/jobs/mark-seen", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/jobs/mark-seen", headers={"origin": "chrome-extension://abcdef"}).status_code == 200
    assert client.post("/api/jobs/mark-seen", headers={"origin": "http://127.0.0.1:8420"}).status_code == 200


def test_ai_endpoints_need_a_key(client):
    r = client.post("/api/ai/answer", json={"question": "Why us?"})
    assert r.status_code == 400 and "API key" in r.json()["detail"]


def test_dashboard_is_served(client):
    html = client.get("/").text
    assert "data-ipm-dashboard" in html and "js/app.js" in html
