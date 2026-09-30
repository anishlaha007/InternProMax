"""Optional password protection for running InternProMax on a server.

Off unless IPM_PASSWORD is set. When on, the dashboard gets an HttpOnly session cookie and the
extension gets the same signed token to send as `Authorization: Bearer ...`.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time

from . import config

COOKIE = "ipm_session"
TTL = 90 * 86400
MAX_FAILURES = 10
FAILURE_WINDOW = 600

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}


def password() -> str | None:
    return os.environ.get("IPM_PASSWORD") or None


def enabled() -> bool:
    return bool(password())


def _server_secret() -> bytes:
    path = config.ensure_data_dir() / "secret.key"
    with _lock:
        if not path.exists():
            path.write_bytes(secrets.token_bytes(32))
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    return path.read_bytes()


def _key() -> bytes:
    # Tied to the password: changing IPM_PASSWORD signs everyone out.
    return hashlib.sha256(_server_secret() + (password() or "").encode()).digest()


def issue() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(_key(), f"v1.{ts}".encode(), hashlib.sha256).hexdigest()
    return f"v1.{ts}.{sig}"


def verify(token: str | None) -> bool:
    if not token:
        return False
    try:
        version, ts, sig = token.split(".")
    except ValueError:
        return False
    if version != "v1" or not ts.isdigit() or time.time() - int(ts) > TTL:
        return False
    expected = hmac.new(_key(), f"v1.{ts}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def check_password(candidate: str) -> bool:
    pw = password()
    if not pw:
        return False
    return hmac.compare_digest(hashlib.sha256(candidate.encode()).digest(), hashlib.sha256(pw.encode()).digest())


def token_from(headers, cookies) -> str | None:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return cookies.get(COOKIE)


def attempt_allowed(client: str) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(client, []) if now - t < FAILURE_WINDOW]
        _failures[client] = recent
        return len(recent) < MAX_FAILURES


def record_failure(client: str) -> None:
    with _lock:
        _failures.setdefault(client, []).append(time.time())


def reset_failures() -> None:
    with _lock:
        _failures.clear()
