// Service worker: talks to the local InternProMax server, remembers which tab belongs to which job.
const DEFAULT_API = "http://127.0.0.1:8420";

// ---------------------------------------------------------------- storage helpers

async function apiBase() {
  const { apiBase } = await chrome.storage.local.get("apiBase");
  return (apiBase || DEFAULT_API).replace(/\/$/, "");
}

async function tabState(tabId) {
  if (tabId === undefined || tabId === null) return {};
  const { tabs = {} } = await chrome.storage.session.get("tabs");
  return tabs[tabId] || {};
}

async function setTabState(tabId, patch) {
  const { tabs = {} } = await chrome.storage.session.get("tabs");
  tabs[tabId] = { ...(tabs[tabId] || {}), ...patch };
  await chrome.storage.session.set({ tabs });
  return tabs[tabId];
}

async function dropTab(tabId) {
  const { tabs = {} } = await chrome.storage.session.get("tabs");
  delete tabs[tabId];
  await chrome.storage.session.set({ tabs });
}

// ---------------------------------------------------------------- API

async function api(path, { method = "GET", body, raw = false } = {}) {
  const base = await apiBase();
  const res = await fetch(base + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (raw) return res;
  return res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
}

let profileCache = { at: 0, data: null };
async function profile() {
  if (Date.now() - profileCache.at < 30000 && profileCache.data) return profileCache.data;
  const data = await api("/api/profile");
  profileCache = { at: Date.now(), data };
  return data;
}

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function filenameFrom(res, fallback) {
  const cd = res.headers.get("content-disposition") || "";
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  return m ? decodeURIComponent(m[1]) : fallback;
}

// ---------------------------------------------------------------- handlers

async function getContext(msg, sender) {
  const tabId = sender.tab?.id;
  let health;
  try {
    health = await api("/api/health");
  } catch {
    return { apiOk: false };
  }
  let st = await tabState(tabId);
  let job = null;
  let application = null;
  let details = null;
  if (st.jobId) {
    try {
      const d = await api(`/api/jobs/${encodeURIComponent(st.jobId)}`);
      ({ job, application, details } = d);
    } catch { /* job was removed */ }
  }
  if (!job) {
    for (const url of [sender.tab?.url, msg.url].filter(Boolean)) {
      try {
        const found = await api(`/api/jobs/lookup?url=${encodeURIComponent(url)}`);
        if (found.job) {
          job = found.job;
          application = found.application;
          st = await setTabState(tabId, { jobId: job.id, company: job.company, title: job.title });
          details = (await api(`/api/jobs/${encodeURIComponent(job.id)}`)).details;
          break;
        }
        if (found.application && !application) application = found.application;
      } catch { /* lookup is best effort */ }
    }
  }
  const prof = await profile();
  return {
    apiOk: true,
    apiBase: await apiBase(),
    ai: !!health.ai,
    job,
    application,
    needsDescription: !!job && !(details && details.description),
    profile: prof.profile,
    flags: prof.flags,
    tab: st,
  };
}

async function getResume(msg, sender) {
  try {
    const st = await tabState(sender.tab?.id);
    const jobId = msg.jobId || st.jobId;
    if (!jobId && st.preparing && Date.now() - st.preparing < 60000 && !msg.noWait) return { pending: true };
    if (jobId) {
      const status = await api(`/api/jobs/${encodeURIComponent(jobId)}/resume-status`);
      if (status.use_tailored && ["queued", "running"].includes(status.tailored) && !msg.noWait) return { pending: true };
      const variant = status.use_tailored && status.tailored === "ready" ? "tailored" : "auto";
      const res = await api(`/api/jobs/${encodeURIComponent(jobId)}/resume.pdf?variant=${variant}`, { raw: true });
      return { b64: toBase64(await res.arrayBuffer()), name: filenameFrom(res, "Resume.pdf"), type: res.headers.get("content-type")?.split(";")[0] || "application/pdf", variant: res.headers.get("x-resume-variant") || variant };
    }
    let res;
    try {
      res = await api("/api/profile/resume-file", { raw: true });
    } catch (e) {
      if (e.status !== 404) throw e;
      res = await api("/api/resume/master.pdf", { raw: true });
    }
    return { b64: toBase64(await res.arrayBuffer()), name: filenameFrom(res, "Resume.pdf"), type: res.headers.get("content-type")?.split(";")[0] || "application/pdf", variant: "base" };
  } catch (e) {
    return { error: e.message };
  }
}

async function markApplied(msg, sender) {
  const tabId = sender.tab?.id;
  const st = await tabState(tabId);
  if (st.applied && st.applicationId && msg.trigger !== "manual") return { application: { id: st.applicationId, status: "applied" }, duplicate: true };
  const out = await api("/api/applications/applied", {
    method: "POST",
    body: {
      job_id: st.jobId || null,
      url: st.url || sender.tab?.url || msg.url,
      company: st.company || msg.company,
      title: st.title || msg.title,
      ats: msg.ats,
      page_title: msg.page_title,
      trigger: msg.trigger,
      source: "extension",
    },
  });
  await setTabState(tabId, { applied: true, applicationId: out.application?.id });
  refreshBadge();
  return out;
}

const POSTING_TTL = 30 * 60 * 1000;

async function createExternalJob(msg, sender) {
  const tabId = sender.tab?.id;
  let st = await tabState(tabId);
  if (st.jobId) return { job: { id: st.jobId, company: st.company, title: st.title } };
  // The form page often doesn't show the posting: fall back to the one viewed last in this tab.
  const stash = st.posting && Date.now() - st.posting.at < POSTING_TTL ? st.posting : null;
  const usePage = msg.description && msg.description.length >= 200;
  await setTabState(tabId, { preparing: Date.now() });
  try {
    const out = await api("/api/jobs/external", {
      method: "POST",
      body: {
        url: sender.tab?.url || msg.url,
        posting_url: !usePage && stash ? stash.url : null,
        company: (stash && !usePage && stash.company) || msg.company,
        title: (stash && !usePage && stash.title) || msg.title,
        location: msg.location || (stash && stash.location) || "",
        description: usePage ? msg.description : (stash ? stash.text : ""),
        source: usePage ? "page" : stash ? "viewed-posting" : "none",
      },
    });
    st = await setTabState(tabId, { jobId: out.job.id, company: out.job.company, title: out.job.title, url: out.job.url, preparing: 0, external: true });
    return out;
  } catch (e) {
    await setTabState(tabId, { preparing: 0 });
    return { error: e.message };
  }
}

async function ensureJob(sender) {
  const tabId = sender.tab?.id;
  const st = await tabState(tabId);
  if (st.jobId) return { job: { id: st.jobId, company: st.company, title: st.title } };
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "PREPARE_JOB" }, { frameId: 0 });
  } catch {
    return { job: null };
  }
}

async function openJob(msg, sender) {
  const job = msg.job;
  if (msg.apiBase) await adoptApiBase(msg.apiBase);
  const tab = await chrome.tabs.create({ url: job.url, openerTabId: sender.tab?.id, active: true });
  await setTabState(tab.id, { jobId: job.id, company: job.company, title: job.title, url: job.url, openedAt: Date.now() });
  return { tabId: tab.id };
}

async function adoptApiBase(origin) {
  // Only switch servers if the page really is an InternProMax dashboard.
  try {
    const res = await fetch(`${origin}/api/health`);
    const data = await res.json();
    if (data.app === "internpromax") {
      await chrome.storage.local.set({ apiBase: origin });
      profileCache = { at: 0, data: null };
    }
  } catch { /* keep the current base */ }
}

async function handle(msg, sender) {
  const tabId = sender.tab?.id;
  switch (msg.type) {
    case "GET_CONTEXT": return getContext(msg, sender);
    case "TAB_STATE": return tabState(tabId);
    case "GET_RESUME": return getResume(msg, sender);
    case "STASH_POSTING":
      if (msg.posting?.text) await setTabState(tabId, { posting: { ...msg.posting, at: Date.now() } });
      return { ok: true };
    case "CREATE_EXTERNAL_JOB": return createExternalJob(msg, sender);
    case "ENSURE_JOB": return ensureJob(sender);
    case "TAILOR_JOB":
      return api(`/api/jobs/${encodeURIComponent(msg.jobId)}/tailor`, { method: "POST", body: { force: true } }).catch((e) => ({ error: e.message }));
    case "AUTOFILL_FRAMES_RESUME":
      if (tabId !== undefined) chrome.tabs.sendMessage(tabId, { type: "REUPLOAD_RESUME" }).catch(() => {});
      return { ok: true };
    case "SUBMIT_ATTEMPT": await setTabState(tabId, { submitAttemptAt: Date.now(), submitTrigger: msg.trigger }); return { ok: true };
    case "MARK_APPLIED": return markApplied(msg, sender);
    case "OPEN_JOB": return openJob(msg, sender);
    case "HELLO_DASHBOARD": await adoptApiBase(msg.origin); return { ok: true };
    case "CAPTURE_DESCRIPTION": {
      const st = await tabState(tabId);
      if (st.captured) return { ok: false };
      await setTabState(tabId, { captured: true });
      return api(`/api/jobs/${encodeURIComponent(msg.jobId)}/description`, { method: "POST", body: { text: msg.text, source: "extension" } }).catch((e) => ({ error: e.message }));
    }
    case "AI_ANSWER":
      return api("/api/ai/answer", { method: "POST", body: { question: msg.question, job_id: msg.jobId || null, company: msg.company, title: msg.title } })
        .catch((e) => ({ error: e.message }));
    case "AUTOFILL_FRAMES":
      if (tabId !== undefined) chrome.tabs.sendMessage(tabId, { type: "DO_AUTOFILL" }).catch(() => {});
      return { ok: true };
    case "FORM_FOUND":
    case "FILL_REPORT":
    case "ASK_CONFIRM":
      // relay from an iframe to the top frame, which owns the panel
      if (tabId !== undefined && sender.frameId !== 0) chrome.tabs.sendMessage(tabId, msg, { frameId: 0 }).catch(() => {});
      return { ok: true };
    case "OPEN_DASHBOARD": {
      const base = await apiBase();
      await chrome.tabs.create({ url: `${base}/#/jobs` });
      return { ok: true };
    }
    // popup
    case "POPUP_STATE": {
      let health = null;
      try { health = await api("/api/health"); } catch { /* offline */ }
      const st = await tabState(msg.tabId);
      let stats = null;
      if (health) { try { stats = await api("/api/stats"); } catch { /* ignore */ } }
      return { apiOk: !!health, apiBase: await apiBase(), tab: st, stats };
    }
    case "SET_API_BASE":
      await chrome.storage.local.set({ apiBase: msg.apiBase });
      profileCache = { at: 0, data: null };
      return { ok: true };
    default:
      return { error: `unknown message ${msg.type}` };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handle(msg, sender).then(sendResponse, (e) => sendResponse({ error: e.message || String(e) }));
  return true;
});

// ---------------------------------------------------------------- tabs

chrome.tabs.onCreated.addListener(async (tab) => {
  // An application often opens in a new tab from the job page: carry the job over.
  if (tab.openerTabId === undefined) return;
  const parent = await tabState(tab.openerTabId);
  if (parent.jobId && !parent.applied) {
    await setTabState(tab.id, { jobId: parent.jobId, company: parent.company, title: parent.title, url: parent.url, openedAt: Date.now(), inherited: true });
  } else if (parent.posting && Date.now() - parent.posting.at < POSTING_TTL) {
    await setTabState(tab.id, { posting: parent.posting }); // "Apply" opened the form in a new tab
  }
});

chrome.tabs.onRemoved.addListener((tabId) => { dropTab(tabId); });

// ---------------------------------------------------------------- badge: new matches

async function refreshBadge() {
  try {
    const stats = await api("/api/stats");
    const n = stats.new_matches || 0;
    await chrome.action.setBadgeBackgroundColor({ color: "#2a63d6" });
    await chrome.action.setBadgeText({ text: n ? (n > 99 ? "99+" : String(n)) : "" });
    await chrome.action.setTitle({ title: n ? `InternProMax: ${n} new matching roles` : "InternProMax" });
  } catch {
    await chrome.action.setBadgeText({ text: "" });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("badge", { periodInMinutes: 30 });
  refreshBadge();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("badge", { periodInMinutes: 30 });
  refreshBadge();
});
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "badge") refreshBadge(); });
