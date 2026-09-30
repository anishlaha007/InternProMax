// Small DOM + API helpers shared by every view.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (k === "value") el.value = v;
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function add(el, ...children) {
  append(el, children);
  return el;
}

export function clear(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

async function request(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const type = res.headers.get("content-type") || "";
  const data = type.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = (data && data.detail) || (typeof data === "string" && data) || `Request failed (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export const api = {
  get: (u) => request("GET", u),
  post: (u, b = {}) => request("POST", u, b),
  put: (u, b) => request("PUT", u, b),
  patch: (u, b) => request("PATCH", u, b),
  del: (u) => request("DELETE", u),
  upload: (u, form) => request("POST", u, form),
};

export function toast(msg, kind = "") {
  const el = h("div", { class: `toast ${kind}` }, msg);
  document.getElementById("toast-root").append(el);
  setTimeout(() => el.remove(), kind === "bad" ? 6000 : 3200);
}

export async function guard(fn, okMsg) {
  try {
    const out = await fn();
    if (okMsg) toast(okMsg);
    return out;
  } catch (e) {
    toast(e.message || String(e), "bad");
    return undefined;
  }
}

// ---------------------------------------------------------------- drawer / modal

let drawerClose = null;
export function openDrawer(build) {
  closeDrawer();
  const root = document.getElementById("drawer-root");
  const overlay = h("div", { class: "overlay", onclick: () => closeDrawer() });
  const panel = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true" });
  root.append(overlay, panel);
  const onKey = (e) => { if (e.key === "Escape" && !document.querySelector(".modal")) closeDrawer(); };
  document.addEventListener("keydown", onKey);
  let cleanup = null;
  drawerClose = () => {
    document.removeEventListener("keydown", onKey);
    if (cleanup) cleanup();
    root.replaceChildren();
    drawerClose = null;
  };
  cleanup = build(panel) || null;
  return panel;
}
export function closeDrawer() { if (drawerClose) drawerClose(); }

export function openModal(title, build) {
  const root = document.getElementById("modal-root");
  const overlay = h("div", { class: "overlay modal-overlay", onclick: () => close() });
  const box = h("div", { class: "modal", role: "dialog", "aria-modal": "true" }, h("h2", { style: { marginBottom: "14px" } }, title));
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { document.removeEventListener("keydown", onKey); overlay.remove(); box.remove(); }
  document.addEventListener("keydown", onKey);
  root.append(overlay, box);
  build(box, close);
  return close;
}

// ---------------------------------------------------------------- formatting

export function ago(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
export function date(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
}
export function datetime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}
export function compact(n) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n || 0);
}

export const STATUS = {
  saved: { label: "Saved", chip: "", color: "var(--text-3)" },
  applied: { label: "Applied", chip: "accent", color: "var(--accent)" },
  oa: { label: "Online assessment", chip: "violet", color: "var(--violet)" },
  interviewing: { label: "Interviewing", chip: "amber", color: "var(--amber)" },
  offer: { label: "Offer", chip: "good", color: "var(--good)" },
  rejected: { label: "Rejected", chip: "bad", color: "var(--bad)" },
  withdrawn: { label: "Withdrawn", chip: "", color: "var(--text-3)" },
  ghosted: { label: "Ghosted", chip: "", color: "var(--text-3)" },
};
export const STATUS_ORDER = Object.keys(STATUS);

export function statusChip(s) {
  const st = STATUS[s] || { label: s, chip: "" };
  return h("span", { class: `chip ${st.chip}` }, st.label);
}

export function statusSelect(value, onChange) {
  const sel = h("select", { style: { width: "auto" }, onchange: () => onChange(sel.value) },
    STATUS_ORDER.map((s) => h("option", { value: s, selected: s === value }, STATUS[s].label)));
  return sel;
}

// ---------------------------------------------------------------- inputs

export function tagInput(values, { placeholder = "Type and press Enter", suggestions = [] } = {}) {
  const list = [...(values || [])];
  const listId = suggestions.length ? `dl-${Math.random().toString(36).slice(2)}` : null;
  const input = h("input", { type: "text", placeholder, list: listId });
  const wrap = h("div", { class: "tags", onclick: () => input.focus() });
  const render = () => {
    clear(wrap,
      ...list.map((v, i) => h("span", { class: "tag" }, v,
        h("button", { type: "button", "aria-label": `Remove ${v}`, onclick: (e) => { e.stopPropagation(); list.splice(i, 1); render(); } }, "×"))),
      input,
      listId ? h("datalist", { id: listId }, suggestions.map((s) => h("option", { value: s }))) : null,
    );
  };
  const commit = () => {
    for (const part of input.value.split(",")) {
      const v = part.trim();
      if (v && !list.some((x) => x.toLowerCase() === v.toLowerCase())) list.push(v);
    }
    input.value = "";
    render();
    input.focus();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
    else if (e.key === "Backspace" && !input.value && list.length) { list.pop(); render(); input.focus(); }
  });
  input.addEventListener("blur", () => { if (input.value.trim()) commit(); });
  render();
  wrap.getValue = () => { if (input.value.trim()) commit(); return [...list]; };
  return wrap;
}

export function field(label, control, hint) {
  return h("label", { class: "field" }, label, control, hint ? h("span", { class: "hint" }, hint) : null);
}

// ---------------------------------------------------------------- extension bridge

export function extensionInfo() {
  const v = document.documentElement.dataset.ipmExtension;
  return v ? { version: v } : null;
}

export function openViaExtension(job) {
  if (!extensionInfo()) return false;
  window.postMessage({ source: "ipm-dashboard", type: "OPEN_JOB", job: { id: job.id, url: job.url, company: job.company, title: job.title } }, window.location.origin);
  return true;
}
