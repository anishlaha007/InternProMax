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

  let activation = null;
  function activate(reason) {
    activation = activation || doActivate(reason);
    return activation;
  }

  let preparing = null;
  function ensurePrepared() {
    preparing = preparing || prepareExternalJob();
    return preparing;
  }

  async function doActivate(reason) {
    active = true;
    ctx = await send({ type: "GET_CONTEXT", url: location.href });
    if (ctx.error && !ctx.apiOk) ctx = { apiOk: false };
    const formHere = looksLikeApplication();
    if (!TOP && formHere) send({ type: "FORM_FOUND" });
    if (TOP && (formHere || ctx.job || reason === "form-in-frame")) showPanel();
    // Capture the posting first so the server can tailor the resume before we attach one.
    if (TOP) await maybeCaptureDescription();
    // Not a job from your lists? Build one from this page (or the posting you just viewed) and tailor for it.
    const formInTab = formHere || reason === "form-in-frame";
    if (TOP && formInTab && !ctx.job && ctx.apiOk && ctx.flags?.tailor_any_site !== false && !ctx.tab?.applied) {
      await ensurePrepared();
    }
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

  const JOB_WORDS = /\b(intern(ship)?|co-?op|engineer(ing)?|developer|analyst|scientist|designer|manager|associate|specialist|researcher|technician|fellow)\b/i;

  function guessJob() {
    // Common page-title shapes: "Job Application for X at Y" (Greenhouse), "X @ Y" (Ashby), "Y - X" (Lever).
    const t = (document.title || "").trim();
    let m = t.match(/^job application for (.+?) at (.+)$/i) || t.match(/^(.+?) @ (.+)$/);
    if (m) return { title: m[1].trim().slice(0, 120), company: m[2].trim().slice(0, 80) };
    m = t.match(/^(.+?)\s+[-–|]\s+(.+)$/);
    if (m) {
      const [a, b] = [m[1].trim(), m[2].replace(/\b(careers?|jobs?)\b.*$/i, "").trim()];
      if (JOB_WORDS.test(a) && b && !JOB_WORDS.test(b)) return { title: a.slice(0, 120), company: b.slice(0, 80) };
      if (JOB_WORDS.test(b) && a && !JOB_WORDS.test(a)) return { title: b.slice(0, 120), company: a.slice(0, 80) };
    }
    const h1 = document.querySelector("h1")?.innerText?.trim();
    const title = h1 && JOB_WORDS.test(h1) ? h1 : (h1 || t);
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
      onTailor: () => tailorNow(),
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

  async function uploadResume(replace = false) {
    if (resumeDone) return;
    const inputs = IPM.resumeInputs();
    if (!inputs.length) return;
    const input = inputs[0];
    const ours = IPM.filledElements.has(input);
    if (input.files && input.files.length && !(replace && ours)) { resumeDone = true; return; }
    if (resumeTried === input) return;
    resumeTried = input;
    if (!TOP && !ctx.job && ctx.flags?.tailor_any_site !== false) {
      // Embedded form: let the top page create the job (and start tailoring) before picking a resume.
      const r = await send({ type: "ENSURE_JOB" });
      if (r.job) ctx.job = r.job;
    }
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
    if (TOP) {
      IPM.panel.update({ resumeVariant: ok ? res.variant : null, canTailor: !!ctx.job || ctx.flags?.tailor_any_site !== false });
      if (ok && res.variant === "tailored" && /being tailored/.test(IPM.panel.state.message || "")) IPM.panel.update({ message: "Added to your tracker." });
    }
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

  // Read the job posting on this page: schema.org JobPosting data first, then the visible text.
  function extractPosting() {
    const out = { text: "", title: "", company: "", location: "", source: "page" };
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const data = JSON.parse(s.textContent);
        const nodes = (Array.isArray(data) ? data : [data]).flatMap((n) => [n, ...((n && n["@graph"]) || [])]);
        const jp = nodes.find((n) => n && String(n["@type"]).includes("JobPosting"));
        if (!jp) continue;
        if (jp.description) {
          // DOMParser builds an inert document: nothing loads or runs.
          const parsed = new DOMParser().parseFromString(jp.description, "text/html");
          out.text = (parsed.body.innerText || parsed.body.textContent || "").replace(/\s+\n/g, "\n").trim();
        }
        out.title = jp.title || "";
        out.company = (jp.hiringOrganization && jp.hiringOrganization.name) || "";
        const addr = [].concat(jp.jobLocation || [])[0]?.address;
        if (addr) out.location = [addr.addressLocality, addr.addressRegion].filter(Boolean).join(", ");
        out.source = "json-ld";
        break;
      } catch { /* ignore malformed JSON-LD */ }
    }
    if (!out.text) {
      const main = document.querySelector("main, article, [role=main], #content, .content") || document.body;
      out.text = ((main && main.innerText) || "").trim();
    }
    out.text = out.text.slice(0, 50000);
    out.hints = (out.text.match(JD_HINT) || []).length;
    const g = guessJob();
    out.title = out.title || g.title;
    out.company = out.company || g.company;
    return out;
  }

  const looksLikePosting = (p) => (p.source === "json-ld" ? p.text.length > 200 : p.text.length > 400 && p.hints >= 2);

  async function maybeCaptureDescription() {
    if (!ctx?.job || !ctx.needsDescription) return;
    const p = extractPosting();
    if (looksLikePosting(p)) await send({ type: "CAPTURE_DESCRIPTION", jobId: ctx.job.id, text: p.text });
  }

  async function prepareExternalJob() {
    const p = extractPosting();
    const posting = looksLikePosting(p) ? p : null;
    const guess = (IPM.panel.mounted && IPM.panel.state.guess) || {};
    IPM.panel.update({ preparing: true, message: "Reading the job posting and tailoring your resume for it…" });
    const res = await send({
      type: "CREATE_EXTERNAL_JOB", url: location.href,
      company: (posting && posting.company) || guess.company || p.company, title: (posting && posting.title) || guess.title || p.title,
      location: p.location, description: posting ? posting.text : "",
    });
    if (res.job) {
      ctx.job = res.job;
      if (res.application) ctx.application = res.application;
      IPM.panel.update({ job: res.job, guess: null, preparing: false, application: res.application || null,
        message: res.created ? "Added to your tracker. Your resume is being tailored to this posting." : null });
    } else {
      IPM.panel.update({ preparing: false, message: res.error ? `Couldn’t read this posting: ${res.error}` : null });
    }
  }

  // Remember postings you look at, so the application page (often a different URL) can be tailored to them.
  function stashPostingIfAny() {
    const hasJsonLd = !!document.querySelector('script[type="application/ld+json"]');
    const jobish = /job|career|position|opening|apply|recruit|greenhouse|lever|workday|ashby|smartrecruiters|icims/i.test(location.href + " " + document.title);
    if (!hasJsonLd && !jobish) return false;
    const p = extractPosting();
    if (!looksLikePosting(p)) return false;
    send({ type: "STASH_POSTING", posting: { url: location.href, text: p.text, title: p.title, company: p.company, location: p.location } });
    return true;
  }

  async function tailorNow() {
    if (!ctx?.job) await ensurePrepared();
    if (!ctx?.job) return;
    IPM.panel.update({ resume: "pending" });
    const res = await send({ type: "TAILOR_JOB", jobId: ctx.job.id });
    if (res.error) { IPM.panel.update({ resume: `couldn’t tailor (${res.error})` }); return; }
    resumeDone = false;
    resumeTried = null;
    useBaseNow = false;
    await uploadResume(true);
    send({ type: "AUTOFILL_FRAMES_RESUME" });
  }

  // ---------------------------------------------------------------- messages from background

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === "REUPLOAD_RESUME") {
      (async () => {
        if (!TOP && ctx) { resumeDone = false; resumeTried = null; useBaseNow = false; await uploadResume(true); }
        sendResponse({ ok: true });
      })();
      return true;
    }
    if (msg.type === "DO_AUTOFILL") {
      (async () => {
        await activate("autofill-request");
        if (looksLikeApplication() || IPM.resumeInputs().length) await runAutofill({ auto: false });
        sendResponse({ ok: true, filled: totalFilled });
      })();
      return true;
    }
    if (!TOP) return false;
    if (msg.type === "PREPARE_JOB") {
      (async () => {
        await activate("form-in-frame");
        if (!ctx.job && ctx.apiOk && ctx.flags?.tailor_any_site !== false) await ensurePrepared();
        sendResponse({ job: ctx.job || null });
      })();
      return true;
    }
    if (msg.type === "FORM_FOUND") {
      if (!active) activate("form-in-frame"); else { showPanel(); if (!ctx?.job && ctx?.apiOk && ctx.flags?.tailor_any_site !== false) ensurePrepared(); }
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
    if (TOP && !tab.jobId) {
      setTimeout(() => { if (!stashPostingIfAny()) setTimeout(stashPostingIfAny, 3500); }, 1200);
    }
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
