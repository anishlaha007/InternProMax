const input = document.getElementById("api");
const pw = document.getElementById("pw");
const status = document.getElementById("status");

chrome.storage.local.get("apiBase").then(({ apiBase }) => { input.value = apiBase || "http://127.0.0.1:8420"; });

document.getElementById("form").addEventListener("submit", (e) => {
  e.preventDefault();
  let url;
  try {
    url = new URL(input.value.trim());
    if (!/^https?:$/.test(url.protocol)) throw new Error("bad scheme");
  } catch {
    status.textContent = "Enter an address like http://127.0.0.1:8420 or http://my-server:8420";
    return;
  }
  const origin = url.origin;
  const base = (origin + url.pathname).replace(/\/$/, "");
  // Must be called straight from the click, before any await, or Chrome won't show the prompt.
  chrome.permissions.request({ origins: [`${origin}/*`] }, (granted) => {
    if (!granted) {
      status.textContent = "The extension needs permission to talk to that address.";
      return;
    }
    connect(base).catch((err) => { status.textContent = `Couldn’t connect: ${err.message}`; });
  });
});

async function connect(base) {
  status.textContent = "Connecting…";
  const health = await (await fetch(`${base}/api/health`)).json();
  if (health.app !== "internpromax") {
    status.textContent = "That address isn’t an InternProMax server.";
    return;
  }
  let token = null;
  if (health.auth_required) {
    const res = await fetch(`${base}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw.value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Wrong password";
      return;
    }
    token = data.token;
  }
  const out = await chrome.runtime.sendMessage({ type: "SET_SERVER", apiBase: base, token });
  if (out && out.error) {
    status.textContent = `Saved, but: ${out.error}`;
    return;
  }
  pw.value = "";
  status.textContent = health.auth_required ? "Connected and logged in ✓" : "Connected ✓";
}
