"""Render a (tailored) resume dict to a clean, single-column, ATS-friendly PDF."""

from __future__ import annotations

import os
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_CANDIDATES = [
    # (regular, bold, italic)
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Italic.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\ariali.ttf"),
]

_ASCII = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
                        "\u2022": "-", "\u2026": "...", "\u00a0": " ", "\u2192": "->", "\u2212": "-"})


def _find_fonts() -> tuple[str, str, str] | None:
    custom = os.environ.get("IPM_RESUME_FONT_DIR")
    cands = list(FONT_CANDIDATES)
    if custom:
        d = Path(custom)
        cands.insert(0, (str(d / "regular.ttf"), str(d / "bold.ttf"), str(d / "italic.ttf")))
    for trio in cands:
        if all(Path(p).exists() for p in trio):
            return trio
    return None


class _Doc:
    def __init__(self, size: float, gap: float):
        self.pdf = FPDF(format="letter", unit="pt")
        self.pdf.set_margins(40, 34, 40)
        self.pdf.set_auto_page_break(True, margin=34)
        self.pdf.add_page()
        self.size = size
        self.gap = gap
        fonts = _find_fonts()
        if fonts:
            self.pdf.add_font("Body", "", fonts[0])
            self.pdf.add_font("Body", "B", fonts[1])
            self.pdf.add_font("Body", "I", fonts[2])
            self.family, self.unicode = "Body", True
        else:
            self.family, self.unicode = "Helvetica", False
        self.width = self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def t(self, s) -> str:
        s = str(s or "").strip()
        if self.unicode:
            return s
        return s.translate(_ASCII).encode("latin-1", "replace").decode("latin-1")

    def font(self, style: str = "", size: float | None = None) -> None:
        self.pdf.set_font(self.family, style, size or self.size)

    def lh(self, size: float | None = None) -> float:
        return (size or self.size) * 1.22

    def centered(self, text: str, style: str = "", size: float | None = None) -> None:
        self.font(style, size)
        self.pdf.cell(self.width, self.lh(size), self.t(text), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def left_right(self, left: str, right: str, lstyle: str = "B", rstyle: str = "", size: float | None = None) -> None:
        pdf = self.pdf
        self.font(rstyle, size)
        rw = pdf.get_string_width(self.t(right)) + 2 if right else 0
        self.font(lstyle, size)
        x, y = pdf.get_x(), pdf.get_y()
        left = self.fit(left, self.width - rw - 8)
        pdf.cell(self.width - rw, self.lh(size), left, new_x=XPos.RIGHT, new_y=YPos.TOP)
        if right:
            self.font(rstyle, size)
            pdf.cell(rw, self.lh(size), self.t(right), align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_xy(x, y + self.lh(size))

    def fit(self, text: str, width: float) -> str:
        """Trim text (with an ellipsis) to the given width in the current font."""
        text = self.t(text)
        if self.pdf.get_string_width(text) <= width:
            return text
        dots = "..."
        while text and self.pdf.get_string_width(text + dots) > width:
            text = text[:-1]
        return text.rstrip(" |,") + dots

    def section(self, title: str) -> None:
        pdf = self.pdf
        pdf.ln(self.gap)
        self.font("B", self.size + 1)
        pdf.cell(self.width, self.lh(self.size + 1), self.t(title.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        y = pdf.get_y()
        pdf.set_line_width(0.6)
        pdf.line(pdf.l_margin, y, pdf.l_margin + self.width, y)
        pdf.ln(2.5)

    def bullets(self, items: list[str]) -> None:
        pdf = self.pdf
        indent = 11
        for b in items:
            if not str(b or "").strip():
                continue
            self.font("")
            y = pdf.get_y()
            pdf.set_fill_color(30, 30, 30)
            pdf.ellipse(pdf.l_margin + 3, y + self.lh() / 2 - 1.3, 2.6, 2.6, style="F")
            pdf.set_x(pdf.l_margin + indent)
            pdf.multi_cell(self.width - indent, self.lh(), self.t(b), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def label_line(self, label: str, text: str) -> None:
        pdf = self.pdf
        self.font("B")
        lw = pdf.get_string_width(self.t(label)) + 3
        x = pdf.get_x()
        pdf.cell(lw, self.lh(), self.t(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.font("")
        pdf.multi_cell(self.width - lw, self.lh(), self.t(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(x)


def _dates(e: dict) -> str:
    start, end = (e.get("start") or "").strip(), (e.get("end") or "").strip()
    if start and end:
        return f"{start} - {end}"
    return start or end


def _display_url(u: str) -> str:
    return u.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def _render(resume: dict, size: float, gap: float) -> _Doc:
    d = _Doc(size, gap)
    p = resume.get("personal") or {}
    d.centered(p.get("name") or "Your Name", "B", size + 8)
    contact = [p.get("location"), p.get("phone"), p.get("email"), _display_url(p.get("linkedin") or ""),
               _display_url(p.get("github") or ""), _display_url(p.get("website") or "")]
    d.centered("  |  ".join(c for c in contact if c), "", size - 0.5)

    if (resume.get("summary") or "").strip():
        d.section("Summary")
        d.font("")
        d.pdf.multi_cell(d.width, d.lh(), d.t(resume["summary"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    edu = [e for e in resume.get("education") or [] if e.get("school")]
    if edu:
        d.section("Education")
        for e in edu:
            grad = " ".join(x for x in (e.get("grad_month"), e.get("grad_year")) if x)
            d.left_right(e.get("school", ""), (f"Expected {grad}" if grad else ""), "B", "")
            degree = e.get("degree") or ""
            if e.get("major"):
                degree = f"{degree} in {e['major']}" if degree else e["major"]
            if e.get("minor"):
                degree += f", Minor in {e['minor']}"
            if e.get("gpa"):
                degree += f"  |  GPA: {e['gpa']}"
            d.left_right(degree, e.get("location", ""), "I", "I")
            if e.get("coursework"):
                d.label_line("Relevant Coursework: ", ", ".join(e["coursework"]))
            d.bullets(e.get("highlights") or [])
            d.pdf.ln(1.5)

    def entries(title: str, items: list[dict]) -> None:
        items = [e for e in items or [] if e.get("company") or e.get("title")]
        if not items:
            return
        d.section(title)
        for e in items:
            d.left_right(e.get("company") or e.get("title", ""), _dates(e), "B", "")
            if e.get("company") and (e.get("title") or e.get("location")):
                d.left_right(e.get("title", ""), e.get("location", ""), "I", "I")
            d.bullets(e.get("bullets") or [])
            d.pdf.ln(2)

    entries("Experience", resume.get("experience"))

    projects = [pr for pr in resume.get("projects") or [] if pr.get("name")]
    if projects:
        d.section("Projects")
        for pr in projects:
            left = pr["name"]
            if pr.get("tech"):
                left += "  |  " + ", ".join(pr["tech"])
            if pr.get("link"):
                d.font("")
                room = d.width - d.pdf.get_string_width(d.t(_dates(pr))) - 10
                d.font("B")
                with_link = left + "  |  " + _display_url(pr["link"])
                if d.pdf.get_string_width(d.t(with_link)) <= room:
                    left = with_link
            d.left_right(left, _dates(pr), "B", "")
            if pr.get("role"):
                d.left_right(pr["role"], "", "I", "")
            d.bullets(pr.get("bullets") or [])
            d.pdf.ln(2)

    entries("Leadership & Activities", resume.get("activities"))

    groups = [g for g in resume.get("skills") or [] if g.get("items")]
    if groups:
        d.section("Skills")
        for g in groups:
            d.label_line(f"{g.get('category') or 'Skills'}: ", ", ".join(g["items"]))

    awards = [a for a in resume.get("awards") or [] if a.get("title")]
    if awards:
        d.section("Awards")
        d.bullets([a["title"] + (f" - {a['detail']}" if a.get("detail") else "") for a in awards])
    return d


def render(resume: dict) -> bytes:
    """Try progressively tighter layouts until the resume fits on one page."""
    doc = None
    for size, gap in ((10.5, 6), (10, 5), (9.5, 4), (9, 3)):
        doc = _render(resume, size, gap)
        if doc.pdf.page_no() == 1:
            break
    return bytes(doc.pdf.output())
