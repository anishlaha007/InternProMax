const main = document.getElementById("main");

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "class") n.className = v;
    else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) n.append(k instanceof Node ? k : String(k));
  return n;
}

async function render() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const s = await chrome.runtime.sendMessage({ type: "POPUP_STATE", tabId: tab?.id });
  const state = s.tab || {};
  main.replaceChildren(
    el("div", {}, el("span", { class: "dot", style: `background:${s.apiOk ? "#16803a" : "#c0392f"}` }),
      s.apiOk ? "Connected to InternProMax" : s.needsLogin ? "Log in to your InternProMax server" : "Can’t reach InternProMax",
      el("div", { class: "muted", style: "font-size:11.5px" }, s.apiBase)),
    !s.apiOk ? el("div", { class: "box" }, s.needsLogin ? "Your server needs your password. " : ["Start it with ", el("code", {}, "python -m internpromax"), ", or "],
      el("a", { href: "#", onclick: (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); } }, s.needsLogin ? "Log in from Options" : "set the address in Options"), ".") : null,
    s.stats ? el("div", { class: "box" },
      el("b", {}, `${s.stats.new_matches || 0} new matches`), el("span", { class: "muted" }, ` · ${s.stats.matches} total`), el("br"),
      el("span", { class: "muted" }, `${s.stats.submitted} applications sent · ${Math.round((s.stats.response_rate || 0) * 100)}% response rate`)) : null,
    state.jobId ? el("div", { class: "box" }, el("div", { class: "muted", style: "font-size:11.5px" }, "This tab"),
      el("b", {}, state.company || ""), el("div", {}, state.title || ""), state.applied ? el("div", { style: "color:#16803a;font-weight:600" }, "✓ Tracked as applied") : null) : null,
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: async () => {
        await chrome.tabs.sendMessage(tab.id, { type: "DO_AUTOFILL" }).catch(() => {});
        window.close();
      } }, "Autofill this page"),
      el("button", { onclick: async () => {
        await chrome.tabs.sendMessage(tab.id, { type: "MARK_APPLIED_NOW" }, { frameId: 0 }).catch(() => {});
        window.close();
      } }, "Mark applied")),
    el("div", { class: "row" },
      el("button", { onclick: () => chrome.tabs.create({ url: `${s.apiBase}/#/jobs` }) }, "Jobs"),
      el("button", { onclick: () => chrome.tabs.create({ url: `${s.apiBase}/#/tracker` }) }, "Tracker"),
      el("button", { onclick: () => chrome.runtime.openOptionsPage() }, "Options")),
  );
}

render();
