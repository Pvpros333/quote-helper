// Quote Helper front end (vanilla JS, no build step).
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const money = (n) => (Number(n) || 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let currentJob = null;

// ---------- tabs ----------
function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$("main > section.panel").forEach((p) => p.id !== "progress" && p.classList.toggle("hidden", p.id !== `tab-${name}`));
  if (name === "jobs") loadJobs();
  if (name === "quote") loadJobOptions();
  if (name === "settings") loadSettings();
  if (name !== "jobs") hideResult();
}
$$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) { e.preventDefault(); showTab(g.dataset.goto); }
});

function hideResult() { $("#result").classList.add("hidden"); $("#error").classList.add("hidden"); }
function showError(msg) { const el = $("#error"); el.textContent = msg; el.classList.remove("hidden"); el.scrollIntoView({ behavior: "smooth" }); }

// ---------- photo thumbnails ----------
$$('input[type=file][name=photos]').forEach((input) => {
  input.addEventListener("change", () => {
    const box = input.closest("form").querySelector(".thumbs");
    box.innerHTML = "";
    [...input.files].slice(0, 20).forEach((f) => {
      if (!f.type.startsWith("image/") || /heic|heif/i.test(f.type)) {
        const s = document.createElement("span"); s.className = "pill"; s.textContent = f.name; box.appendChild(s); return;
      }
      const img = document.createElement("img"); img.src = URL.createObjectURL(f); box.appendChild(img);
    });
  });
});

// ---------- settings ----------
async function loadSettings() {
  const s = await (await fetch("/api/settings")).json();
  const f = $("#settings-form");
  for (const [k, v] of Object.entries(s)) if (f.elements[k] && k !== "api_key") f.elements[k].value = v ?? "";
  $("#key-hint").textContent = s.api_key_set ? `(saved ${s.api_key_hint || "from environment"})` : "(not set)";
  return s;
}
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  e.target.elements.api_key.value = "";
  await loadSettings();
  checkSetup();
  const ok = $("#settings-saved"); ok.classList.remove("hidden"); setTimeout(() => ok.classList.add("hidden"), 2000);
});
async function checkSetup() {
  const s = await (await fetch("/api/settings")).json();
  document.body.classList.toggle("no-key", !s.api_key_set);
  $("#setup-banner").classList.toggle("hidden", !!s.zip);
}

// ---------- running AI tasks ----------
async function runTask(url, form) {
  hideResult();
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;
  const res = await fetch(url, { method: "POST", body: new FormData(form) });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { btn.disabled = false; return showError(body.error || "Request failed"); }

  const log = $("#progress-log");
  log.innerHTML = "";
  $("#progress").classList.remove("hidden");
  $("#progress").scrollIntoView({ behavior: "smooth" });
  let seen = 0;
  while (true) {
    await new Promise((r) => setTimeout(r, 1500));
    let t;
    try { t = await (await fetch(`/api/tasks/${body.task_id}`)).json(); }
    catch { continue; }
    for (; seen < (t.progress || []).length; seen++) {
      const li = document.createElement("li"); li.textContent = t.progress[seen]; log.appendChild(li);
      log.scrollTop = log.scrollHeight;
    }
    if (t.error && !t.status) { showError(t.error); break; }
    if (t.status === "error") { showError(t.error); break; }
    if (t.status === "done") { await openJob(t.job_id); break; }
  }
  $("#progress").classList.add("hidden");
  btn.disabled = false;
}
// manual mode: build the prompt, then show the copy / paste steps
$$("[data-manual]").forEach((btn) => btn.addEventListener("click", async () => {
  hideResult();
  const form = btn.closest("form");
  btn.disabled = true;
  try {
    const res = await fetch(btn.dataset.manual, { method: "POST", body: new FormData(form) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) return showError(body.error || "Request failed");
    await openJob(body.job_id);
    copyPrompt(true);
  } finally { btn.disabled = false; }
}));

async function copyPrompt(silent = false) {
  const text = (currentJob && currentJob.pending && currentJob.pending.prompt) || "";
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch {
    const ta = $("#prompt-text");
    if (ta) { ta.closest("details").open = true; ta.select(); try { ok = document.execCommand("copy"); } catch {} }
  }
  const tag = $("#copied");
  if (tag) {
    tag.textContent = ok ? "Copied ✓" : (silent ? "" : "Select the prompt below and press ⌘C");
    tag.classList.remove("hidden");
  }
}

$("#estimate-form").addEventListener("submit", (e) => { e.preventDefault(); runTask("/api/estimate", e.target); });
$("#quote-form").addEventListener("submit", (e) => { e.preventDefault(); runTask("/api/check-quote", e.target); });

// ---------- jobs ----------
async function loadJobs() {
  const jobs = await (await fetch("/api/jobs")).json();
  const tb = $("#tab-jobs tbody");
  tb.innerHTML = jobs.map((j) => `
    <tr>
      <td><a data-open="${esc(j.id)}">${esc(j.name || "(untitled job)")}</a>${j.pending ? ' <span class="pill wait">waiting for Claude reply</span>' : ""}</td>
      <td>${esc((j.created_at || "").replace("T", " ").slice(0, 16))}</td>
      <td class="num">${j.has_estimate ? money(j.estimate_total) : "—"}</td>
      <td class="num">${j.has_quote_check ? money(j.quote_total) : "—"}</td>
      <td class="num"><button class="link" data-del="${esc(j.id)}">Delete</button></td>
    </tr>`).join("");
  $("#tab-jobs .empty").classList.toggle("hidden", jobs.length > 0);
}
$("#tab-jobs").addEventListener("click", async (e) => {
  const open = e.target.closest("[data-open]");
  const del = e.target.closest("[data-del]");
  if (open) openJob(open.dataset.open);
  if (del && confirm("Delete this job and its photos?")) {
    await fetch(`/api/jobs/${del.dataset.del}`, { method: "DELETE" });
    hideResult(); loadJobs();
  }
});
async function loadJobOptions() {
  const jobs = await (await fetch("/api/jobs")).json();
  const sel = $("#quote-form select[name=job_id]");
  const keep = sel.value;
  sel.innerHTML = '<option value="">— none —</option>' +
    jobs.map((j) => `<option value="${esc(j.id)}">${esc(j.name)} (${esc((j.created_at || "").slice(0, 10))})</option>`).join("");
  sel.value = keep;
}

async function openJob(id) {
  const res = await fetch(`/api/jobs/${id}`);
  if (!res.ok) return showError("Couldn't load that job.");
  currentJob = await res.json();
  renderJob();
}

// ---------- rendering ----------
function stat(label, value, sub = "", cls = "") {
  return `<div class="stat ${cls}"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
}
function list(title, items, cls = "") {
  if (!items || !items.length) return "";
  return `<h3>${title}</h3><ul class="plain ${cls}">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
}

function itemsTable(kind, data) {
  const rows = (data.line_items || []).map((it, i) => {
    const link = it.source_url ? `<a href="${esc(it.source_url)}" target="_blank" rel="noopener">${esc(it.supplier || "source")}</a>` : esc(it.supplier || "estimated");
    return `<tr>
      <td>${esc(it.category)}</td>
      <td><strong>${esc(it.item)}</strong><div class="spec">${esc(it.spec)}</div>${it.quantity_math ? `<div class="math">${esc(it.quantity_math)}</div>` : ""}${it.notes ? `<div class="math">${esc(it.notes)}</div>` : ""}</td>
      <td class="num"><input class="edit" data-kind="${kind}" data-i="${i}" data-f="quantity" type="number" step="any" value="${it.quantity}"> ${esc(it.unit)}</td>
      <td class="num"><input class="edit" data-kind="${kind}" data-i="${i}" data-f="unit_price" type="number" step="0.01" value="${it.unit_price}"><div class="spec">${money(it.price_low)}–${money(it.price_high)}</div></td>
      <td class="num"><strong>${money(it.line_total)}</strong></td>
      <td>${link} ${it.is_local ? '<span class="pill local">local</span>' : ""}<br><span class="pill ${esc(it.confidence)}">${esc(it.confidence)} confidence</span></td>
      <td><button class="link" data-remove="${i}" data-kind="${kind}" title="Remove line">✕</button></td>
    </tr>`;
  }).join("");
  const t = data.totals;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Category</th><th>Item</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Total</th><th>Source</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <table class="totals" style="max-width:380px;margin-left:auto;margin-top:10px">
      <tr><td>Items subtotal</td><td class="num">${money(t.items_subtotal)}</td></tr>
      <tr><td>Waste (${t.waste_pct}%)</td><td class="num">${money(t.waste_amount)}</td></tr>
      <tr><td>Consumables allowance</td><td class="num">${money(t.consumables)}</td></tr>
      <tr><td>Sales tax (${t.sales_tax_pct}%)</td><td class="num">${money(t.sales_tax)}</td></tr>
      <tr class="grand"><td>Material total</td><td class="num">${money(t.expected)}</td></tr>
      <tr><td class="spec">Range</td><td class="num spec">${money(t.low)} – ${money(t.high)}</td></tr>
    </table>
    ${data.consumables_note ? `<p class="summary">Consumables: ${esc(data.consumables_note)}</p>` : ""}`;
}

function renderJob(scroll = true) {
  const j = currentJob;
  let html = "";
  const pd = j.pending;
  if (pd) {
    const what = pd.kind === "estimate" ? "material estimate" : "quote check";
    html += `<div class="card pending">
      <h2>Run the ${what} in your Claude app${j.name ? " – " + esc(j.name) : ""}</h2>
      <ol class="steps">
        <li><button class="primary" data-copy>Copy prompt</button> <span id="copied" class="saved hidden"></span><br>
          Open <a href="https://claude.ai/new" target="_blank" rel="noopener">claude.ai</a> or the Claude app and start a <b>new chat</b>.
          Make sure <b>Web search</b> is on (in the “Search and tools” menu).</li>
        <li>Paste the prompt (⌘V).
          ${pd.photos ? `Attach the ${pd.photos} photo(s) too. <button data-reveal>Show photos in Finder</button>` : ""}
          ${pd.pdf ? "Attach the Jobber quote PDF too." : ""} Then send it.</li>
        <li>Wait for Claude to finish. It searches stores, which takes a few minutes. Then copy its final reply.
          The quickest way is the copy button on the code block.</li>
        <li>Paste Claude’s reply here:
          <textarea id="reply-text" rows="6" placeholder="Paste Claude's reply here"></textarea>
          <button class="primary" data-import>Import results</button>
          <button class="link" data-cancel>Cancel</button></li>
      </ol>
      <details><summary>Show the prompt</summary><textarea id="prompt-text" rows="8" readonly>${esc(pd.prompt)}</textarea></details>
    </div>`;
  }
  const qc = j.quote_check;
  if (qc) {
    const p = qc.profit, e = p.expected;
    const cls = (m) => (m >= 0 ? "good" : "bad");
    html += `<div class="card">
      <h2>Quote check – ${esc(j.name)}</h2>
      <p class="summary">${esc(qc.quote_summary)}</p>
      <div class="stats">
        ${stat("Quote total", money(p.quote_total), p.revenue_basis !== p.quote_total ? `${money(p.revenue_basis)} before tax` : "")}
        ${stat("Material cost", money(e.material_cost), `${p.material_pct_of_quote}% of quote · range ${money(p.best_case.material_cost)}–${money(p.worst_case.material_cost)}`)}
        ${stat("After materials", money(e.gross_after_materials), `${e.gross_margin_pct}% margin`, cls(e.gross_after_materials))}
        ${stat("Net profit", money(e.net_profit), `${e.net_margin_pct}% · labor ${money(p.labor_cost)} + other ${money(p.other_costs)}`, cls(e.net_profit))}
      </div>
      <p class="summary">Net profit range: ${money(p.worst_case.net_profit)} (high material prices) to ${money(p.best_case.net_profit)} (low prices).</p>
      <div class="row" id="labor-row">
        <label>Labor hours <input data-labor="hours" type="number" step="0.25" value="${qc.labor?.hours || ""}"></label>
        <label>Labor cost / hr <input data-labor="rate" type="number" step="0.01" value="${qc.labor?.rate || ""}"></label>
        <label>Other costs $ <input data-labor="other" type="number" step="0.01" value="${qc.labor?.other || ""}"></label>
      </div>
      ${list("⚠️ Watch out for", qc.warnings, "warn-list")}
      ${list("Differences from the assessment", qc.scope_differences)}
      <h3>Materials needed for the quoted work</h3>
      ${itemsTable("quote_check", qc)}
      ${qc.quote_line_items?.length ? `<h3>Quote line items (as read)</h3><div class="table-wrap"><table>
        <thead><tr><th>Line</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Total</th></tr></thead>
        <tbody>${qc.quote_line_items.map((l) => `<tr><td><strong>${esc(l.name)}</strong><div class="spec">${esc(l.description)}</div></td><td class="num">${l.quantity}</td><td class="num">${money(l.unit_price)}</td><td class="num">${money(l.total)}</td></tr>`).join("")}</tbody></table></div>` : ""}
      ${qc.pricing_notes ? `<h3>Pricing notes</h3><p class="summary">${esc(qc.pricing_notes)}</p>` : ""}
      <div class="actions">
        <a href="/api/jobs/${esc(j.id)}/csv?kind=quote_check"><button>Download CSV</button></a>
        <button onclick="window.print()">Print</button>
      </div>
    </div>`;
  }
  const est = j.estimate;
  if (est) {
    html += `<div class="card">
      <h2>Material estimate – ${esc(j.name)}</h2>
      <p class="summary">${esc(est.job_summary)}</p>
      <div class="stats">
        ${stat("Estimated materials", money(est.totals.expected), "incl. waste, consumables & tax")}
        ${stat("Low – high", `${money(est.totals.low)}`, `up to ${money(est.totals.high)}`)}
        ${stat("Line items", (est.line_items || []).length, `${j.photo_count || 0} photo(s) saved`)}
      </div>
      ${list("Scope of work", est.scope_of_work)}
      <h3>Materials</h3>
      ${itemsTable("estimate", est)}
      ${list("Assumptions", est.assumptions)}
      ${list("Confirm with the customer", est.questions_to_confirm, "warn-list")}
      ${est.pricing_notes ? `<h3>Pricing notes</h3><p class="summary">${esc(est.pricing_notes)}</p>` : ""}
      <div class="actions">
        <a href="/api/jobs/${esc(j.id)}/csv?kind=estimate"><button>Download CSV</button></a>
        <button onclick="window.print()">Print</button>
        <button data-check-quote="${esc(j.id)}">Check the Jobber quote for this job →</button>
      </div>
    </div>`;
  }
  const r = $("#result");
  r.innerHTML = html;
  r.classList.remove("hidden");
  if (scroll) r.scrollIntoView({ behavior: "smooth" });
}

// edits inside results
let editTimer;
$("#result").addEventListener("change", async (e) => {
  const el = e.target;
  if (el.matches("input.edit")) {
    const res = await fetch(`/api/jobs/${currentJob.id}/items`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: el.dataset.kind, edits: [{ index: +el.dataset.i, [el.dataset.f]: el.value }] }),
    });
    currentJob = await res.json(); renderJobKeepScroll();
  }
  if (el.matches("[data-labor]")) {
    clearTimeout(editTimer);
    editTimer = setTimeout(async () => {
      const body = {}; $$("[data-labor]").forEach((i) => (body[i.dataset.labor] = i.value));
      const res = await fetch(`/api/jobs/${currentJob.id}/labor`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      currentJob = await res.json(); renderJobKeepScroll();
    }, 200);
  }
});
$("#result").addEventListener("click", async (e) => {
  const rm = e.target.closest("[data-remove]");
  if (rm && confirm("Remove this line?")) {
    const res = await fetch(`/api/jobs/${currentJob.id}/items`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: rm.dataset.kind, delete: +rm.dataset.remove }),
    });
    currentJob = await res.json(); renderJobKeepScroll();
  }
  if (e.target.closest("[data-copy]")) copyPrompt();
  if (e.target.closest("[data-reveal]")) {
    const res = await fetch(`/api/jobs/${currentJob.id}/reveal-photos`, { method: "POST" });
    const b = await res.json();
    if (!res.ok) showError(b.error); else if (!b.opened) alert("Photos are saved in:\n" + b.path);
  }
  if (e.target.closest("[data-import]")) {
    const text = $("#reply-text").value;
    if (!text.trim()) return showError("Paste Claude's reply first.");
    const res = await fetch(`/api/jobs/${currentJob.id}/import`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    const b = await res.json();
    if (!res.ok) return showError(b.error);
    $("#error").classList.add("hidden");
    currentJob = b; renderJob();
  }
  if (e.target.closest("[data-cancel]") && confirm("Cancel this? The prompt will be discarded.")) {
    const b = await (await fetch(`/api/jobs/${currentJob.id}/cancel-pending`, { method: "POST" })).json();
    if (b.deleted) hideResult(); else { currentJob = b; renderJob(); }
  }
  const cq = e.target.closest("[data-check-quote]");
  if (cq) {
    showTab("quote");
    await loadJobOptions();
    $("#quote-form select[name=job_id]").value = cq.dataset.checkQuote;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
});
function renderJobKeepScroll() { const y = window.scrollY; renderJob(false); window.scrollTo(0, y); }

checkSetup();
