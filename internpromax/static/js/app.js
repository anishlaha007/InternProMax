// Router + sidebar.
import { api, guard, toast, ago, closeDrawer, extensionInfo } from "./lib.js";
import { renderJobs } from "./jobs.js";
import { renderTracker } from "./tracker.js";
import { renderInbox } from "./inbox.js";
import { renderProfile } from "./profile.js";
import { renderSettings } from "./settings.js";

const main = document.getElementById("main");
const routes = { jobs: renderJobs, tracker: renderTracker, inbox: renderInbox, profile: renderProfile, settings: renderSettings };

async function refreshNav() {
  const [stats, health, prof] = await Promise.all([
    api.get("/api/stats").catch(() => null), api.get("/api/health").catch(() => null), api.get("/api/profile").catch(() => null),
  ]);
  const set = (id, text, badge) => {
    const el = document.getElementById(id);
    el.textContent = text || "";
    el.classList.toggle("badge", !!badge && !!text);
  };
  if (stats) {
    set("nav-jobs", stats.new_matches ? `${stats.new_matches} new` : stats.matches ? String(stats.matches) : "", !!stats.new_matches);
    set("nav-tracker", stats.submitted ? String(stats.submitted) : "");
    set("nav-inbox", stats.pending_emails ? String(stats.pending_emails) : "", !!stats.pending_emails);
  }
  if (prof) set("nav-profile", prof.completeness.score < 100 ? `${prof.completeness.score}%` : "");
  const status = document.getElementById("sync-status");
  if (health) {
    status.textContent = health.sync_running ? "Syncing listings…"
      : health.last_sync ? `${health.jobs.toLocaleString()} listings · synced ${ago(health.last_sync.at)}` : "Listings not synced yet";
  }
  const ext = extensionInfo();
  const extEl = document.getElementById("ext-status");
  extEl.textContent = ext ? "● Extension connected" : "○ Extension not detected";
  extEl.style.color = ext ? "var(--good)" : "var(--text-3)";
  return health;
}

async function route() {
  closeDrawer();
  const name = (location.hash.replace(/^#\/?/, "").split("?")[0] || "jobs");
  const render = routes[name] || routes.jobs;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  main.focus({ preventScroll: true });
  await render(main, refreshNav);
}

document.getElementById("sync-btn").addEventListener("click", async (e) => {
  e.target.disabled = true;
  await guard(() => api.post("/api/sync", {}), "Syncing listings in the background…");
  const poll = setInterval(async () => {
    const h = await refreshNav();
    if (h && !h.sync_running) {
      clearInterval(poll);
      e.target.disabled = false;
      const r = h.last_sync?.results || [];
      const err = r.find((x) => x.error);
      if (err) toast(`Sync problem: ${err.error}`, "bad");
      else toast(`Synced: ${r.reduce((n, x) => n + (x.added || 0), 0)} new listings`);
      if ((location.hash || "#/jobs").startsWith("#/jobs")) route();
    }
  }, 1500);
});

window.addEventListener("hashchange", route);
window.addEventListener("ipm-extension-ready", () => refreshNav());

(async () => {
  const health = await refreshNav();
  if (health && !health.last_sync && !health.sync_running && health.jobs === 0) {
    toast("Pulling the latest internship listings…");
    await api.post("/api/sync", {}).catch(() => {});
    const poll = setInterval(async () => {
      const h = await refreshNav();
      if (h && !h.sync_running) { clearInterval(poll); route(); }
    }, 1500);
  }
  route();
})();
