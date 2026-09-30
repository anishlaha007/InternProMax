// Settings: listing sources, automation, AI, email (IMAP), extension, data.
import { h, clear, api, guard, toast, ago, field, extensionInfo } from "./lib.js";

export async function renderSettings(main, refreshNav) {
  const [s, meta, authState] = await Promise.all([guard(() => api.get("/api/settings")), guard(() => api.get("/api/meta")), guard(() => api.get("/api/auth/status"))]);
  if (!s || !meta) return;
  const S = structuredClone(s);
  const reload = () => renderSettings(main, refreshNav);

  const bool = (obj, key, label, hint) => {
    const el = h("input", { type: "checkbox", checked: !!obj[key] });
    el.addEventListener("change", () => { obj[key] = el.checked; });
    return h("div", {}, h("label", { class: "check" }, el, label), hint ? h("div", { class: "hint", style: { marginLeft: "22px" } }, hint) : null);
  };
  const input = (obj, key, attrs = {}) => {
    const el = h("input", { type: "text", ...attrs, value: obj[key] ?? "" });
    el.addEventListener("input", () => { obj[key] = attrs.type === "number" ? Number(el.value) : el.value; });
    return el;
  };
  const choose = (obj, key, options) => {
    const el = h("select", {}, options.map(([v, l]) => h("option", { value: v, selected: String(obj[key]) === String(v) }, l)));
    el.addEventListener("change", () => { obj[key] = el.value; });
    return el;
  };

  // ---- sources
  const sourceRows = h("div", { class: "stack" });
  const renderSources = () => clear(sourceRows, S.sources.map((src, i) => {
    const m = s.source_meta?.[src.url] || {};
    const en = h("input", { type: "checkbox", checked: !!src.enabled });
    en.addEventListener("change", () => { src.enabled = en.checked; });
    return h("div", { class: "row between", style: { padding: "8px 0", borderBottom: "1px solid var(--border)" } },
      h("label", { class: "check grow" }, en, h("span", { class: "grow" }, h("b", {}, src.name || "Custom list"), h("div", { class: "tiny faint ellipsis" }, src.url))),
      h("span", { class: "small muted nowrap" }, m.error ? h("span", { style: { color: "var(--bad)" } }, "Sync error") : m.synced_at ? `${(m.total || 0).toLocaleString()} listings · ${ago(m.synced_at)}` : "Not synced"),
      i >= 2 ? h("button", { class: "btn btn-ghost btn-sm btn-icon", "aria-label": "Remove source", onclick: () => { S.sources.splice(i, 1); renderSources(); } }, "✕") : null);
  }));
  renderSources();
  const newUrl = h("input", { type: "url", placeholder: "https://raw.githubusercontent.com/<owner>/<repo>/<branch>/.github/scripts/listings.json" });

  const key = h("input", { type: "password", placeholder: s.anthropic_api_key_set ? (s.anthropic_api_key_from_env ? "Using ANTHROPIC_API_KEY from the environment" : "•••••••• saved") : "sk-ant-…", autocomplete: "off" });
  const imapPass = h("input", { type: "password", placeholder: s.imap.password_set ? "•••••••• saved" : "App password", autocomplete: "off" });
  const ext = extensionInfo();

  const save = async () => {
    const payload = structuredClone(S);
    delete payload.source_meta; delete payload.last_sync; delete payload.imap_last;
    payload.anthropic_api_key = key.value.trim() || null;
    payload.imap.password = imapPass.value;
    const res = await guard(() => api.put("/api/settings", payload), "Settings saved");
    if (res) { refreshNav(); reload(); }
  };

  clear(main,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Settings"), h("div", { class: "sub" }, "Data lives in the data/ folder next to the app. Nothing is uploaded anywhere except Claude API calls when AI is on."))),

    h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "Job lists"),
        h("button", { class: "btn btn-sm", onclick: async () => { await guard(() => api.post("/api/sync", { force: true }), "Syncing in the background…"); } }, "Sync now")),
      h("p", { class: "small muted" }, "Any GitHub repo that publishes a SimplifyJobs-style listings.json works. The Summer 2027 list also includes off-season terms, which is where co-ops show up."),
      sourceRows,
      h("div", { class: "row", style: { marginTop: "10px" } }, newUrl,
        h("button", { class: "btn btn-sm", onclick: () => {
          const url = newUrl.value.trim();
          if (!/^https:\/\//.test(url)) { toast("Enter an https URL to a listings.json file", "bad"); return; }
          S.sources.push({ name: url.split("/").slice(3, 5).join("/"), url, enabled: true });
          newUrl.value = ""; renderSources();
        } }, "Add list")),
      h("div", { class: "grid g3", style: { marginTop: "12px" } },
        field("Re-sync every", choose(S, "sync_interval_hours", [[1, "1 hour"], [3, "3 hours"], [6, "6 hours"], [12, "12 hours"], [24, "24 hours"]])))),

    h("div", { class: "card" }, h("h2", {}, "When you click Apply"),
      h("div", { class: "stack" },
        bool(S, "auto_analyze_on_apply", "Analyze the posting automatically", "Pulls the full description and extracts required skills, projects they want, constraints and your gaps."),
        bool(S, "auto_tailor_on_apply", "Tailor my resume automatically", "Builds a tailored version from your master resume while the application page loads."),
        bool(S, "use_tailored_resume", "Upload the tailored resume in forms (falls back to your uploaded file)"),
        bool(S, "autofill_on_load", "Autofill as soon as an application form is detected", "Otherwise click Autofill in the extension panel."),
        bool(S, "tailor_any_site", "Work on any job site, not just jobs from your lists", "When you open an application anywhere, the extension reads the posting on the page (or the one you just viewed), adds the job to your tracker, and tailors your resume to it before attaching it."))),

    h("div", { class: "card" }, h("h2", {}, "AI (Claude)"),
      h("p", { class: "small muted" }, "Optional. Without a key, the built-in analyzer and tailoring still work. With a key, Claude reads postings like a recruiter, rewrites bullets toward what each posting wants (never inventing anything), drafts answers to free-text questions, and classifies unclear emails."),
      h("div", { class: "grid g3" },
        h("div", { class: "span2" }, field("Anthropic API key", key, "Stored in your local database. Get one at console.anthropic.com.")),
        field("Model", choose(S, "ai_model", meta.ai_models.map((m) => [m, m]))),
        field("Effort", choose(S, "ai_effort", [["low", "Low (fastest)"], ["medium", "Medium"], ["high", "High (most thorough)"]]))),
      s.anthropic_api_key_set && !s.anthropic_api_key_from_env
        ? h("button", { class: "btn btn-sm btn-ghost btn-danger", style: { marginTop: "8px" }, onclick: async () => { await guard(() => api.post("/api/settings/clear-secret", { name: "anthropic_api_key" }), "Key removed"); reload(); } }, "Remove saved key") : null),

    h("div", { class: "card" }, h("h2", {}, "Email updates (IMAP)"),
      h("p", { class: "small muted" }, "For Gmail: turn on 2-Step Verification, create an app password at myaccount.google.com/apppasswords, and use imap.gmail.com. Emails are read-only and processed locally."),
      h("div", { class: "grid g3" },
        h("div", { class: "span-all" }, bool(S.imap, "enabled", "Check my inbox automatically")),
        field("IMAP host", input(S.imap, "host")), field("Port", input(S.imap, "port", { type: "number" })), field("Folder", input(S.imap, "folder")),
        field("Email / username", input(S.imap, "username", { type: "email" })), field("App password", imapPass),
        field("Look back (days)", input(S.imap, "lookback_days", { type: "number" })),
        field("Check every (minutes)", input(S.imap, "interval_minutes", { type: "number" })),
        h("div", { class: "span2" }, bool(S, "email_auto_apply", "Apply high-confidence updates without asking", "Only moves applications forward (never reopens a rejection).")),
        field("Auto-apply confidence", choose(S, "email_auto_apply_min_confidence", [[0.75, "75%"], [0.85, "85%"], [0.9, "90%"]])))),

    h("div", { class: "card" }, h("h2", {}, "Chrome extension"),
      ext ? h("div", { class: "callout good" }, `Connected (v${ext.version}). Apply buttons open jobs with autofill and automatic tracking.`)
        : h("div", { class: "callout warn" }, "Not detected on this page."),
      h("ol", { class: "small", style: { marginTop: "10px" } },
        h("li", {}, "Open chrome://extensions and turn on Developer mode."),
        h("li", {}, "Click “Load unpacked” and choose the extension/ folder in this project."),
        authState?.auth_required
          ? h("li", {}, "Open the extension’s Options (right-click its icon → Options), enter ", h("b", {}, location.origin), " and your password, and click Connect.")
          : null,
        h("li", {}, "Reload this dashboard. The sidebar will say “Extension connected”."))),

    authState?.auth_required ? h("div", { class: "card" }, h("h2", {}, "Server"),
      h("p", { class: "small muted" }, "This InternProMax is running in server mode with a password."),
      h("button", { class: "btn btn-sm", onclick: async () => { await api.post("/api/auth/logout"); location.href = "/login.html"; } }, "Log out")) : null,

    h("div", { class: "card" }, h("h2", {}, "Your data"),
      h("div", { class: "row wrap" },
        h("a", { class: "btn btn-sm", href: "/api/export" }, "Export everything (JSON)"),
        h("a", { class: "btn btn-sm", href: "/api/export/applications.csv" }, "Export applications (CSV)"))),

    h("div", { class: "sticky-save" }, h("div", { class: "inner" }, h("button", { class: "btn btn-primary", onclick: save }, "Save settings"))),
  );
}
