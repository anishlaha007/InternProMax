// Runs on localhost pages. On the InternProMax dashboard it lets "Apply" open jobs through the
// extension (so the new tab is linked to the job) and tells the dashboard the extension is installed.
(() => {
  const version = chrome.runtime.getManifest().version;
  const root = () => document.documentElement;
  if (root()) root().dataset.ipmExtension = version;

  const announce = () => {
    root().dataset.ipmExtension = version;
    if (!root().dataset.ipmDashboard) return;
    window.dispatchEvent(new Event("ipm-extension-ready"));
    chrome.runtime.sendMessage({ type: "HELLO_DASHBOARD", origin: location.origin }).catch(() => {});
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", announce, { once: true });
  else announce();

  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== location.origin) return;
    const data = e.data || {};
    if (data.source !== "ipm-dashboard" || !root().dataset.ipmDashboard) return;
    if (data.type === "OPEN_JOB" && data.job && /^https?:\/\//.test(data.job.url || "")) {
      chrome.runtime.sendMessage({ type: "OPEN_JOB", job: data.job, apiBase: location.origin }).catch(() => {});
    }
  });
})();
