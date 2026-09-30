// End-to-end: real Chromium + the unpacked extension + the real backend + mock ATS pages.
// Usage: node tests/e2e/run_e2e.cjs   (needs `playwright` resolvable, Python deps installed)
const { chromium } = require("playwright");
const { spawn, execFileSync } = require("child_process");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const SITE_DIR = path.join(__dirname, "site");
const EXT_DIR = path.join(ROOT, "extension");
const API_PORT = 8431;
const SITE_PORT = 8765;
const API = `http://127.0.0.1:${API_PORT}`;
const SITE = `http://jobs.acme.test:${SITE_PORT}`;
const OUT = process.env.E2E_OUT || fs.mkdtempSync(path.join(os.tmpdir(), "ipm-e2e-out-"));
const PY = process.env.PYTHON || "python3";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!ok) failures++;
}
async function until(fn, timeout = 20000, every = 250) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try { last = await fn(); if (last) return last; } catch (e) { last = undefined; }
    await sleep(every);
  }
  return last;
}
const getJSON = async (p) => (await fetch(API + p)).json();

function staticServer() {
  return http.createServer((req, res) => {
    const clean = decodeURIComponent(req.url.split("?")[0]).replace(/\/thanks$/, "");
    const file = path.join(SITE_DIR, clean === "/" ? "greenhouse.html" : clean);
    if (!file.startsWith(SITE_DIR) || !fs.existsSync(file)) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    fs.createReadStream(file).pipe(res);
  }).listen(SITE_PORT);
}

(async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "ipm-e2e-data-"));
  const env = { ...process.env, IPM_DATA_DIR: dataDir, IPM_NO_BACKGROUND: "1" };
  execFileSync(PY, [path.join(__dirname, "seed.py"), SITE], { env, stdio: "inherit" });
  const server = spawn(PY, ["-m", "internpromax", "serve", "--no-browser", "--port", String(API_PORT)], { cwd: ROOT, env, stdio: ["ignore", "pipe", "pipe"] });
  let serverLog = "";
  server.stdout.on("data", (d) => { serverLog += d; });
  server.stderr.on("data", (d) => { serverLog += d; });
  const site = staticServer();
  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "ipm-e2e-chrome-"));
  let context;
  try {
    await until(async () => (await getJSON("/api/health")).ok, 20000);
    context = await chromium.launchPersistentContext(profileDir, {
      channel: "chromium",
      headless: true,
      viewport: { width: 1280, height: 900 },
      args: [`--disable-extensions-except=${EXT_DIR}`, `--load-extension=${EXT_DIR}`, "--host-resolver-rules=MAP *.test 127.0.0.1"],
    });
    const logs = [];
    context.on("page", (p) => p.on("console", (m) => { if (m.type() === "error") logs.push(`[${p.url()}] ${m.text()}`); }));
    let [worker] = context.serviceWorkers();
    if (!worker) worker = await context.waitForEvent("serviceworker");
    check("extension service worker started", !!worker);

    // ---------- 1. Apply from the dashboard (Greenhouse-style form, full page navigation on submit)
    const dash = await context.newPage();
    await dash.goto(`${API}/#/jobs`);
    const detected = await until(() => dash.evaluate(() => document.documentElement.dataset.ipmExtension), 10000);
    check("dashboard detects the extension", !!detected, detected);
    await until(() => worker.evaluate(async (api) => (await chrome.storage.local.get("apiBase")).apiBase === api, API), 10000);
    await dash.waitForSelector(".job");
    const row = dash.locator(".job", { hasText: "Acme Robotics" });
    const [gh] = await Promise.all([context.waitForEvent("page"), row.getByRole("button", { name: "Apply" }).click()]);
    await gh.waitForLoadState("domcontentloaded");
    check("Apply opened the posting in a new tab", gh.url().startsWith(`${SITE}/greenhouse.html`), gh.url());

    const filled = await until(() => gh.evaluate(() => document.querySelector("#first_name").value === "Alex"), 15000);
    check("autofill ran on page load", !!filled);
    const vals = await gh.evaluate(() => {
      const v = (s) => document.querySelector(s).value;
      const t = (s) => { const el = document.querySelector(s); return el.options[el.selectedIndex]?.textContent; };
      return {
        last: v("#last_name"), email: v("#email"), phone: v("#phone"), linkedin: v("#question_1"), website: v("#question_2"),
        school: v("#question_3"), degree: t("#question_4"), grad: v("#question_5"), auth: t("#question_6"), sponsor: t("#question_7"),
        heard: v("#question_8"), why: v("#question_9"), gender: t("#gender"), hispanic: t("#hispanic_ethnicity"),
        veteran: t("#veteran_status"), disability: t("#disability_status"), consent: document.querySelector("[name=consent]").checked,
      };
    });
    check("name/email/phone", vals.last === "Rivera" && vals.email === "alex.rivera@example.edu" && vals.phone === "(412) 555-0199", JSON.stringify([vals.last, vals.email, vals.phone]));
    check("LinkedIn + website", vals.linkedin.includes("linkedin.com/in/alexrivera") && vals.website.includes("github.com/alexrivera"), `${vals.linkedin} | ${vals.website}`);
    check("school + degree select", vals.school === "University of Pittsburgh" && vals.degree === "Bachelor's Degree", `${vals.school} | ${vals.degree}`);
    check("graduation date in MM/YYYY", vals.grad === "05/2028", vals.grad);
    check("work authorization = Yes, sponsorship = No", vals.auth === "Yes" && vals.sponsor === "No", `${vals.auth} / ${vals.sponsor}`);
    check("how did you hear", vals.heard.length > 0, vals.heard);
    check("EEO answers default to decline / not a veteran", /decline/i.test(vals.gender) && /decline/i.test(vals.hispanic) && /don't wish/i.test(vals.veteran) && /do not want/i.test(vals.disability),
      `${vals.gender} | ${vals.hispanic} | ${vals.veteran} | ${vals.disability}`);
    check("free-text 'why us' left for you", vals.why === "");
    check("consent checkbox left for you", vals.consent === false);

    const attached = await until(() => gh.evaluate(() => document.querySelector("#resume").files.length === 1), 60000, 500);
    check("resume attached to the file input", !!attached);
    const fileInfo = await gh.evaluate(() => { const f = document.querySelector("#resume").files[0]; return f && { name: f.name, type: f.type, size: f.size }; });
    const panelResume = await until(() => gh.evaluate(() => {
      const host = document.querySelector("internpromax-panel");
      return host ? "panel" : null;
    }), 5000);
    check("panel is shown on the application page", panelResume === "panel");
    check("attached file is a named PDF", !!fileInfo && fileInfo.type === "application/pdf" && /Alex_Rivera_Resume\.pdf/.test(fileInfo.name), JSON.stringify(fileInfo));

    const details = await until(async () => { const d = await getJSON("/api/jobs/e2e-greenhouse"); return d.details?.status === "ready" && d; }, 30000, 500);
    check("posting captured from the page and analyzed", !!details, details ? details.details.fetch_method : "");
    if (details) check("analysis found required skills", (details.details.analysis.required_skills || []).includes("Python"), (details.details.analysis.required_skills || []).join(", "));
    const tailored = await until(async () => { const d = await getJSON("/api/jobs/e2e-greenhouse"); return d.resume?.status === "ready" && d.resume; }, 30000, 500);
    check("tailored resume generated for this posting", !!tailored, tailored ? tailored.method : "");
    const tailoredPdf = Buffer.from(await (await fetch(`${API}/api/jobs/e2e-greenhouse/resume.pdf?variant=tailored`)).arrayBuffer());
    const attachedBytes = await gh.evaluate(async () => Array.from(new Uint8Array(await document.querySelector("#resume").files[0].arrayBuffer())));
    check("the tailored version is the one attached", attachedBytes.length === tailoredPdf.length, `${attachedBytes.length} vs ${tailoredPdf.length} bytes`);
    await gh.screenshot({ path: path.join(OUT, "greenhouse-filled.png"), fullPage: false });

    await gh.fill("#question_9", "I want to build reliable robot fleet software.");
    await Promise.all([gh.waitForURL(/confirmation\.html/), gh.click("#submit_app")]);
    const ghApp = await until(async () => (await getJSON("/api/applications")).items.find((a) => a.job_id === "e2e-greenhouse" && a.status === "applied"), 15000);
    check("submitting marked the application as Applied", !!ghApp, ghApp ? `${ghApp.company} via ${ghApp.source}` : "");
    await sleep(500);
    await gh.screenshot({ path: path.join(OUT, "greenhouse-confirmation.png") });

    // ---------- 2. Visit a posting directly (Lever-style SPA, no navigation on submit)
    const lv = await context.newPage();
    await lv.goto(`${SITE}/lever.html`);
    const lvFilled = await until(() => lv.evaluate(() => document.querySelector("[name=name]").value === "Alex Rivera"), 15000);
    check("direct visit: job recognized by URL and autofilled", !!lvFilled);
    const lvVals = await lv.evaluate(() => ({
      email: document.querySelector("[name=email]").value, org: document.querySelector("[name=org]").value,
      gh: document.querySelector("[name='urls[GitHub]']").value, adult: document.querySelector("input[type=radio][value=Yes]").checked,
      resume: document.querySelector("[name=resume]").files.length,
    }));
    check("Lever: email, current company, GitHub", lvVals.email === "alex.rivera@example.edu" && lvVals.org === "Acme Health" && lvVals.gh.includes("github.com"), JSON.stringify(lvVals));
    check("Lever: 18+ radio answered Yes", lvVals.adult === true);
    await until(() => lv.evaluate(() => document.querySelector("[name=resume]").files.length === 1), 60000, 500);
    await lv.click("button.template-btn-submit");
    const lvApp = await until(async () => (await getJSON("/api/applications")).items.find((a) => a.job_id === "e2e-lever" && a.status === "applied"), 15000);
    check("Lever: in-page confirmation marked Applied", !!lvApp);
    await lv.screenshot({ path: path.join(OUT, "lever-done.png") });

    // ---------- 3. Workday-style: data-automation-id fields, listbox dropdown, radio fieldset
    const wd = await context.newPage();
    await wd.goto(`${SITE}/workday.html`);
    const wdFilled = await until(() => wd.evaluate(() => document.querySelector("#input-1").value === "Alex"), 15000);
    check("Workday: autofilled", !!wdFilled);
    const wdVals = await until(() => wd.evaluate(() => {
      const v = { last: document.querySelector("#input-2").value, email: document.querySelector("#input-3").value, city: document.querySelector("#input-5").value,
        zip: document.querySelector("#input-6").value, country: document.querySelector("#country").textContent.trim(),
        auth: document.querySelector("input[name=auth][value=yes]").checked };
      return v.country !== "Select One" && v;
    }), 10000);
    check("Workday: text fields", wdVals && wdVals.last === "Rivera" && wdVals.city === "Pittsburgh" && wdVals.zip === "15213", JSON.stringify(wdVals));
    check("Workday: country listbox picked United States", wdVals && wdVals.country === "United States of America", wdVals && wdVals.country);
    check("Workday: authorization radio = Yes", wdVals && wdVals.auth === true);
    await wd.click("#submit");
    const wdApp = await until(async () => (await getJSON("/api/applications")).items.find((a) => a.job_id === "e2e-workday" && a.status === "applied"), 15000);
    check("Workday: confirmation popup marked Applied", !!wdApp);
    await wd.screenshot({ path: path.join(OUT, "workday-done.png") });

    // ---------- 4. A job that isn't on any list: posting page, then a separate apply page
    const CAREERS = `http://careers.initrode.test:${SITE_PORT}`;
    const ext = await context.newPage();
    await ext.goto(`${CAREERS}/careers-jd.html`);
    await sleep(2500); // lets the extension remember the posting
    await Promise.all([ext.waitForURL(/careers-apply/), ext.click("#apply")]);
    const extJob = await until(async () => (await getJSON(`/api/jobs/lookup?url=${encodeURIComponent(`${CAREERS}/careers-jd.html`)}`)).job, 15000);
    check("unlisted job created from the posting you viewed", !!extJob && extJob.source === "extension", extJob ? `${extJob.company} | ${extJob.title}` : "");
    if (extJob) {
      check("company and title read from the posting", extJob.company === "Initrode Aerospace" && extJob.title === "Propulsion Engineering Intern");
      const extFilled = await until(() => ext.evaluate(() => document.querySelector("#fn").value === "Alex" && document.querySelector("#auth").value === "Yes"), 15000);
      check("unlisted job: form autofilled", !!extFilled);
      const extDetails = await until(async () => { const d = await getJSON(`/api/jobs/${extJob.id}`); return d.details?.status === "ready" && d.details; }, 30000, 500);
      check("unlisted job: posting analyzed", !!extDetails && extDetails.analysis.required_skills.includes("CAD"), extDetails ? extDetails.analysis.required_skills.join(", ") : "");
      await until(() => ext.evaluate(() => document.querySelector("#cv").files.length === 1), 60000, 500);
      const extTailored = await until(async () => (await getJSON(`/api/jobs/${extJob.id}`)).resume?.status === "ready", 30000, 500);
      const extPdf = Buffer.from(await (await fetch(`${API}/api/jobs/${extJob.id}/resume.pdf?variant=tailored`)).arrayBuffer());
      const extBytes = await ext.evaluate(async () => Array.from(new Uint8Array(await document.querySelector("#cv").files[0].arrayBuffer())));
      check("unlisted job: tailored resume attached", !!extTailored && extBytes.length === extPdf.length, `${extBytes.length} vs ${extPdf.length} bytes`);
      await ext.screenshot({ path: path.join(OUT, "unlisted-apply.png") });
      await Promise.all([ext.waitForURL(/confirmation\.html/), ext.click("button[type=submit]")]);
      const extApp = await until(async () => (await getJSON("/api/applications")).items.find((a) => a.job_id === extJob.id && a.status === "applied"), 15000);
      check("unlisted job: submission tracked", !!extApp, extApp ? extApp.company : "");
    }

    // ---------- 5. Application form embedded in an iframe on the company's page
    const emb = await context.newPage();
    await emb.goto(`http://jobs.umbrella.test:${SITE_PORT}/embed-jd.html`);
    const frame = await until(() => emb.frames().find((f) => f.url().includes("embed-form.html")), 10000);
    const embFilled = frame && await until(() => frame.evaluate(() => document.querySelector("#email").value === "alex.rivera@example.edu"), 15000);
    check("embedded form: autofilled inside the iframe", !!embFilled);
    const embJob = await until(async () => (await getJSON(`/api/jobs/lookup?url=${encodeURIComponent(`http://jobs.umbrella.test:${SITE_PORT}/embed-jd.html`)}`)).job, 15000);
    check("embedded form: job created from the surrounding page", !!embJob, embJob ? `${embJob.company} | ${embJob.title}` : "");
    if (embJob && frame) {
      await until(() => frame.evaluate(() => document.querySelector("#resume").files.length === 1), 60000, 500);
      await until(async () => (await getJSON(`/api/jobs/${embJob.id}`)).resume?.status === "ready", 30000, 500);
      const embPdf = Buffer.from(await (await fetch(`${API}/api/jobs/${embJob.id}/resume.pdf?variant=tailored`)).arrayBuffer());
      const embBytes = await frame.evaluate(async () => Array.from(new Uint8Array(await document.querySelector("#resume").files[0].arrayBuffer())));
      check("embedded form: tailored resume attached in the iframe", embBytes.length === embPdf.length, `${embBytes.length} vs ${embPdf.length} bytes`);
      await emb.screenshot({ path: path.join(OUT, "embedded.png") });
    }

    // ---------- 6. Tracker shows everything applied
    await dash.goto(`${API}/#/tracker`);
    await dash.waitForSelector(".app-card");
    const cards = await dash.locator(".col[data-status=applied] .app-card").count();
    check("tracker board shows 4 applied", cards === 4, String(cards));
    await dash.screenshot({ path: path.join(OUT, "tracker.png") });

    if (logs.length) console.log("page console errors:\n  " + logs.join("\n  "));
  } catch (e) {
    failures++;
    console.error("E2E crashed:", e);
    console.error(serverLog.split("\n").slice(-30).join("\n"));
  } finally {
    if (context) await context.close();
    server.kill();
    site.close();
  }
  console.log(`\nScreenshots: ${OUT}`);
  console.log(failures ? `${failures} check(s) failed` : "All end-to-end checks passed");
  process.exit(failures ? 1 : 0);
})();
