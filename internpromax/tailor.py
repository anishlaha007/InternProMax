"""Tailor the master resume to a posting, without ever inventing anything.

Two paths share the same guardrails:
* rules: rank + reorder entries/bullets/skills by overlap with what the posting asks for
* AI:    Claude rewrites bullets; `assemble()` rebuilds the resume from the master copy by id, reverts
         bullets that introduce numbers not in the original, and drops skills you don't have.
"""

from __future__ import annotations

import copy
import re

from . import skills
from .profile import all_skills, resume_text

STOPWORDS = set("""a an and are as at be but by for from has have in into is it its of on or our that the their them they
this to we will with you your who what when where which while work working team teams role intern interns internship
experience ability strong using use used able across within including such other new about more well etc also must
plus skills skill knowledge understanding currently pursuing degree year years help building build""".split())

_NUM = re.compile(r"(?<![A-Za-z])(?:\$?\d[\d,]*(?:\.\d+)?\s?(?:%|k|K|M|x|X|\+)?)")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9+#.\-]{2,}", text.lower()) if w not in STOPWORDS}


def targets(analysis: dict) -> dict:
    """Weighted skill targets + theme words from an analysis."""
    weights: dict[str, float] = {}
    for s in analysis.get("required_skills") or []:
        weights[s] = max(weights.get(s, 0), 3)
    for s in analysis.get("preferred_skills") or []:
        weights[s] = max(weights.get(s, 0), 2)
    for s in analysis.get("keywords") or []:
        weights.setdefault(s, 1)
    theme_text = " ".join((analysis.get("responsibilities") or []) + (analysis.get("project_themes") or []))
    return {"skills": weights, "words": _words(theme_text)}


def score_text(text: str, tg: dict, tech: list[str] | tuple = ()) -> tuple[float, list[str]]:
    found = set(skills.extract(text)) | {skills.canonical(t) for t in tech}
    low = text.lower()
    score = 0.0
    hits: list[str] = []
    for s, w in tg["skills"].items():
        canon = skills.canonical(s)
        if canon in found or (canon not in skills.SKILLS and len(s) > 2 and s.lower() in low):
            score += w
            hits.append(canon)
    overlap = _words(text) & tg["words"]
    score += 0.4 * min(len(overlap), 6)
    return score, hits


def _entry_text(e: dict) -> str:
    head = ". ".join(x for x in (e.get("title"), e.get("company"), e.get("name"), e.get("role")) if x)
    tech = ", ".join(list(e.get("tech") or []) + list(e.get("skills") or []))
    return ". ".join(x for x in (head, f"Tech: {tech}" if tech else "", ". ".join(e.get("bullets") or [])) if x)


def _entry_tech(e: dict) -> list[str]:
    return list(e.get("tech") or []) + list(e.get("skills") or [])


def rank_entries(profile: dict, analysis: dict, limit: int = 3) -> list[dict]:
    tg = targets(analysis)
    res = profile.get("resume") or {}
    ranked = []
    for kind in ("experience", "projects", "activities"):
        for e in res.get(kind) or []:
            sc, hits = score_text(_entry_text(e), tg, _entry_tech(e))
            if sc > 0:
                ranked.append({"kind": kind, "id": e.get("id"), "name": e.get("company") or e.get("name") or e.get("title"),
                               "score": round(sc, 1), "hits": hits})
    ranked.sort(key=lambda r: -r["score"])
    return ranked[:limit]


def _header(profile: dict) -> dict:
    p = profile.get("personal") or {}
    loc = ", ".join(x for x in (p.get("city"), p.get("state")) if x)
    return {
        "name": " ".join(x for x in (p.get("preferred_name") or p.get("first_name"), p.get("last_name")) if x),
        "email": p.get("email", ""), "phone": p.get("phone", ""), "linkedin": p.get("linkedin", ""),
        "github": p.get("github", ""), "website": p.get("website", ""), "location": loc,
    }


def base_resume(profile: dict) -> dict:
    res = copy.deepcopy(profile.get("resume") or {})
    return {
        "personal": _header(profile),
        "summary": res.get("summary", ""),
        "education": copy.deepcopy(profile.get("education") or []),
        "experience": res.get("experience") or [],
        "projects": res.get("projects") or [],
        "activities": res.get("activities") or [],
        "skills": res.get("skills") or [],
        "awards": res.get("awards") or [],
    }


# ------------------------------------------------------------------ rules path

def tailor_rules(profile: dict, analysis: dict, max_projects: int = 3) -> tuple[dict, list[str], list[str]]:
    tg = targets(analysis)
    out = base_resume(profile)
    changes: list[str] = []

    def reorder_bullets(entry: dict) -> None:
        bullets = list(entry.get("bullets") or [])
        if len(bullets) < 2:
            return
        scored = [(score_text(b, tg)[0], i, b) for i, b in enumerate(bullets)]
        new = [b for _, _, b in sorted(scored, key=lambda t: (-t[0], t[1]))]
        if new != bullets:
            entry["bullets"] = new
            lead_hits = score_text(new[0], tg)[1]
            label = entry.get("company") or entry.get("name")
            changes.append(f"{label}: led with the bullet about {', '.join(lead_hits[:3]) or 'the most relevant work'}")

    for e in out["experience"]:
        reorder_bullets(e)

    for kind, cap in (("projects", max_projects), ("activities", 3)):
        entries = out[kind]
        scored = [(score_text(_entry_text(e), tg, _entry_tech(e)), i, e) for i, e in enumerate(entries)]
        scored.sort(key=lambda t: (-t[0][0], t[1]))
        kept = [e for (_s, _i, e) in scored[:cap]] if len(entries) > cap else [e for (_s, _i, e) in scored]
        if [e.get("id") for e in kept] != [e.get("id") for e in entries]:
            dropped = [e.get("name") or e.get("company") for e in entries if e not in kept]
            top = scored[0]
            changes.append(f"{kind.title()}: put {top[2].get('name') or top[2].get('company')} first"
                           + (f" (matches {', '.join(top[0][1][:3])})" if top[0][1] else "")
                           + (f"; left out {', '.join(d for d in dropped if d)}" if dropped else ""))
        for e in kept:
            reorder_bullets(e)
            if e.get("tech"):
                tech = list(e["tech"])
                e["tech"] = sorted(tech, key=lambda t: (-(tg["skills"].get(skills.canonical(t), 0)
                                                          or tg["skills"].get(t, 0)), tech.index(t)))
        out[kind] = kept

    wanted = {skills.canonical(s) for s in tg["skills"]}
    groups = []
    for g in out["skills"]:
        items = list(g.get("items") or [])
        new_items = sorted(items, key=lambda s: (skills.canonical(s) not in wanted, items.index(s)))
        groups.append({"category": g.get("category", ""), "items": new_items,
                       "_hits": sum(skills.canonical(s) in wanted for s in items)})
    order = sorted(range(len(groups)), key=lambda i: (-groups[i]["_hits"], i))
    new_groups = [{"category": groups[i]["category"], "items": groups[i]["items"]} for i in order]
    if new_groups != out["skills"]:
        firsts = [s for g in new_groups for s in g["items"] if skills.canonical(s) in wanted][:5]
        if firsts:
            changes.append("Skills: moved " + ", ".join(firsts) + " to the front")
    out["skills"] = new_groups

    if out["education"]:
        cw = list(out["education"][0].get("coursework") or [])
        if len(cw) > 1:
            ranked = sorted(cw, key=lambda c: (-score_text(c, tg)[0], cw.index(c)))
            if ranked != cw:
                out["education"][0]["coursework"] = ranked
                changes.append("Coursework: listed the most relevant courses first")

    if not changes:
        changes.append("Your resume already lines up with this posting; nothing needed reordering.")
    return out, changes, []


# ------------------------------------------------------------------ AI guardrails

def _numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", m.group(0)).lower() for m in _NUM.finditer(text or "")}


def _closest(bullet: str, originals: list[str]) -> str | None:
    if not originals:
        return None
    bw = _words(bullet)
    return max(originals, key=lambda o: len(bw & _words(o)))


def check_bullets(new_bullets: list[str], original: dict, label: str, warnings: list[str]) -> list[str]:
    source_text = _entry_text(original)
    allowed = _numbers(source_text)
    originals = list(original.get("bullets") or [])
    out: list[str] = []
    for b in new_bullets:
        b = (b or "").strip()
        if not b:
            continue
        extra = _numbers(b) - allowed
        if extra:
            fallback = _closest(b, [o for o in originals if o not in out])
            warnings.append(f"{label}: kept your original wording for one bullet (the rewrite added {', '.join(sorted(extra))})")
            if fallback:
                out.append(fallback)
            continue
        out.append(b)
    return out or originals


def assemble_ai(profile: dict, ai_out: dict) -> tuple[dict, list[str], list[str]]:
    """Rebuild a tailored resume from the master copy + the model's suggestions."""
    out = base_resume(profile)
    res = profile.get("resume") or {}
    warnings: list[str] = []
    allowed_skills = {s.lower() for s in all_skills(profile)}
    master_text = resume_text(profile).lower()

    def has_skill(s: str) -> bool:
        c = skills.canonical(s)
        return c.lower() in allowed_skills or s.lower() in allowed_skills or (
            len(s) > 2 and re.search(r"(?<![a-z0-9])" + re.escape(s.lower()) + r"(?![a-z0-9])", master_text) is not None)

    # experience: keep master order and every entry; take rewritten bullets by id
    by_id = {e.get("id"): e for e in res.get("experience") or []}
    suggested = {x.get("source_id"): x for x in ai_out.get("experience") or []}
    for sid in suggested:
        if sid not in by_id:
            warnings.append("Ignored an experience entry that isn't in your master resume")
    exp = []
    for e in res.get("experience") or []:
        new = copy.deepcopy(e)
        if e.get("id") in suggested:
            new["bullets"] = check_bullets(suggested[e["id"]].get("bullets") or [], e, e.get("company", "Experience"), warnings)
        exp.append(new)
    out["experience"] = exp

    for kind in ("projects", "activities"):
        by_id = {e.get("id"): e for e in res.get(kind) or []}
        items = []
        for x in ai_out.get(kind) or []:
            e = by_id.get(x.get("source_id"))
            if not e:
                warnings.append(f"Ignored a {kind[:-1]} that isn't in your master resume")
                continue
            if any(i.get("id") == e.get("id") for i in items):
                continue
            new = copy.deepcopy(e)
            label = e.get("name") or e.get("company") or kind
            new["bullets"] = check_bullets(x.get("bullets") or [], e, label, warnings)
            if kind == "projects" and x.get("tech"):
                own = {t.lower() for t in e.get("tech") or []}
                tech = [t for t in x["tech"] if t.lower() in own or has_skill(t)]
                new["tech"] = tech + [t for t in e.get("tech") or [] if t.lower() not in {q.lower() for q in tech}]
            items.append(new)
        out[kind] = items if items or not res.get(kind) else copy.deepcopy(res.get(kind))

    # skills: only what you have; keep anything the model dropped
    groups: list[dict] = []
    placed: set[str] = set()
    rejected: list[str] = []
    for g in ai_out.get("skills") or []:
        kept = []
        for s in g.get("items") or []:
            if s.lower() in placed:
                continue
            if has_skill(s):
                kept.append(s)
                placed.add(s.lower())
            else:
                rejected.append(s)
        if kept:
            groups.append({"category": g.get("category") or "Skills", "items": kept})
    for g in res.get("skills") or []:
        missing = [s for s in g.get("items") or [] if s.lower() not in placed]
        if not missing:
            continue
        target = next((x for x in groups if x["category"].lower() == (g.get("category") or "").lower()), None)
        if target:
            target["items"] += missing
        else:
            groups.append({"category": g.get("category") or "Other", "items": missing})
        placed.update(s.lower() for s in missing)
    if rejected:
        warnings.append("Not added because they aren't in your resume: " + ", ".join(sorted(set(rejected))))
    out["skills"] = groups or out["skills"]

    # coursework: subset of what you listed
    if out["education"] and ai_out.get("coursework"):
        cw = out["education"][0].get("coursework") or []
        low = {c.lower(): c for c in cw}
        picked = [low[c.lower()] for c in ai_out["coursework"] if c.lower() in low]
        if picked:
            out["education"][0]["coursework"] = picked

    # summary only when the master resume has one, with the same number check
    master_summary = res.get("summary") or ""
    if master_summary and ai_out.get("summary"):
        extra = _numbers(ai_out["summary"]) - _numbers(master_text)
        out["summary"] = master_summary if extra else ai_out["summary"].strip()
    else:
        out["summary"] = master_summary

    changes = [c for c in ai_out.get("changes") or [] if c]
    return out, changes, warnings


def master_for_prompt(profile: dict) -> dict:
    """The master resume as sent to the model (ids included, personal info excluded)."""
    res = profile.get("resume") or {}
    return {
        "summary": res.get("summary", ""),
        "education": [{k: ed.get(k) for k in ("school", "degree", "major", "minor", "gpa", "grad_month", "grad_year", "coursework", "highlights")}
                      for ed in profile.get("education") or []],
        "experience": res.get("experience") or [],
        "projects": res.get("projects") or [],
        "activities": res.get("activities") or [],
        "skills": res.get("skills") or [],
        "awards": res.get("awards") or [],
    }
