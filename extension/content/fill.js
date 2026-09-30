// Filling: resolve profile values and write them into inputs/selects/radios/comboboxes safely.
(() => {
  const IPM = globalThis.IPM;
  const { norm, describe, classify, groupQuestion, optionLabel, visible, YES_NO, EEO } = IPM;

  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const DECLINE = /decline|prefer not|don.?t wish|do not wish|not wish|choose not|rather not|not to (say|disclose|answer|self)|don.?t want|do not want|no answer/i;
  const STOP = new Set("the a an and or to of for in on at is are you your do does did what why how with this that we our be have has please describe tell us about".split(" "));

  const filled = new WeakSet(); // elements we've written to: never touch them again
  const seen = new WeakSet(); // elements already considered

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---------------------------------------------------------------- values

  function monthIndex(m) {
    if (!m) return -1;
    const i = MONTHS.findIndex((x) => x.toLowerCase().startsWith(String(m).toLowerCase().slice(0, 3)));
    return i >= 0 ? i : Number(m) - 1;
  }

  function degreeChoices(e) {
    const level = e.degree_level || "Bachelor's";
    const map = {
      "Bachelor's": ["Bachelor's", "Bachelor", "Bachelors", "BS", "B.S.", "BA", "Undergraduate", "4 Year Degree"],
      "Master's": ["Master's", "Master", "Masters", "MS", "M.S.", "Graduate"],
      PhD: ["PhD", "Ph.D.", "Doctorate", "Doctoral"],
      MBA: ["MBA", "Master of Business Administration", "Master's"],
      "Associate's": ["Associate's", "Associate", "2 Year Degree"],
    };
    return [e.degree, ...(map[level] || [level])].filter(Boolean);
  }

  function valueFor(key, P) {
    const p = P.personal || {};
    const e = (P.education || [])[0] || {};
    const w = P.work_auth || {};
    const a = P.application || {};
    const q = P.eeo || {};
    const exp = ((P.resume || {}).experience || [])[0] || {};
    const eeo = (v) => ({ choices: [v].filter(Boolean), decline: true });
    switch (key) {
      case "first_name": return p.first_name;
      case "last_name": return p.last_name;
      case "preferred_name": return p.preferred_name || p.first_name;
      case "full_name": return [p.first_name, p.last_name].filter(Boolean).join(" ");
      case "email": return p.email;
      case "phone": return p.phone;
      case "linkedin": return p.linkedin;
      case "github": return p.github;
      case "website": return p.website || p.github;
      case "address": return p.address;
      case "address2": return null;
      case "city": return p.city;
      case "state": return { text: p.state, choices: [p.state, STATE_NAMES[(p.state || "").toUpperCase()]].filter(Boolean) };
      case "zip": return p.zip;
      case "country": return { text: p.country, choices: [p.country, ...(/united states|usa|^us$/i.test(p.country || "") ? ["United States", "United States of America", "USA", "US"] : [])].filter(Boolean) };
      case "location": return [p.city, p.state].filter(Boolean).join(", ");
      case "pronouns": return p.pronouns;
      case "school": return e.school;
      case "degree": return { text: e.degree || e.degree_level, choices: degreeChoices(e) };
      case "major": return e.major;
      case "gpa": return e.gpa;
      case "grad_date": return e.grad_year ? { grad: true, month: monthIndex(e.grad_month), year: String(e.grad_year) } : null;
      case "start_date": return a.earliest_start;
      case "current_company": return a.current_company || exp.company;
      case "current_title": return a.current_title || exp.title;
      case "how_heard": return { text: a.how_heard, choices: [a.how_heard, "LinkedIn", "Job Board", "Online Job Board", "Company Website", "Website", "Internet", "Other"].filter(Boolean) };
      case "salary": return a.salary_expectation;
      case "work_auth": return { yes: !!w.authorized_us };
      case "sponsorship": return { yes: !!w.needs_sponsorship };
      case "over_18": return { yes: w.over_18 !== false };
      case "relocate": return { yes: !!w.willing_to_relocate };
      case "previously_employed": return { yes: !!a.previously_employed };
      case "us_citizen": return { yes: !!w.us_citizen };
      case "gender": return eeo(q.gender);
      case "race": return eeo(q.race);
      case "hispanic": return eeo(q.hispanic);
      case "veteran": return eeo(q.veteran);
      case "disability": return eeo(q.disability);
      case "lgbtq": return eeo(q.lgbtq);
      default: return null; // clearance, non_compete, cover_letter: leave for the human
    }
  }

  const STATE_NAMES = { AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut",
    DE: "Delaware", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
    KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
    MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
    NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island",
    SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington",
    WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming", DC: "District of Columbia" };

  function gradText(v, el) {
    const mm = String(v.month + 1).padStart(2, "0");
    const ph = `${el.getAttribute("placeholder") || ""} ${el.getAttribute("data-automation-id") || ""}`.toLowerCase();
    if (el.type === "date") return `${v.year}-${mm}-01`;
    if (el.type === "month") return `${v.year}-${mm}`;
    if (/mm\s*\/\s*dd\s*\/\s*yyyy/.test(ph)) return `${mm}/01/${v.year}`;
    if (/mm\s*\/\s*yyyy|mm\/yy/.test(ph)) return `${mm}/${v.year}`;
    if (/^\s*yyyy\s*$|year/.test(ph) || v.month < 0) return v.year;
    return `${MONTHS[v.month]} ${v.year}`;
  }

  // ---------------------------------------------------------------- writers

  function mark(el) {
    filled.add(el);
    el.dataset.ipmFilled = "1";
    el.style.boxShadow = "0 0 0 2px rgba(42, 99, 214, .45)";
    el.style.transition = "box-shadow .2s";
  }

  function setText(el, value) {
    if (value === null || value === undefined || value === "") return false;
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, String(value));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
    mark(el);
    return true;
  }

  function score(optionText, want) {
    const o = norm(optionText);
    if (!o) return 0;
    if (want instanceof RegExp) return want.test(o) ? 3 : 0;
    const w = norm(want);
    if (!w) return 0;
    if (o === w) return 5;
    if (o.startsWith(w) || w.startsWith(o)) return o.length >= 2 && w.length >= 2 ? 4 : 0;
    if (w.length >= 3 && o.includes(w)) return 3;
    if (o.length >= 4 && w.includes(o)) return 2;
    return 0;
  }

  function wants(key, v) {
    // Candidate answers in priority order (strings or regexes) + whether "decline" is an acceptable fallback.
    if (v === null || v === undefined) return null;
    if (typeof v === "string") return { list: [v], decline: false };
    if ("yes" in v) return { list: v.yes ? [/^yes\b/, /^y$/, /^true$/, /^i am\b/, /^i do\b/, /^i will\b/] : [/^no\b/, /^n$/, /^false$/, /^i am not\b/, /^i do not\b/, /^i will not\b/], decline: false };
    if (v.grad) return { list: [MONTHS[v.month], v.year].filter(Boolean), decline: false };
    return { list: v.choices || [v.text], decline: !!v.decline };
  }

  function pick(options, want) {
    // options: [{label, el}] -> best option or null
    let best = null;
    let bestScore = 0;
    for (const cand of want.list) {
      for (const o of options) {
        const s = score(o.label, cand);
        if (s > bestScore) { best = o; bestScore = s; }
      }
      if (bestScore >= 4) break;
    }
    if (!best && want.decline) best = options.find((o) => DECLINE.test(o.label)) || null;
    return best;
  }

  const isPlaceholder = (opt) => !opt.value || /^(select|choose|please|--|—|-)/i.test(opt.textContent.trim());

  function fillSelect(sel, key, v) {
    const current = sel.options[sel.selectedIndex];
    if (current && !isPlaceholder(current)) return false;
    let want = wants(key, v);
    if (!want) return false;
    if (v && v.grad) {
      const txt = [...sel.options].map((o) => o.textContent).join(" ");
      want = { list: /20\d\d/.test(txt) ? [v.year] : [MONTHS[v.month], String(v.month + 1)], decline: false };
    }
    const opts = [...sel.options].filter((o) => !isPlaceholder(o) && !o.disabled).map((o) => ({ label: o.textContent, el: o }));
    const hit = pick(opts, want);
    if (!hit) return false;
    sel.value = hit.el.value;
    sel.dispatchEvent(new Event("input", { bubbles: true }));
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    mark(sel);
    return true;
  }

  function fillGroup(inputs, key, v) {
    if (inputs.some((i) => i.checked)) return false;
    const want = wants(key, v);
    if (!want) return false;
    const opts = inputs.map((el) => ({ label: optionLabel(el), el }));
    const hit = pick(opts, want);
    if (!hit) return false;
    hit.el.click();
    if (!hit.el.checked) {
      hit.el.checked = true;
      hit.el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    mark(hit.el.closest("label") || hit.el);
    return true;
  }

  async function fillCombobox(el, key, v) {
    // react-select / Workday-style dropdowns: open, type, click the best option.
    const want = wants(key, v);
    if (!want) return false;
    const typed = typeof v === "string" ? v : v.text || (want.list.find((x) => typeof x === "string") || "");
    const isInput = el.tagName === "INPUT";
    el.focus();
    if (isInput) {
      if (typed) setText(el, typed);
      else el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    } else {
      el.click();
    }
    let options = [];
    for (let i = 0; i < 12 && !options.length; i++) {
      await sleep(150);
      const listId = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
      const scope = (listId && document.getElementById(listId)) || document;
      options = [...scope.querySelectorAll("[role=option]")].filter(visible);
    }
    const hit = pick(options.map((o) => ({ label: o.innerText || o.textContent, el: o })), want);
    if (!hit) {
      if (!isInput) el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      return false;
    }
    hit.el.scrollIntoView({ block: "nearest" });
    for (const type of ["mousedown", "mouseup", "click"]) hit.el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    mark(el);
    return true;
  }

  async function uploadFile(input, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    filled.add(input);
    return input.files && input.files.length === 1;
  }

  // ---------------------------------------------------------------- answer bank

  const words = (s) => new Set(norm(s).split(/[^a-z0-9+#]+/).filter((w) => w.length > 2 && !STOP.has(w)));
  function bankAnswer(question, answers) {
    const q = words(question);
    if (!q.size) return null;
    let best = null;
    let bestScore = 0;
    for (const a of answers || []) {
      if (!a.question || !a.answer) continue;
      const b = words(a.question);
      const inter = [...q].filter((w) => b.has(w)).length;
      const s = inter / Math.max(1, Math.min(q.size, b.size) + 0.5 * Math.abs(q.size - b.size));
      if (s > bestScore) { best = a; bestScore = s; }
    }
    return bestScore >= 0.6 ? best.answer : null;
  }

  // ---------------------------------------------------------------- orchestrator

  const TEXTISH = new Set(["", "text", "email", "tel", "url", "number", "search", "date", "month"]);

  async function autofill(P, { onlyNew = false } = {}) {
    const report = { filled: [], needsYou: [], skipped: 0 };
    const doc = document;

    // 1) radio & checkbox groups
    const groups = new Map();
    for (const el of doc.querySelectorAll("input[type=radio], input[type=checkbox]")) {
      if (el.disabled || (onlyNew && seen.has(el))) continue;
      const name = el.name || el.closest("fieldset, [role=radiogroup], [role=group]")?.id || "";
      if (!name) continue;
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(el);
    }
    for (const inputs of groups.values()) {
      inputs.forEach((i) => seen.add(i));
      if (inputs.length < 2 && inputs[0].type === "checkbox") continue; // consent boxes stay with the human
      const question = groupQuestion(inputs);
      const { key } = classify(inputs[0], { primary: question, secondary: "", all: question });
      const v = key ? valueFor(key, P) : null;
      if (key && v != null && fillGroup(inputs, key, v)) report.filled.push({ key, label: question.slice(0, 80) });
      else if (inputs[0].required || /\*/.test(question)) report.needsYou.push({ label: question.slice(0, 120) });
    }

    // 2) selects, text inputs, textareas, comboboxes
    const controls = [...doc.querySelectorAll("input, select, textarea, [role=combobox], button[aria-haspopup=listbox]")];
    for (const el of controls) {
      if (filled.has(el) || (onlyNew && seen.has(el))) continue;
      seen.add(el);
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (el.tagName === "INPUT" && !TEXTISH.has(type) && el.getAttribute("role") !== "combobox") continue;
      if (el.disabled || (el.readOnly && el.getAttribute("role") !== "combobox") || !visible(el)) continue;
      const desc = describe(el);
      const { key } = classify(el, desc);
      const label = desc.primary || desc.secondary;
      const shown = desc.label || label;
      const isCombo = el.getAttribute("role") === "combobox" || el.getAttribute("aria-haspopup") === "listbox";

      if (!key) {
        if ((el.tagName === "TEXTAREA" || type === "" || type === "text") && !el.value) {
          const answer = bankAnswer(label, P.answers);
          if (answer && setText(el, answer)) { report.filled.push({ key: "answer_bank", label: label.slice(0, 80) }); continue; }
          if (el.tagName === "TEXTAREA" || el.required || /\?/.test(label)) report.needsYou.push({ label: shown.slice(0, 120), textarea: el.tagName === "TEXTAREA", el });
        }
        continue;
      }
      const v = valueFor(key, P);
      if (v === null || v === undefined || v === "") { if (el.required) report.needsYou.push({ label: shown.slice(0, 120) }); continue; }
      let ok = false;
      try {
        if (el.tagName === "SELECT") ok = fillSelect(el, key, v);
        else if (isCombo) {
          if (el.tagName === "INPUT" && el.value) continue;
          if (el.tagName === "BUTTON" && !/^(select|choose)/i.test((el.innerText || "").trim())) continue;
          ok = await fillCombobox(el, key, v);
        } else {
          if (el.value) continue; // never overwrite what's there
          if (typeof v === "string") ok = setText(el, v);
          else if (v.grad) ok = setText(el, gradText(v, el));
          else if (v.text) ok = setText(el, v.text);
          else if ("yes" in v) ok = setText(el, v.yes ? "Yes" : "No");
        }
      } catch (err) {
        console.debug("[InternProMax] could not fill", label, err);
      }
      if (ok) report.filled.push({ key, label: label.slice(0, 80) });
      else if (el.required && !el.value) report.needsYou.push({ label: shown.slice(0, 120) });
    }
    return report;
  }

  Object.assign(IPM, { autofill, setText, uploadFile, valueFor, bankAnswer, filledElements: filled, sleep });
})();
