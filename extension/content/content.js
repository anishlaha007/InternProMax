// Content script entry: detect application forms, autofill, upload resume, detect submission, capture postings.
(() => {
  const IPM = globalThis.IPM;
  if (!IPM || IPM.started) return;
  IPM.started = true;
  if (document.documentElement.dataset.ipmDashboard) return; // never act on the InternProMax dashboard itself

  const TOP = window === window.top;
  const CONFIRM_RE = /(thank(s| you) for (applying|your application|submitting)|application (has been |was )?(successfully )?(submitted|received|sent|complete)|we('ve| have) (successfully )?received your application|your application (has been|was) (successfully )?(submitted|received)|successfully (applied|submitted)|you('ve| have) (successfully )?applied|application submitted)/i;
  const CONFIRM_URL = /(confirmation|thank[-_]?you|\/thanks|submitted|application[-_]?complete|\/success)/i;
  const SUBMIT_TEXT = /^(submit|send|submit( my| your)? application|send( my)? application|submit & apply|submit and (apply|finish)|complete( my)? application|finish( application)?)$/i;
  const APPLY_TEXT = /^(apply|apply now|submit & apply)$/i;
  const JD_HINT = /(responsibilit|qualification|requirement|what you('ll| will) (do|bring|need)|about the (role|team|job)|who you are|nice to have|preferred)/gi;

  const send = (msg) => new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(msg, (res) => resolve(chrome.runtime.lastError ? { error: chrome.runtime.lastError.message } : res || {}));
    } catch (e) {
      resolve({ error: String(e) }); // extension reloaded: this page is orphaned
    }
  });

  let ctx = null;
  let active = false;
  let autoFilled = false;
  let resumeDone = false;
  let submitAttemptAt = 0;
  let preSubmitConfirm = false;
  let appliedSent = false;
  let totalFilled = 0;
  let needsYou = [];

  // ---------------------------------------------------------------- activation

  function looksLikeApplication() {
    return IPM.applicationScore() >= 4;
  }

  async function activate(reason) {
    if (active) return;
    active = true;
    ctx = await send({ type: "GET_CONTEXT", url: location.href });
    if (ctx.error && !ctx.apiOk) ctx = { apiOk: false };
    const formHere = looksLikeApplication();
    if (!TOP && formHere) send({ type: "FORM_FOUND" });
    if (TOP && (formHere || ctx.job || reason === "form-in-frame")) showPanel();
    // Capture the posting first so the server can tailor the resume before we attach one.
    if (TOP) await maybeCaptureDescription();
    if (ctx.tab && ctx.tab.submitAttemptAt && Date.now() - ctx.tab.submitAttemptAt < 3 * 60 * 1000 && !ctx.tab.applied) {
      // A submit happened on the previous page in this tab: is this the confirmation page?
      preSubmitConfirm = false;
      submitAttemptAt = ctx.tab.submitAttemptAt;
      watchConfirmation();
    }
    if (formHere && ctx.apiOk && ctx.flags?.autofill_on_load && !ctx.tab?.applied) {
      runAutofill({ auto: true });
    }
  }

  function guessJob() {
    const title = document.querySelector("h1")?.innerText?.trim() || document.title;
    const og = document.querySelector('meta[property="og:site_name"]')?.content;
    const host = location.hostname.replace(/^www\./, "");
    const parts = location.pathname.split("/").filter(Boolean);
    const ats = IPM.atsName();
    let company = og || "";
    if (!company && ["greenhouse", "lever", "ashby", "smartrecruiters"].includes(ats) && parts[0]) company = parts[0].replace(/[-_]+/g, " ");
    if (!company && ats === "workday") company = host.split(".")[0];
    if (!company) company = host.split(".").slice(-2, -1)[0] || host;
    company = company.replace(/\b\w/g, (c) => c.toUpperCase());
    return { company, title: (title || "").slice(0, 120) };
  }

  function showPanel() {
    if (!TOP || IPM.panel.mounted) return;
    IPM.panel.mount({
      apiOk: !!ctx.apiOk, job: ctx.job, application: ctx.application, applied: !!ctx.tab?.applied || ["applied", "oa", "interviewing", "offer"].includes(ctx.application?.status),
      ai: !!ctx.ai, guess: ctx.job ? null : guessJob(), dashboard: !!ctx.apiBase, minimized: false,
    }, {
      onAutofill: () => runAutofill({ auto: false }),
      onMarkApplied: () => markApplied("manual"),
      onConfirm: (yes) => { IPM.panel.update({ askConfirm: false }); if (yes) markApplied("confirmed-by-you"); },
      onOpenDashboard: () => send({ type: "OPEN_DASHBOARD", jobId: ctx.job?.id }),
      onUseBase: () => { useBaseNow = true; },
    });
  }

  // ---------------------------------------------------------------- autofill

  let fillRunning = false;
  let useBaseNow = false;

  async function runAutofill({ auto, onlyNew = false }) {
    if (fillRunning || !ctx?.apiOk || !ctx.profile) return;
    fillRunning = true;
    if (TOP) IPM.panel.update({ busy: true });
    if (!auto && TOP) send({ type: "AUTOFILL_FRAMES" }); // ask iframes (embedded forms) to fill too
    try {
      const report = await IPM.autofill(ctx.profile, { onlyNew });
      totalFilled += report.filled.length;
      mergeNeeds(report.needsYou);
      addAiButtons(report.needsYou);
      autoFilled = true;
      await uploadResume();
      if (TOP) IPM.panel.update({ busy: false, fillCount: totalFilled, needsYou: publicNeeds() });
      else send({ type: "FILL_REPORT", report: { filled: report.filled.length, needsYou: publicNeeds() } });
    } finally {
      fillRunning = false;
      if (TOP) IPM.panel.update({ busy: false });
    }
  }

  function mergeNeeds(list) {
    for (const n of list) if (!needsYou.some((x) => x.label === n.label)) needsYou.push(n);
    needsYou = needsYou.filter((n) => !n.el || (!n.el.value && n.el.isConnected));
  }
  const publicNeeds = () => needsYou.map((n) => ({ label: n.label }));

  let resumeTried = null; // the input we already tried, so DOM churn doesn't refetch

  async function uploadResume() {
    if (resumeDone) return;
    const inputs = IPM.resumeInputs();
    if (!inputs.length) return;
    const input = inputs[0];
    if (input.files && input.files.length) { resumeDone = true; return; }
    if (resumeTried === input) return;
    resumeTried = input;
    const setResume = (text) => TOP ? IPM.panel.update({ resume: text }) : send({ type: "FILL_REPORT", report: { resume: text } });
    let res = await send({ type: "GET_RESUME", jobId: ctx.job?.id });
    const started = Date.now();
    while (res.pending && !useBaseNow && Date.now() - started < 90000) {
      setResume("pending");
      await IPM.sleep(3000);
      res = await send({ type: "GET_RESUME", jobId: ctx.job?.id });
    }
    if (res.pending) res = await send({ type: "GET_RESUME", jobId: ctx.job?.id, noWait: true });
    if (!res.b64) { setResume(res.error ? `not attached (${res.error})` : "no resume on file"); return; }
    const bytes = Uint8Array.from(atob(res.b64), (c) => c.charCodeAt(0));
    const file = new File([bytes], res.name || "Resume.pdf", { type: res.type || "application/pdf" });
    const ok = await IPM.uploadFile(input, file);
    resumeDone = ok;
    setResume(ok ? `${res.variant === "tailored" ? "tailored version" : "your resume"} attached ✓` : "couldn’t attach automatically");
  }

  function addAiButtons(list) {
    if (!ctx.ai) return;
    for (const n of list) {
      const target = n.el;
      if (!target || !n.textarea || target.dataset.ipmAi) continue;
      target.dataset.ipmAi = "1";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "✨ Draft with InternProMax";
      btn.style.cssText = "margin:6px 0;padding:5px 10px;border-radius:7px;border:1px solid #9db6ea;background:#e7eefc;color:#1d4ba6;font:600 12px system-ui,sans-serif;cursor:pointer;";
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        btn.disabled = true;
        btn.textContent = "Drafting…";
        const res = await send({ type: "AI_ANSWER", question: n.label, jobId: ctx.job?.id, company: ctx.job?.company || guessJob().company, title: ctx.job?.title || guessJob().title });
        btn.disabled = false;
        if (res.answer) {
          IPM.setText(target, res.answer);
          btn.textContent = "✨ Redraft";
        } else btn.textContent = `Couldn’t draft: ${res.error || "unknown error"}`;
      });
      target.insertAdjacentElement("afterend", btn);
    }
  }

  // ---------------------------------------------------------------- submission tracking

  function pageText() {
    return (document.body?.innerText || "").slice(0, 20000);
  }

  function isConfirmation() {
    const text = pageText();
    const urlHit = CONFIRM_URL.test(location.pathname + location.hash + location.search);
    const textHit = CONFIRM_RE.test(text);
    if (textHit && !preSubmitConfirm) return true;
    if (urlHit && (textHit || !IPM.resumeInputs().length)) return true;
    return false;
  }

  function onSubmitAttempt(trigger) {
    if (appliedSent) return;
    if (!submitAttemptAt || Date.now() - submitAttemptAt > 5000) {
      preSubmitConfirm = CONFIRM_RE.test(pageText());
    }
    submitAttemptAt = Date.now();
    send({ type: "SUBMIT_ATTEMPT", trigger });
    watchConfirmation();
  }

  let watching = null;
  function watchConfirmation() {
    if (watching) return;
    const deadline = Date.now() + 2 * 60 * 1000;
    const check = () => {
      if (appliedSent) return stop();
      if (isConfirmation()) { stop(); markApplied("confirmation-page"); return; }
      if (Date.now() > deadline) {
        stop();
        if (TOP && IPM.panel.mounted) IPM.panel.update({ askConfirm: true, minimized: false });
        else if (!TOP) send({ type: "ASK_CONFIRM" });
      }
    };
    const obs = new MutationObserver(() => check());
    obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    const timer = setInterval(check, 1000);
    const onHash = () => check();
    window.addEventListener("hashchange", onHash);
    const stop = () => { obs.disconnect(); clearInterval(timer); window.removeEventListener("hashchange", onHash); watching = null; };
    watching = stop;
    setTimeout(check, 300);
  }

  async function markApplied(trigger) {
    if (appliedSent) return;
    appliedSent = true;
    const guess = TOP && IPM.panel.mounted ? IPM.panel.state.guess : guessJob();
    const res = await send({
      type: "MARK_APPLIED", trigger, url: location.href, ats: IPM.atsName(), page_title: document.title,
      company: ctx?.job?.company || guess?.company, title: ctx?.job?.title || guess?.title,
    });
    if (res.error) {
      appliedSent = false;
      if (TOP && IPM.panel.mounted) IPM.panel.update({ message: `Couldn’t record it: ${res.error}` });
      return;
    }
    if (TOP && IPM.panel.mounted) IPM.panel.update({ applied: true, askConfirm: false, application: res.application, minimized: false, message: "Saved to your tracker." });
    else if (!TOP) send({ type: "FILL_REPORT", report: { applied: true } });
  }

  document.addEventListener("submit", (e) => {
    if (!active || !looksLikeApplication()) return;
    if (e.target instanceof HTMLFormElement && e.target.closest("internpromax-panel")) return;
    onSubmitAttempt("form-submit");
  }, true);

  document.addEventListener("click", (e) => {
    if (!active) return;
    const btn = e.target.closest && e.target.closest("button, input[type=submit], input[type=button], [role=button], a");
    if (!btn) return;
    const text = (btn.innerText || btn.value || btn.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ");
    const auto = (btn.getAttribute("data-automation-id") || "").toLowerCase();
    const form = btn.closest("form");
    const isSubmit = SUBMIT_TEXT.test(text) || (/submit/.test(auto) && /submit/i.test(text))
      || (APPLY_TEXT.test(text) && (btn.type === "submit" || !!form?.querySelector("input[type=email], input[type=file]")));
    if (isSubmit && looksLikeApplication()) onSubmitAttempt("submit-click");
  }, true);

  // ---------------------------------------------------------------- posting capture

  async function maybeCaptureDescription() {
    if (!ctx?.job || !ctx.needsDescription) return;
    let text = "";
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const data = JSON.parse(s.textContent);
        const nodes = Array.isArray(data) ? data : [data, ...(data["@graph"] || [])];
        const jp = nodes.find((n) => n && String(n["@type"]).includes("JobPosting"));
        if (jp?.description) {
          // DOMParser builds an inert document: nothing loads or runs.
          const parsed = new DOMParser().parseFromString(jp.description, "text/html");
          text = (parsed.body.textContent || "").replace(/\s+\n/g, "\n").trim();
          break;
        }
      } catch { /* ignore malformed JSON-LD */ }
    }
    if (!text) {
      const main = document.querySelector("main, article, [role=main], #content, .content") || document.body;
      text = (main.innerText || "").trim();
    }
    const hints = (text.match(JD_HINT) || []).length;
    if (text.length > 400 && hints >= 2) await send({ type: "CAPTURE_DESCRIPTION", jobId: ctx.job.id, text: text.slice(0, 50000) });
  }

  // ---------------------------------------------------------------- messages from background

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === "DO_AUTOFILL") {
      (async () => {
        if (!active) await activate("autofill-request");
        if (looksLikeApplication() || IPM.resumeInputs().length) await runAutofill({ auto: false });
        sendResponse({ ok: true, filled: totalFilled });
      })();
      return true;
    }
    if (!TOP) return false;
    if (msg.type === "FORM_FOUND") {
      if (!active) activate("form-in-frame"); else showPanel();
    } else if (msg.type === "FILL_REPORT") {
      const r = msg.report || {};
      const patch = {};
      if (r.filled) { totalFilled += r.filled; patch.fillCount = totalFilled; }
      if (r.needsYou) { mergeNeeds(r.needsYou); patch.needsYou = publicNeeds(); }
      if (r.resume) patch.resume = r.resume;
      if (r.applied) { patch.applied = true; patch.message = "Saved to your tracker."; }
      if (IPM.panel.mounted) IPM.panel.update(patch);
    } else if (msg.type === "ASK_CONFIRM") {
      if (IPM.panel.mounted) IPM.panel.update({ askConfirm: true, minimized: false });
    } else if (msg.type === "MARK_APPLIED_NOW") {
      markApplied("manual");
    } else if (msg.type === "PANEL_STATE") {
      sendResponse({ mounted: IPM.panel.mounted, filled: totalFilled, applied: appliedSent || !!IPM.panel.state.applied });
    }
    return false;
  });

  // ---------------------------------------------------------------- boot

  async function boot() {
    const tab = await send({ type: "TAB_STATE" });
    if (tab.jobId || looksLikeApplication()) return activate("boot");
    // Single-page apps render forms late: watch for a while.
    let tries = 0;
    const obs = new MutationObserver(() => {
      if (active) return obs.disconnect();
      if (++tries % 5 !== 0) return;
      if (looksLikeApplication()) { obs.disconnect(); activate("late-form"); }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(() => obs.disconnect(), 120000);
  }

  // Multi-step forms (Workday) keep adding fields: fill new ones as they appear.
  let refillTimer = null;
  new MutationObserver(() => {
    if (!active || !autoFilled || appliedSent || !ctx?.flags?.autofill_on_load) return;
    clearTimeout(refillTimer);
    refillTimer = setTimeout(() => {
      resumeDone = resumeDone && IPM.resumeInputs().every((i) => i.files && i.files.length);
      runAutofill({ auto: true, onlyNew: true });
    }, 900);
  }).observe(document.documentElement, { childList: true, subtree: true });

  boot();
})();
