"""Fetch the full text of a job posting (ATS APIs first, then JSON-LD, then page text)."""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser

import httpx

from . import ats

MIN_USEFUL_CHARS = 300

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
          "article", "header", "footer", "table", "blockquote", "dd", "dt", "hr"}
_SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head", "nav", "footer", "form", "button"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self, skip_layout: bool = True):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip_depth = 0
        self.skip = _SKIP if skip_layout else {"script", "style", "noscript", "svg", "template"}

    def handle_starttag(self, tag, attrs):
        if tag in self.skip:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in _BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("• ")
        if tag in _HEADINGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.skip:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(data)


def html_to_text(markup: str, skip_layout: bool = False) -> str:
    if not markup:
        return ""
    parser = _TextExtractor(skip_layout=skip_layout)
    parser.feed(markup)
    parser.close()
    return clean_text("".join(parser.out))


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln or ln == "•":
            blank = True
            continue
        if blank and out:
            out.append("")
        out.append(ln)
        blank = False
    return "\n".join(out).strip()


def _client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(
        timeout=25,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; InternProMax/0.1)", "Accept-Language": "en-US,en;q=0.9"},
    ), True


# ------------------------------------------------------------------ ATS fetchers

def _greenhouse(info: dict, c: httpx.Client) -> str | None:
    if not info.get("board") or not info.get("job_id"):
        return None
    r = c.get(f"https://boards-api.greenhouse.io/v1/boards/{info['board']}/jobs/{info['job_id']}")
    if r.status_code != 200:
        return None
    data = r.json()
    return html_to_text(html.unescape(data.get("content") or ""))


def _lever(info: dict, c: httpx.Client) -> str | None:
    if not info.get("company") or not info.get("job_id"):
        return None
    r = c.get(f"https://api.lever.co/v0/postings/{info['company']}/{info['job_id']}")
    if r.status_code != 200:
        return None
    d = r.json()
    parts = [d.get("descriptionPlain") or html_to_text(d.get("description") or "")]
    for lst in d.get("lists") or []:
        parts.append("\n" + (lst.get("text") or "") + "\n" + html_to_text(lst.get("content") or ""))
    parts.append(d.get("additionalPlain") or html_to_text(d.get("additional") or ""))
    return clean_text("\n".join(p for p in parts if p))


def _ashby(info: dict, c: httpx.Client) -> str | None:
    if not info.get("org") or not info.get("job_id"):
        return None
    r = c.get(f"https://api.ashbyhq.com/posting-api/job-board/{info['org']}")
    if r.status_code != 200:
        return None
    for job in r.json().get("jobs") or []:
        if str(job.get("id", "")).lower() == info["job_id"]:
            return job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
    return None


def _workday(info: dict, url: str, c: httpx.Client) -> str | None:
    if not info.get("tenant") or not info.get("site") or not info.get("job_path"):
        return None
    host = re.match(r"https?://([^/]+)", url).group(1)
    api = f"https://{host}/wday/cxs/{info['tenant']}/{info['site']}/job/{info['job_path']}"
    r = c.get(api, headers={"Accept": "application/json"})
    if r.status_code != 200:
        return None
    posting = (r.json() or {}).get("jobPostingInfo") or {}
    return html_to_text(posting.get("jobDescription") or "")


def _smartrecruiters(info: dict, c: httpx.Client) -> str | None:
    if not info.get("company") or not info.get("job_id"):
        return None
    r = c.get(f"https://api.smartrecruiters.com/v1/companies/{info['company']}/postings/{info['job_id']}")
    if r.status_code != 200:
        return None
    sections = ((r.json() or {}).get("jobAd") or {}).get("sections") or {}
    parts = []
    for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
        sec = sections.get(key) or {}
        if sec.get("text"):
            parts.append((sec.get("title") or "") + "\n" + html_to_text(sec["text"]))
    return clean_text("\n\n".join(parts))


# ------------------------------------------------------------------ generic HTML

def extract_from_html(markup: str) -> tuple[str | None, str]:
    """(text, method) from a posting page: JSON-LD JobPosting first, then readable body text."""
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', markup, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _iter_nodes(data):
            if isinstance(node, dict) and "JobPosting" in str(node.get("@type", "")):
                desc = html_to_text(html.unescape(node.get("description") or ""))
                if len(desc) >= MIN_USEFUL_CHARS // 2:
                    title = node.get("title")
                    return (f"{title}\n\n{desc}" if title else desc), "json-ld"
    main = re.search(r"<(main|article)\b.*?</\1>", markup, re.S | re.I)
    text = html_to_text(main.group(0) if main else markup, skip_layout=True)
    return (text or None), "page-text"


def _iter_nodes(data):
    if isinstance(data, list):
        for x in data:
            yield from _iter_nodes(x)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])


def fetch(url: str, client: httpx.Client | None = None) -> dict:
    """Returns {'text', 'method', 'error'}; text is None if we couldn't get a useful description."""
    info = ats.parse(url)
    c, own = _client(client)
    errors: list[str] = []
    try:
        fetchers = {
            "greenhouse": lambda: _greenhouse(info, c),
            "lever": lambda: _lever(info, c),
            "ashby": lambda: _ashby(info, c),
            "workday": lambda: _workday(info, url, c),
            "smartrecruiters": lambda: _smartrecruiters(info, c),
        }
        if info.get("ats") in fetchers:
            try:
                text = fetchers[info["ats"]]()
                if text and len(text) >= MIN_USEFUL_CHARS:
                    return {"text": text, "method": f"{info['ats']}-api", "error": None}
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                errors.append(f"{info['ats']} api: {exc}")
        try:
            r = c.get(url)
            if r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
                text, method = extract_from_html(r.text)
                if text and len(text) >= MIN_USEFUL_CHARS:
                    return {"text": text, "method": method, "error": None}
                errors.append("page has little server-rendered text (needs the browser extension to capture)")
            else:
                errors.append(f"HTTP {r.status_code}")
        except httpx.HTTPError as exc:
            errors.append(str(exc))
        return {"text": None, "method": None, "error": "; ".join(errors) or "no description found"}
    finally:
        if own:
            c.close()

