"""Profile-driven job filtering and explainable scoring."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from . import skills
from .profile import all_skills, primary_education

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}
STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}
CA_PROVINCES = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE"}

CITY_ALIASES = {
    "sf": "San Francisco, CA",
    "nyc": "New York, NY",
    "la": "Los Angeles, CA",
    "dc": "Washington, DC",
}
REGIONS = {
    "bay area": ["san francisco", "sf", "san jose", "palo alto", "mountain view", "sunnyvale", "menlo park",
                 "redwood city", "oakland", "santa clara", "cupertino", "berkeley", "fremont", "san mateo",
                 "foster city", "south san francisco", "burlingame", "milpitas", "san carlos", "emeryville"],
    "silicon valley": ["san jose", "palo alto", "mountain view", "sunnyvale", "menlo park", "santa clara",
                       "cupertino", "milpitas", "redwood city"],
    "seattle area": ["seattle", "bellevue", "redmond", "kirkland"],
    "new york": ["new york", "nyc", "brooklyn", "manhattan", "jersey city", "hoboken"],
    "boston": ["boston", "cambridge", "somerville", "waltham", "burlington, ma"],
}
COUNTRY_WORDS = {
    "usa": "US", "us": "US", "united states": "US", "america": "US",
    "canada": "CA_COUNTRY", "uk": "UK", "united kingdom": "UK", "england": "UK",
}

DEGREE_LEVELS = ["Associate's", "Bachelor's", "Master's", "MBA", "PhD"]


def _now() -> float:
    return time.time()


def parse_location(loc: str) -> dict:
    raw = loc.strip()
    low = raw.lower()
    expanded = CITY_ALIASES.get(low, raw)
    info = {"raw": raw, "text": expanded.lower(), "remote": "remote" in low, "state": None, "country": None}
    parts = [p.strip() for p in expanded.split(",")]
    if len(parts) >= 2:
        tail = parts[-1]
        if tail.upper() in US_STATES:
            info["state"], info["country"] = tail.upper(), "US"
        elif tail.upper() in CA_PROVINCES or tail.lower() == "canada":
            info["country"] = "CA_COUNTRY"
        elif tail.lower() in ("uk", "united kingdom", "england"):
            info["country"] = "UK"
        elif tail.lower() in ("usa", "us", "united states"):
            info["country"] = "US"
    if info["remote"]:
        if "usa" in low or " us" in low or "united states" in low:
            info["country"] = "US"
        elif "canada" in low:
            info["country"] = "CA_COUNTRY"
    return info


def location_matches(pref: str, loc: dict) -> bool:
    p = pref.strip().lower()
    if not p:
        return False
    if p == "remote":
        return loc["remote"]
    if p in COUNTRY_WORDS:
        return loc["country"] == COUNTRY_WORDS[p]
    if p.upper() in US_STATES and len(p) == 2:
        return loc["state"] == p.upper()
    if p in STATE_BY_NAME:
        return loc["state"] == STATE_BY_NAME[p]
    if p in REGIONS:
        return any(re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", loc["text"]) for c in REGIONS[p])
    target = CITY_ALIASES.get(p, pref).lower()
    city = target.split(",")[0].strip()
    return re.search(r"(?<![a-z])" + re.escape(city) + r"(?![a-z])", loc["text"]) is not None


@dataclass
class Scored:
    score: int
    reasons: list[dict] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)


def _reason(kind: str, text: str, points: int) -> dict:
    return {"kind": kind, "text": text, "points": points}


class Matcher:
    """Pre-computes profile-derived data once, then scores many jobs quickly."""

    def __init__(self, profile: dict):
        self.profile = profile
        prefs = profile.get("preferences") or {}
        self.prefs = prefs
        self.terms = {t.lower() for t in prefs.get("terms") or []}
        self.categories = list(prefs.get("categories") or [])
        self.locations = [loc for loc in prefs.get("locations") or [] if loc.strip()]
        self.remote_ok = bool(prefs.get("remote_ok", True))
        self.strict_location = bool(prefs.get("strict_location"))
        self.include_kw = [k for k in prefs.get("include_keywords") or [] if k.strip()]
        self.exclude_kw = [k for k in prefs.get("exclude_keywords") or [] if k.strip()]
        self.dream = [c.strip().lower() for c in prefs.get("dream_companies") or [] if c.strip()]
        self.excluded_cos = [c.strip().lower() for c in prefs.get("excluded_companies") or [] if c.strip()]
        self.interest_families = [i for i in prefs.get("interests") or [] if i]
        self.hide_closed = bool(prefs.get("hide_closed", True))
        auth = profile.get("work_auth") or {}
        self.needs_sponsorship = bool(auth.get("needs_sponsorship"))
        self.us_citizen = bool(auth.get("us_citizen"))
        edu = primary_education(profile)
        self.degree_level = edu.get("degree_level") or "Bachelor's"
        self.ignore_degree = bool(prefs.get("ignore_degree_filter"))
        self.skills = [s for s in all_skills(profile) if len(s) > 1]
        self.now = _now()

    # ------------------------------------------------------------------ filters
    def hard_filters(self, job: dict) -> list[str]:
        out: list[str] = []
        if self.hide_closed and not job.get("active"):
            out.append("Closed")
        terms = job.get("terms") or []
        if self.terms and not any(t.lower() in self.terms for t in terms):
            out.append(f"Term: {', '.join(terms) or 'unknown'}")
        spons = job.get("sponsorship") or ""
        if self.needs_sponsorship and spons in ("Does Not Offer Sponsorship", "U.S. Citizenship is Required"):
            out.append("No visa sponsorship")
        if not self.us_citizen and spons == "U.S. Citizenship is Required":
            out.append("Requires U.S. citizenship")
        degrees = job.get("degrees") or []
        if degrees and not self.ignore_degree and self.degree_level not in degrees:
            out.append(f"Degree: {'/'.join(degrees)}")
        company = job.get("company", "").lower()
        if any(c == company or c in company for c in self.excluded_cos):
            out.append("Excluded company")
        title = job.get("title", "")
        for kw in self.exclude_kw:
            if skills.title_has(title, kw):
                out.append(f"Excluded keyword: {kw}")
        if self.strict_location and self.locations:
            locs = [parse_location(loc) for loc in job.get("locations") or []]
            ok = any(location_matches(p, loc) for p in self.locations for loc in locs)
            if not ok and not (self.remote_ok and any(loc["remote"] for loc in locs)):
                out.append("Location")
        return out

    # ------------------------------------------------------------------ score
    def score(self, job: dict, ai_fit: int | None = None) -> Scored:
        reasons: list[dict] = []
        title = job.get("title", "")
        category = job.get("category") or "Other"

        # category (25)
        if self.categories:
            if category in self.categories:
                pts = 25 if self.categories.index(category) == 0 else 20
                reasons.append(_reason("category", category, pts))
        else:
            reasons.append(_reason("category", category, 10))

        # title vs interests / keywords / skills (30)
        title_pts = 0
        matched_families = []
        for fam in self.interest_families:
            kws = skills.ROLE_FAMILIES.get(fam, [fam])
            if any(skills.title_has(title, k) for k in kws):
                matched_families.append(fam)
        if matched_families:
            title_pts += 18 + 6 * (len(matched_families) - 1)
            reasons.append(_reason("title", "Title fits: " + ", ".join(matched_families), 0))
        kw_hits = [k for k in self.include_kw if skills.title_has(title, k)]
        if kw_hits:
            title_pts += 10 * len(kw_hits)
            reasons.append(_reason("keyword", "Keyword: " + ", ".join(kw_hits), 0))
        skill_hits = [s for s in self.skills if skills.title_has(title, s)]
        if skill_hits:
            title_pts += 6 * len(skill_hits)
            reasons.append(_reason("skill", "Your skills in title: " + ", ".join(skill_hits[:4]), 0))
        title_pts = min(title_pts, 30)
        if title_pts:
            # attribute the capped total to the first title-ish reason for display
            for r in reasons:
                if r["kind"] in ("title", "keyword", "skill"):
                    r["points"] = title_pts
                    break

        # location (15)
        locs = [parse_location(loc) for loc in job.get("locations") or []]
        if self.locations:
            hit = next((loc["raw"] for p in self.locations for loc in locs if location_matches(p, loc)), None)
            if hit:
                reasons.append(_reason("location", f"Location: {hit}", 15))
            elif self.remote_ok and any(loc["remote"] for loc in locs):
                reasons.append(_reason("location", "Remote", 12))
        else:
            reasons.append(_reason("location", "Any location", 7))

        # dream company (15)
        company = job.get("company", "").lower()
        if any(d == company or d in company for d in self.dream):
            reasons.append(_reason("company", "Dream company", 15))

        # freshness (10)
        posted = job.get("date_posted") or 0
        if posted:
            days = (self.now - posted) / 86400
            pts = 10 if days <= 1 else 8 if days <= 3 else 6 if days <= 7 else 3 if days <= 14 else 0
            if pts:
                reasons.append(_reason("fresh", "Posted today" if days <= 1 else f"Posted {int(days)}d ago", pts))

        # sponsorship bonus (5)
        if self.needs_sponsorship and job.get("sponsorship") == "Offers Sponsorship":
            reasons.append(_reason("sponsorship", "Offers sponsorship", 5))

        # penalties
        low = title.lower()
        if self.degree_level in ("Bachelor's", "Associate's"):
            if re.search(r"\bph\.?d\b|doctoral", low):
                reasons.append(_reason("penalty", "PhD-level title", -15))
            elif re.search(r"\bmaster'?s?\b|\bms\b|\bmba\b", low):
                reasons.append(_reason("penalty", "Graduate-level title", -10))
        if re.search(r"\b(senior|staff|principal|manager|director|lead)\b", low) and "intern" not in low:
            reasons.append(_reason("penalty", "Seniority mismatch", -10))

        total = max(0, min(100, sum(r["points"] for r in reasons)))
        if ai_fit is not None:
            total = round(0.5 * total + 0.5 * max(0, min(100, ai_fit)))
            reasons.append(_reason("ai", f"Posting fit: {ai_fit}", 0))
        return Scored(score=int(total), reasons=reasons)


def job_from_row(row) -> dict:
    d = dict(row)
    for f in ("terms", "locations", "degrees"):
        if isinstance(d.get(f), str):
            d[f] = json.loads(d[f])
    return d
