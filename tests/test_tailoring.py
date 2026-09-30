"""Posting analysis, resume tailoring (rules + AI guardrails), PDF output, and the Claude call shape."""

import io
import types

import pytest
from pypdf import PdfReader

from internpromax import ai, analysis, resume_pdf, tailor


def test_rules_analysis_extracts_requirements(profile_data, posting_text):
    a = analysis.analyze(posting_text, profile_data, {"title": "Software Engineer Intern, Backend"})
    assert {"Go", "Java", "Python"} <= set(a["required_skills"])
    assert {"Docker", "Kubernetes", "AWS"} <= set(a["preferred_skills"])
    assert "Kubernetes" in a["missing_skills"] and "Python" in a["matched_skills"]
    assert "2027" in a["constraints"]["graduation"] and "sponsor" in a["constraints"]["work_authorization"]
    assert any("projects outside of class" in t for t in a["project_themes"])
    assert a["responsibilities"] and 0 < a["fit_score"] <= 100
    assert a["summary"].startswith("Our Payments Infrastructure team")


def test_grad_year_mismatch_lowers_fit(profile_data, posting_text):
    base = analysis.analyze(posting_text, profile_data)["fit_score"]
    profile_data["education"][0]["grad_year"] = "2030"
    later = analysis.analyze(posting_text, profile_data)
    assert later["fit_score"] < base
    assert any("graduate 2030" in r for r in later["fit_reasons"])


def test_rules_tailoring_reorders_without_inventing(profile_data, posting_text):
    a = analysis.analyze(posting_text, profile_data)
    out, changes, warnings = tailor.tailor_rules(profile_data, a)
    assert out["projects"][0]["name"] == "RaftKV"  # Go + distributed systems project leads for a backend posting
    assert out["experience"][0]["bullets"][0].startswith("Designed REST APIs")
    assert out["skills"][0]["items"][:2] == ["Python", "Java"]
    master_bullets = {b for e in profile_data["resume"]["experience"] + profile_data["resume"]["projects"] for b in e["bullets"]}
    tailored_bullets = {b for e in out["experience"] + out["projects"] for b in e["bullets"]}
    assert tailored_bullets <= master_bullets
    assert changes and warnings == []


def test_ai_output_is_checked_against_master(profile_data):
    raw = {
        "summary": "Backend-focused CS student",
        "experience": [
            {"source_id": "exp-1", "bullets": [
                "Designed Python REST APIs on PostgreSQL, cutting page load time by 35%",
                "Scaled the scheduler to 10,000 users with Kubernetes",  # invents a number
            ]},
            {"source_id": "exp-999", "bullets": ["Made-up job"]},
        ],
        "projects": [{"source_id": "pro-2", "tech": ["Go", "gRPC", "Rust"], "bullets": ["Built a Raft-replicated key-value store in Go"]},
                     {"source_id": "pro-404", "tech": [], "bullets": ["fake"]}],
        "activities": [],
        "skills": [{"category": "Languages", "items": ["Go", "Python", "Rust"]}],
        "coursework": ["Distributed Systems", "Underwater Basket Weaving"],
        "changes": ["Led with backend work"],
    }
    out, changes, warnings = tailor.assemble_ai(profile_data, raw)
    exp = {e["company"]: e for e in out["experience"]}
    assert set(exp) == {"Acme Health", "Pitt CS Department"}  # unknown dropped, omitted kept
    assert "10,000" not in " ".join(exp["Acme Health"]["bullets"])
    assert any("10,000" in w for w in warnings)
    assert [p["name"] for p in out["projects"]] == ["RaftKV"]
    assert "Rust" not in out["projects"][0]["tech"]
    all_skills = [s for g in out["skills"] for s in g["items"]]
    assert "Rust" not in all_skills and "Java" in all_skills  # nothing invented, nothing lost
    assert out["education"][0]["coursework"] == ["Distributed Systems"]
    assert out["summary"] == ""  # master resume has no summary
    assert changes == ["Led with backend work"]


def test_pdf_is_one_page_and_contains_content(profile_data, posting_text):
    a = analysis.analyze(posting_text, profile_data)
    out, _, _ = tailor.tailor_rules(profile_data, a)
    pdf = resume_pdf.render(out)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Alex Rivera" in text and "RaftKV" in text and "University of Pittsburgh" in text


# ------------------------------------------------------------------ Claude request shape (no network)

class _FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def _fake_client(calls, message):
    def stream(**kwargs):
        calls.append(kwargs)
        return _FakeStream(message)

    return types.SimpleNamespace(
        beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream)),
        messages=types.SimpleNamespace(stream=stream),
    )


def _msg(text, stop="end_turn"):
    return types.SimpleNamespace(stop_reason=stop, content=[types.SimpleNamespace(type="text", text=text)])


def test_structured_call_shape(monkeypatch):
    import anthropic

    calls = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake_client(calls, _msg('{"answer": "hi"}')))
    settings = {"anthropic_api_key": "sk-test", "ai_model": "claude-opus-5-5", "ai_effort": "medium"}
    assert ai.structured(settings, "sys", "prompt", ai.ANSWER_SCHEMA) == {"answer": "hi"}
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["effort"] == "medium"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert "thinking" not in kw and "temperature" not in kw

    calls.clear()
    ai.structured({**settings, "ai_model": "claude-haiku-4-5"}, "sys", "p", ai.ANSWER_SCHEMA)
    assert "effort" not in calls[0]["output_config"] and "fallbacks" not in calls[0]


def test_structured_call_handles_refusal(monkeypatch):
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake_client([], _msg("", stop="refusal")))
    with pytest.raises(ai.AIError):
        ai.structured({"anthropic_api_key": "sk-test"}, "s", "p", ai.ANSWER_SCHEMA)
    with pytest.raises(ai.AIUnavailable):
        ai.structured({}, "s", "p", ai.ANSWER_SCHEMA)


def test_schemas_are_strict():
    def walk(schema):
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(schema["properties"])
            for sub in schema["properties"].values():
                walk(sub)
        elif schema.get("type") == "array":
            walk(schema["items"])

    for s in (ai.ANALYSIS_SCHEMA, ai.TAILOR_SCHEMA, ai.ANSWER_SCHEMA, ai.EMAIL_SCHEMA, ai.RESUME_SCHEMA):
        walk(s)
