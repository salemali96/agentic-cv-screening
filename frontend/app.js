"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const f1 = n => (n == null || isNaN(n)) ? "–" : (+n).toFixed(1);
const clone = o => JSON.parse(JSON.stringify(o));

const S = { pid: null, saved: null, draft: null, baseline: null, ranking: null, compare: null, view: "setup", cid: null, guide: null, settings: null, detail: null };

async function api(method, path, body, isForm) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opt.body = body; else { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  }
  const r = await fetch(path, opt);
  let j = null; try { j = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((j && j.detail) || r.statusText);
  return j;
}
let toastT;
function toast(m) { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 3500); }
const sleep = ms => new Promise(r => setTimeout(r, ms));
// Long agent runs execute as background jobs on the server; the page polls and shows the log as it grows.
function usageText(u) {
  if (!u || !u.calls) return "";
  return ` · ${u.calls} model calls · ${(u.input_tokens + u.output_tokens).toLocaleString()} tokens` + (u.retries ? ` · ${u.retries} retries (${Math.round(u.waited_seconds)} s waiting)` : "");
}
async function followJob(job, done) {
  const box = $("#live"); if (!box) return;
  box.hidden = false;
  box.innerHTML = `<h3 id="liveHead"></h3><ol class="log" id="liveLog"></ol>`;
  let since = 0, j = job;
  const finishedNow = job.status === "done" || job.status === "error";  // serverless hosting runs jobs inside the request
  while (true) {
    if (!(finishedNow && since === 0)) { try { j = await api("GET", `/api/jobs/${job.id}?since=${since}`); } catch (er) { toast(er.message); return; } }
    if (!$("#liveLog")) return;  // user left the view; the job keeps running on the server
    $("#liveLog").insertAdjacentHTML("beforeend", j.log.filter(l => l.kind !== "summary").map(l => `<li>${l.kind && LOGK[l.kind] ? chip(LOGK[l.kind]) + " " : ""}${esc(l.text)}</li>`).join(""));
    since = j.log_total;
    $("#liveHead").innerHTML = `${esc(j.label)} <span class="muted small-t">${j.status === "running" || j.status === "queued" ? "running" : j.status} · ${Math.round(j.elapsed)} s${usageText(j.usage)}</span>`;
    if (j.status === "done" || j.status === "error") break;
    await sleep(1500);
  }
  if (j.status === "error") toast(j.error);
  await done(j);
}
async function runJob(kind, body, btn, label, done) {
  busy(btn, true, label);
  let job;
  try { job = await api("POST", `/api/positions/${S.pid}/jobs`, { kind, ...body }); }
  catch (er) { toast(er.message); busy(btn, false); return; }
  await followJob(job, done);
}
async function reattachJob(kinds, btn, label, done) {
  const j = await api("GET", `/api/positions/${S.pid}/jobs/current`).catch(() => null);
  if (j && kinds.includes(j.kind)) { busy(btn, true, label); await followJob(j, done); }
}
function busy(btn, on, label) { if (!btn) return; if (on) { btn.dataset.l = btn.textContent; btn.textContent = label || "Working…"; btn.disabled = true; } else { btn.textContent = btn.dataset.l || btn.textContent; btn.disabled = false; } }

const CRIT = { qualifications: "Qualifications", publications: "Research publications", teaching: "Teaching experience", research_experience: "Academic & research experience", leadership: "Leadership & service", funding: "Research funding", supervision: "Research supervision" };
const ELIG = { eligible: ["Eligible", "c-good"], unresolved: ["Eligibility not established", "c-warn"], ineligible: ["Ineligible", "c-bad"] };
const SL = { robust_in: ["Shortlisted (robust)", "c-good"], uncertain: ["Uncertain: verify", "c-warn"], robust_out: ["Not shortlisted (robust)", ""], ineligible: ["Ineligible", "c-bad"] };
const RS = { met: ["Met", "c-good"], not_met: ["Not met", "c-bad"], not_established: ["Not established", "c-warn"], manual: ["Committee judgement", "c-info"], not_used: ["Not used", ""] };
const TIER = { required: "Required", preferred: "Preferred", nice: "Good to have", hr: "Committee", excluded: "Not used" };
const LOGK = { agent: ["Agent", "c-acc"], tool: ["Action", "c-info"], decision: ["Decision", "c-good"], error: ["Refused / error", "c-warn"], info: ["Run", ""] };
const chip = ([t, c]) => `<span class="chip ${c}">${esc(t)}</span>`;
const vf = c => ({ exact: "✓ found in document", approx: "≈ close match in document", missing: "⚠ not found in document", external: "✓ external / reply" }[c] || "");

function evidenceHtml(list) {
  return (list || []).map(e => `<div class="ev">“${esc(e.quote)}” <b>— ${esc(e.doc || "")}</b> <span class="vf-${esc(e.check)}">${vf(e.check)}</span>${e.url ? ` · <a href="${esc(e.url)}" target="_blank" rel="noopener">source</a>` : ""}</div>`).join("");
}

// ------------------------------------------------------------------------------------------------
async function boot() {
  [S.guide, S.settings] = await Promise.all([api("GET", "/api/guide"), api("GET", "/api/settings")]);
  if (S.settings.llm.public_demo) $(".top").insertAdjacentHTML("afterend", `<div class="demo-banner">Public demo with fictional applications. AI model calls, uploads and live lookups are switched off; the agents run their scripted versions on recorded data. Run it locally to use your own model and files.</div>`);
  let ps = await api("GET", "/api/positions");
  if (!ps.length) { await api("POST", "/api/positions", { demo: true }); ps = await api("GET", "/api/positions"); toast("Created an example position with 14 demo applications."); }
  let pid = null; try { pid = localStorage.getItem("pid"); } catch (e) {}
  if (!ps.find(p => p.id === pid)) pid = ps[ps.length - 1].id;
  await selectPosition(pid);
  $("#tabs").onclick = e => { const b = e.target.closest("button"); if (b) go(b.dataset.v); };
  $("#posSelect").onchange = e => selectPosition(e.target.value);
  $("#newPos").onclick = async () => { const r = await api("POST", "/api/positions", {}); await selectPosition(r.id); go("setup"); toast("New position created with the default academic template."); };
  window.onhashchange = () => { const v = location.hash.slice(1); if (v && v !== S.view) go(v, true); };
  go(location.hash.slice(1) || "ranking", true);
}

async function selectPosition(pid) {
  S.pid = pid; try { localStorage.setItem("pid", pid); } catch (e) {}
  const p = await api("GET", `/api/positions/${pid}`);
  S.saved = p.template; S.draft = clone(p.template); S.position = p; S.baseline = null; S.compare = null;
  const ps = await api("GET", "/api/positions");
  $("#posSelect").innerHTML = ps.map(x => `<option value="${x.id}" ${x.id === pid ? "selected" : ""}>${esc(x.title)} (${x.candidates})</option>`).join("");
  $("#posTitle").textContent = S.draft.position.title;
  await refreshRanking();
  render();
}

async function refreshRanking() {
  S.ranking = await api("POST", `/api/positions/${S.pid}/rank`, { template: S.draft });
  if (S.baseline) {
    const c = await api("POST", `/api/positions/${S.pid}/compare`, { template_a: S.baseline, template_b: S.draft });
    S.compare = Object.fromEntries(c.changes.map(x => [x.candidate_id, x]));
  } else S.compare = null;
}

function go(v, fromHash) {
  if (v.startsWith("cand-")) { S.cid = v.slice(5); v = "candidate"; }
  S.view = v;
  if (!fromHash) location.hash = v === "candidate" ? "cand-" + S.cid : v;
  [...$("#tabs").children].forEach(b => b.setAttribute("aria-current", b.dataset.v === v));
  render();
  window.scrollTo(0, 0);
}
function render() {
  const v = S.view;
  if (v === "setup") return renderSetup();
  if (v === "applications") return renderApplications();
  if (v === "candidate") return renderCandidate();
  if (v === "resolve") return renderResolve();
  if (v === "screen") return renderScreening();
  return renderRanking();
}
const dirty = () => JSON.stringify(S.draft) !== JSON.stringify(S.saved);

// ------------------------------------------------------------------------------------------------
// 1. Position and parameters
// ------------------------------------------------------------------------------------------------
const PARAMS = [
  ["Publications", [["criteria.publications.recency_years", "Recency window (years)", 1, 15, 1], ["criteria.publications.points.journal", "Points per journal article", 0, 5, 0.25], ["criteria.publications.points.conference", "Points per conference paper", 0, 5, 0.25], ["criteria.publications.cap", "Points needed for full marks", 1, 30, 1]]],
  ["Teaching", [["criteria.teaching.points_per_year.lead", "Points per year as lead instructor", 0, 5, 0.25], ["criteria.teaching.points_per_year.assistant", "Points per year as assistant", 0, 5, 0.25], ["criteria.teaching.cap", "Points needed for full marks", 1, 30, 1]]],
  ["Academic & research experience", [["criteria.research_experience.points_per_year", "Points per year in academic or research posts", 0, 5, 0.25], ["criteria.research_experience.cap", "Points needed for full marks", 1, 30, 1]]],
  ["Leadership & service", [["criteria.leadership.points_per_year", "Points per year in a leadership role", 0, 5, 0.25], ["criteria.leadership.cap", "Points needed for full marks", 1, 30, 1]]],
  ["Funding", [["criteria.funding.points.PI", "Points per grant as PI", 0, 10, 0.5], ["criteria.funding.points.Co-I", "Points per grant as Co-I", 0, 10, 0.5]]],
  ["Qualifications", [["criteria.qualifications.points.phd", "PhD (out of 10)", 0, 10, 0.5], ["criteria.qualifications.points.phd_in_progress", "PhD in progress", 0, 10, 0.5], ["criteria.qualifications.points.masters", "Master's", 0, 10, 0.5], ["criteria.qualifications.unrelated_field_factor", "Multiplier if field is unrelated", 0, 1, 0.05]]],
  ["Incomplete information", [["uncertainty.undated_role_min_years", "Years credited to an undated role (supported score)", 0, 5, 0.5], ["uncertainty.undated_role_max_years", "Years an undated role could represent (possible score)", 0, 10, 0.5], ["criteria.supervision.unknown_count_max", "Students assumed at most when the count is not stated", 1, 10, 1]]],
];
const getP = (o, path) => path.split(".").reduce((a, k) => a?.[k], o);
function setP(o, path, v) { const ks = path.split("."); let a = o; ks.slice(0, -1).forEach(k => a = a[k]); a[ks[ks.length - 1]] = v; }

function weightsHtml(compact) {
  const cr = S.draft.criteria, tot = Object.values(cr).reduce((a, c) => a + (+c.weight || 0), 0) || 1;
  return Object.keys(CRIT).map(k => `<div class="param"><label for="w_${k}">${CRIT[k]} <span class="muted small-t">(${(cr[k].weight / tot * 100).toFixed(0)}% of the score)</span></label>
    <span class="row"><input type="range" id="wr_${k}" data-w="${k}" min="0" max="60" step="1" value="${cr[k].weight}"><input type="number" id="w_${k}" data-w="${k}" min="0" max="100" value="${cr[k].weight}"></span>
    ${compact ? "" : `<div class="explain">${esc(S.guide.criteria[k])}</div>`}</div>`).join("");
}
function bindWeights(root, after) {
  root.querySelectorAll("[data-w]").forEach(inp => inp.addEventListener("input", e => {
    S.draft.criteria[e.target.dataset.w].weight = Math.max(0, +e.target.value || 0);
    root.querySelectorAll(`[data-w="${e.target.dataset.w}"]`).forEach(x => { if (x !== e.target) x.value = e.target.value; });
    clearTimeout(bindWeights.t); bindWeights.t = setTimeout(after, 250);
  }));
}

function renderSetup() {
  const t = S.draft, g = S.guide;
  $("#view").innerHTML = `
  <div class="row spread"><h1>Position and evaluation parameters</h1>
    <div class="row"><span class="chip c-warn" id="dirtyChip" ${dirty() ? "" : "hidden"}>Unsaved changes · ranking already uses them</span><button id="resetDraft">Undo changes</button><button id="saveDraft" class="primary">Save parameters</button></div></div>
  <div class="grid2">
    <section class="panel"><h2>Position</h2>
      <label class="label" for="pTitle">Title</label><input id="pTitle" value="${esc(t.position.title)}">
      <label class="label" for="pDesc">Advert / description</label><textarea id="pDesc" rows="7">${esc(t.position.description)}</textarea>
      <div class="row"><label for="pK" class="label">Shortlist size (k)</label><input type="number" id="pK" min="1" max="50" value="${t.shortlist_size}">
      <span class="muted small-t">The top k eligible candidates by supported score form the shortlist.</span></div>
    </section>
    <section class="panel"><h2>Requirements</h2>
      <p class="muted small-t" style="margin:0">Required items decide eligibility: <b>not met</b> (positive evidence) makes a candidate ineligible; <b>not established</b> (missing or unclear) leaves eligibility open. An omission is never treated as “not met”.</p>
      ${t.requirements.map(r => `<div class="req"><span>${chip([TIER[r.tier], r.tier === "required" ? "c-bad" : r.tier === "preferred" ? "c-warn" : r.tier === "nice" ? "c-good" : "c-info"])}</span><span>${esc(r.text)}<br><span class="muted small-t">${esc(g.req_kinds[r.kind] || r.kind)}</span></span></div>`).join("")}
      <p class="muted small-t" style="margin:0">Requirement thresholds are set in the position template (editing them on screen is planned).</p>
    </section>
  </div>
  <section class="panel"><h2>How the overall score is calculated</h2>
    <p style="margin:0" class="mono small-t">criterion score (0–10) = min(points, cap) ÷ cap × 10 &nbsp;·&nbsp; overall (0–100) = Σ (weight ÷ total weight) × criterion score × 10</p>
    <p style="margin:0" class="muted">Every candidate gets two scores. The <b>supported score</b> counts only facts with evidence found in the documents (or confirmed by a verified source or a reply). The <b>possible score</b> is the highest the candidate could reach if every unresolved item were resolved in their favour, under the rules below. If that range crosses the shortlist cut-off, the candidate is marked <b>uncertain</b> instead of being ordered confidently.</p>
  </section>
  <div class="grid2">
    <section class="panel"><h2>Criterion weights</h2><p class="muted small-t" style="margin:0">Weights are relative: each is divided by the total. Raising a weight helps candidates who score above average on that criterion.</p><div id="wbox">${weightsHtml(false)}</div></section>
    <section class="panel"><h2>Scoring rules</h2>
      ${PARAMS.map(([grp, ps]) => `<details ${grp === "Incomplete information" ? "open" : ""}><summary>${esc(grp)}</summary>${ps.map(([path, lab, mn, mx, st]) => `<div class="param"><label for="p_${path}">${esc(lab)}</label><input type="number" id="p_${path}" data-p="${path}" min="${mn}" max="${mx}" step="${st}" value="${getP(t, path)}"></div>`).join("")}</details>`).join("")}
    </section>
  </div>
  <section class="panel"><h2>What each parameter changes</h2>${g.parameters.map(p => `<div class="param"><b>${esc(p.param)}</b><span class="mono small-t muted">${esc(p.where)}</span><div class="explain">${esc(p.effect)}</div></div>`).join("")}</section>
  <section class="panel"><h2>AI model</h2>
    <p class="muted small-t" style="margin:0 0 8px">Used to read applications (extraction) and to run the missing-information agent. Any provider below can be selected; add your own for OpenAI, Ollama, OpenRouter, Groq, Mistral, DeepSeek, Together, LM Studio or any other OpenAI-compatible server.</p>
    <div class="formrow"><label>Active provider<select id="prov"><option value="offline">Offline (stored extractions for demo applications)</option>${S.settings.llm.providers.map(p => `<option value="${esc(p.id)}">${esc(p.label)}${p.model ? " · " + esc(p.model) : ""}</option>`).join("")}</select></label><button id="useProv" class="primary">Use this provider</button></div>
    <div id="provEdit"></div>
    <details><summary>Add a provider</summary>
      <div class="formrow"><label>Template<select id="npPreset">${S.settings.llm.presets.map(p => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("")}</select></label>
        <label>Name<input id="npName"></label><label>Base URL<input id="npUrl" placeholder="https://…/v1"></label>
        <label>Model<input id="npModel" placeholder="model name, as the provider spells it"></label>
        <label>API key<input type="password" id="npKey" placeholder="leave empty for local servers"></label><button id="npAdd">Add provider</button></div>
    </details>
    <p class="muted small-t" style="margin:0">Keys are held in the server's memory only (or read from an environment variable) and are never sent to the browser. Extraction answers are cached, so re-running is free and reproducible. Small local models may not support tool calling, which the agent needs.</p>
  </section>`;
  $("#prov").value = S.settings.llm.provider;
  const after = async () => {
    await refreshRanking(); $("#dirtyChip").hidden = !dirty();
    const tot = Object.values(S.draft.criteria).reduce((a, c) => a + (+c.weight || 0), 0) || 1;
    Object.keys(CRIT).forEach(k => { const l = $(`label[for="w_${k}"] .muted`); if (l) l.textContent = `(${(S.draft.criteria[k].weight / tot * 100).toFixed(0)}% of the score)`; });
  };
  $("#pTitle").addEventListener("change", () => { $("#dirtyChip").hidden = !dirty(); });
  bindWeights($("#wbox"), after);
  $("#view").querySelectorAll("[data-p]").forEach(i => i.addEventListener("input", e => { setP(S.draft, e.target.dataset.p, +e.target.value); clearTimeout(bindWeights.t); bindWeights.t = setTimeout(after, 300); }));
  $("#pTitle").oninput = e => { S.draft.position.title = e.target.value; };
  $("#pDesc").oninput = e => { S.draft.position.description = e.target.value; };
  $("#pK").oninput = e => { S.draft.shortlist_size = Math.max(1, +e.target.value || 1); clearTimeout(bindWeights.t); bindWeights.t = setTimeout(after, 300); };
  $("#resetDraft").onclick = async () => { S.draft = clone(S.saved); await refreshRanking(); renderSetup(); };
  $("#saveDraft").onclick = async e => { busy(e.target, true); try { const r = await api("PUT", `/api/positions/${S.pid}/template`, S.draft); S.saved = r.template; S.draft = clone(r.template); $("#posTitle").textContent = S.draft.position.title; toast("Parameters saved."); renderSetup(); } finally { busy(e.target, false); } };
  const LLM = S.settings.llm, saveLLM = async body => { const r = await api("PUT", "/api/settings", body); S.settings.llm = r.llm; renderSetup(); return r; };
  const editProv = () => {
    const p = LLM.providers.find(x => x.id === $("#prov").value), box = $("#provEdit");
    if (!p) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="formrow"><span class="muted small-t">${esc(LLM.protocols[p.kind])}</span>
      ${p.builtin ? "" : `<label>Name<input id="peName" value="${esc(p.label)}"></label>`}
      ${p.kind === "openai" ? `<label>Base URL<input id="peUrl" value="${esc(p.base_url || "")}"></label>` : ""}
      <label>Model<input id="peModel" value="${esc(p.model)}" placeholder="required"></label>
      <label>API key<input type="password" id="peKey" placeholder="${p.key_set ? "set (hidden)" : p.key_required ? "not set" + (p.key_env ? " (or set " + esc(p.key_env) + ")" : "") : "optional"}"></label>
      <button id="peSave">Save</button>${p.builtin ? "" : `<button id="peDel" class="small">Remove</button>`}</div>`;
    $("#peSave").onclick = async () => {
      const u = { model: $("#peModel").value };
      if ($("#peName")) u.label = $("#peName").value; if ($("#peUrl")) u.base_url = $("#peUrl").value; if ($("#peKey").value) u.key = $("#peKey").value;
      try { await saveLLM({ providers: { [p.id]: u } }); toast("Provider saved."); } catch (er) { toast(er.message); }
    };
    if ($("#peDel")) $("#peDel").onclick = async () => { try { const r = await api("DELETE", `/api/settings/providers/${encodeURIComponent(p.id)}`); S.settings.llm = r.llm; renderSetup(); toast("Provider removed."); } catch (er) { toast(er.message); } };
  };
  $("#prov").value = LLM.provider; editProv();
  $("#prov").onchange = editProv;
  $("#useProv").onclick = async () => { try { await saveLLM({ provider: $("#prov").value }); toast("Now using: " + S.settings.llm.active_label); } catch (er) { toast(er.message); } };
  const preset = () => { const t = LLM.presets.find(x => x.id === $("#npPreset").value); $("#npName").value = t.label; $("#npUrl").value = t.base_url; };
  $("#npPreset").onchange = preset; preset();
  $("#npAdd").onclick = async () => {
    const t = LLM.presets.find(x => x.id === $("#npPreset").value), name = $("#npName").value.trim() || t.label;
    let id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "provider";
    while (LLM.providers.some(x => x.id === id)) id += "-2";
    const body = { label: name, kind: t.kind, base_url: $("#npUrl").value, model: $("#npModel").value, key_required: t.key_required !== false };
    if ($("#npKey").value) body.key = $("#npKey").value;
    try { await saveLLM({ providers: { [id]: body }, provider: id }); toast("Added and selected: " + name); } catch (er) { toast(er.message); }
  };
}

// ------------------------------------------------------------------------------------------------
// 2. Applications
// ------------------------------------------------------------------------------------------------
async function renderApplications() {
  const list = await api("GET", `/api/positions/${S.pid}/candidates`);
  const st = s => ({ uploaded: ["Not extracted", ""], extracting: ["Extracting…", "c-info"], extracted: ["Extracted", "c-good"], error: ["Error", "c-bad"] }[s] || [s, ""]);
  $("#view").innerHTML = `
  <div class="row spread"><h1>Applications <span class="muted">(${list.length} / 100)</span></h1>
    <div class="row"><button id="demo">Add the 14 demo applications</button><button id="exAll" class="primary">Extract information from all</button></div><div id="live" class="live" hidden></div></div>
  <section class="panel">
    <div class="drop" id="drop" tabindex="0" role="button"><b>Drop application files or folders here</b><br><span class="muted small-t">PDF, DOCX or TXT. Put each applicant's files in one folder, or name them like <span class="mono">omar_farouk_cv.pdf</span>, <span class="mono">omar_farouk_cover_letter.pdf</span>, <span class="mono">omar_farouk_publications.pdf</span>.</span></div>
    <div class="row"><input type="file" id="fFiles" multiple accept=".pdf,.docx,.txt" hidden><button id="pickFiles">Choose files</button><input type="file" id="fDir" webkitdirectory multiple hidden><button id="pickDir">Choose a folder</button>
    <span class="muted small-t">AI model: <b>${esc(S.settings.llm.active_label)}</b>. Offline mode can only extract the demo applications; choose a provider under step 1 for your own files.</span></div>
  </section>
  <div class="table-wrap"><table><thead><tr><th>Applicant</th><th>Documents</th><th>Extraction</th><th>Evidence check</th><th></th></tr></thead><tbody>
  ${list.length ? list.map(c => `<tr><td><b>${esc(c.name)}</b>${c.scenario ? `<div class="muted small-t">${esc(c.scenario)}</div>` : ""}${(c.upload_errors || []).map(e => `<div class="small-t" style="color:var(--bad)">${esc(e)}</div>`).join("")}</td>
    <td>${c.documents.map(d => `<span class="chip">${esc(d.type.replace("_", " "))}</span>`).join(" ")}</td>
    <td>${chip(st(c.status))}${c.error ? `<div class="small-t" style="color:var(--bad)">${esc(c.error)}</div>` : ""}</td>
    <td class="small-t">${c.quote_check ? `${c.quote_check.exact + c.quote_check.approx} quotes found, <span style="color:${c.quote_check.missing ? "var(--bad)" : "inherit"}">${c.quote_check.missing} not found</span>` : "–"}</td>
    <td class="row"><button class="small" data-ex="${c.id}">${c.status === "extracted" ? "Extract again" : "Extract information"}</button>${c.status === "extracted" ? `<button class="small" data-view="${c.id}">View</button>` : ""}<button class="small link" data-del="${c.id}">Remove</button></td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">No applications yet.</div></td></tr>`}
  </tbody></table></div>`;
  const up = async files => {
    if (!files.length) return;
    const fd = new FormData(); const paths = [];
    for (const f of files) { fd.append("files", f, f.name); paths.push(f.webkitRelativePath || f.name); }
    fd.append("paths", paths.join("\n"));
    const r = await api("POST", `/api/positions/${S.pid}/upload`, fd, true);
    toast(`Added ${r.applications.length} application(s). Press “Extract information”.`); renderApplications();
  };
  $("#pickFiles").onclick = () => $("#fFiles").click(); $("#pickDir").onclick = () => $("#fDir").click();
  $("#fFiles").onchange = e => up([...e.target.files]); $("#fDir").onchange = e => up([...e.target.files]);
  const d = $("#drop"); d.onclick = () => $("#fFiles").click();
  d.ondragover = e => { e.preventDefault(); d.classList.add("over"); }; d.ondragleave = () => d.classList.remove("over");
  d.ondrop = async e => { e.preventDefault(); d.classList.remove("over"); up(await droppedFiles(e.dataTransfer)); };
  $("#demo").onclick = async e => { busy(e.target, true); await api("POST", `/api/positions/${S.pid}/demo`); busy(e.target, false); toast("Added 14 demo applications."); renderApplications(); };
  const exDone = async j => {
    await refreshRanking();
    if (j.status === "done") toast(`Extracted ${j.result.extracted}${j.result.failed.length ? `, ${j.result.failed.length} failed` : ""}.`);
    if (S.view === "applications") renderApplications();
  };
  $("#exAll").onclick = e => runJob("extract", {}, e.target, "Extracting…", exDone);
  reattachJob(["extract"], $("#exAll"), "Extracting…", exDone);
  $("#view").onclick = async e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.ex) { busy(b, true, "Extracting…"); try { await api("POST", `/api/candidates/${b.dataset.ex}/extract`); await refreshRanking(); toast("Extracted."); } catch (err) { toast(err.message); } renderApplications(); }
    if (b.dataset.view) go("cand-" + b.dataset.view);
    if (b.dataset.del) { await api("DELETE", `/api/candidates/${b.dataset.del}`); await refreshRanking(); renderApplications(); }
  };
}
async function droppedFiles(dt) {
  const out = [];
  const walk = (entry, path) => new Promise(res => {
    if (entry.isFile) entry.file(f => { Object.defineProperty(f, "webkitRelativePath", { value: path + f.name }); out.push(f); res(); });
    else { const r = entry.createReader(); r.readEntries(async es => { for (const x of es) await walk(x, path + entry.name + "/"); res(); }); }
  });
  const items = [...(dt.items || [])].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (items.length) { for (const it of items) await walk(it, ""); return out; }
  return [...dt.files];
}

// ------------------------------------------------------------------------------------------------
// 3. Ranking
// ------------------------------------------------------------------------------------------------
function renderRanking() {
  const R = S.ranking.ranking, k = S.ranking.k;
  const elig = R.filter(e => e.eligibility !== "ineligible");
  const cutoff = elig.length >= k ? elig[k - 1].lo : null;
  const cnt = s => R.filter(e => e.shortlist_status === s).length;
  $("#view").innerHTML = `
  <div class="row spread"><h1>Ranking</h1>
    <div class="row">${S.baseline ? `<span class="chip c-info">Comparing with the baseline you set</span><button id="clearBase">Clear baseline</button>` : `<button id="setBase">Set current parameters as baseline</button>`}
    <button id="toSetup">All parameters</button></div></div>
  ${S.ranking.pending.length ? `<div class="panel" style="background:var(--warn-soft);border:0">${S.ranking.pending.length} application(s) not yet extracted. <button class="link" id="toApps">Go to applications</button></div>` : ""}
  <div class="stats"><div><span class="label">Applications</span><b>${R.length}</b></div><div><span class="label">Shortlisted (robust)</span><b>${cnt("robust_in")}</b></div><div><span class="label">Uncertain</span><b>${cnt("uncertain")}</b></div><div><span class="label">Eligibility open</span><b>${R.filter(e => e.eligibility === "unresolved").length}</b></div><div><span class="label">Ineligible</span><b>${cnt("ineligible")}</b></div><div><span class="label">Shortlist size</span><b>${k}</b></div></div>
  <details class="panel" ${S.baseline ? "open" : ""}><summary>Adjust weights here (the ranking recalculates as you move them)</summary><div id="wbox2">${weightsHtml(true)}</div>
    <p class="muted small-t" style="margin:0">Tip for the demo: press “Set current parameters as baseline”, then change a weight. The <b>Change</b> column shows each candidate's movement and the reason.</p></details>
  <div class="table-wrap"><table><thead><tr><th>#</th><th>Candidate</th><th>Eligibility</th><th>Supported</th><th>Possible</th><th style="min-width:200px">Score range (cut-off in red)</th><th>Shortlist</th>${S.baseline ? "<th>Change</th>" : ""}<th>Most useful open item</th></tr></thead><tbody>
  ${R.map((e, i) => {
    const c = S.compare && S.compare[e.candidate_id];
    const g = e.gaps.find(x => x.priority <= 3);
    const mv = c ? (c.move > 0 ? `<span class="move-up">▲ ${c.move}</span>` : c.move < 0 ? `<span class="move-down">▼ ${-c.move}</span>` : "–") : "";
    return `<tr class="click ${i === k - 1 ? "cut" : ""}" data-c="${e.candidate_id}"><td class="num">${e.rank}</td>
      <td><b>${esc(e.name)}</b>${e.scenario ? `<div class="muted small-t">${esc(e.scenario)}</div>` : ""}</td>
      <td>${chip(ELIG[e.eligibility])}</td><td class="num">${f1(e.lo)}</td><td class="num">${f1(e.hi)}</td>
      <td><div class="range" title="${f1(e.lo)}–${f1(e.hi)}"><div class="lo" style="width:${e.lo}%"></div><div class="hi" style="left:${e.lo}%;width:${Math.max(0, e.hi - e.lo)}%"></div>${cutoff != null ? `<div class="cut" style="left:${cutoff}%"></div>` : ""}</div></td>
      <td>${chip(SL[e.shortlist_status])}<div class="why">${esc(e.status_reason)}</div></td>
      ${S.baseline ? `<td>${mv}${c && c.move ? `<div class="why">${c.rank_a} → ${c.rank_b}. ${esc((c.why || []).join(" "))}</div>` : ""}</td>` : ""}
      <td class="small-t">${g ? `<b>${esc(g.label)}</b><div class="muted">${esc(g.priority_label)}${g.width ? ` · up to +${f1(g.width)} pts` : ""}</div>` : '<span class="muted">None that could change the shortlist</span>'}</td></tr>`;
  }).join("")}
  </tbody></table></div>
  <p class="muted small-t">Rows are ordered by supported score. The dashed line marks the shortlist cut-off. The hatched part of each bar is what unresolved information could add.</p>`;
  bindWeights($("#wbox2"), async () => { await refreshRanking(); renderRanking(); });
  $("#view").querySelectorAll("tr.click").forEach(tr => tr.onclick = () => go("cand-" + tr.dataset.c));
  const sb = $("#setBase"); if (sb) sb.onclick = async () => { S.baseline = clone(S.draft); await refreshRanking(); renderRanking(); toast("Baseline set. Now change a weight or rule."); };
  const cb = $("#clearBase"); if (cb) cb.onclick = async () => { S.baseline = null; await refreshRanking(); renderRanking(); };
  $("#toSetup").onclick = () => go("setup");
  const ta = $("#toApps"); if (ta) ta.onclick = () => go("applications");
}

// ------------------------------------------------------------------------------------------------
// Candidate
// ------------------------------------------------------------------------------------------------
const SECTIONS = [
  ["degrees", "Education", d => [d.level ? ({ phd: "PhD", masters: "Master's", bachelors: "Bachelor's" }[d.level] || d.level) : null, d.field, d.institution], d => [["Year", d.year], ["Status", d.status ? d.status.replace("_", " ") : null], d.expected_year ? ["Expected", d.expected_year] : null]],
  ["positions", "Positions", d => [d.title, d.organisation], d => [["Start", d.start], ["End", d.end], ["Type", d.category]]],
  ["teaching", "Teaching", d => [d.course, d.institution], d => [["Role", d.role], ["Start", d.start], ["End", d.end]]],
  ["leadership", "Leadership & service", d => [d.role, d.organisation], d => [["Start", d.start], ["End", d.end]]],
  ["publications", "Publications", d => [d.title], d => [["Venue", d.venue], ["Year", d.year], ["Type", d.type], ["DOI", d.doi]]],
  ["grants", "Research funding", d => [d.title, d.funder], d => [["Role", d.role], ["Year", d.year]]],
  ["supervision", "Supervision", d => [d.level ? d.level + " students" : "Students"], d => [["Number", d.count], ["Status", d.status]]],
];
const val = v => v == null || v === "" ? '<span class="notstated">not stated</span>' : esc(v);

async function renderCandidate() {
  $("#view").innerHTML = `<div class="empty">Loading…</div>`;
  const d = await api("GET", `/api/candidates/${S.cid}`); S.detail = d;
  if (!d.profile) { $("#view").innerHTML = `<div class="panel"><h2>${esc(d.name)}</h2><p>This application has not been extracted yet.</p><button class="primary" id="exNow">Extract information</button></div>`; $("#exNow").onclick = async e => { busy(e.target, true, "Extracting…"); try { await api("POST", `/api/candidates/${S.cid}/extract`); await refreshRanking(); renderCandidate(); } catch (err) { toast(err.message); busy(e.target, false); } }; return; }
  const e = S.ranking.ranking.find(x => x.candidate_id === S.cid) || d.evaluation;
  const p = d.profile;
  const cmp = S.compare && S.compare[S.cid];
  $("#view").innerHTML = `
  <div class="row"><button class="small" id="back">← Ranking</button></div>
  <section class="panel"><div class="row spread"><div><h1>${esc(e.name || d.name)}</h1><div class="muted">${esc(p.current_position || "")}${p.orcid ? ` · ORCID ${esc(p.orcid)}` : ""}</div>${d.scenario ? `<div class="small-t muted">Demo scenario: ${esc(d.scenario)}</div>` : ""}</div>
    <div class="row">${chip(ELIG[e.eligibility])}${chip(SL[e.shortlist_status])}</div></div>
    <div class="stats"><div><span class="label">Rank</span><b>${e.rank}</b></div><div><span class="label">Supported score</span><b>${f1(e.lo)}</b></div><div><span class="label">Possible score</span><b>${f1(e.hi)}</b></div><div><span class="label">Could rank</span><b>${e.best_rank ?? "–"}–${e.worst_rank ?? "–"}</b></div></div>
    <div class="muted">${esc(e.status_reason)}</div>${cmp && cmp.move ? `<div class="why">Since the baseline: rank ${cmp.rank_a} → ${cmp.rank_b}. ${esc(cmp.why.join(" "))}</div>` : ""}</section>
  <div class="grid2">
    <section class="panel"><h2>Requirements</h2>${e.requirements.map(r => `<div class="req"><span>${chip(RS[r.status])}<div class="muted small-t">${TIER[r.tier]}</div></span><span><b>${esc(r.text)}</b><div class="small-t">${esc(r.reason)}${r.conflict ? ' <span class="chip c-warn">sources disagree</span>' : ""}</div>${evidenceHtml(r.evidence)}</span></div>`).join("")}</section>
    <section class="panel"><h2>Score breakdown</h2><div class="crit" style="border-top:0"><span class="label">Criterion</span><span class="label">Weight</span><span class="label">Score /10</span><span class="label">Points</span></div>
      ${Object.entries(e.criteria).map(([k, c]) => `<details class="crit"><summary style="display:contents"><span><b>${CRIT[k]}</b></span><span class="num">${(c.weight_norm * 100).toFixed(0)}%</span><span class="num">${f1(c.lo)}${c.hi > c.lo ? `–${f1(c.hi)}` : ""}</span><span class="num">${f1(c.contrib_lo)}${c.contrib_hi > c.contrib_lo ? `–${f1(c.contrib_hi)}` : ""}</span></summary>
        <div class="crit-items">${c.items.length ? c.items.map(it => `<div class="item"><span class="t">${esc(it.label)} <span class="num muted">${f1(it.lo)}${it.hi > it.lo ? `–${f1(it.hi)}` : ""} pts${it.years ? ` · ${esc(it.years)}` : ""}</span></span>${it.note ? `<span class="small-t notstated">${esc(it.note)}</span>` : ""}${evidenceHtml(it.evidence)}</div>`).join("") : '<div class="muted small-t">Nothing listed in the documents.</div>'}
        <div class="muted small-t">Raw points ${f1(c.raw_lo)}${c.raw_hi > c.raw_lo ? `–${f1(c.raw_hi)}` : ""} of ${c.cap} needed for full marks.</div></div></details>`).join("")}
      <div class="crit"><b>Overall</b><span></span><span></span><span class="num"><b>${f1(e.lo)}${e.hi > e.lo ? `–${f1(e.hi)}` : ""}</b></span></div>
      <p class="muted small-t" style="margin:0">Click a criterion to see each item, its points and the quote it rests on.</p></section>
  </div>
  <section class="panel"><div class="row spread"><h2>Open items</h2>${d.reply_patches && d.reply_patches.length ? `<button class="small" id="clearReplies">Remove recorded replies (${d.reply_patches.length})</button>` : ""}</div>
    <p class="muted small-t" style="margin:0">Ordered by whether they could change eligibility or the shortlist. Record an applicant's answer to see the ranking update.</p>
    ${(() => { const ec = new Set(e.gaps.filter(g => g.type === "eligibility" && ["unstated", "implied"].includes(g.code)).map(g => g.criterion));
       const gs = e.gaps.filter(g => !(g.type.endsWith("_unstated") && ec.has(g.criterion)));
       return gs.length ? gs.map(g => gapHtml(g, p)).join("") : '<div class="muted">No open items.</div>'; })()}
    ${e.clarification ? `<h3>Clarification request</h3><pre class="doc">${esc(e.clarification.message)}</pre><div class="row"><button class="small" id="copyMsg">Copy message</button></div>` : '<div class="muted small-t">No clarification is needed: nothing open could change this candidate\'s outcome.</div>'}
    ${e.gaps.length ? replyAgentHtml(d) : ""}
  </section>
  ${(p.conflicts || []).length ? `<section class="panel"><h2>Conflicting evidence</h2>${p.conflicts.map(c => `<div class="item"><span class="t">${esc(c.topic)} ${chip([c.source === "external" ? "external source vs document" : "between documents", "c-warn"])}</span>${c.values.map(v => `<div class="ev"><b>${esc(v.value)}</b> — ${esc(v.doc)}: “${esc(v.quote)}”${v.url ? ` · <a href="${esc(v.url)}" target="_blank" rel="noopener">source</a>` : ""}</div>`).join("")}<span class="small-t muted">Kept unresolved; the score range covers every version.</span></div>`).join("")}</section>` : ""}
  <section class="panel"><h2>Extracted information</h2>
    ${p.indicators && p.indicators.phd_indicated && !p.degrees.some(x => x.level === "phd") ? `<div class="chip c-warn">Documents imply a doctorate that is not stated: ${esc((p.indicators.notes || []).join("; "))}</div>` : ""}
    <div class="grid2">${SECTIONS.map(([key, title, head, fields]) => `<div><h3>${title} <span class="muted num small-t">${p[key].length}</span></h3>
      ${p[key].length ? p[key].map(it => `<div class="item"><span class="t">${head(it).filter(Boolean).map(esc).join(", ") || '<span class="notstated">untitled</span>'}</span><span class="small-t">${fields(it).filter(Boolean).map(([l, v]) => `${l}: ${val(v)}`).join(" · ")}</span>${evidenceHtml(it.evidence)}</div>`).join("") : '<div class="muted small-t">None mentioned in the documents (not the same as none held).</div>'}</div>`).join("")}</div></section>
  ${d.provenance.length ? `<section class="panel"><h2>External verification records</h2><div class="table-wrap"><table><thead><tr><th>Claim</th><th>Source</th><th>Identity check</th><th>Outcome</th><th>Retrieved</th></tr></thead><tbody>
    ${d.provenance.map(r => `<tr><td>${esc(r.claim)}${Object.keys(r.fields || {}).length ? `<div class="small-t muted">${esc(Object.entries(r.fields).map(([k, v]) => k + ": " + v).join(", "))}</div>` : ""}</td><td>${esc(r.source_label || r.source || "")}${r.url ? `<div><a class="small-t" href="${esc(r.url)}" target="_blank" rel="noopener">record</a></div>` : ""}</td>
      <td>${chip([r.identity, r.identity === "match" ? "c-good" : r.identity === "mismatch" ? "c-bad" : "c-warn"])}<div class="small-t muted">${esc((r.identity_basis || []).join("; "))}</div></td>
      <td>${chip([r.outcome.replace(/_/g, " "), { filled: "c-good", confirmed: "c-good", conflict: "c-warn", rejected: "c-bad" }[r.outcome] || ""])}</td><td class="small-t mono">${esc((r.retrieved_at || "").replace("T", " ").slice(0, 16))}</td></tr>`).join("")}</tbody></table></div></section>` : ""}
  <section class="panel"><h2>Submitted documents</h2>${d.documents.map(x => `<details><summary>${esc(x.label)} · ${esc(x.filename)}</summary><pre class="doc">${esc(x.text)}</pre></details>`).join("")}</section>`;
  $("#back").onclick = () => go("ranking");
  const cm = $("#copyMsg"); if (cm) cm.onclick = async () => { try { await navigator.clipboard.writeText(e.clarification.message); toast("Copied."); } catch (er) { toast("Select the text and copy it."); } };
  const cr = $("#clearReplies"); if (cr) cr.onclick = async () => { await api("DELETE", `/api/candidates/${S.cid}/replies`); await refreshRanking(); renderCandidate(); };
  $("#view").querySelectorAll("form.reply").forEach(f => f.onsubmit = async ev => { ev.preventDefault(); await submitReply(f, e, p); });
  bindReplyAgent(d, e);
}

// Reply agent: the AI reads a pasted reply and proposes updates; nothing changes until the committee approves.
function replyAgentHtml(d) {
  const pr = d.pending_reply;
  return `<h3>Read the applicant's reply with AI</h3>
    <p class="muted small-t" style="margin:0 0 6px">Paste the reply e-mail. The AI proposes updates for the open items, each backed by the applicant's own words; nothing changes until you approve. Model: ${esc(S.settings.llm.active_label)}.</p>
    <textarea id="replyText" rows="5" style="width:100%" placeholder="Paste the applicant's reply here">${pr ? esc(pr.text) : ""}</textarea>
    <div class="row" style="margin-top:6px"><button id="readReply" class="primary small">Read reply</button></div>
    ${pr ? `<div id="replyProps" style="margin-top:10px">
      ${pr.summary ? `<p><b>AI summary:</b> ${esc(pr.summary)}</p>` : ""}
      ${pr.proposals.length ? pr.proposals.map(x => `<label class="row" style="flex-direction:row;align-items:flex-start;gap:8px;color:var(--ink);margin-bottom:6px"><input type="checkbox" data-prop="${esc(x.id)}" checked>
          <span><b>${esc(x.change)}</b><br><span class="small-t muted">“${esc(x.quote)}”</span></span></label>`).join("") : '<div class="muted small-t">No updates proposed.</div>'}
      ${pr.unanswered.length ? `<div class="small-t muted">Not answered: ${pr.unanswered.map(u => esc(u.label) + " (" + esc(u.reason) + ")").join("; ")}</div>` : ""}
      <div class="row" style="margin-top:8px">${pr.proposals.length ? '<button id="applyProps" class="primary small">Apply selected</button>' : ""}<button id="discardProps" class="small">Discard</button></div>
      <details><summary class="small-t">What the AI did</summary><ol class="log">${pr.log.map(l => `<li>${LOGK[l.kind] ? chip(LOGK[l.kind]) + " " : ""}${esc(l.text)}</li>`).join("")}</ol></details>
    </div>` : ""}`;
}
function bindReplyAgent(d, e) {
  const rb = $("#readReply"); if (!rb) return;
  rb.onclick = async ev => {
    busy(ev.target, true, "Reading…");
    try { await api("POST", `/api/candidates/${S.cid}/reply/propose`, { text: $("#replyText").value }); renderCandidate(); }
    catch (er) { toast(er.message); busy(ev.target, false); }
  };
  const ap = $("#applyProps"), dp = $("#discardProps");
  const send = async ids => {
    const before = e.rank;
    await api("POST", `/api/candidates/${S.cid}/reply/apply`, { proposal_ids: ids });
    await refreshRanking();
    const after = S.ranking.ranking.find(x => x.candidate_id === S.cid);
    toast(ids.length ? `Applied ${ids.length} update(s). Rank ${before} → ${after.rank}; ${SL[after.shortlist_status][0].toLowerCase()}.` : "Proposals discarded.");
    renderCandidate();
  };
  if (ap) ap.onclick = () => send([...$("#view").querySelectorAll("[data-prop]")].filter(x => x.checked).map(x => x.dataset.prop));
  if (dp) dp.onclick = () => send([]);
}

function gapHtml(g, p) {
  const cls = g.priority === 1 ? "p1" : g.priority === 2 ? "p2" : "";
  const pc = g.priority === 1 ? "c-bad" : g.priority === 2 ? "c-warn" : g.priority === 3 ? "c-info" : "";
  return `<div class="gap ${cls}"><div class="row spread"><b>${esc(g.label)}</b>${chip([g.priority_label, pc])}</div>
    <div class="small-t">${esc(g.detail)}${g.width ? ` · could add up to <b>${f1(g.width)}</b> points` : ""}</div>
    ${(g.impact || []).map(i => `<div class="small-t" style="color:var(--bad)">${esc(i)}</div>`).join("")}
    ${replyForm(g, p)}</div>`;
}
function replyForm(g, p) {
  const id = g.id.replace(/[^a-z0-9]/gi, "_");
  const inp = (n, l, t = "text", ph = "") => `<label>${l}<input name="${n}" id="${id}_${n}" type="${t}" placeholder="${ph}"></label>`;
  let fields = "";
  const t = g.type, sec = g.section, req = g.request || {};
  if ((t === "eligibility" && ["unstated", "implied"].includes(g.code) && g.criterion === "qualifications") || t === "degree_unstated")
    fields = inp("field", "PhD field", "text", "Computer Science") + inp("institution", "Institution") + inp("year", "Year awarded", "number");
  else if ((t === "eligibility" && g.code === "unstated" && g.criterion === "teaching") || t === "teaching_unstated")
    fields = inp("course", "Course") + inp("institution", "Institution") + `<label>Role<select name="role"><option value="lead">Lead</option><option value="assistant">Assistant</option></select></label>` + inp("start", "Start year", "number") + inp("end", "End year or present");
  else if (t === "dates") fields = inp("start", "Start year", "number") + inp("end", "End year or present");
  else if (t === "publication_details") fields = inp("year", "Year", "number") + inp("venue", "Venue") + `<label>Type<select name="type"><option value="journal">Journal</option><option value="conference">Conference</option><option value="chapter">Chapter</option><option value="preprint">Preprint</option></select></label>`;
  else if (t === "grant_role") fields = `<label>Role<select name="role"><option>PI</option><option>Co-I</option></select></label>`;
  else if (t === "supervision_details") fields = inp("count", "Number of students", "number");
  else if (t === "conflict" && (req.conflict || []).length) fields = `<label>Correct value<select name="resolve">${req.conflict[0].values.map(v => `<option value="${esc(JSON.stringify(v.value))}">${esc(v.value)} (${esc(v.doc)})</option>`).join("")}</select></label>`;
  else if (t === "eligibility" && g.code === "in_progress") fields = inp("year", "Award year", "number");
  if (!fields) return "";
  return `<details><summary class="small-t">Record the applicant's reply</summary><form class="reply formrow" data-gap="${esc(g.id)}">${fields}<button class="small primary" type="submit">Apply reply</button></form></details>`;
}
async function submitReply(f, e, p) {
  const g = e.gaps.find(x => x.id === f.dataset.gap); const v = Object.fromEntries(new FormData(f).entries());
  const num = x => x === "" || x == null ? null : (/^present$/i.test(x) ? "present" : (isNaN(+x) ? x : +x));
  const patches = [];
  if (v.field !== undefined && v.year !== undefined && v.institution !== undefined)
    patches.push({ op: "add", section: "degrees", item: { level: "phd", field: v.field || null, institution: v.institution || null, year: num(v.year), status: "completed", expected_year: null, evidence: [] } });
  else if (v.course !== undefined)
    patches.push({ op: "add", section: "teaching", item: { course: v.course || "Teaching", institution: v.institution || null, role: v.role, university: true, start: num(v.start), end: num(v.end), evidence: [] } });
  else if (v.resolve !== undefined) patches.push({ op: "resolve", conflict: g.request.conflict[0].id, value: JSON.parse(v.resolve) });
  else if (g.type === "eligibility" && g.code === "in_progress") { const i = p.degrees.findIndex(d => d.level === "phd"); patches.push({ op: "set", section: "degrees", index: i, field: "status", value: "completed" }, { op: "set", section: "degrees", index: i, field: "year", value: num(v.year) }); }
  else for (const [k, x] of Object.entries(v)) if (x !== "") patches.push({ op: "set", section: g.section, index: g.item_index, field: k, value: k === "role" || k === "venue" || k === "type" ? x : num(x) });
  if (g.type === "publication_details" && v.type && v.type !== "preprint") patches.push({ op: "set", section: "publications", index: g.item_index, field: "peer_reviewed", value: true });
  if (!patches.length) return toast("Fill in at least one field.");
  const before = e.rank;
  await api("POST", `/api/candidates/${S.cid}/reply`, { patches, note: Object.entries(v).filter(([, x]) => x !== "").map(([k, x]) => `${k}: ${x}`).join(", ") });
  await refreshRanking();
  const after = S.ranking.ranking.find(x => x.candidate_id === S.cid);
  toast(`Reply recorded. Rank ${before} → ${after.rank}; ${SL[after.shortlist_status][0].toLowerCase()}.`);
  renderCandidate();
}

// ------------------------------------------------------------------------------------------------
// 4. Missing information
// ------------------------------------------------------------------------------------------------
function renderResolve() {
  const res = S.position.resolution || {}, last = S.position.last_resolution;
  const R = S.ranking.ranking;
  const reqs = R.filter(e => e.clarification);
  const allGaps = R.flatMap(e => e.gaps), pursued = allGaps.filter(g => g.priority <= 3);
  $("#view").innerHTML = `
  <h1>Missing information</h1>
  <section class="panel"><h2>Resolution process</h2>
    <p style="margin:0">An <b>AI agent</b> (the model chosen under <i>AI model</i>) works through the open items: it decides which applicants and gaps matter (${pursued.length} of ${allGaps.length} open items could change eligibility or the shortlist now), which approved source to query, whether to retry a failed lookup with a different search, and what to ask each applicant. It sees the effect of every change on the shortlist before deciding the next step.</p>
    <p class="muted small-t" style="margin:6px 0 0">Enforced in code, whatever the agent decides: scores come only from the scoring rules; only approved sources are used; records that fail the identity check are never used; documented values are never overwritten (disagreements become conflicts); applicants are never asked about items that cannot change the outcome. Without an AI model, a fixed scripted procedure runs instead.</p>
    <div class="formrow"><label class="row" style="flex-direction:row;color:var(--ink)"><input type="checkbox" id="extOk" ${res.external_permitted ? "checked" : ""}> External verification is permitted for this position</label></div>
    <div class="formrow">${Object.entries(S.settings.sources).map(([k, l]) => `<label class="row" style="flex-direction:row;color:var(--ink)"><input type="checkbox" data-src="${k}" ${(res.sources || Object.keys(S.settings.sources)).includes(k) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div>
    <div class="formrow"><label>Source access<select id="trans"><option value="fixture">Recorded responses (demo applications)</option><option value="live">Live internet access</option></select></label><button class="primary" id="runRes">Run the process</button>${last && last.stopped ? `<button id="resumeRes">Continue where it stopped</button>` : ""}</div>
    <div id="live" class="live" hidden></div>
    ${last && last.stopped ? `<p class="small-t muted" style="margin:4px 0 0">The last run stopped before finishing. <i>Continue</i> keeps what it already did and picks up the rest; <i>Run the process</i> starts over.</p>` : ""}
    ${last ? `<div><h3>Last run <span class="muted small-t">${esc(last.at.replace("T", " ").slice(0, 16))} UTC${last.mode ? " · " + esc(last.mode) : ""}</span></h3>${last.summary ? `<p><b>Agent summary:</b> ${esc(last.summary)}</p>` : ""}<ol class="log">${last.log.filter(l => l.kind !== "summary").map(l => `<li>${l.kind && LOGK[l.kind] ? chip(LOGK[l.kind]) + " " : ""}${esc(l.text)}</li>`).join("")}</ol></div>` : ""}
  </section>
  <section class="panel"><h2>Clarification requests <span class="muted">(${reqs.length})</span></h2>
    ${reqs.length ? reqs.map(e => `<details><summary>${esc(e.name)} · ${e.clarification.questions.length} question(s) · ${chip(SL[e.shortlist_status])}</summary>
      ${e.clarification_plan ? `<p class="small-t muted">Chosen by the agent: ${esc(e.clarification_plan.reason || "")}</p>` : ""}
      <ul>${e.clarification.questions.map(q => `<li>${esc(q.question)} <span class="muted small-t">(${esc(q.why)})</span></li>`).join("")}</ul><pre class="doc">${esc(e.clarification.message)}</pre>
      <div class="row"><button class="small" data-open="${e.candidate_id}">Open candidate to record the reply</button></div></details>`).join("") : '<div class="muted">None needed.</div>'}
  </section>
  <section class="panel"><h2>Open items not pursued</h2><p class="muted small-t" style="margin:0">These could not change eligibility or the shortlist under the current parameters, so no one is asked about them.</p>
    ${R.filter(e => e.gaps.some(g => g.priority === 4)).map(e => `<div class="item"><span class="t">${esc(e.name)}</span><span class="small-t muted">${e.gaps.filter(g => g.priority === 4).map(g => esc(g.label) + " — " + esc(g.priority_label.replace("Not pursued: ", ""))).join("; ")}</span></div>`).join("") || '<div class="muted">None.</div>'}
  </section>`;
  $("#trans").value = res.transport || "fixture";
  $("#view").querySelectorAll("[data-open]").forEach(b => b.onclick = () => go("cand-" + b.dataset.open));
  const finished = async j => {
    S.position = await api("GET", `/api/positions/${S.pid}`); await refreshRanking();
    if (j.status === "done") toast(j.result && j.result.stopped ? "The run stopped part-way. Its work is kept: use Continue where it stopped." : "Process complete.");
    if (S.view === "resolve") renderResolve();
  };
  const start = resume => ev => {
    const sources = [...$("#view").querySelectorAll("[data-src]")].filter(x => x.checked).map(x => x.dataset.src);
    runJob("resolve", { external_permitted: $("#extOk").checked, sources, transport: $("#trans").value, resume }, ev.target, "Agent working…", finished);
  };
  $("#runRes").onclick = start(false);
  if ($("#resumeRes")) $("#resumeRes").onclick = start(true);
  reattachJob(["resolve"], $("#runRes"), "Agent working…", finished);
}

// ------------------------------------------------------------------------------------------------
// 5. AI screening (lead agent)
// ------------------------------------------------------------------------------------------------
function renderScreening() {
  const res = S.position.resolution || {}, last = S.position.last_screening;
  $("#view").innerHTML = `
  <h1>AI screening</h1>
  <section class="panel"><h2>Run the whole pipeline</h2>
    <p style="margin:0">A lead AI agent (${esc(S.settings.llm.active_label)}) extracts any applications not yet read, re-reads weak extractions, runs the missing-information agent, tests whether the shortlist holds when the weights change, and writes a briefing for the committee.</p>
    <p class="muted small-t" style="margin:6px 0 0">It cannot change scores, weights, requirements or the shortlist: those stay with the scoring rules and the committee. The table in the briefing comes from the scoring engine, not from the AI. Without an AI model, a fixed scripted procedure runs instead.</p>
    <div class="formrow"><label class="row" style="flex-direction:row;color:var(--ink)"><input type="checkbox" id="scExt" ${res.external_permitted ? "checked" : ""}> External verification is permitted (approved sources as set under Missing information)</label></div>
    <div class="formrow"><label>Source access<select id="scTrans"><option value="fixture">Recorded responses (demo applications)</option><option value="live">Live internet access</option></select></label><button class="primary" id="runScreen">Screen applications</button></div>
    <div id="live" class="live" hidden></div>
  </section>
  ${last ? `<section class="panel"><h2>Briefing <span class="muted small-t">${esc(last.at.replace("T", " ").slice(0, 16))} UTC · ${esc(last.mode)}</span></h2>
    ${last.briefing ? `<p>${esc(last.briefing.overview)}</p>
      ${last.briefing.needs_attention.length ? `<h3>Needs attention</h3><ul>${last.briefing.needs_attention.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <h3>How robust is the shortlist?</h3><p>${esc(last.briefing.robustness)}</p>
      ${last.briefing.next_steps.length ? `<h3>Next steps</h3><ol>${last.briefing.next_steps.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : ""}` : '<p class="muted">No briefing was written.</p>'}
    ${last.table.length ? `<h3>Candidates <span class="muted small-t">(from the scoring engine)</span></h3><div class="table-wrap"><table><thead><tr><th>#</th><th>Applicant</th><th>Score</th><th>Eligibility</th><th>Shortlist</th><th>Clarification</th></tr></thead><tbody>
      ${last.table.map(r => `<tr><td class="num">${r.rank}</td><td><a href="#cand-${esc(r.candidate_id || "")}" data-name="${esc(r.name)}">${esc(r.name)}</a></td><td class="num">${f1(r.supported)}${r.possible > r.supported ? "–" + f1(r.possible) : ""}</td><td>${chip(ELIG[r.eligibility])}</td><td>${chip(SL[r.shortlist_status])}</td><td>${r.clarification ? "drafted" : ""}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <details><summary>What the agent did (${last.tool_calls} tool calls)</summary><ol class="log">${last.log.filter(l => l.kind !== "summary").map(l => `<li>${LOGK[l.kind] ? chip(LOGK[l.kind]) + " " : ""}${esc(l.text)}</li>`).join("")}</ol></details>
  </section>` : ""}`;
  $("#scTrans").value = res.transport || "fixture";
  $("#view").querySelectorAll("a[data-name]").forEach(a => a.onclick = ev => { ev.preventDefault(); const r = S.ranking.ranking.find(x => x.name === a.dataset.name); if (r) go("cand-" + r.candidate_id); });
  const finished = async j => {
    S.position = await api("GET", `/api/positions/${S.pid}`); await refreshRanking();
    if (j.status === "done") toast("Screening complete.");
    if (S.view === "screen") renderScreening();
  };
  $("#runScreen").onclick = ev => runJob("screen", { external_permitted: $("#scExt").checked, sources: res.sources, transport: $("#scTrans").value }, ev.target, "Agent working…", finished);
  reattachJob(["screen"], $("#runScreen"), "Agent working…", finished);
}

boot().catch(e => { $("#view").innerHTML = `<div class="panel">Could not start: ${esc(e.message)}</div>`; });
