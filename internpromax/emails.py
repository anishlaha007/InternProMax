"""Classify recruiting emails and match them to applications."""

from __future__ import annotations

import re
from email.utils import parseaddr

ATS_DOMAINS = ("greenhouse.io", "greenhouse-mail.io", "lever.co", "hire.lever.co", "myworkday.com", "workday.com",
               "ashbyhq.com", "icims.com", "smartrecruiters.com", "jobvite.com", "successfactors.com", "taleo.net",
               "oraclecloud.com", "workablemail.com", "workable.com", "eightfold.ai", "hackerrank.com",
               "codesignal.com", "hirevue.com", "gmail.com", "outlook.com", "yahoo.com", "karat.io", "goodtime.io",
               "bamboohr.com", "rippling.com", "paylocity.com", "phenompeople.com", "avature.net", "gem.com",
               "sendgrid.net", "mailgun.org", "amazonses.com")

P = {
    "offer": [r"pleased to (?:offer|extend)", r"offer (?:letter|of employment)", r"extend(?:ing)? (?:you )?an? (?:internship |co-?op )?offer",
              r"congratulations[^.]{0,120}\boffer\b", r"we(?:'d| would) like to offer you", r"excited to offer you"],
    "rejected_strong": [r"not (?:to )?(?:be )?mov(?:e|ing) forward with your", r"(?:decided|chosen|chose) to (?:move|moving) forward with other",
                        r"(?:will|won't|will not) (?:not )?be moving forward", r"not been selected", r"were not selected",
                        r"pursue other candidates", r"regret to inform", r"position has been filled", r"no longer (?:under consideration|being considered)",
                        r"decided not to (?:proceed|move forward)", r"not (?:a|the right) (?:fit|match) (?:for|at this time)",
                        r"other (?:applicants|candidates) whose", r"unable to offer you", r"not able to offer you",
                        r"decided to go in a different direction", r"not selected to move forward", r"application was not successful",
                        r"will not be proceeding"],
    "rejected_weak": [r"\bunfortunately\b"],
    "oa": [r"online assessment", r"coding (?:challenge|assessment|test|exercise)", r"\bhackerrank\b", r"\bcodesignal\b", r"\bcodility\b",
           r"\bhirevue\b", r"technical assessment", r"take[- ]home", r"\bkarat\b", r"assessment invitation", r"invit\w+ to (?:complete|take) (?:an?|the|our)",
           r"complete (?:the|an|your|our) (?:online )?assessment", r"\bpymetrics\b", r"(?:skills|aptitude|cognitive) (?:test|assessment)",
           r"\bcodepair\b", r"\bcoderpad\b"],
    "interviewing": [r"\binterview(?:s|ing)?\b", r"schedule (?:a|your|an?) (?:call|time|chat|conversation|meeting)", r"phone screen",
                     r"next (?:round|steps?) (?:in|of) (?:the|our)", r"your availability", r"\bsuperday\b", r"\bon-?site\b", r"calendly\.com",
                     r"\bgoodtime\b", r"meet with (?:our|the) team", r"recruiter (?:call|chat|screen)", r"speak with you", r"book a time"],
    "applied": [r"(?:thank you|thanks) for (?:applying|your application|submitting)", r"(?:we(?:'ve| have)|has been) received your application",
                r"application (?:has been |was )?(?:received|submitted)", r"we received your application", r"your application (?:to|for) .{0,80} (?:has been|was) (?:received|submitted)"],
}
_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in P.items()}
JOB_WORDS = re.compile(r"\b(application|applied|applying|position|role|internship|intern\b|co-?op|candidate|recruit\w*|interview|assessment|opportunit)", re.I)

SUFFIXES = r"\b(inc|incorporated|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|plc|gmbh|technologies|technology|labs|group|holdings|the|lp|llp)\b\.?"


def _hits(kind: str, text: str) -> list[str]:
    return [m.group(0) for pat in _COMPILED[kind] if (m := pat.search(text))]


def classify(subject: str, body: str) -> dict:
    text = f"{subject}\n{body}"
    h = {k: _hits(k, text) for k in _COMPILED}
    status, conf, why = None, 0.0, []
    if h["offer"] and not h["rejected_strong"]:
        status, conf, why = "offer", 0.9, h["offer"]
    elif h["rejected_strong"]:
        status, conf, why = "rejected", 0.92, h["rejected_strong"]
    elif h["oa"]:
        status, conf, why = "oa", 0.85, h["oa"]
    elif h["interviewing"] and not h["rejected_weak"]:
        status, conf, why = "interviewing", 0.85 if len(h["interviewing"]) >= 2 else 0.72, h["interviewing"]
    elif h["rejected_weak"] and not h["interviewing"]:
        status, conf, why = "rejected", 0.7, h["rejected_weak"]
    elif h["interviewing"] and h["rejected_weak"]:
        status, conf, why = "interviewing", 0.5, h["interviewing"]
    elif h["applied"]:
        status, conf, why = "applied", 0.8, h["applied"]
    return {"status": status, "confidence": conf, "reasons": why[:4], "job_related": bool(status or JOB_WORDS.search(text))}


def norm_company(name: str) -> str:
    n = name.lower().replace("&", " and ")
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(SUFFIXES, " ", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _domain(sender: str) -> str:
    addr = parseaddr(sender or "")[1].lower()
    return addr.split("@", 1)[1] if "@" in addr else ""


def match_application(sender: str, subject: str, body: str, apps: list[dict]) -> tuple[dict | None, float, str]:
    display = parseaddr(sender or "")[0].lower()
    domain = _domain(sender)
    is_ats = any(domain == d or domain.endswith("." + d) for d in ATS_DOMAINS)
    sld = domain.split(".")[-2] if domain.count(".") >= 1 else ""
    subj, bod = subject.lower(), body.lower()[:20000]
    best: tuple[dict | None, float, str] = (None, 0.0, "")
    for app in apps:
        name = norm_company(app.get("company") or "")
        if not name or len(name) < 2:
            continue
        compact = name.replace(" ", "")
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(name).replace(r"\ ", r"[\s\-]*") + r"(?![a-z0-9])")
        score, why = 0.0, ""
        if not is_ats and sld and (sld == compact or (len(sld) >= 4 and (compact.startswith(sld) or sld.startswith(compact)))):
            score, why = 0.95, f"sender domain {domain}"
        elif pat.search(subj):
            score, why = 0.9, "company named in subject"
        elif pat.search(display):
            score, why = 0.85, "company in sender name"
        elif pat.search(bod):
            score, why = 0.7, "company named in email body"
        if score and app.get("title") and app["title"].lower() in (subj + " " + bod):
            score = min(1.0, score + 0.05)
            why += " + role title"
        if score:
            active = app.get("status") not in ("rejected", "withdrawn")
            score += 0.01 if active else 0.0
            if score > best[1] or (score == best[1] and (app.get("applied_at") or 0) > ((best[0] or {}).get("applied_at") or 0)):
                best = (app, round(min(score, 1.0), 2), why)
    return best
