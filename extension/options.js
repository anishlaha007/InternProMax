const input = document.getElementById("api");
const status = document.getElementById("status");

chrome.storage.local.get("apiBase").then(({ apiBase }) => { input.value = apiBase || "http://127.0.0.1:8420"; });

document.getElementById("save").addEventListener("click", async () => {
  const base = input.value.trim().replace(/\/$/, "");
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(base)) {
    status.textContent = "Use a local address like http://127.0.0.1:8420";
    return;
  }
  await chrome.runtime.sendMessage({ type: "SET_API_BASE", apiBase: base });
  try {
    const res = await fetch(`${base}/api/health`);
    const data = await res.json();
    status.textContent = data.app === "internpromax" ? `Connected ✓ (${data.jobs.toLocaleString()} listings)` : "That server isn’t InternProMax.";
  } catch {
    status.textContent = "Saved, but nothing is answering there yet. Is the server running?";
  }
});
