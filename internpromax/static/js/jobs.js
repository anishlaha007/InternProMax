// Jobs feed + job detail drawer (posting analysis, tailored resume, application status).
import { h, add, clear, api, guard, toast, openDrawer, closeDrawer, ago, date, statusChip, statusSelect, extensionInfo, openViaExtension } from "./lib.js";
import { renderResume } from "./resume.js";

const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(`ipm.${k}`)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`ipm.${k}`, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

const state = { view: "matches", q: "", term: "", category: "", sort: "score", limit: 60, ...store.get("feed", {}) };
let meta = null;

export async function renderJobs(main, refreshNav) {
  meta = meta || await api.get("/api/meta");
  const listEl = h("div", { class: "job-list" });
  const segEl = h("div", { class: "seg", role: "tablist" });
  const subEl = h("div", { class: "sub" });
  const search = h("input", { type: "search", class: "search", placeholder: "Search company, title, location…", value: state.q });
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { state.q = search.value; state.limit = 60; load(); }, 220); });
  const termSel = h("select", { onchange: () => { state.term = termSel.value; load(); } },
    h("option", { value: "" }, "All my terms"), meta.terms.map((t) => h("option", { value: t.term, selected: t.term === state.term }, `${t.term} (${t.count})`)));
  const catSel = h("select", { onchange: () => { state.category = catSel.value; load(); } },
    h("option", { value: "" }, "All categories"), meta.categories.map((c) => h("option", { value: c, selected: c === state.category }, c)));
  const sortSel = h("select", { onchange: () => { state.sort = sortSel.value; load(); } },
    h("option", { value: "score", selected: state.sort === "score" }, "Best match"),
    h("option", { value: "newest", selected: state.sort === "newest" }, "Newest"));

  clear(main,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Jobs for you"), subEl),
      h("div", { class: "row" },
        h("button", { class: "btn btn-sm", onclick: async () => { await api.post("/api/jobs/mark-seen"); toast("Marked everything as seen"); load(); refreshNav(); } }, "Mark all seen"))),
    h("div", { class: "toolbar" }, search, segEl),
    h("div", { class: "toolbar" }, termSel, catSel, sortSel),
    listEl,
  );

  const views = [["matches", "Matches"], ["new", "New"], ["saved", "Saved"], ["applied", "Applied"], ["filtered", "Filtered out"], ["hidden", "Hidden"]];

  async function load() {
    store.set("feed", { view: state.view, term: state.term, category: state.category, sort: state.sort });
    const params = new URLSearchParams({ view: state.view === "new" ? "matches" : state.view, q: state.q, term: state.term,
      category: state.category, sort: state.sort, limit: state.limit, new_only: state.view === "new" });
    listEl.replaceChildren(h("div", { class: "empty" }, h("span", { class: "spinner" })));
    const data = await guard(() => api.get(`/api/jobs?${params}`));
    if (!data) return;
    clear(segEl, views.map(([id, label]) => h("button", {
      class: state.view === id ? "on" : "", role: "tab", "aria-selected": String(state.view === id),
      onclick: () => { state.view = id; state.limit = 60; load(); },
    }, label, h("span", { class: "n" }, data.counts[id] ?? ""))));
    subEl.textContent = `${data.counts.matches.toLocaleString()} open roles fit your profile · ${data.counts.new} new since you last looked`;
    if (!data.items.length) {
      clear(listEl, emptyState(data));
      return;
    }
    clear(listEl, data.items.map((j) => jobRow(j, load, refreshNav)));
    if (data.total > data.items.length) {
      listEl.append(h("div", { class: "load-more" },
        h("button", { class: "btn", onclick: () => { state.limit += 60; load(); } }, `Show more (${data.total - data.items.length} left)`)));
    }
  }
  await load();
}

function emptyState(data) {
  if (state.view === "matches" && data.counts.filtered + data.counts.matches === 0) {
    return h("div", { class: "empty" }, h("h3", {}, "No listings yet"),
      h("p", {}, "Click “Sync listings” in the sidebar to pull the latest internships."));
  }
  if (state.view === "matches") {
    return h("div", { class: "empty" }, h("h3", {}, "Nothing matches right now"),
      h("p", {}, "Loosen your preferences in Profile → Preferences, or check “Filtered out” to see why roles were excluded."));
  }
  return h("div", { class: "empty" }, h("h3", {}, "Nothing here"));
}

function scoreBadge(score, fit) {
  const cls = score >= 65 ? "s-high" : score >= 40 ? "s-mid" : "s-low";
  return h("div", { class: `score ${cls}`, title: fit != null ? `Includes posting fit ${fit}` : "Match score" },
    score ?? "–", fit != null ? h("small", {}, "fit") : null);
}

function flags(j) {
  const out = [];
  if (j.sponsorship === "Does Not Offer Sponsorship") out.push(h("span", { class: "chip warn" }, "No sponsorship"));
  if (j.sponsorship === "U.S. Citizenship is Required") out.push(h("span", { class: "chip warn" }, "U.S. citizens only"));
  if (j.sponsorship === "Offers Sponsorship") out.push(h("span", { class: "chip good" }, "Sponsors visas"));
  if (!j.active) out.push(h("span", { class: "chip bad" }, "Closed"));
  if (/co-?op/i.test(j.title)) out.push(h("span", { class: "chip" }, "Co-op"));
  return out;
}

export async function applyTo(job, after) {
  // Open synchronously (inside the click) so popup blockers stay quiet.
  const viaExt = openViaExtension(job);
  if (!viaExt) window.open(job.url, "_blank", "noopener");
  await guard(() => api.post(`/api/jobs/${job.id}/open`));
  toast(viaExt ? "Opened with autofill. Review, then submit; it'll be tracked automatically."
    : "Opened the posting. Install the Chrome extension for autofill + automatic tracking.");
  if (after) after();
}

function jobRow(j, reload, refreshNav) {
  const reasons = (j.filtered || []).length
    ? j.filtered.map((f) => h("span", { class: "chip bad" }, f))
    : (j.reasons || []).filter((r) => (r.points > 0 && r.kind !== "fresh") || r.kind === "ai").slice(0, 4).map((r) => h("span", { class: "chip" }, r.text));
  const row = h("div", { class: `job ${j.active ? "" : "closed"}`, tabindex: "0", onclick: () => openJob(j.id, () => { reload(); refreshNav(); }),
    onkeydown: (e) => { if (e.key === "Enter") openJob(j.id, () => { reload(); refreshNav(); }); } },
    scoreBadge(j.score, j.fit),
    h("div", { class: "job-main" },
      h("div", { class: "job-line" },
        j.is_new ? h("span", { class: "chip new" }, "New") : null,
        h("span", { class: "job-company" }, j.company), h("span", { class: "faint" }, "·"), h("span", { class: "job-title" }, j.title),
        j.app_status ? statusChip(j.app_status) : null),
      h("div", { class: "job-meta" },
        h("span", {}, (j.locations || []).slice(0, 3).join(" · ") + ((j.locations || []).length > 3 ? ` +${j.locations.length - 3}` : "")),
        h("span", {}, (j.terms || []).join(", ")),
        h("span", {}, j.date_posted ? `Posted ${ago(j.date_posted)}` : ""),
        ...flags(j)),
      h("div", { class: "job-reasons" }, reasons)),
    h("div", { class: "job-actions", onclick: (e) => e.stopPropagation() },
      h("button", { class: "btn btn-primary btn-sm", onclick: () => applyTo(j, reload) }, "Apply"),
      !j.app_status ? h("button", { class: "btn btn-sm", title: "Save for later", onclick: async () => { await guard(() => api.post(`/api/jobs/${j.id}/save`), "Saved"); reload(); refreshNav(); } }, "Save") : null,
      h("button", { class: "btn btn-ghost btn-sm btn-icon", title: j.hidden ? "Unhide" : "Not interested", "aria-label": j.hidden ? "Unhide" : "Hide",
        onclick: async () => { await guard(() => api.post(`/api/jobs/${j.id}/hide`, { hidden: !j.hidden })); reload(); } }, j.hidden ? "↺" : "✕")),
  );
  return row;
}

// ---------------------------------------------------------------- job drawer

export function openJob(jobId, onChange) {
  let poll = null;
  let alive = true;
  openDrawer((panel) => {
    const head = h("div", { class: "drawer-head" });
    const body = h("div", { class: "drawer-body" }, h("div", { class: "empty" }, h("span", { class: "spinner" })));
    panel.append(head, body);
    let editing = false;

    async function refresh() {
      if (!alive || editing) return;
      const d = await guard(() => api.get(`/api/jobs/${jobId}`));
      if (!d || !alive) return;
      render(d);
      const ds = d.details?.status;
      const rs = d.resume?.status;
      const working = ["queued", "fetching", "analyzing"].includes(ds) || ["queued", "running"].includes(rs);
      clearTimeout(poll);
      if (working) poll = setTimeout(refresh, 2000);
    }

    function render(d) {
      const j = d.job;
      clear(head,
        h("div", { class: "grow" },
          h("div", { class: "row wrap" }, h("h2", { style: { fontSize: "18px" } }, j.company), d.application ? statusChip(d.application.status) : null),
          h("div", { style: { fontSize: "15px", fontWeight: 560, marginTop: "2px" } }, j.title),
          h("div", { class: "job-meta" }, h("span", {}, (j.locations || []).join(" · ")), h("span", {}, (j.terms || []).join(", ")),
            h("span", {}, j.date_posted ? `Posted ${date(j.date_posted)}` : ""), ...flags({ ...j, active: j.active })),
          h("div", { class: "row wrap", style: { marginTop: "12px" } },
            h("button", { class: "btn btn-primary", onclick: () => applyTo(j, () => { refresh(); onChange && onChange(); }) }, "Apply ↗"),
            !d.application ? h("button", { class: "btn", onclick: async () => { await guard(() => api.post(`/api/jobs/${j.id}/save`), "Saved to tracker"); refresh(); onChange && onChange(); } }, "Save") : null,
            !d.application || d.application.status === "saved"
              ? h("button", { class: "btn", onclick: async () => { await guard(() => api.post("/api/applications/applied", { job_id: j.id, source: "dashboard", trigger: "manual" }), "Marked as applied"); refresh(); onChange && onChange(); } }, "Mark applied")
              : statusSelect(d.application.status, async (s) => { await guard(() => api.patch(`/api/applications/${d.application.id}`, { status: s }), "Status updated"); refresh(); onChange && onChange(); }),
            h("a", { class: "btn btn-ghost", href: j.url, target: "_blank", rel: "noopener" }, "View posting"),
          )),
        scoreBadge(d.score, d.details?.analysis?.fit_score),
        h("button", { class: "btn btn-ghost btn-icon", "aria-label": "Close", onclick: closeDrawer }, "✕"),
      );
      clear(body,
        whyCard(d),
        analysisCard(d, refresh),
        resumeCard(d, refresh, (v) => { editing = v; }),
        d.application ? timelineCard(d.application) : null,
      );
    }
    refresh();
    return () => { alive = false; clearTimeout(poll); };
  });
}

function whyCard(d) {
  const good = (d.reasons || []).filter((r) => r.points > 0);
  const bad = [...(d.filtered || []), ...(d.reasons || []).filter((r) => r.points < 0).map((r) => r.text)];
  return h("div", { class: "card" },
    h("div", { class: "section-title" }, "Why it’s in your feed"),
    h("div", { class: "skill-row" },
      good.map((r) => h("span", { class: "chip good" }, `${r.text} +${r.points}`)),
      bad.map((t) => h("span", { class: "chip bad" }, t)),
      !good.length && !bad.length ? h("span", { class: "muted" }, "No strong signals from the title alone. Analyze the posting for a real fit score.") : null));
}

function analysisCard(d, refresh) {
  const det = d.details || {};
  const a = det.analysis;
  const status = det.status;
  const card = h("div", { class: "card" });
  const head = h("div", { class: "card-head" }, h("h2", {}, "What they’re looking for"),
    h("div", { class: "row" },
      a ? h("span", { class: `chip ${det.analysis_method === "ai" ? "violet" : ""}` }, det.analysis_method === "ai" ? "AI analysis" : "Built-in analysis") : null,
      h("button", { class: "btn btn-sm", disabled: ["queued", "fetching", "analyzing"].includes(status),
        onclick: async () => { await guard(() => api.post(`/api/jobs/${d.job.id}/analyze`, { force: !!a })); refresh(); } }, a ? "Re-analyze" : "Analyze posting")));
  add(card, head);

  if (["queued", "fetching", "analyzing"].includes(status)) {
    add(card, h("p", { class: "muted" }, h("span", { class: "spinner" }), " ",
      status === "fetching" ? "Fetching the posting…" : status === "analyzing" ? "Reading the requirements…" : "Queued…"));
  }
  if (det.error) add(card, h("div", { class: `callout ${status === "needs_capture" ? "warn" : "bad"}`, style: { marginBottom: "10px" } }, det.error));
  if (status === "needs_capture" || (!a && status === "error")) add(card, captureBox(d.job.id, refresh));
  if (!a) {
    if (!status || status === "none") add(card, h("p", { class: "muted" }, "Pull the full posting to see required skills, the kinds of projects they want, and how you stack up."));
    return card;
  }

  const matched = new Set((a.matched_skills || []).map((s) => s.toLowerCase()));
  const skillChips = (list) => h("div", { class: "skill-row" }, (list || []).length
    ? list.map((s) => h("span", { class: `chip ${matched.has(s.toLowerCase()) ? "good" : "bad"}`, title: matched.has(s.toLowerCase()) ? "On your resume" : "Not on your resume yet" },
      matched.has(s.toLowerCase()) ? "✓ " : "✗ ", s))
    : h("span", { class: "faint" }, "None listed"));

  add(card,
    a.summary ? h("p", {}, a.summary) : null,
    h("div", { class: "row", style: { gap: "18px", alignItems: "flex-start", margin: "8px 0 4px" } },
      h("div", {}, h("div", { class: "fit-big" }, a.fit_score ?? "–"), h("div", { class: "tiny muted" }, "posting fit")),
      h("div", { class: "grow" }, h("ul", {}, (a.fit_reasons || []).map((r) => h("li", {}, r))))),
    a.role_focus ? h("div", { class: "muted small" }, "Focus: ", h("b", {}, a.role_focus)) : null,
    h("div", { class: "section-title" }, "Required skills"), skillChips(a.required_skills),
    h("div", { class: "section-title" }, "Nice to have"), skillChips(a.preferred_skills),
    (a.project_themes || []).length ? [h("div", { class: "section-title" }, "Projects & experience that stand out"), h("ul", {}, a.project_themes.map((t) => h("li", {}, t)))] : null,
    (a.responsibilities || []).length ? [h("div", { class: "section-title" }, "What you’d work on"), h("ul", {}, a.responsibilities.map((t) => h("li", {}, t)))] : null,
    constraints(a.constraints),
    (a.resume_focus || []).length ? [h("div", { class: "section-title" }, "Emphasize from your background"), h("div", { class: "skill-row" }, a.resume_focus.map((t) => h("span", { class: "chip accent" }, t)))] : null,
    (a.gaps_advice || []).length ? [h("div", { class: "section-title" }, "Closing the gaps"), h("ul", {}, a.gaps_advice.map((t) => h("li", {}, t)))] : null,
  );
  return card;
}

function constraints(c) {
  if (!c) return null;
  const rows = [["Graduation", c.graduation], ["GPA", c.gpa], ["Degree", c.degree], ["Work authorization", c.work_authorization]]
    .filter(([, v]) => v);
  (c.other || []).forEach((o) => rows.push(["Other", o]));
  if (!rows.length) return null;
  return [h("div", { class: "section-title" }, "Hard requirements"),
    h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]))];
}

function captureBox(jobId, refresh) {
  const ta = h("textarea", { placeholder: "Paste the full job description here…", style: { minHeight: "140px" } });
  return h("div", { class: "stack", style: { marginBottom: "8px" } },
    h("div", { class: "small muted" }, extensionInfo()
      ? "Tip: open the job with Apply. The extension captures the posting from the page automatically."
      : "Paste the posting text, or install the Chrome extension to capture it automatically."),
    ta,
    h("div", {}, h("button", { class: "btn btn-sm btn-primary", onclick: async () => {
      if (await guard(() => api.post(`/api/jobs/${jobId}/description`, { text: ta.value, source: "pasted", force: true }), "Got it, analyzing…")) refresh();
    } }, "Analyze this text")));
}

function resumeCard(d, refresh, setEditing) {
  const r = d.resume;
  const card = h("div", { class: "card" });
  const busy = r && ["queued", "running"].includes(r.status);
  add(card, h("div", { class: "card-head" }, h("h2", {}, "Tailored resume"),
    h("div", { class: "row" },
      r?.status === "ready" ? h("span", { class: `chip ${r.method === "ai" ? "violet" : ""}` }, r.method === "ai" ? "AI tailored" : r.method === "edited" ? "Your edits" : "Built-in tailoring") : null,
      h("button", { class: "btn btn-sm", disabled: busy, onclick: async () => {
        await guard(() => api.post(`/api/jobs/${d.job.id}/tailor`, { force: r?.status === "ready" })); refresh();
      } }, r?.status === "ready" ? "Regenerate" : "Tailor my resume"))));

  if (busy) add(card, h("p", { class: "muted" }, h("span", { class: "spinner" }), " Tailoring your resume to this posting…"));
  if (r?.status === "error") add(card, h("div", { class: "callout bad" }, r.error || "Tailoring failed"));
  if (!r) add(card, h("p", { class: "muted" }, "Builds a version of your master resume that leads with the experience and skills this posting asks for. It never adds anything you haven’t done. The extension uploads it when you apply."));
  if (r?.status !== "ready" || !r.data) return card;

  const paper = renderResume(r.data, { editable: false });
  const holder = h("div", {}, paper);
  const editBtn = h("button", { class: "btn btn-sm", onclick: () => {
    const editable = renderResume(r.data, { editable: true });
    holder.replaceChildren(editable);
    setEditing(true);
    editBtn.classList.add("hidden");
    saveBtn.classList.remove("hidden");
    cancelBtn.classList.remove("hidden");
    saveBtn.onclick = async () => {
      if (await guard(() => api.put(`/api/jobs/${d.job.id}/resume`, { data: editable.getData(), changes: ["Edited by you", ...(r.changes || [])] }), "Saved your edits")) {
        setEditing(false); refresh();
      }
    };
  } }, "Edit text");
  const saveBtn = h("button", { class: "btn btn-sm btn-primary hidden" }, "Save edits");
  const cancelBtn = h("button", { class: "btn btn-sm hidden", onclick: () => { setEditing(false); refresh(); } }, "Cancel");

  add(card,
    (r.changes || []).length ? [h("div", { class: "section-title" }, "What changed"), h("ul", {}, r.changes.map((c) => h("li", {}, c)))] : null,
    (r.warnings || []).length ? h("div", { class: "callout warn", style: { margin: "8px 0" } }, h("b", {}, "Kept honest: "), h("ul", {}, r.warnings.map((w) => h("li", {}, w)))) : null,
    h("div", { class: "row", style: { margin: "12px 0" } },
      h("a", { class: "btn btn-sm btn-primary", href: `/api/jobs/${d.job.id}/resume.pdf?variant=tailored`, target: "_blank" }, "Download PDF"),
      editBtn, saveBtn, cancelBtn,
      h("span", { class: "small muted" }, d.resume && "The extension uploads this version when you apply here.")),
    holder,
  );
  return card;
}

export function timelineCard(app) {
  const labels = { created: "Added", status: "Status", submitted: "Submitted", email: "Email", note: "Note" };
  return h("div", { class: "card" },
    h("h2", {}, "Timeline"),
    h("ul", { class: "timeline" }, (app.events || []).map((e) => h("li", {},
      h("span", { class: "faint small" }, new Date(e.ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })),
      h("span", {}, h("b", {}, labels[e.type] || e.type), " ",
        e.to_status ? [e.from_status ? `${e.from_status} → ` : "", e.to_status] : "",
        e.detail?.source ? h("span", { class: "faint small" }, ` via ${e.detail.source}`) : "",
        e.detail?.subject ? h("div", { class: "small muted" }, `“${e.detail.subject}”`) : null,
        e.detail?.notes ? h("div", { class: "small muted" }, e.detail.notes) : null)))));
}
