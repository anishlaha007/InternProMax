// Field detection: figure out what each form control is asking for.
// Shared by the other content scripts through globalThis.IPM (isolated world, not the page).
(() => {
  const IPM = (globalThis.IPM = globalThis.IPM || {});

  const norm = (s) => (s || "")
    .replace(/\(required\)|\brequired\b|\(optional\)/gi, " ")
    .replace(/[*:✱]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

  const humanize = (s) => (s || "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_\-.[\]]+/g, " ")
    .trim();

  const textOf = (el) => (el ? (el.innerText || el.textContent || "") : "").trim();

  function ownLabelText(label, control) {
    // Text of a wrapping <label> without the text of the control (e.g. select options).
    const clone = label.cloneNode(true);
    clone.querySelectorAll("select, option, input, textarea, button, [role=listbox]").forEach((n) => n.remove());
    return textOf(clone) || clone.textContent || "";
  }

  function nearbyText(el) {
    let node = el;
    for (let depth = 0; depth < 5 && node && node !== document.body; depth++) {
      let sib = node.previousElementSibling;
      while (sib) {
        if (!sib.matches("script, style, input, select, textarea, button") && !sib.querySelector("input, select, textarea")) {
          const t = textOf(sib);
          if (t && t.length <= 300) return t;
        }
        sib = sib.previousElementSibling;
      }
      node = node.parentElement;
    }
    return "";
  }

  function byIds(ids) {
    return (ids || "").split(/\s+/).map((id) => textOf(document.getElementById(id))).join(" ");
  }

  // primary = what a human reads next to the field; secondary = machine hints (name, id, placeholder…)
  function describe(el) {
    const primary = [];
    if (el.getAttribute("aria-labelledby")) primary.push(byIds(el.getAttribute("aria-labelledby")));
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) primary.push(ownLabelText(l, el));
    }
    const wrap = el.closest("label");
    if (wrap) primary.push(ownLabelText(wrap, el));
    if (el.getAttribute("aria-label")) primary.push(el.getAttribute("aria-label"));
    let raw = primary.join(" ");
    if (!norm(raw)) raw = nearbyText(el);
    const p = norm(raw);
    const secondary = norm([el.getAttribute("placeholder"), el.getAttribute("title"), humanize(el.getAttribute("data-automation-id")),
      humanize(el.getAttribute("name")), humanize(el.id), el.getAttribute("autocomplete")].filter(Boolean).join(" "));
    const label = raw.replace(/[*✱]+/g, " ").replace(/\s+/g, " ").trim();
    return { primary: p, secondary, all: `${p} ${secondary}`.trim(), label };
  }

  // ---------------------------------------------------------------- rules
  // Order matters: the first rule that matches wins.
  const R = (key, re, opts = {}) => ({ key, re, ...opts });
  const RULES = [
    // yes/no questions first: their labels often contain words like "work" or "name"
    R("sponsorship", /sponsor|visa status|h-?1b|immigration (status|support|sponsorship)|employment visa/),
    R("work_auth", /authori[sz]ed to work|work authori[sz]ation|eligible to work|right to work|legally (able|eligible|permitted) to work|able to work (lawfully|legally)/),
    R("over_18", /18 years|at least 18|over (the age of )?18|age of 18|of legal (working )?age/),
    R("relocate", /relocat/),
    R("previously_employed", /(previously|ever) (been )?(employed|worked)|former employee|current or former|worked (for|at|with) [\w\s&.,'-]{1,40} (before|previously)/),
    R("us_citizen", /u\.?s\.? citizen|united states citizen|citizenship status|are you a citizen/),
    R("clearance", /security clearance|active clearance/),
    R("non_compete", /non-?compete|non-?solicit/),
    // EEO
    R("hispanic", /hispanic|latin[oax]/),
    R("gender", /\bgender\b|\bsex\b/, { not: /orientation|transgender|identity other/ }),
    R("race", /\brace\b|ethnicity|ethnic background/),
    R("veteran", /veteran|military service/),
    R("disability", /disabilit/),
    R("lgbtq", /lgbt|sexual orientation|transgender/),
    // identity & contact
    R("preferred_name", /preferred (first )?name|nick ?name|goes by|name you (prefer|go by)/),
    R("first_name", /\b(first|given|legal first) ?name\b|^first$|firstname|\bfname\b|given-name/, { not: /last|middle|preferred|emergency|reference|manager|recruiter|referr|parent|spouse/ }),
    R("last_name", /\b(last|family|sur) ?name\b|^last$|surname|lastname|\blname\b|family-name/, { not: /first|preferred|emergency|reference|manager|recruiter|referr|parent|maiden/ }),
    R("email", /e-?mail/, { not: /referr|reference|manager|recruiter|alternate|secondary/ }),
    R("phone", /phone|mobile|\bcell\b|telephone|\btel\b/, { not: /type|extension|\bext\b|device|country code|phone code/ }),
    R("linkedin", /linked ?in/),
    R("github", /git ?hub/),
    R("website", /website|portfolio|personal (site|url|page|link)|blog|other (url|link|website)|\burl\b/, { not: /linked ?in|git ?hub|twitter|company website/ }),
    R("full_name", /^(your |full |legal |candidate |applicant )?name\b|full name|legal name|\bname$|^name /, { not: /company|school|university|employer|manager|reference|referr|emergency|user ?name|file|project|recruiter|hiring|college|institution|organization|last|first|preferred|middle/ }),
    // location
    R("address", /address( line)? ?1?\b|street/, { not: /e-?mail|line 2|address 2|ip address|web address/ }),
    R("address2", /address line 2|address 2|apartment|suite|apt/),
    R("zip", /\bzip\b|postal|post code|postcode/),
    R("city", /\bcity\b|\btown\b/, { not: /state|country|citizenship/ }),
    R("state", /\bstate\b|province|region|county/, { not: /united states|statement|country|city|state (your|why|how)/ }),
    R("country", /\bcountry\b/, { not: /code|phone|citizenship|dial/ }),
    R("location", /\blocation\b|where are you (currently )?(located|based)|current (city|location)|city,? state|where do you live|based in/, { not: /preferred|desired|willing|office|work location preference/ }),
    // education
    R("school", /school|university|college|institution/, { not: /high school|graduat|year|degree|major/ }),
    R("grad_date", /graduat|class of|expected (completion|grad)|completion date|degree (end|completion)|end date.*(degree|education)/, { not: /high school/ }),
    R("degree", /\bdegree\b|level of (education|study)|education level|highest education/, { not: /major|field|discipline|graduat|year|date|gpa/ }),
    R("major", /\bmajor\b|field of study|discipline|area of study|concentration|course of study/),
    R("gpa", /\bgpa\b|grade point/),
    // work / application
    R("start_date", /earliest (possible )?start|start date|available to start|availability|when can you start/),
    R("current_company", /current (company|employer)|most recent (company|employer)|^company( name)?$|^employer$|^organization$|^org$/, { not: /school|why|previous|referr/ }),
    R("current_title", /current (job )?title|current (role|position)|most recent (title|role)|^job title$|^title$/),
    R("how_heard", /how did you (hear|find|learn)|where did you (hear|find|learn|see)|referral source|source of (your )?application|how .{0,30}hear about|how were you referred/),
    R("salary", /salary|compensation expect|desired (pay|compensation)|pay expectation|expected (pay|compensation)/),
    R("pronouns", /pronoun/),
    R("cover_letter", /cover letter/),
  ];

  const YES_NO = new Set(["sponsorship", "work_auth", "over_18", "relocate", "previously_employed", "us_citizen", "clearance", "non_compete"]);
  const EEO = new Set(["hispanic", "gender", "race", "veteran", "disability", "lgbtq"]);

  const AUTOCOMPLETE = {
    "given-name": "first_name", "family-name": "last_name", name: "full_name", email: "email", tel: "phone",
    "tel-national": "phone", "address-line1": "address", "address-line2": "address2", "address-level2": "city",
    "address-level1": "state", "postal-code": "zip", country: "country", "country-name": "country", url: "website",
    organization: "current_company", "organization-title": "current_title",
  };

  function classify(el, desc) {
    desc = desc || describe(el);
    const ac = (el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/).pop();
    if (AUTOCOMPLETE[ac]) return { key: AUTOCOMPLETE[ac], desc };
    for (const text of [desc.primary, desc.secondary]) {
      if (!text) continue;
      for (const rule of RULES) {
        if (rule.re.test(text) && !(rule.not && rule.not.test(text))) return { key: rule.key, desc };
      }
    }
    return { key: null, desc };
  }

  // Question text for a radio/checkbox group.
  function groupQuestion(inputs) {
    const first = inputs[0];
    const box = first.closest("fieldset, [role=radiogroup], [role=group]");
    if (box) {
      const legend = box.querySelector("legend");
      if (legend && textOf(legend)) return norm(textOf(legend));
      if (box.getAttribute("aria-labelledby")) return norm(byIds(box.getAttribute("aria-labelledby")));
      if (box.getAttribute("aria-label")) return norm(box.getAttribute("aria-label"));
    }
    let container = first.parentElement;
    while (container && !inputs.every((i) => container.contains(i))) container = container.parentElement;
    if (!container) return "";
    const direct = [...container.children].find((c) => !c.querySelector("input") && textOf(c) && textOf(c).length < 300);
    return norm(direct ? textOf(direct) : nearbyText(container));
  }

  function optionLabel(input) {
    if (input.id) {
      const l = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (l) return textOf(l);
    }
    const wrap = input.closest("label");
    if (wrap) return textOf(wrap);
    if (input.getAttribute("aria-label")) return input.getAttribute("aria-label");
    const next = input.nextSibling;
    if (next && (next.textContent || "").trim()) return next.textContent.trim();
    return input.value || "";
  }

  const ATS_HOSTS = [
    ["greenhouse", /greenhouse\.io$/], ["lever", /lever\.co$/], ["ashby", /ashbyhq\.com$/], ["workday", /myworkday(jobs|site)\.com$/],
    ["smartrecruiters", /smartrecruiters\.com$/], ["icims", /icims\.com$/], ["jobvite", /jobvite\.com$/], ["oracle", /oraclecloud\.com$/],
    ["successfactors", /successfactors\.(com|eu)$/], ["taleo", /taleo\.net$/], ["workable", /workable\.com$/], ["eightfold", /eightfold\.ai$/],
    ["bamboohr", /bamboohr\.com$/], ["rippling", /rippling\.com$/], ["paylocity", /paylocity\.com$/], ["dayforce", /dayforcehcm\.com$/],
  ];
  function atsName(host = location.hostname) {
    const hit = ATS_HOSTS.find(([, re]) => re.test(host));
    return hit ? hit[0] : null;
  }

  const visible = (el) => {
    if (!el.isConnected) return false;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  function resumeInputs(root = document) {
    const files = [...root.querySelectorAll("input[type=file]")].filter((f) => !f.disabled);
    const scored = files.map((f) => {
      const d = describe(f);
      const text = `${d.all} ${norm(nearbyText(f))} ${norm(f.getAttribute("accept"))}`;
      let s = 0;
      if (/resume|résumé|\bcv\b|curriculum/.test(text)) s += 5;
      if (/cover|transcript|portfolio sample|writing sample|other|additional/.test(text)) s -= 6;
      return { f, s };
    });
    const best = scored.filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.f);
    if (best.length) return best.slice(0, 1);
    return files.length === 1 && scored[0].s >= 0 ? files : [];
  }

  // How much does this document look like a job application form?
  function applicationScore(root = document) {
    let score = 0;
    const inputs = [...root.querySelectorAll("input, select, textarea")].filter((i) => i.type !== "hidden");
    if (inputs.length < 3) return 0;
    if (resumeInputs(root).length) score += 3;
    const keys = new Set();
    for (const el of inputs.slice(0, 80)) {
      if (el.type === "file" || el.type === "submit" || el.type === "button") continue;
      const { key } = classify(el);
      if (key) keys.add(key);
    }
    if (keys.has("email")) score += 2;
    if (keys.has("first_name") || keys.has("last_name") || keys.has("full_name")) score += 2;
    if (keys.has("phone")) score += 1;
    if (keys.has("linkedin") || keys.has("school") || keys.has("work_auth") || keys.has("sponsorship")) score += 1;
    if (atsName()) score += 2;
    return score;
  }

  Object.assign(IPM, { norm, textOf, describe, classify, groupQuestion, optionLabel, nearbyText, RULES, YES_NO, EEO,
    atsName, visible, resumeInputs, applicationScore });
})();
