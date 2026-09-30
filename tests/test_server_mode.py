"""Server mode: password login, tokens for the extension, allowed hosts, CSRF and rate limiting."""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from internpromax import auth, config
from internpromax.server import app

SERVER = "http://ipm.tail1234.ts.net:8420"


@pytest.fixture
def server_mode(monkeypatch):
    monkeypatch.setenv("IPM_PASSWORD", "correct horse battery")
    monkeypatch.setattr(config, "ALLOWED_HOSTS", ["*.ts.net", "100.101.102.103"])
    auth.reset_failures()
    yield
    auth.reset_failures()


def test_needs_login(server_mode):
    c = TestClient(app, base_url=SERVER, follow_redirects=False)
    assert c.get("/api/profile").status_code == 401
    root = c.get("/")
    assert root.status_code == 303 and root.headers["location"] == "/login.html"
    assert c.get("/login.html").status_code == 200 and c.get("/js/lib.js").status_code == 200
    health = c.get("/api/health").json()
    assert health == {"ok": True, "app": "internpromax", "version": health["version"], "auth_required": True, "authenticated": False}


def test_login_cookie_and_bearer_token(server_mode):
    c = TestClient(app, base_url=SERVER)
    assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    res = c.post("/api/auth/login", json={"password": "correct horse battery"})
    assert res.status_code == 200 and auth.COOKIE in res.cookies
    token = res.json()["token"]
    assert c.get("/api/profile").status_code == 200  # cookie
    ext = TestClient(app, base_url=SERVER)
    assert ext.get("/api/profile", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    tampered = token[:-1] + ("1" if token[-1] == "0" else "0")
    assert ext.get("/api/profile", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    c.post("/api/auth/logout")
    assert c.get("/api/profile").status_code == 401


def test_changing_password_signs_everyone_out(server_mode, monkeypatch):
    token = TestClient(app, base_url=SERVER).post("/api/auth/login", json={"password": "correct horse battery"}).json()["token"]
    monkeypatch.setenv("IPM_PASSWORD", "a new password")
    r = TestClient(app, base_url=SERVER).get("/api/profile", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_hosts_and_origins(server_mode):
    assert TestClient(app, base_url="http://100.101.102.103:8420").get("/api/health").status_code == 200
    assert TestClient(app, base_url="http://evil.example").get("/api/health").status_code == 403
    c = TestClient(app, base_url=SERVER)
    c.post("/api/auth/login", json={"password": "correct horse battery"})
    assert c.post("/api/jobs/mark-seen", headers={"origin": SERVER}).status_code == 200
    assert c.post("/api/jobs/mark-seen", headers={"origin": "https://ipm.tail1234.ts.net"}).status_code == 200  # behind tailscale serve
    assert c.post("/api/jobs/mark-seen", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/jobs/mark-seen", headers={"origin": "chrome-extension://abc"}).status_code == 200


def test_rate_limits_wrong_passwords(server_mode):
    c = TestClient(app, base_url=SERVER)
    for _ in range(auth.MAX_FAILURES):
        assert c.post("/api/auth/login", json={"password": "guess"}).status_code == 401
    assert c.post("/api/auth/login", json={"password": "correct horse battery"}).status_code == 429


def test_local_mode_is_unchanged(monkeypatch):
    monkeypatch.delenv("IPM_PASSWORD", raising=False)
    c = TestClient(app, base_url="http://127.0.0.1:8420")
    assert c.get("/api/profile").status_code == 200
    assert c.post("/api/auth/login", json={}).json()["auth_required"] is False


def test_refuses_public_bind_without_password(tmp_path):
    env = {"IPM_DATA_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-m", "internpromax", "serve", "--no-browser", "--host", "0.0.0.0"],
                         cwd=config.ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode != 0 and "IPM_PASSWORD" in out.stderr
