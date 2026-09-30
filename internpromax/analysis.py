"""Rule-based posting analysis (free, offline). Output matches ai.ANALYSIS_SCHEMA."""

from __future__ import annotations

import re

from . import skills, tailor
from .profile import all_skills, primary_education

PREF_HEAD = re.compile(r"\b(preferred|nice[- ]to[- ]haves?|bonus|pluses|a plus|desired|ideal(ly)?|great to have|extra credit|stand ?out|additional qualifications)\b", re.I)
REQ_HEAD = re.compile(r"\b(minimum|basic|required|requirements?|must[- ]haves?|qualifications?|what you(?:'ll| will)? (?:need|bring)|who you are|you (?:have|bring|should have)|about you|what we(?:'re| are)? looking for|skills)\b", re.I)
RESP_HEAD = re.compile(r"\b(responsibilit\w*|what you(?:'ll| will)? (?:do|work on|be doing)|the role|your role|day[- ]to[- ]day|in this role|you will|about the role|the opportunity|your impact|what you'll own)\b", re.I)
INTRO_HEAD = re.compile(r"^(about (the|this) (team|role|position|job|opportunity)|overview|job summary|position summary|job description|description|the team|who we're looking for)\b", re.I)
OTHER_HEAD = re.compile(r"\b(about us|about the company|who we are|benefits|perks|compensation|salary|pay range|equal opportunity|eeo|our values|why join|location|how to apply|accommodation)\b", re.I)

THEME_HINT = re.compile(r"\b(experience (?:building|with|in|developing|designing|working)|projects?|built|build|shipped|portfolio|hackathons?|open[- ]source|contribut\w+|research experience|side projects?|end[- ]to[- ]end|production|deployed|prototype)\b", re.I)
AUTH_HINT = re.compile(r"\b(sponsor\w*|citizen\w*|clearance|authori[sz]ed to work|work authori[sz]ation|green card|permanent resident|itar|export control)\b", re.I)
GRAD_HINT = re.compile(r"\b(graduat\w*|class of|expected (?:to )?(?:graduate|graduation)|returning to school|remaining in (?:your|their) (?:degree|program))\b", re.I)
DEGREE_HINT = re.compile(r"\b(pursuing|enrolled|bachelor'?s|master'?s|ph\.?d|b\.?s\.?|m\.?s\.?|degree in|majoring|major in)\b", re.I)
GPA_HINT = re.compile(r"\bgpa\b|grade point", re.I)


def _is_heading(line: str) -> bool:
    if len(line) > 90 or line.startswith(("•", "-", "*", "·")):
        return False
    words = len(line.split())
    if line.endswith(":") and words <= 10:
        return True
    if words <= 7 and (PREF_HEAD.search(line) or REQ_HEAD.search(line) or RESP_HEAD.search(line)
                       or OTHER_HEAD.search(line) or INTRO_HEAD.search(line)):
        return not line.endswith(".")
    return False


def _kind(heading: str) -> str:
    if INTRO_HEAD.search(heading):
        return "intro"
    if OTHER_HEAD.search(heading) and not (REQ_HEAD.search(heading) or RESP_HEAD.search(heading)):
        return "other"
    if PREF_HEAD.search(heading):
        return "preferred"
    if RESP_HEAD.search(heading):
        return "responsibilities"
    if REQ_HEAD.search(heading):
        return "required"
    return "other"


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"intro": [], "required": [], "preferred": [], "responsibilities": [], "other": []}
    current = "intro"
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        head, sep, rest = line.partition(":")
        if sep and rest.strip() and len(head.split()) <= 5 and _kind(head) != "other":
            current = _kind(head)
            sections[current].append(rest.strip())
            continue
        if _is_heading(line):
            current = _kind(line.rstrip(":"))
            continue
        sections[current].append(line.lstrip("•-*· ").strip())
    return sections


def _sentences(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        ln = ln.strip().lstrip("•-*· ").strip()
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", ln) if s.strip()]
    return out


def _first(pattern: re.Pattern, sentences: list[str], limit: int = 2) -> str:
    hits = [s[:220] for s in sentences if pattern.search(s)]
    return " ".join(dict.fromkeys(hits[:limit]))


def analyze(description: str, profile: dict, job: dict | None = None) -> dict:
    job = job or {}
    sec = split_sections(description)
    req_text = "\n".join(sec["required"])
    pref_text = "\n".join(sec["preferred"])
    all_text = description

    if req_text.strip():
        required = skills.extract(req_text)
        preferred = [s for s in skills.extract(pref_text) if s not in required]
    else:
        required = skills.extract("\n".join(sec["intro"] + sec["responsibilities"] + sec["other"]))
        preferred = [s for s in skills.extract(pref_text) if s not in required]
    mentioned = [s for s in skills.extract(all_text) if s not in required and s not in preferred]

    responsibilities = [ln for ln in sec["responsibilities"] if 15 < len(ln) < 300][:8]
    themes = [ln for ln in sec["required"] + sec["preferred"] + sec["responsibilities"] if THEME_HINT.search(ln) and 15 < len(ln) < 300]
    sentences = _sentences(description.split("\n"))

    constraints = {
        "graduation": _first(GRAD_HINT, sentences),
        "gpa": _first(GPA_HINT, sentences, 1),
        "degree": _first(DEGREE_HINT, [s for s in sentences if len(s) < 260], 1),
        "work_authorization": _first(AUTH_HINT, sentences),
        "other": [],
    }

    have = {s.lower() for s in all_skills(profile)}
    wanted = required + preferred
    matched = [s for s in wanted if s.lower() in have]
    missing = [s for s in wanted if s.lower() not in have]

    req_cov = (sum(s.lower() in have for s in required) / len(required)) if required else 0.6
    pref_cov = (sum(s.lower() in have for s in preferred) / len(preferred)) if preferred else 0.5
    fit = 100 * (0.75 * req_cov + 0.25 * pref_cov)
    reasons = []
    if required:
        reasons.append(f"You show {sum(s.lower() in have for s in required)} of {len(required)} required skills")
    if preferred:
        reasons.append(f"{sum(s.lower() in have for s in preferred)} of {len(preferred)} nice-to-haves")

    grad_year = str(primary_education(profile).get("grad_year") or "")
    if grad_year and constraints["graduation"]:
        years = set(re.findall(r"\b20\d{2}\b", constraints["graduation"]))
        if years and grad_year not in years:
            lo, hi = min(years), max(years)
            if len(years) == 1 or not (lo <= grad_year <= hi):
                fit -= 15
                reasons.append(f"Graduation window mentions {', '.join(sorted(years))}; you graduate {grad_year}")
    if constraints["gpa"]:
        m = re.search(r"(\d\.\d{1,2})", constraints["gpa"])
        gpa = primary_education(profile).get("gpa")
        try:
            if m and gpa and float(gpa) < float(m.group(1)):
                fit -= 10
                reasons.append(f"GPA requirement {m.group(1)} is above yours")
        except ValueError:
            pass

    advice = []
    for s in missing[:5]:
        tier = "required" if s in required else "nice-to-have"
        advice.append(f"{s} ({tier}): if you've used it in a class or project, add it to your resume; otherwise mention you're learning it")

    prose = [x for x in _sentences(sec["intro"] + sec["responsibilities"]) if len(x.split()) >= 8]
    first_intro = " ".join(prose[:2])
    families = [f for f, kws in skills.ROLE_FAMILIES.items() if any(skills.title_has(job.get("title", ""), k) for k in kws)]
    analysis = {
        "summary": first_intro[:500],
        "role_focus": " / ".join(families[:2]) or (job.get("category") or ""),
        "required_skills": required,
        "preferred_skills": preferred,
        "responsibilities": responsibilities,
        "project_themes": list(dict.fromkeys(themes))[:6],
        "keywords": (required + preferred + mentioned)[:20],
        "constraints": constraints,
        "matched_skills": matched,
        "missing_skills": missing,
        "fit_score": int(max(0, min(100, round(fit)))),
        "fit_reasons": reasons,
        "gaps_advice": advice,
        "resume_focus": [],
    }
    analysis["resume_focus"] = [f"{r['name']} ({', '.join(r['hits'][:3])})" if r["hits"] else r["name"]
                                for r in tailor.rank_entries(profile, analysis)]
    return analysis
