"""Recognize applicant-tracking systems and stable job keys from URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

_TRAILING = re.compile(r"/(apply|application|applications|thanks|confirmation)/?$", re.I)


def url_key(url: str | None) -> str | None:
    """Host + path, lowercased, without query, fragment, trailing /apply etc."""
    if not url:
        return None
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = _TRAILING.sub("", p.path or "").rstrip("/")
    if not host:
        return None
    return f"{host}{path}".lower()


def parse(url: str | None) -> dict:
    """Return {'ats': name|None, 'key': stable id|None, ...extra parts}."""
    out: dict = {"ats": None, "key": None}
    if not url:
        return out
    try:
        p = urlparse(url.strip())
    except ValueError:
        return out
    host = (p.hostname or "").lower()
    path = p.path or ""
    qs = parse_qs(p.query)

    # Greenhouse: boards.greenhouse.io/<board>/jobs/<id>, job-boards.greenhouse.io/..., embed?token=, ?gh_jid=
    if "greenhouse.io" in host:
        out["ats"] = "greenhouse"
        m = re.search(r"^/(?:embed/job_app)?/?([^/]+)/jobs/(\d+)", path)
        if m:
            out.update(board=m.group(1), job_id=m.group(2), key=f"gh:{m.group(2)}")
        elif qs.get("token"):
            out.update(job_id=qs["token"][0], key=f"gh:{qs['token'][0]}")
            if qs.get("for"):
                out["board"] = qs["for"][0]
        return out
    if qs.get("gh_jid"):
        out.update(ats="greenhouse", job_id=qs["gh_jid"][0], key=f"gh:{qs['gh_jid'][0]}")
        return out

    if host.endswith("lever.co"):
        out["ats"] = "lever"
        m = re.search(rf"^/([^/]+)/({UUID})", path, re.I)
        if m:
            out.update(company=m.group(1), job_id=m.group(2).lower(), key=f"lever:{m.group(2).lower()}")
        return out

    if host.endswith("ashbyhq.com"):
        out["ats"] = "ashby"
        m = re.search(rf"^/([^/]+)/({UUID})", path, re.I)
        if m:
            out.update(org=m.group(1), job_id=m.group(2).lower(), key=f"ashby:{m.group(2).lower()}")
        return out

    if "myworkdayjobs.com" in host or "myworkdaysite.com" in host:
        out["ats"] = "workday"
        tenant = host.split(".")[0]
        segs = [s for s in path.split("/") if s]
        # optional locale segment like en-US
        if segs and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", segs[0]):
            segs = segs[1:]
        if "job" in segs:
            i = segs.index("job")
            site = segs[i - 1] if i >= 1 else None
            rest = segs[i + 1:]
            if "apply" in rest:
                rest = rest[: rest.index("apply")]
            out.update(tenant=tenant, site=site, job_path="/".join(rest))
            for seg in reversed(rest):
                m = re.search(r"_([A-Za-z]*-?\d[\w-]*)$", seg)
                if m:
                    req = re.sub(r"-\d+$", "", m.group(1))
                    out.update(req_id=req, key=f"wd:{tenant}:{req.lower()}")
                    break
        return out

    if host.endswith("smartrecruiters.com"):
        out["ats"] = "smartrecruiters"
        m = re.search(r"^/([^/]+)/(\d+)", path)
        if m:
            out.update(company=m.group(1), job_id=m.group(2), key=f"sr:{m.group(2)}")
        return out

    if "icims.com" in host:
        out["ats"] = "icims"
        m = re.search(r"/jobs/(\d+)", path)
        if m:
            out.update(job_id=m.group(1), key=f"icims:{host.split('.')[0]}:{m.group(1)}")
        return out

    for name, needle in (
        ("oracle", "oraclecloud.com"),
        ("successfactors", "successfactors"),
        ("taleo", "taleo.net"),
        ("jobvite", "jobvite.com"),
        ("workable", "workable.com"),
        ("eightfold", "eightfold.ai"),
        ("bamboohr", "bamboohr.com"),
        ("rippling", "rippling.com"),
        ("paylocity", "paylocity.com"),
    ):
        if needle in host:
            out["ats"] = name
            return out
    return out
