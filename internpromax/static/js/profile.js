// Profile: autofill data, preferences, master resume, answer bank.
import { h, clear, api, guard, toast, tagInput, field } from "./lib.js";

const MONTHS = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const EEO = {
  gender: ["Male", "Female", "Non-binary", "Decline to self-identify"],
  race: ["American Indian or Alaska Native", "Asian", "Black or African American", "Hispanic or Latino",
    "Native Hawaiian or Other Pacific Islander", "White", "Two or More Races", "Decline to self-identify"],
  hispanic: ["Yes", "No", "Decline to self-identify"],
  veteran: ["I am not a protected veteran", "I identify as one or more of the classifications of protected veteran", "I don't wish to answer"],
  disability: ["No, I do not have a disability", "Yes, I have a disability (or previously had a disability)", "I don't wish to answer"],
  lgbtq: ["Yes", "No", "Decline to self-identify"],
};
const LOCATION_SUGGESTIONS = ["Remote", "Bay Area", "NYC", "Seattle area", "Boston", "Los Angeles", "Austin", "Chicago", "CA", "NY", "WA", "TX", "USA", "Canada", "UK"];

let tab = "basics";

export async function renderProfile(main, refreshNav) {
  const [data, meta] = await Promise.all([guard(() => api.get("/api/profile")), guard(() => api.get("/api/meta"))]);
  if (!data || !meta) return;
  const P = structuredClone(data.profile);
  let collectors = [];
  let scope = null; // collectors of the list editor currently rendering
  const flush = () => { collectors.forEach((c) => c()); collectors = []; };

  // ---- binders (mutate the working copy P)
  const text = (obj, key, attrs = {}) => {
    const el = h("input", { type: "text", ...attrs, value: obj[key] ?? "" });
    el.addEventListener("input", () => { obj[key] = el.value; });
    return el;
  };
  const area = (obj, key, attrs = {}) => {
    const el = h("textarea", { ...attrs, value: obj[key] ?? "" });
    el.addEventListener("input", () => { obj[key] = el.value; });
    return el;
  };
  const lines = (obj, key, attrs = {}) => {
    const el = h("textarea", { ...attrs, value: (obj[key] || []).join("\n") });
    el.addEventListener("input", () => { obj[key] = el.value.split("\n").map((s) => s.trim()).filter(Boolean); });
    return el;
  };
  const check = (obj, key, label) => {
    const el = h("input", { type: "checkbox", checked: !!obj[key] });
    el.addEventListener("change", () => { obj[key] = el.checked; });
    return h("label", { class: "check" }, el, label);
  };
  const select = (obj, key, options) => {
    const opts = options.includes(obj[key]) || !obj[key] ? options : [obj[key], ...options];
    const el = h("select", {}, opts.map((o) => h("option", { value: o, selected: o === obj[key] }, o || "—")));
    el.addEventListener("change", () => { obj[key] = el.value; });
    return el;
  };
  const tags = (obj, key, opts) => {
    const t = tagInput(obj[key] || [], opts);
    (scope || collectors).push(() => { obj[key] = t.getValue(); });
    return t;
  };
  const multi = (obj, key, options) => {
    const set = new Set(obj[key] || []);
    return h("div", { class: "check-grid" }, options.map((o) => {
      const [value, label] = Array.isArray(o) ? o : [o, o];
      const el = h("input", { type: "checkbox", checked: set.has(value) });
      el.addEventListener("change", () => {
        if (el.checked) set.add(value); else set.delete(value);
        obj[key] = [...(obj[key] || []).filter((x) => set.has(x)), ...[...set].filter((x) => !(obj[key] || []).includes(x))];
      });
      return h("label", { class: "check" }, el, label);
    }));
  };

  function listEditor(arr, fields, { add, label, empty }) {
    const wrap = h("div", { class: "editor-list" });
    const local = [];
    collectors.push(() => local.forEach((c) => c()));
    const render = () => {
      local.forEach((c) => c());
      local.length = 0;
      const prev = scope;
      scope = local;
      try { build(); } finally { scope = prev; }
    };
    const build = () => {
      clear(wrap,
        arr.length ? null : h("div", { class: "muted small" }, empty),
        arr.map((item, i) => h("div", { class: "editor-item" },
          h("div", { class: "row between" }, h("b", { class: "small" }, label(item) || "New entry"),
            h("div", { class: "row", style: { gap: "2px" } },
              h("button", { class: "btn btn-ghost btn-sm btn-icon", type: "button", title: "Move up", "aria-label": "Move up", disabled: i === 0, onclick: () => { [arr[i - 1], arr[i]] = [arr[i], arr[i - 1]]; render(); } }, "↑"),
              h("button", { class: "btn btn-ghost btn-sm btn-icon", type: "button", title: "Move down", "aria-label": "Move down", disabled: i === arr.length - 1, onclick: () => { [arr[i + 1], arr[i]] = [arr[i], arr[i + 1]]; render(); } }, "↓"),
              h("button", { class: "btn btn-ghost btn-sm btn-icon btn-danger", type: "button", title: "Remove", "aria-label": "Remove", onclick: () => { arr.splice(i, 1); render(); } }, "✕"))),
          h("div", { class: "grid g4", style: { marginTop: "6px" } }, fields.map((f) => {
            const control = f.type === "lines" ? lines(item, f.key, { placeholder: f.placeholder || "One per line", style: { minHeight: "96px" } })
              : f.type === "tags" ? tags(item, f.key, { placeholder: f.placeholder })
                : f.type === "area" ? area(item, f.key, { placeholder: f.placeholder })
                  : f.type === "select" ? select(item, f.key, f.options)
                    : text(item, f.key, { placeholder: f.placeholder || "" });
            return h("div", { style: { gridColumn: `span ${f.span || 1}` } }, field(f.label, control, f.hint));
          })))),
        h("div", {}, h("button", { class: "btn btn-sm", type: "button", onclick: () => { arr.push(add()); render(); } }, "+ Add")));
    };
    render();
    return wrap;
  }

  // ---- tabs
  const tabsEl = h("div", { class: "tabs", role: "tablist" });
  const body = h("div");
  const TABS = [["basics", "Basics"], ["education", "Education"], ["prefs", "Job preferences"], ["resume", "Master resume"],
    ["answers", "Application answers"], ["eeo", "Authorization & EEO"]];

  function show(id) {
    flush();
    tab = id;
    clear(tabsEl, TABS.map(([t, label]) => h("button", { class: tab === t ? "on" : "", role: "tab", onclick: () => show(t) }, label)));
    clear(body, ({ basics, education, prefs, resume, answers, eeo })[tab]());
  }

  const basics = () => {
    const p = P.personal;
    return h("div", { class: "card" },
      h("h2", {}, "Contact details"), h("p", { class: "small muted" }, "Used to fill application forms and your resume header."),
      h("div", { class: "grid g3" },
        field("First name", text(p, "first_name")), field("Last name", text(p, "last_name")), field("Preferred name", text(p, "preferred_name")),
        field("Email", text(p, "email", { type: "email" })), field("Phone", text(p, "phone", { type: "tel" })), field("Pronouns", text(p, "pronouns", { placeholder: "e.g. she/her" })),
        field("LinkedIn URL", text(p, "linkedin", { type: "url" })), field("GitHub URL", text(p, "github", { type: "url" })), field("Website / portfolio", text(p, "website", { type: "url" })),
        h("div", { class: "span2" }, field("Street address", text(p, "address"))), field("City", text(p, "city")),
        field("State / province", text(p, "state", { placeholder: "e.g. PA" })), field("ZIP / postal code", text(p, "zip")), field("Country", text(p, "country"))));
  };

  const education = () => h("div", { class: "card" },
    h("h2", {}, "Education"), h("p", { class: "small muted" }, "The first entry is used for autofill and for degree/graduation matching."),
    listEditor(P.education, [
      { key: "school", label: "School", span: 2 }, { key: "degree", label: "Degree", placeholder: "Bachelor of Science" },
      { key: "degree_level", label: "Level", type: "select", options: meta.degree_levels },
      { key: "major", label: "Major", span: 2 }, { key: "minor", label: "Minor" }, { key: "gpa", label: "GPA", placeholder: "3.7" },
      { key: "grad_month", label: "Graduation month", type: "select", options: MONTHS }, { key: "grad_year", label: "Graduation year", placeholder: "2028" },
      { key: "location", label: "Location", span: 2 },
      { key: "coursework", label: "Relevant coursework", type: "tags", span: 4, placeholder: "Add a course and press Enter" },
      { key: "highlights", label: "Honors / highlights", type: "lines", span: 4, placeholder: "One per line (optional)" },
    ], { add: () => ({ school: "", degree: "", degree_level: "Bachelor's", major: "", coursework: [], highlights: [] }), label: (e) => e.school, empty: "Add your school." }));

  const prefs = () => {
    const pr = P.preferences;
    return [
      h("div", { class: "card" }, h("h2", {}, "What you’re looking for"),
        h("div", { class: "section-title" }, "Terms"), h("p", { class: "small muted" }, "Summer 2027 internships plus off-season co-ops (Winter / Spring / Fall 2027). Counts are open roles."),
        multi(pr, "terms", meta.terms.map((t) => [t.term, `${t.term} (${t.count})`])),
        h("div", { class: "section-title" }, "Categories (first one checked gets the biggest boost)"), multi(pr, "categories", meta.categories),
        h("div", { class: "section-title" }, "Role interests (matched against job titles)"), multi(pr, "interests", meta.interests)),
      h("div", { class: "card" }, h("h2", {}, "Location"),
        h("div", { class: "grid g2" },
          h("div", { class: "span2" }, field("Preferred locations", tags(pr, "locations", { placeholder: "City, state code, region (Bay Area), country, or Remote", suggestions: LOCATION_SUGGESTIONS }))),
          check(pr, "remote_ok", "Remote roles are fine"), check(pr, "strict_location", "Only show roles in these locations"))),
      h("div", { class: "card" }, h("h2", {}, "Fine-tuning"),
        h("div", { class: "grid g2" },
          field("Boost title keywords", tags(pr, "include_keywords", { placeholder: "e.g. backend, compiler" })),
          field("Exclude title keywords", tags(pr, "exclude_keywords", { placeholder: "e.g. PhD, sales" })),
          field("Dream companies", tags(pr, "dream_companies", { placeholder: "Company name" })),
          field("Never show companies", tags(pr, "excluded_companies", { placeholder: "Company name" })),
          check(pr, "hide_closed", "Hide closed postings"),
          check(pr, "ignore_degree_filter", "Show roles that list a different degree level"))),
    ];
  };

  const resume = () => {
    const r = P.resume;
    const fileInfo = h("div", { class: "small muted" }, data.resume_file ? `Uploaded: ${data.resume_file.name} (${Math.round(data.resume_file.size / 1024)} KB)` : "No file uploaded yet.");
    const importOut = h("div");
    const fileInput = h("input", { type: "file", accept: ".pdf,.docx,.doc", class: "hidden" });
    fileInput.addEventListener("change", async () => {
      if (!fileInput.files[0]) return;
      const fd = new FormData();
      fd.append("file", fileInput.files[0]);
      const res = await guard(() => api.upload("/api/profile/resume-file", fd), "Resume uploaded");
      if (res) {
        data.resume_file = res.file;
        fileInfo.textContent = `Uploaded: ${res.file.name} (${Math.round(res.file.size / 1024)} KB) · ${res.skills_found.length} skills detected`;
      }
    });
    const doImport = async () => {
      const res = await guard(() => api.post("/api/profile/import-resume"));
      if (!res) return;
      const pr = res.proposal;
      clear(importOut, h("div", { class: "callout", style: { marginTop: "10px" } },
        res.note ? h("div", {}, res.note) : null,
        h("div", {}, res.method === "ai" ? `Found ${pr.experience?.length || 0} experiences, ${pr.projects?.length || 0} projects, ${(pr.skills || []).reduce((n, g) => n + g.items.length, 0)} skills.`
          : `Detected skills: ${(pr.skills || []).flatMap((g) => g.items).join(", ") || "none"}`),
        h("div", { class: "row", style: { marginTop: "8px" } },
          h("button", { class: "btn btn-sm btn-primary", onclick: () => { applyImport(pr); toast("Imported. Review, then Save profile."); show("resume"); } }, "Use this"))));
    };
    return [
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Your resume file"),
          h("div", { class: "row" },
            h("button", { class: "btn btn-sm", onclick: () => fileInput.click() }, data.resume_file ? "Replace file" : "Upload PDF"),
            h("button", { class: "btn btn-sm", disabled: !data.resume_file, onclick: doImport }, "Import into profile"),
            h("a", { class: "btn btn-sm btn-ghost", href: "/api/resume/master.pdf", target: "_blank" }, "Preview generated PDF"))),
        fileInfo, fileInput,
        h("p", { class: "small muted", style: { marginTop: "6px" } }, "The uploaded file is what gets attached when a job has no tailored version. Everything below is your ", h("b", {}, "master resume"),
          ": list everything you’ve done. Tailored versions pick from it and never add anything that isn’t here."),
        importOut),
      h("div", { class: "card" }, h("h2", {}, "Summary (optional)"), area(r, "summary", { placeholder: "Leave blank if you don’t use a summary line." })),
      h("div", { class: "card" }, h("h2", {}, "Experience"), listEditor(r.experience, entryFields(), { add: blankEntry, label: (e) => [e.company, e.title].filter(Boolean).join(" · "), empty: "Internships, jobs, research, TA positions…" })),
      h("div", { class: "card" }, h("h2", {}, "Projects"), listEditor(r.projects, [
        { key: "name", label: "Project name", span: 2 }, { key: "role", label: "Role (optional)" }, { key: "link", label: "Link" },
        { key: "start", label: "Start", placeholder: "Jan 2026" }, { key: "end", label: "End", placeholder: "Mar 2026" },
        { key: "tech", label: "Tech", type: "tags", span: 2, placeholder: "Python, React…" },
        { key: "bullets", label: "Bullets", type: "lines", span: 4, hint: "One per line. Be specific and include real results; tailoring won’t invent numbers." },
      ], { add: () => ({ name: "", tech: [], bullets: [] }), label: (e) => e.name, empty: "Class, hackathon, research and side projects." })),
      h("div", { class: "card" }, h("h2", {}, "Leadership & activities"), listEditor(r.activities, entryFields(), { add: blankEntry, label: (e) => [e.company, e.title].filter(Boolean).join(" · "), empty: "Clubs, organizing, volunteering…" })),
      h("div", { class: "card" }, h("h2", {}, "Skills"), listEditor(r.skills, [
        { key: "category", label: "Group", placeholder: "Languages" }, { key: "items", label: "Skills", type: "tags", span: 3, placeholder: "Add a skill and press Enter" },
      ], { add: () => ({ category: "", items: [] }), label: (g) => g.category, empty: "e.g. Languages / Frameworks / Tools" })),
      h("div", { class: "card" }, h("h2", {}, "Awards"), listEditor(r.awards, [
        { key: "title", label: "Award", span: 2 }, { key: "detail", label: "Detail", span: 2 },
      ], { add: () => ({ title: "", detail: "" }), label: (a) => a.title, empty: "Scholarships, hackathon wins, dean’s list…" })),
    ];
  };

  function applyImport(pr) {
    const empty = !(P.resume.experience.length || P.resume.projects.length);
    if (pr.personal) for (const [k, v] of Object.entries(pr.personal)) if (v && !P.personal[k]) P.personal[k] = v;
    if (pr.education?.length && !P.education[0]?.school) P.education = pr.education;
    const replace = empty || confirm("Replace your current experience, projects and skills with the imported ones?");
    if (pr.experience && replace) {
      for (const k of ["experience", "projects", "activities", "skills", "awards"]) if (pr[k]) P.resume[k] = pr[k];
      if (pr.summary) P.resume.summary = pr.summary;
    } else if (pr.skills && !pr.experience) {
      const have = new Set(P.resume.skills.flatMap((g) => g.items.map((s) => s.toLowerCase())));
      for (const g of pr.skills) {
        const items = g.items.filter((s) => !have.has(s.toLowerCase()));
        if (!items.length) continue;
        const target = P.resume.skills.find((x) => x.category.toLowerCase() === g.category.toLowerCase());
        if (target) target.items.push(...items); else P.resume.skills.push({ category: g.category, items });
      }
    }
  }

  const answers = () => {
    const a = P.application;
    return [
      h("div", { class: "card" }, h("h2", {}, "Common questions"),
        h("div", { class: "grid g2" },
          field("How did you hear about us?", text(a, "how_heard")), field("Earliest start date", text(a, "earliest_start", { placeholder: "May 2027" })),
          field("Current / most recent employer", text(a, "current_company")), field("Current title", text(a, "current_title")),
          field("Salary expectation (optional)", text(a, "salary_expectation", { placeholder: "Leave blank to skip" })),
          check(a, "previously_employed", "I’ve worked at companies I apply to before (answers “Yes”)"))),
      h("div", { class: "card" }, h("h2", {}, "Answer bank"),
        h("p", { class: "small muted" }, "The extension fills a text box when its question closely matches one of these. For new questions it can draft an answer with AI."),
        listEditor(P.answers, [
          { key: "question", label: "Question", span: 4 }, { key: "answer", label: "Answer", type: "area", span: 4 },
        ], { add: () => ({ question: "", answer: "" }), label: (x) => x.question, empty: "No saved answers." })),
    ];
  };

  const eeo = () => {
    const w = P.work_auth;
    const e = P.eeo;
    return [
      h("div", { class: "card" }, h("h2", {}, "Work authorization"),
        h("p", { class: "small muted" }, "Used to answer the yes/no questions and to filter out roles you can’t take."),
        h("div", { class: "stack" },
          check(w, "authorized_us", "I’m authorized to work in the U.S."),
          check(w, "needs_sponsorship", "I will now or in the future need visa sponsorship"),
          check(w, "us_citizen", "I’m a U.S. citizen (needed for citizenship-only / clearance roles)"),
          check(w, "over_18", "I’m 18 or older"),
          check(w, "willing_to_relocate", "I’m willing to relocate"))),
      h("div", { class: "card" }, h("h2", {}, "Voluntary self-identification"),
        h("p", { class: "small muted" }, "Optional. Only used to fill EEO questions; “Decline” is always a valid choice."),
        h("div", { class: "grid g2" },
          field("Gender", select(e, "gender", EEO.gender)), field("Race / ethnicity", select(e, "race", EEO.race)),
          field("Hispanic or Latino?", select(e, "hispanic", EEO.hispanic)), field("Veteran status", select(e, "veteran", EEO.veteran)),
          field("Disability status", select(e, "disability", EEO.disability)), field("LGBTQ+?", select(e, "lgbtq", EEO.lgbtq)))),
    ];
  };

  const completeness = h("span", { class: `chip ${data.completeness.score === 100 ? "good" : "warn"}` }, `Profile ${data.completeness.score}% complete`);
  clear(main,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Your profile"), h("div", { class: "sub" }, "Everything used to rank jobs, fill applications and tailor your resume. Stored only on this computer.")),
      completeness),
    tabsEl, body,
    h("div", { class: "sticky-save" }, h("div", { class: "inner" },
      h("span", { class: "small muted" }, "Changes aren’t saved until you click Save."),
      h("button", { class: "btn btn-primary", onclick: async () => {
        flush();
        const res = await guard(() => api.put("/api/profile", { profile: P }), "Profile saved");
        if (res) {
          Object.assign(P, res.profile);
          completeness.textContent = `Profile ${res.completeness.score}% complete`;
          completeness.className = `chip ${res.completeness.score === 100 ? "good" : "warn"}`;
          refreshNav();
          show(tab);
        }
      } }, "Save profile"))),
  );
  show(tab);
}

function entryFields() {
  return [
    { key: "company", label: "Organization", span: 2 }, { key: "title", label: "Title", span: 2 },
    { key: "location", label: "Location" }, { key: "start", label: "Start", placeholder: "May 2026" }, { key: "end", label: "End", placeholder: "Aug 2026 / Present" },
    { key: "skills", label: "Skills used", type: "tags", placeholder: "optional" },
    { key: "bullets", label: "Bullets", type: "lines", span: 4, hint: "One per line. Include every accomplishment worth mentioning; tailored versions choose and reword from these." },
  ];
}
function blankEntry() { return { company: "", title: "", location: "", start: "", end: "", bullets: [], skills: [] }; }
