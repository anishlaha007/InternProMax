// Render a resume dict as a paper preview. When editable, bullets/summary can be edited in place.
import { h, add } from "./lib.js";

const url = (u) => (u || "").replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/$/, "");
const dates = (e) => [e.start, e.end].filter(Boolean).join(" – ");

export function renderResume(resume, { editable = false } = {}) {
  const r = structuredClone(resume || {});
  const p = r.personal || {};
  const ed = (tag, text, bind, attrs = {}) => {
    const el = h(tag, { ...attrs, contenteditable: editable ? "true" : null, spellcheck: editable ? "true" : null }, text);
    if (editable) el.addEventListener("input", () => bind(el.innerText.trim()));
    return el;
  };
  const bullets = (entry) => h("ul", {}, (entry.bullets || []).map((b, i) =>
    ed("li", b, (v) => { entry.bullets[i] = v; })));

  const paper = h("div", { class: "resume-paper" },
    h("div", { class: "r-name" }, p.name || "Your Name"),
    h("div", { class: "r-contact" }, [p.location, p.phone, p.email, url(p.linkedin), url(p.github), url(p.website)].filter(Boolean).join("  |  ")),
  );

  if (r.summary) {
    add(paper, h("div", { class: "r-sec" }, "Summary"), ed("div", r.summary, (v) => { r.summary = v; }));
  }
  const edu = (r.education || []).filter((e) => e.school);
  if (edu.length) {
    add(paper, h("div", { class: "r-sec" }, "Education"));
    for (const e of edu) {
      const grad = [e.grad_month, e.grad_year].filter(Boolean).join(" ");
      let degree = e.degree || "";
      if (e.major) degree = degree ? `${degree} in ${e.major}` : e.major;
      if (e.minor) degree += `, Minor in ${e.minor}`;
      if (e.gpa) degree += `  |  GPA: ${e.gpa}`;
      add(paper,
        h("div", { class: "r-line" }, h("span", { class: "r-b" }, e.school), h("span", {}, grad ? `Expected ${grad}` : "")),
        h("div", { class: "r-line" }, h("span", { class: "r-i" }, degree), h("span", { class: "r-i" }, e.location || "")),
        (e.coursework || []).length ? h("div", {}, h("span", { class: "r-b" }, "Relevant Coursework: "), e.coursework.join(", ")) : null,
      );
    }
  }
  const entries = (title, list) => {
    list = (list || []).filter((e) => e.company || e.title);
    if (!list.length) return;
    add(paper, h("div", { class: "r-sec" }, title));
    for (const e of list) {
      add(paper,
        h("div", { class: "r-line" }, h("span", { class: "r-b" }, e.company || e.title), h("span", {}, dates(e))),
        e.company && (e.title || e.location) ? h("div", { class: "r-line" }, h("span", { class: "r-i" }, e.title || ""), h("span", { class: "r-i" }, e.location || "")) : null,
        bullets(e),
      );
    }
  };
  entries("Experience", r.experience);
  const projects = (r.projects || []).filter((x) => x.name);
  if (projects.length) {
    add(paper, h("div", { class: "r-sec" }, "Projects"));
    for (const pr of projects) {
      add(paper,
        h("div", { class: "r-line" }, h("span", {}, h("span", { class: "r-b" }, pr.name),
          (pr.tech || []).length ? h("span", { class: "r-i" }, `  |  ${pr.tech.join(", ")}`) : null,
          pr.link ? h("span", {}, `  |  ${url(pr.link)}`) : null), h("span", {}, dates(pr))),
        bullets(pr),
      );
    }
  }
  entries("Leadership & Activities", r.activities);
  const groups = (r.skills || []).filter((g) => (g.items || []).length);
  if (groups.length) {
    add(paper, h("div", { class: "r-sec" }, "Skills"),
      ...groups.map((g) => h("div", {}, h("span", { class: "r-b" }, `${g.category || "Skills"}: `), g.items.join(", "))));
  }
  const awards = (r.awards || []).filter((a) => a.title);
  if (awards.length) {
    add(paper, h("div", { class: "r-sec" }, "Awards"), h("ul", {}, awards.map((a) => h("li", {}, a.title + (a.detail ? ` – ${a.detail}` : "")))));
  }
  paper.getData = () => r;
  return paper;
}
