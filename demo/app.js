/* app.js — wires the playground UI to the local apii backend (/api/analyze).
   Detection (incl. names/orgs via on-device NER) runs in the real engine;
   this file just renders the result and animates the round trip. */
(function () {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const elInput = $("#input");
  const elExamples = $("#examples");
  const elLlm = $("#out-llm");
  const elYou = $("#out-you");
  const elLegend = $("#legend");
  const elVaultBody = $("#vault tbody");
  const elVaultCount = $("#vault-count");
  const elNer = $("#ner");
  const elStatus = $("#status");
  const elSimulate = $("#simulate");
  const elReply = $("#reply");
  const elRestoreBtn = $("#restore-btn");
  const elRestored = $("#restored");
  const elRestoreStatus = $("#restore-status");

  const KIND_LABEL = {
    EMAIL: "Email", PHONE: "Phone", IBAN: "IBAN", NATIONAL_ID: "National ID",
    COMMERCIAL_REGISTRATION: "CR", TAX_NUMBER: "Tax / VAT",
    PERSON: "Person", ORGANIZATION: "Org", ADDRESS: "Address",
  };
  const NER_KINDS = new Set(["PERSON", "ORGANIZATION", "ADDRESS"]);

  let EXAMPLES = [];
  let lang = "en";
  let lastResult = null;
  let seq = 0; // guards against out-of-order responses

  const isRtl = () => lang === "ar";
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  function entSpan(kind, content, isToken) {
    return `<span class="ent${isToken ? " tok" : ""}" data-kind="${kind}" style="--c: var(--${kind})">${esc(content)}</span>`;
  }

  function setStatus(msg, kind) {
    elStatus.textContent = msg || "";
    elStatus.className = "status" + (kind ? " " + kind : "");
  }

  function renderViews(r) {
    const llm = [], you = [];
    for (const s of r.segments) {
      if (s.type === "text") { llm.push(esc(s.text)); you.push(esc(s.text)); }
      else { llm.push(entSpan(s.kind, s.token, true)); you.push(entSpan(s.kind, s.text, false)); }
    }
    elLlm.innerHTML = llm.join("") || '<span class="muted">—</span>';
    elYou.innerHTML = you.join("") || '<span class="muted">—</span>';
    elLlm.setAttribute("dir", isRtl() ? "rtl" : "ltr");
    elYou.setAttribute("dir", isRtl() ? "rtl" : "ltr");
  }

  function renderLegend(r) {
    const kinds = [...new Set(r.segments.filter((s) => s.type === "entity").map((s) => s.kind))];
    elLegend.innerHTML = kinds
      .map((k) => `<span class="lg"><span class="sw" style="background: var(--${k})"></span>${KIND_LABEL[k] || k}</span>`)
      .join("");
  }

  function renderVault(r) {
    elVaultBody.innerHTML =
      r.vault.map((v) => {
        const rtl = isRtl() && NER_KINDS.has(v.kind);
        return `<tr>
          <td class="tcell">${esc(v.token)}</td>
          <td><span class="kind-pill" style="--c: var(--${v.kind})">${KIND_LABEL[v.kind] || v.kind}</span></td>
          <td class="vcell"${rtl ? ' dir="rtl"' : ""}>${esc(v.value)}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="3" class="muted">No PII detected.</td></tr>`;
    elVaultCount.textContent = r.vault.length + (r.vault.length === 1 ? " token" : " tokens");
  }

  async function run() {
    const text = elInput.value;
    const ner = elNer.checked;
    const mine = ++seq;
    setStatus(ner ? "analyzing… (first NER run loads models)" : "analyzing…", "busy");
    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text, ner }),
      });
      const r = await resp.json();
      if (mine !== seq) return; // a newer request superseded this one
      if (!r.ok) { setStatus("error: " + (r.error || "unknown"), "err"); return; }
      lastResult = r;
      renderViews(r);
      renderLegend(r);
      renderVault(r);
      // reset the restore tester for the new input
      elReply.value = "";
      elRestored.innerHTML = "";
      elRestoreStatus.textContent = "";
      elSimulate.disabled = r.vault.length === 0;
      elRestoreBtn.disabled = r.vault.length === 0;
      if (r.ner_error) setStatus("NER unavailable — structured only (" + r.ner_error + ")", "warn");
      else setStatus(`${r.count} detected${ner ? "" : " · NER off"}`, "ok");
    } catch (e) {
      if (mine !== seq) return;
      setStatus("backend not reachable — run: .venv/bin/python demo/server.py", "err");
    }
  }

  // ── round trip: real two-way restore via the engine ────────────────
  function buildReply(vault) {
    const by = {};
    for (const v of vault) (by[v.kind] ||= []).push(v.token);
    const p = (k) => (by[k] ? by[k][0] : null);
    const parts = ["Thanks — I've reviewed the record."];
    const person = p("PERSON"), org = p("ORGANIZATION"), phone = p("PHONE"),
      email = p("EMAIL"), id = p("NATIONAL_ID"), iban = p("IBAN"),
      cr = p("COMMERCIAL_REGISTRATION"), vat = p("TAX_NUMBER");
    if (person) parts.push(`Customer ${person}${org ? ` (at ${org})` : ""} looks good.`);
    const c = [phone && `phone ${phone}`, email && `email ${email}`].filter(Boolean);
    if (c.length) parts.push(`I can reach them via ${c.join(" or ")}.`);
    if (id) parts.push(`National ID ${id} is on file.`);
    if (iban) parts.push(`Primary account ${iban}${cr ? `, CR ${cr}` : ""}${vat ? `, VAT ${vat}` : ""} — all verified.`);
    return parts.join(" ");
  }
  function simulate() {
    if (!lastResult) return;
    elReply.value = buildReply(lastResult.vault);
    restore();
  }

  async function restore() {
    const text = elReply.value;
    if (!lastResult) return;
    if (!text.trim()) { elRestored.innerHTML = '<span class="muted">—</span>'; elRestoreStatus.textContent = ""; return; }
    elRestoreStatus.textContent = "restoring…";
    elRestoreStatus.className = "status busy";
    try {
      const resp = await fetch("/api/deanonymize", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text, vault: lastResult.vault }),
      });
      const r = await resp.json();
      if (!r.ok) { elRestoreStatus.textContent = "error: " + (r.error || "?"); elRestoreStatus.className = "status err"; return; }
      // highlight known values in the restored text
      const sorted = lastResult.vault.slice().sort((a, b) => b.value.length - a.value.length);
      let html = esc(r.text);
      for (const v of sorted) html = html.split(esc(v.value)).join(entSpan(v.kind, v.value, false));
      elRestored.innerHTML = html || '<span class="muted">—</span>';
      const nR = (r.restored || []).length, nU = (r.unrestored || []).length;
      elRestoreStatus.textContent =
        `${nR} token${nR === 1 ? "" : "s"} restored by the engine` +
        (nU ? ` · ⚠️ ${nU} unrestored: ${r.unrestored.join(", ")}` : " · all restored ✓");
      elRestoreStatus.className = "status " + (nU ? "warn" : "ok");
    } catch (e) {
      elRestoreStatus.textContent = "backend not reachable";
      elRestoreStatus.className = "status err";
    }
  }

  // ── examples ────────────────────────────────────────────────────────
  function selectExample(ex, chip) {
    lang = ex.lang || "en";
    elInput.value = ex.text;
    elInput.setAttribute("dir", isRtl() ? "rtl" : "ltr");
    document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    if (chip) chip.classList.add("active");
    run();
  }
  function renderExamples() {
    elExamples.innerHTML = "";
    EXAMPLES.forEach((ex, i) => {
      const chip = document.createElement("button");
      chip.className = "chip";
      chip.textContent = ex.title;
      chip.addEventListener("click", () => selectExample(ex, chip));
      elExamples.appendChild(chip);
      if (i === 0) selectExample(ex, chip);
    });
  }

  // ── wiring ──────────────────────────────────────────────────────────
  let t;
  elInput.addEventListener("input", () => {
    lang = /[؀-ۿ]/.test(elInput.value) ? "ar" : "en"; // auto RTL on Arabic
    elInput.setAttribute("dir", isRtl() ? "rtl" : "ltr");
    document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    clearTimeout(t);
    t = setTimeout(run, 400);
  });
  elNer.addEventListener("change", run);
  elSimulate.addEventListener("click", simulate);
  elRestoreBtn.addEventListener("click", restore);
  let rt;
  elReply.addEventListener("input", () => { clearTimeout(rt); rt = setTimeout(restore, 350); });

  // hosted vs local: change the banner so the privacy claim stays honest
  fetch("/api/meta").then((r) => r.json()).then((m) => {
    if (!m.hosted) return;
    const bar = document.getElementById("privacy-bar");
    if (!bar) return;
    bar.classList.add("hosted");
    bar.innerHTML =
      '⚠️ <strong>Hosted demo</strong> — text is sent to a server to be analyzed. ' +
      'Use the <strong>synthetic samples</strong>; don\'t paste real PII. ' +
      'For real use, run <span class="mono">apii</span> locally — then nothing leaves your machine.';
  }).catch(() => {});

  fetch("examples.json")
    .then((r) => r.json())
    .then((data) => { EXAMPLES = data.examples || []; renderExamples(); })
    .catch(() => {
      elInput.value = "Customer: Khalid Al-Otaibi\nEmail: omar@aajil.sa\nMobile: 0551234567\nIBAN: SA0380000000608010167519";
      run();
    });
})();
