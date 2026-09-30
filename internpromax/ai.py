"""Optional Claude integration. Everything here degrades gracefully when no API key is set."""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

# Models that accept server-side refusal fallbacks ("default" routing) on the Claude API.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
NO_EFFORT_MODELS = {"claude-haiku-4-5"}
MODEL_CHOICES = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"]


class AIUnavailable(RuntimeError):
    """No API key configured or the SDK isn't installed."""


class AIError(RuntimeError):
    """The model call failed or returned something unusable."""


def api_key(settings: dict) -> str | None:
    return (settings.get("anthropic_api_key") or "").strip() or os.environ.get("ANTHROPIC_API_KEY") or None


def available(settings: dict) -> bool:
    if not api_key(settings):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def structured(settings: dict, system: str, prompt: str, schema: dict, max_tokens: int = 32000) -> dict:
    """One Claude call constrained to a JSON schema. Returns the parsed object."""
    key = api_key(settings)
    if not key:
        raise AIUnavailable("Set an Anthropic API key in Settings (or ANTHROPIC_API_KEY) to enable AI features.")
    try:
        import anthropic
    except ImportError as exc:
        raise AIUnavailable("pip install anthropic to enable AI features") from exc

    model = settings.get("ai_model") or "claude-opus-5-5"
    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if model not in NO_EFFORT_MODELS:
        output_config["effort"] = settings.get("ai_effort") or "medium"
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config=output_config,
    )
    client = anthropic.Anthropic(api_key=key, timeout=600.0, max_retries=2)
    try:
        if model in FALLBACK_MODELS:
            with client.beta.messages.stream(
                **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            ) as stream:
                message = stream.get_final_message()
        else:
            with client.messages.stream(**kwargs) as stream:
                message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise AIError("Anthropic API key was rejected") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Rate limited by the Anthropic API; try again shortly") from exc
    except anthropic.BadRequestError as exc:
        raise AIError(f"Bad request: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Could not reach the Anthropic API") from exc

    if message.stop_reason == "refusal":
        raise AIError("The model declined this request")
    if message.stop_reason == "max_tokens":
        raise AIError("The model ran out of output tokens")
    text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), None)
    if not text:
        raise AIError("Empty response from the model")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError("Model returned invalid JSON") from exc


# ------------------------------------------------------------------ schemas

def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}

ANALYSIS_SCHEMA = _obj({
    "summary": _STR,
    "role_focus": _STR,
    "required_skills": _STRS,
    "preferred_skills": _STRS,
    "responsibilities": _STRS,
    "project_themes": _STRS,
    "keywords": _STRS,
    "constraints": _obj({"graduation": _STR, "gpa": _STR, "degree": _STR, "work_authorization": _STR, "other": _STRS}),
    "matched_skills": _STRS,
    "missing_skills": _STRS,
    "fit_score": {"type": "integer"},
    "fit_reasons": _STRS,
    "gaps_advice": _STRS,
    "resume_focus": _STRS,
})

_ENTRY = _obj({"source_id": _STR, "bullets": _STRS})
_PROJECT = _obj({"source_id": _STR, "tech": _STRS, "bullets": _STRS})
TAILOR_SCHEMA = _obj({
    "summary": _STR,
    "experience": {"type": "array", "items": _ENTRY},
    "projects": {"type": "array", "items": _PROJECT},
    "activities": {"type": "array", "items": _ENTRY},
    "skills": {"type": "array", "items": _obj({"category": _STR, "items": _STRS})},
    "coursework": _STRS,
    "changes": _STRS,
})

ANSWER_SCHEMA = _obj({"answer": _STR})

EMAIL_SCHEMA = _obj({
    "status": {"type": "string", "enum": ["applied", "oa", "interviewing", "offer", "rejected", "none"]},
    "company": _STR,
    "confidence": {"type": "number"},
    "reason": _STR,
})

_R_ENTRY = _obj({"company": _STR, "title": _STR, "location": _STR, "start": _STR, "end": _STR, "bullets": _STRS})
RESUME_SCHEMA = _obj({
    "personal": _obj({"first_name": _STR, "last_name": _STR, "email": _STR, "phone": _STR, "linkedin": _STR,
                      "github": _STR, "website": _STR, "city": _STR, "state": _STR}),
    "education": {"type": "array", "items": _obj({
        "school": _STR, "degree": _STR, "degree_level": _STR, "major": _STR, "minor": _STR, "gpa": _STR,
        "grad_month": _STR, "grad_year": _STR, "location": _STR, "coursework": _STRS, "highlights": _STRS})},
    "summary": _STR,
    "experience": {"type": "array", "items": _R_ENTRY},
    "projects": {"type": "array", "items": _obj({"name": _STR, "role": _STR, "link": _STR, "start": _STR,
                                                 "end": _STR, "tech": _STRS, "bullets": _STRS})},
    "activities": {"type": "array", "items": _R_ENTRY},
    "skills": {"type": "array", "items": _obj({"category": _STR, "items": _STRS})},
    "awards": {"type": "array", "items": _obj({"title": _STR, "detail": _STR})},
})

SYSTEM = (
    "You help a university student apply to internships and co-ops. You read job postings like an experienced "
    "technical recruiter and you write resumes like a careful career coach. You are precise, concrete and honest: "
    "you never invent experience, employers, projects, skills, metrics or dates the student does not have."
)


def analyze_posting(settings: dict, job: dict, description: str, candidate: str) -> dict:
    prompt = f"""Analyze this job posting for the candidate below.

<job company="{job.get('company', '')}" title="{job.get('title', '')}" locations="{', '.join(job.get('locations') or [])}">
{description}
</job>

<candidate>
{candidate}
</candidate>

Return:
- summary: 2-3 sentences on what the team does and what this intern will actually work on.
- role_focus: a short label (e.g. "Backend / distributed systems").
- required_skills / preferred_skills: concrete skills, tools, languages and knowledge areas, split by how the posting frames them. Use common canonical names ("Python", "Kubernetes", "Distributed Systems").
- responsibilities: the main things the intern will do (max 8, short).
- project_themes: the kinds of projects or experience that would make an applicant stand out, phrased as things a student could have built or done (e.g. "Built and deployed a full-stack web app with real users"). Infer from the posting's language; max 6.
- keywords: important terms an ATS or recruiter would scan for (max 20).
- constraints: graduation window, GPA, degree/major, work authorization/citizenship/clearance, and any other hard requirements; empty string when not stated.
- matched_skills / missing_skills: compare the posting's skills with what the candidate actually shows evidence of.
- fit_score: 0-100, how strong this candidate is for this posting relative to typical applicants.
- fit_reasons: 2-5 short bullets justifying the score.
- gaps_advice: specific, honest suggestions for closing or framing the gaps (max 5).
- resume_focus: which of the candidate's experiences/projects (by name) best match and should be emphasized."""
    return structured(settings, SYSTEM, prompt, ANALYSIS_SCHEMA)


def tailor_resume(settings: dict, job: dict, analysis: dict, master: dict) -> dict:
    prompt = f"""Tailor the candidate's resume for this posting.

<job company="{job.get('company', '')}" title="{job.get('title', '')}">
{json.dumps({k: analysis.get(k) for k in ('summary', 'required_skills', 'preferred_skills', 'responsibilities', 'project_themes', 'keywords')}, indent=1)}
</job>

<master_resume>
{json.dumps(master, indent=1)}
</master_resume>

Rules:
1. Only use entries that exist in the master resume. Reference each by its exact "source_id". You may omit weak projects/activities (keep all work experience) and reorder projects/activities by relevance.
2. Rewrite bullets to foreground what this posting wants, mirroring its language where it is truthful. Keep every fact faithful to the original bullet: do not add numbers, tools, scope, outcomes or responsibilities that are not already stated. Keep 2-5 bullets per entry, one line (~25 words) each, strong action verbs.
3. skills: regroup/reorder so the posting's skills that the candidate has come first. Only list skills present in the master resume.
4. coursework: the most relevant courses from the master resume (max 6), or empty.
5. summary: one or two lines targeted at this role if the master resume has a summary, otherwise an empty string.
6. changes: short notes for the candidate describing what you emphasized and why."""
    return structured(settings, SYSTEM, prompt, TAILOR_SCHEMA)


def draft_answer(settings: dict, question: str, job: dict, analysis: dict | None, candidate: str, max_words: int) -> str:
    prompt = f"""Draft the candidate's answer to this application question.

<question>{question}</question>
<job company="{job.get('company', '')}" title="{job.get('title', '')}">
{json.dumps(analysis or {}, indent=1)[:6000]}
</job>
<candidate>
{candidate}
</candidate>

Write in first person, specific and genuine, grounded only in the candidate's real experience. No clichés, no
flattery, no placeholders. Aim for at most {max_words} words."""
    return structured(settings, SYSTEM, prompt, ANSWER_SCHEMA, max_tokens=8000)["answer"]


def classify_email(settings: dict, sender: str, subject: str, body: str, companies: list[str]) -> dict:
    prompt = f"""Classify this email about a job application.

<email from="{sender}" subject="{subject}">
{body[:8000]}
</email>

Companies the candidate has applied to: {', '.join(companies[:200])}

status: applied (application received confirmation), oa (online assessment / coding challenge), interviewing
(interview invite or scheduling), offer, rejected, or none (not about an application).
company: which of the listed companies this is about ("" if unclear). confidence: 0-1."""
    return structured(settings, SYSTEM, prompt, EMAIL_SCHEMA, max_tokens=4000)


def parse_resume(settings: dict, text: str) -> dict:
    prompt = f"""Convert this resume into structured JSON. Copy wording faithfully; do not embellish.
Dates as written (e.g. "May 2025"). degree_level is one of Associate's, Bachelor's, Master's, MBA, PhD.
Use "" or [] for anything absent.

<resume>
{text}
</resume>"""
    return structured(settings, SYSTEM, prompt, RESUME_SCHEMA)
