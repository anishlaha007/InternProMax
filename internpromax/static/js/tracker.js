// Application tracker: stat tiles, weekly chart, kanban board / list, application drawer.
import { h, clear, api, guard, toast, openDrawer, closeDrawer, openModal, ago, date, compact, STATUS, STATUS_ORDER, statusChip, statusSelect, field } from "./lib.js";
import { openJob, timelineCard } from "./jobs.js";

let mode = "board";
let sortKey = "updated_at";

export async function renderTracker(main, refreshNav) {
  const data = await guard(() => api.get("/api/applications"));
  if (!data) return;
  const reload = () => renderTracker(main, refreshNav).then(refreshNav);
  const content = h("div");
  clear(main,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Application tracker"),
        h("div", { class: "sub" }, "Updates itself when the extension sees you submit. Email updates land in Inbox.")),
      h("div", { class: "row" },
        h("div", { class: "seg" },
          h("button", { class: mode === "board" ? "on" : "", onclick: () => { mode = "board"; reload(); } }, "Board"),
          h("button", { class: mode === "list" ? "on" : "", onclick: () => { mode = "list"; reload(); } }, "List")),
        h("a", { class: "btn btn-sm", href: "/api/export/applications.csv" }, "Export CSV"),
        h("button", { class: "btn btn-primary btn-sm", onclick: () => addApplication(reload) }, "+ Add application"))),
    tiles(data.stats),
    content,
  );
  if (!data.items.length) {
    content.append(h("div", { class: "card empty" }, h("h3", {}, "No applications yet"),
      h("p", {}, "Hit Apply on a job. When you submit the form, the extension records it here. You can also add one manually.")));
    return;
  }
  content.append(mode === "board" ? board(data.items, reload) : list(data.items, reload));
}

function tiles(s) {
  const c = s.counts;
  const tile = (label, value, foot) => h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), h("div", { class: "foot" }, foot || ""));
  return h("div", { class: "tiles" },
    tile("Applications sent", compact(s.submitted), `${c.saved} saved for later`),
    tile("Response rate", `${Math.round(s.response_rate * 100)}%`, "any reply: OA, interview, offer or rejection"),
    tile("Interviews", compact(c.interviewing + c.offer), `${c.oa} online assessments`),
    tile("Offers", compact(c.offer), `${c.rejected} rejections`),
    h("div", { class: "tile chart-tile" }, h("div", { class: "label" }, "Applications per week"), weeklyChart(s.weekly)),
  );
}

function weeklyChart(weeks) {
  const W = 320, H = 86, pad = 16, gap = 8;
  const max = Math.max(1, ...weeks.map((w) => w.count));
  const bw = (W - gap * (weeks.length - 1)) / weeks.length;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Applications per week for the last 8 weeks: ${weeks.map((w) => w.count).join(", ")}`);
  const wrap = h("div", { class: "chart" });
  const tip = h("div", { class: "tooltip hidden" });
  const base = document.createElementNS(ns, "line");
  Object.entries({ x1: 0, x2: W, y1: H - pad, y2: H - pad, class: "base" }).forEach(([k, v]) => base.setAttribute(k, v));
  svg.append(base);
  weeks.forEach((w, i) => {
    const x = i * (bw + gap);
    const bh = w.count ? Math.max(3, (H - pad - 6) * (w.count / max)) : 0;
    const y = H - pad - bh;
    if (bh) {
      // bar with 4px rounded top anchored to the baseline
      const r = Math.min(4, bh, bw / 2);
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", `M${x},${H - pad} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${H - pad} Z`);
      path.setAttribute("class", "bar");
      svg.append(path);
    }
    const hit = document.createElementNS(ns, "rect");
    Object.entries({ x, y: 0, width: bw, height: H - pad, class: "bar-hit" }).forEach(([k, v]) => hit.setAttribute(k, v));
    const label = `Week of ${new Date(w.start * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" })}: ${w.count} application${w.count === 1 ? "" : "s"}`;
    hit.addEventListener("mouseenter", () => {
      tip.textContent = label;
      tip.classList.remove("hidden");
      tip.style.left = `${((x + bw / 2) / W) * 100}%`;
      tip.style.top = `${(y / H) * 100}%`;
    });
    hit.addEventListener("mouseleave", () => tip.classList.add("hidden"));
    svg.append(hit);
    if (i === 0 || i === weeks.length - 1) {
      const t = document.createElementNS(ns, "text");
      t.setAttribute("x", i === 0 ? x : x + bw);
      t.setAttribute("y", H - 3);
      t.setAttribute("text-anchor", i === 0 ? "start" : "end");
      t.setAttribute("class", "axis");
      t.textContent = i === 0 ? "8 wks ago" : "this week";
      svg.append(t);
    }
  });
  wrap.append(svg, tip);
  return wrap;
}

function board(items, reload) {
  const columns = ["saved", "applied", "oa", "interviewing", "offer", "rejected"];
  const closed = items.filter((a) => ["withdrawn", "ghosted"].includes(a.status));
  const el = h("div", { class: "board" });
  for (const status of [...columns, ...(closed.length ? ["closed"] : [])]) {
    const apps = status === "closed" ? closed : items.filter((a) => a.status === status);
    const st = STATUS[status] || { label: "Withdrawn / ghosted", color: "var(--text-3)" };
    const col = h("div", { class: "col", "data-status": status },
      h("div", { class: "col-head" }, h("span", { class: "dot", style: { background: st.color } }), st.label, h("span", { class: "count" }, apps.length)),
      apps.map((a) => card(a, reload)));
    if (status !== "closed") {
      col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("drop"); });
      col.addEventListener("dragleave", () => col.classList.remove("drop"));
      col.addEventListener("drop", async (e) => {
        e.preventDefault();
        col.classList.remove("drop");
        const id = e.dataTransfer.getData("text/ipm-app");
        if (id) { await guard(() => api.patch(`/api/applications/${id}`, { status }), `Moved to ${st.label}`); reload(); }
      });
    }
    el.append(col);
  }
  return el;
}

function card(a, reload) {
  const c = h("div", { class: "app-card", draggable: "true", tabindex: "0", onclick: () => openApplication(a.id, reload),
    onkeydown: (e) => { if (e.key === "Enter") openApplication(a.id, reload); } },
    h("div", { class: "co" }, a.company),
    h("div", { class: "ti ellipsis", title: a.title }, a.title || "—"),
    h("div", { class: "ft" },
      h("span", {}, a.applied_at ? `Applied ${ago(a.applied_at)}` : `Saved ${ago(a.created_at)}`),
      a.stale ? h("span", { class: "chip warn", title: "No updates in 30+ days" }, "quiet") : null,
      ["withdrawn", "ghosted"].includes(a.status) ? statusChip(a.status) : null));
  c.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/ipm-app", String(a.id)); c.classList.add("dragging"); });
  c.addEventListener("dragend", () => c.classList.remove("dragging"));
  return c;
}

function list(items, reload) {
  const cols = [["company", "Company"], ["title", "Role"], ["status", "Status"], ["applied_at", "Applied"], ["updated_at", "Last update"]];
  const sorted = [...items].sort((x, y) => {
    const a = x[sortKey] ?? "", b = y[sortKey] ?? "";
    if (sortKey === "status") return STATUS_ORDER.indexOf(a) - STATUS_ORDER.indexOf(b);
    return typeof a === "number" ? b - a : String(a).localeCompare(String(b));
  });
  return h("table", { class: "list" },
    h("thead", {}, h("tr", {}, cols.map(([k, label]) => h("th", { onclick: () => { sortKey = k; reload(); } }, label, sortKey === k ? " ↓" : "")))),
    h("tbody", {}, sorted.map((a) => h("tr", { onclick: () => openApplication(a.id, reload) },
      h("td", {}, h("b", {}, a.company)), h("td", {}, a.title), h("td", {}, statusChip(a.status)),
      h("td", { class: "nowrap" }, date(a.applied_at)), h("td", { class: "nowrap muted" }, ago(a.updated_at))))));
}

export function openApplication(appId, onChange) {
  openDrawer((panel) => {
    const head = h("div", { class: "drawer-head" });
    const body = h("div", { class: "drawer-body" });
    panel.append(head, body);
    const load = async () => {
      const a = await guard(() => api.get(`/api/applications/${appId}`));
      if (!a) return;
      const notes = h("textarea", { placeholder: "Recruiter name, interview dates, prep notes…", value: a.notes || "" });
      const company = h("input", { type: "text", value: a.company });
      const title = h("input", { type: "text", value: a.title || "" });
      const url = h("input", { type: "url", value: a.url || "" });
      clear(head,
        h("div", { class: "grow" }, h("h2", { style: { fontSize: "18px" } }, a.company), h("div", { class: "muted" }, a.title),
          h("div", { class: "row wrap", style: { marginTop: "10px" } },
            statusSelect(a.status, async (s) => { await guard(() => api.patch(`/api/applications/${a.id}`, { status: s }), "Status updated"); load(); onChange && onChange(); }),
            a.job_id ? h("button", { class: "btn btn-sm", onclick: () => { closeDrawer(); openJob(a.job_id, onChange); } }, "Posting analysis & resume") : null,
            a.url ? h("a", { class: "btn btn-sm btn-ghost", href: a.url, target: "_blank", rel: "noopener" }, "Open posting ↗") : null)),
        h("button", { class: "btn btn-ghost btn-icon", "aria-label": "Close", onclick: closeDrawer }, "✕"));
      clear(body,
        h("div", { class: "card" },
          h("div", { class: "grid g2" }, field("Company", company), field("Role", title), h("div", { class: "span2" }, field("Posting URL", url)),
            h("div", { class: "span2" }, field("Notes", notes))),
          h("div", { class: "row between", style: { marginTop: "12px" } },
            h("button", { class: "btn btn-sm btn-danger btn-ghost", onclick: async () => {
              if (!confirm(`Delete the ${a.company} application and its history?`)) return;
              await guard(() => api.del(`/api/applications/${a.id}`), "Deleted"); closeDrawer(); onChange && onChange();
            } }, "Delete"),
            h("button", { class: "btn btn-primary btn-sm", onclick: async () => {
              await guard(() => api.patch(`/api/applications/${a.id}`, { company: company.value, title: title.value, url: url.value, notes: notes.value }), "Saved");
              load(); onChange && onChange();
            } }, "Save"))),
        h("div", { class: "card" }, h("dl", { class: "kv" },
          h("dt", {}, "Status"), h("dd", {}, statusChip(a.status)),
          h("dt", {}, "Applied"), h("dd", {}, a.applied_at ? new Date(a.applied_at * 1000).toLocaleString() : "Not yet"),
          h("dt", {}, "Tracked via"), h("dd", {}, a.source || "manual"))),
        timelineCard(a));
    };
    load();
  });
}

function addApplication(reload) {
  openModal("Add an application", (box, close) => {
    const company = h("input", { type: "text", required: true });
    const title = h("input", { type: "text" });
    const url = h("input", { type: "url", placeholder: "https://…" });
    const status = h("select", {}, STATUS_ORDER.map((s) => h("option", { value: s, selected: s === "applied" }, STATUS[s].label)));
    box.append(h("div", { class: "stack" }, field("Company", company), field("Role", title), field("Posting URL", url), field("Status", status),
      h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "6px" } },
        h("button", { class: "btn", onclick: close }, "Cancel"),
        h("button", { class: "btn btn-primary", onclick: async () => {
          if (!company.value.trim()) { toast("Company is required", "bad"); return; }
          if (await guard(() => api.post("/api/applications", { company: company.value, title: title.value, url: url.value || null, status: status.value }), "Added")) { close(); reload(); }
        } }, "Add"))));
    company.focus();
  });
}
