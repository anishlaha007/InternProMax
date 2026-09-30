// Floating panel (top frame only), isolated from page styles with a shadow root.
(() => {
  const IPM = globalThis.IPM;

  const CSS = `
  :host { all: initial; }
  .wrap { position: fixed; right: 18px; bottom: 18px; z-index: 2147483646; font: 13px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    color: #17171b; }
  .panel { width: 318px; background: #fff; border: 1px solid #e3e2dc; border-radius: 14px; box-shadow: 0 12px 40px rgba(20,20,30,.22); overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #2a63d6; color: #fff; }
  .logo { width: 20px; height: 20px; border-radius: 5px; background: #fff; color: #2a63d6; font-weight: 800; font-size: 11px; display: grid; place-items: center; }
  .title { font-weight: 650; flex: 1; }
  .icon { background: none; border: 0; color: #fff; cursor: pointer; font-size: 15px; padding: 2px 5px; border-radius: 6px; opacity: .85; }
  .icon:hover { background: rgba(255,255,255,.18); opacity: 1; }
  .body { padding: 12px; display: flex; flex-direction: column; gap: 9px; }
  .job b { display: block; font-size: 14px; }
  .muted { color: #5b5a63; }
  .small { font-size: 12px; }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  button.btn { font: 600 12.5px/1 inherit; font-family: inherit; height: 30px; padding: 0 11px; border-radius: 8px; border: 1px solid #cfcec7; background: #fff; color: #17171b; cursor: pointer; }
  button.btn:hover { background: #f1f0ec; }
  button.primary { background: #2a63d6; border-color: #2a63d6; color: #fff; }
  button.primary:hover { background: #2253b8; }
  button.btn:disabled { opacity: .55; cursor: default; }
  .chip { display: inline-block; border-radius: 99px; padding: 1px 8px; font-size: 11.5px; font-weight: 600; background: #f1f0ec; color: #52515a; }
  .chip.good { background: #e3f3e8; color: #16803a; }
  .chip.accent { background: #e7eefc; color: #1d4ba6; }
  .chip.warn { background: #fdf1d4; color: #8a5a00; }
  .chip.bad { background: #fbe9e7; color: #c0392f; }
  .box { background: #f6f6f3; border-radius: 9px; padding: 8px 10px; }
  ul { margin: 4px 0 0; padding-left: 16px; max-height: 110px; overflow: auto; }
  li { margin: 1px 0; }
  input { width: 100%; box-sizing: border-box; height: 28px; border: 1px solid #cfcec7; border-radius: 7px; padding: 0 8px; font: inherit; }
  a { color: #1d4ba6; text-decoration: none; cursor: pointer; }
  .pill { display: flex; align-items: center; gap: 8px; background: #2a63d6; color: #fff; border-radius: 99px; padding: 7px 12px 7px 8px; cursor: pointer; box-shadow: 0 8px 26px rgba(20,20,30,.25); font-weight: 600; }
  .spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #cfd9f5; border-top-color: #2a63d6; animation: s .8s linear infinite; display: inline-block; vertical-align: -2px; }
  @keyframes s { to { transform: rotate(360deg); } }
  @media (prefers-color-scheme: dark) {
    .panel { background: #1b1b1e; border-color: #2e2e33; color: #f1f1f3; }
    .muted { color: #b9b8c0; } .box { background: #232327; }
    button.btn { background: #232327; border-color: #3d3d44; color: #f1f1f3; } button.btn:hover { background: #2c2c31; }
    .chip { background: #2c2c31; color: #b9b8c0; } input { background: #232327; color: #f1f1f3; border-color: #3d3d44; }
    a { color: #9dbdf7; }
  }`;

  let host = null;
  let root = null;
  let state = {};
  let handlers = {};

  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "class") n.className = v;
      else n.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : String(kid));
    return n;
  }

  const STATUS = { saved: "Saved", applied: "Applied", oa: "Online assessment", interviewing: "Interviewing", offer: "Offer", rejected: "Rejected", withdrawn: "Withdrawn", ghosted: "Ghosted" };

  function render() {
    if (!root) return;
    const s = state;
    const wrap = el("div", { class: "wrap" });
    if (s.minimized) {
      wrap.append(el("div", { class: "pill", role: "button", tabindex: "0", title: "Open InternProMax", onclick: () => update({ minimized: false }) },
        el("span", { class: "logo" }, "IP"),
        s.applied ? "Applied ✓" : s.busy ? "Filling…" : s.fillCount ? `${s.fillCount} fields filled` : "InternProMax"));
      root.replaceChildren(wrap);
      return;
    }
    const status = s.applied ? el("span", { class: "chip good" }, "✓ Tracked as applied")
      : s.application ? el("span", { class: "chip accent" }, STATUS[s.application.status] || s.application.status)
        : el("span", { class: "chip" }, "Not applied yet");

    const jobBlock = s.job
      ? el("div", { class: "job" }, el("b", {}, s.job.company), el("span", { class: "muted" }, s.job.title))
      : el("div", { class: "stack" },
        el("div", { class: "small muted" }, "Not in your job list. It will be tracked as:"),
        el("input", { value: s.guess?.company || "", placeholder: "Company", "aria-label": "Company", oninput: (e) => { state.guess = { ...state.guess, company: e.target.value }; } }),
        el("input", { value: s.guess?.title || "", placeholder: "Role", "aria-label": "Role", style: "margin-top:5px", oninput: (e) => { state.guess = { ...state.guess, title: e.target.value }; } }));

    const resumeLine = s.resume ? el("div", { class: "small" }, "Resume: ", s.resume === "pending" ? [el("span", { class: "spin" }), " tailoring your resume to this posting… ",
      el("a", { onclick: () => handlers.onUseBase && handlers.onUseBase() }, "use base now")] : [s.resume,
      s.resumeVariant && s.resumeVariant !== "tailored" && s.canTailor ? [" · ", el("a", { onclick: () => handlers.onTailor && handlers.onTailor() }, "tailor it to this job")] : null]) : null;

    const needs = (s.needsYou || []).filter((n) => n.label);
    const body = el("div", { class: "body" },
      el("div", { class: "row", style: "justify-content:space-between" }, jobBlock, status),
      !s.apiOk ? el("div", { class: "box small" }, el("span", { class: "chip bad" }, s.needsLogin ? "Log in" : "Offline"),
        s.needsLogin ? " Open the InternProMax extension’s Options and click Connect to log in to your server."
          : " Start InternProMax (python -m internpromax) or check the server address in the extension’s Options.") : null,
      el("div", { class: "row" },
        el("button", { class: "btn primary", disabled: !s.apiOk || s.busy ? "" : null, onclick: () => handlers.onAutofill() },
          s.busy ? "Filling…" : s.fillCount ? "Fill again" : "Autofill"),
        !s.applied ? el("button", { class: "btn", disabled: !s.apiOk ? "" : null, onclick: () => handlers.onMarkApplied() }, "Mark applied") : null,
        s.dashboard ? el("a", { class: "small", onclick: () => handlers.onOpenDashboard() }, "Dashboard ↗") : null),
      s.preparing ? el("div", { class: "small" }, el("span", { class: "spin" }), " Reading the job posting on this page…") : null,
      s.fillCount || s.filledNote ? el("div", { class: "small muted" }, s.filledNote || `Filled ${s.fillCount} field${s.fillCount === 1 ? "" : "s"}. Review everything before you submit.`) : null,
      resumeLine,
      needs.length ? el("div", { class: "box small" }, el("b", {}, `${needs.length} question${needs.length === 1 ? "" : "s"} need${needs.length === 1 ? "s" : ""} you`),
        s.ai ? el("span", { class: "muted" }, " (✨ Draft buttons are next to the text boxes)") : null,
        el("ul", {}, needs.slice(0, 8).map((n) => el("li", {}, n.label)))) : null,
      s.askConfirm ? el("div", { class: "box small" }, el("div", {}, el("b", {}, "Did your application go through?")),
        el("div", { class: "row", style: "margin-top:6px" },
          el("button", { class: "btn primary", onclick: () => handlers.onConfirm(true) }, "Yes, mark applied"),
          el("button", { class: "btn", onclick: () => handlers.onConfirm(false) }, "Not yet"))) : null,
      s.message ? el("div", { class: "small muted" }, s.message) : null,
    );
    wrap.append(el("div", { class: "panel", role: "dialog", "aria-label": "InternProMax" },
      el("div", { class: "head" }, el("span", { class: "logo" }, "IP"), el("span", { class: "title" }, "InternProMax"),
        el("button", { class: "icon", title: "Minimize", "aria-label": "Minimize", onclick: () => update({ minimized: true }) }, "–"),
        el("button", { class: "icon", title: "Close", "aria-label": "Close", onclick: () => destroy() }, "×")),
      body));
    root.replaceChildren(wrap);
  }

  function mount(initial, h) {
    handlers = h;
    state = { ...initial };
    if (!host) {
      host = document.createElement("internpromax-panel");
      root = host.attachShadow({ mode: "closed" });
      const style = document.createElement("style");
      style.textContent = CSS;
      root.append(style);
      const holder = document.createElement("div");
      root.append(holder);
      root = holder;
      (document.body || document.documentElement).append(host);
    }
    render();
  }

  function update(patch) {
    state = { ...state, ...patch };
    render();
  }

  function destroy() {
    if (host) host.remove();
    host = null;
    root = null;
  }

  IPM.panel = { mount, update, destroy, get state() { return state; }, get mounted() { return !!host; } };
})();
