// Inbox: paste an email or review IMAP suggestions → update application status.
import { h, clear, api, guard, toast, ago, datetime, STATUS, STATUS_ORDER, statusChip, field } from "./lib.js";

export async function renderInbox(main, refreshNav) {
  const [apps, sugg, settings] = await Promise.all([
    guard(() => api.get("/api/applications")), guard(() => api.get("/api/email/suggestions")), guard(() => api.get("/api/settings")),
  ]);
  if (!apps || !sugg || !settings) return;
  const reload = () => renderInbox(main, refreshNav).then(refreshNav);
  const appOptions = (selected) => [h("option", { value: "" }, "Choose application…"),
    ...apps.items.map((a) => h("option", { value: a.id, selected: a.id === selected }, `${a.company}: ${a.title || "(no title)"} [${STATUS[a.status].label}]`))];
  const statusOptions = (selected) => STATUS_ORDER.map((s) => h("option", { value: s, selected: s === selected }, STATUS[s].label));

  // ---- paste flow
  const from = h("input", { type: "text", placeholder: "recruiting@company.com (optional)" });
  const subject = h("input", { type: "text", placeholder: "Your application to …" });
  const body = h("textarea", { placeholder: "Paste the email text here", style: { minHeight: "150px" } });
  const result = h("div");
  const analyze = async () => {
    if (!body.value.trim() && !subject.value.trim()) { toast("Paste an email first", "bad"); return; }
    const r = await guard(() => api.post("/api/email/analyze", { from: from.value, subject: subject.value, body: body.value }));
    if (!r) return;
    const appSel = h("select", {}, appOptions(r.application?.id));
    const stSel = h("select", {}, statusOptions(r.status || "applied"));
    clear(result, h("div", { class: "card", style: { marginTop: "12px", background: "var(--surface-2)" } },
      r.status
        ? h("div", { class: "row wrap" }, h("span", {}, "Looks like: "), statusChip(r.status),
          h("span", { class: "muted small" }, `${Math.round(r.status_confidence * 100)}% sure`, r.method === "ai" ? " · AI" : "",
            r.reasons?.length ? ` · matched “${r.reasons.join("”, “")}”` : ""))
        : h("div", { class: "muted" }, "Couldn’t tell what this email means. Pick the status yourself."),
      h("div", { class: "small muted", style: { margin: "6px 0 10px" } },
        r.application ? `Matched ${r.application.company} (${r.match_reason})` : "No matching application found. Choose one below.",
        r.application && r.status && !r.would_advance ? " · this wouldn’t move the application forward" : ""),
      h("div", { class: "grid g2" }, field("Application", appSel), field("New status", stSel)),
      h("div", { class: "row", style: { marginTop: "10px", justifyContent: "flex-end" } },
        h("button", { class: "btn btn-primary", onclick: async () => {
          if (!appSel.value) { toast("Choose which application this is about", "bad"); return; }
          if (await guard(() => api.post("/api/email/apply", { application_id: Number(appSel.value), status: stSel.value, from: from.value, subject: subject.value, body: body.value }), "Application updated")) {
            from.value = subject.value = body.value = ""; clear(result); reload();
          }
        } }, "Update application"))));
  };

  // ---- IMAP suggestions
  const imap = settings.imap || {};
  const suggestions = sugg.items.map((s) => {
    const appSel = h("select", {}, appOptions(s.application_id));
    const stSel = h("select", {}, statusOptions(s.suggested_status));
    return h("div", { class: "card" },
      h("div", { class: "row between wrap" },
        h("div", { class: "grow" }, h("b", {}, s.subject || "(no subject)"), h("div", { class: "small muted" }, s.sender, " · ", s.received_at ? datetime(s.received_at) : ago(s.created_at))),
        h("div", { class: "row" }, statusChip(s.suggested_status), h("span", { class: "small muted" }, `${Math.round((s.confidence || 0) * 100)}%`))),
      h("p", { class: "small muted", style: { margin: "8px 0" } }, s.snippet),
      h("div", { class: "grid g2" }, field("Application", appSel), field("Status", stSel)),
      h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "10px" } },
        h("button", { class: "btn btn-ghost", onclick: async () => { await guard(() => api.post(`/api/email/suggestions/${s.id}/dismiss`)); reload(); } }, "Dismiss"),
        h("button", { class: "btn btn-primary", onclick: async () => {
          if (await guard(() => api.post(`/api/email/suggestions/${s.id}/accept`, { status: stSel.value, application_id: appSel.value ? Number(appSel.value) : null }), "Application updated")) reload();
        } }, "Accept")));
  });

  clear(main,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Inbox"), h("div", { class: "sub" }, "Turn recruiter emails into status updates: rejected, online assessment, interview, offer.")),
      h("div", { class: "row" },
        imap.enabled && imap.username
          ? h("button", { class: "btn btn-sm", onclick: async (e) => {
            e.target.disabled = true;
            const r = await guard(() => api.post("/api/email/imap-sync"));
            e.target.disabled = false;
            if (r) { toast(`Checked ${r.checked} emails · ${r.suggested} new suggestions${r.applied ? ` · ${r.applied} applied automatically` : ""}`); reload(); }
          } }, "Check email now")
          : h("a", { class: "btn btn-sm", href: "#/settings" }, "Connect email (IMAP)"))),
    h("div", { class: "card" }, h("h2", {}, "Paste an email"),
      h("div", { class: "grid g2" }, field("From", from), field("Subject", subject), h("div", { class: "span2" }, field("Body", body))),
      h("div", { class: "row", style: { marginTop: "10px", justifyContent: "flex-end" } }, h("button", { class: "btn btn-primary", onclick: analyze }, "Analyze")),
      result),
    h("div", { class: "section-title", style: { margin: "24px 0 10px" } }, `Suggested updates from your email (${sugg.items.length})`),
    suggestions.length ? suggestions : h("div", { class: "card empty" },
      h("p", {}, imap.enabled ? "No pending suggestions. New recruiting emails show up here after each check."
        : "Connect your inbox in Settings (Gmail works with an app password) and matching emails will show up here automatically.")),
    settings.imap_last ? h("p", { class: "small faint", style: { marginTop: "10px" } }, `Last checked ${ago(settings.imap_last.at)} · ${settings.imap_last.checked} emails scanned`) : null,
  );
}
