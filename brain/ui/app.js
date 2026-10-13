/* AI-BRAIN UI: vanilla JS + one vendored library (force-graph). Works fully offline. */
const $ = (s, el = document) => el.querySelector(s)
const $$ = (s, el = document) => [...el.querySelectorAll(s)]
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
const fmt = (n) => Number(n || 0).toLocaleString()
const short = (qn) => { const p = String(qn || "").split("."); return p.length > 2 ? p.slice(-2).join(".") : qn }
const ago = (ts) => { if (!ts) return "never"; if (typeof ts === "string") ts = Date.parse(ts) / 1000; const s = Date.now() / 1000 - ts
  return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago` }
let STATUS = null, SETS = { all: [] }, REPOS = []

/* ---------------------------------------------------------- API + session */
class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status } }
async function api(path, opts = {}) {
  const headers = { "X-Brain-UI": "1", ...(opts.headers || {}) }
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json) }
  const res = await fetch(path, { ...opts, headers, credentials: "same-origin" })
  if (res.status === 401 && path !== "/api/login") { showLogin(); throw new ApiError(401, "Please sign in") }
  let data = null
  try { data = await res.json() } catch { data = null }
  if (!res.ok) throw new ApiError(res.status, (data && (data.detail || data.error)) || `HTTP ${res.status}`)
  return data
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 4200) }
function showLogin() { $("#login").hidden = false; $(".rail").hidden = true; $("main").hidden = true; setTimeout(() => $("#login-user").focus(), 50) }
function showApp() { $("#login").hidden = true; $(".rail").hidden = false; $("main").hidden = false }
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("#login-err").textContent = ""
  try {
    await api("/api/login", { method: "POST", json: { username: $("#login-user").value, password: $("#login-pass").value } })
    $("#login-pass").value = ""; boot()
  } catch (err) { $("#login-err").textContent = err.message }
})
$("#logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); showLogin() })

/* ---------------------------------------------------------- tiny markdown renderer (trusted structure, escaped text) */
function md(src) {
  const blocks = String(src || "").split(/```/)
  return blocks.map((b, i) => {
    if (i % 2) { const nl = b.indexOf("\n"); return `<pre><code>${esc(nl >= 0 ? b.slice(nl + 1) : b)}</code></pre>` }
    let html = "", list = null
    const inline = (t) => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\*([^*\s][^*]*)\*/g, "<i>$1</i>")
    const close = () => { if (list) { html += `</${list}>`; list = null } }
    for (const line of b.split("\n")) {
      let m
      if ((m = line.match(/^(#{1,4})\s+(.*)/))) { close(); const n = Math.min(4, m[1].length + 1); html += `<h${n}>${inline(m[2])}</h${n}>` }
      else if ((m = line.match(/^\s*[-*]\s+(.*)/))) { if (list !== "ul") { close(); html += "<ul>"; list = "ul" } html += `<li>${inline(m[1])}</li>` }
      else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); html += "<ol>"; list = "ol" } html += `<li>${inline(m[1])}</li>` }
      else if ((m = line.match(/^>\s?(.*)/))) { close(); html += `<blockquote>${inline(m[1])}</blockquote>` }
      else if (line.trim()) { close(); html += `<p>${inline(line)}</p>` }
      else close()
    }
    close(); return html
  }).join("")
}

/* ---------------------------------------------------------- jobs + progress */
function jobHtml(j) {
  const pct = j.progress != null ? Math.round(j.progress * 100) : null
  return `<div class="job ${j.state}"><div class="t"><b>${esc(j.title)}</b><span class="st ${j.state}">${j.state}</span>
    <span class="muted">${j.seconds}s</span></div>
    <div class="s">${esc(j.error || j.step || "")}</div>
    ${j.state === "running" ? `<div class="bar ${pct == null ? "indet" : ""}"><i style="width:${pct || 0}%"></i></div>` : ""}</div>`
}
async function followJob(id, el) {
  for (;;) {
    const j = await api(`/api/jobs/${id}`)
    el.innerHTML = j.state === "running" ? jobHtml(j) : (j.state === "error" ? `<div class="alert">${esc(j.error)}</div>` : "")
    if (j.state !== "running") { if (j.state === "error") throw new Error(j.error); return j.result }
    await new Promise((r) => setTimeout(r, 900))
  }
}

/* ---------------------------------------------------------- navigation */
const inited = {}, REFRESH = {}, INIT = {}
function show(view) {
  if (!document.getElementById(view)) view = "overview"
  $$(".rail>button").forEach((b) => b.classList.toggle("on", b.dataset.view === view))
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === view))
  if (!inited[view] && INIT[view]) { inited[view] = true; INIT[view]() }
  if (REFRESH[view]) REFRESH[view]()
  history.replaceState(null, "", "#" + view)
}
$$(".rail>button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)))
window.addEventListener("hashchange", () => !$("main").hidden && show(location.hash.slice(1)))
function seg(el, onChange) { el.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return
  $$("button", el).forEach((x) => x.classList.toggle("on", x === b)); onChange && onChange(b.dataset.v) }) }
const segVal = (el) => $("button.on", el).dataset.v

/* ---------------------------------------------------------- status / overview */
async function loadStatus() {
  try {
    STATUS = await api("/api/status")
    const e = STATUS.engines, bad = Object.values(e).some((x) => x.state === "error") || STATUS.llm.state === "error"
    $("#health").className = "dot " + (STATUS.ready ? "ok" : bad ? "bad" : "warn")
    $("#health-text").textContent = STATUS.ready ? "all systems ready" : bad ? "attention needed" : "starting…"
  } catch (err) { if (err.status !== 401) { $("#health").className = "dot bad"; $("#health-text").textContent = "server unreachable" } }
  return STATUS
}
async function loadRepos() {
  try { const r = await api("/api/repos"); SETS = r.sets; REPOS = r.repos; $("#r-file").textContent = r.file } catch {}
  for (const sel of $$(".scope-select")) {   // one repository, or a set (all of its repositories)
    const cur = sel.value
    sel.innerHTML = `<optgroup label="Sets (all their repositories)">${Object.entries(SETS).map(([k, v]) => `<option value="set:${esc(k)}">${k === "all" ? "All repositories" : esc(k)} (${v.length})</option>`).join("")}</optgroup>`
      + `<optgroup label="One repository">${REPOS.map((r) => `<option value="repo:${esc(r.name)}">${esc(r.name)}</option>`).join("")}</optgroup>`
    if (cur && $(`option[value="${CSS.escape(cur)}"]`, sel)) sel.value = cur
  }
  for (const sel of [$("#e-repo"), $("#d-repo")]) {
    const cur = sel.value
    sel.innerHTML = `<option value="">${sel.id === "e-repo" ? "(auto)" : "choose"}</option>` + REPOS.map((r) => `<option>${esc(r.name)}</option>`).join("")
    if (cur) sel.value = cur
  }
}
async function loadModels() {
  const r = await api("/api/models").catch(() => null)
  if (!r) return
  for (const sel of $$(".model-select")) {
    const cur = sel.value, def = r.defaults[sel.dataset.role] || ""
    sel.innerHTML = `<option value="">default (${esc(def || "not set")})</option>` + r.models.map((m) => `<option>${esc(m)}</option>`).join("")
    sel.title = r.listed ? "Models listed by the corporate API" : `The API did not list models${r.error ? ": " + r.error : ""}; showing the configured ones`
    if (cur) sel.value = cur
  }
}
const STATE_LABEL = { ready: "ready", starting: "starting", error: "error", stopped: "stopped" }
REFRESH.overview = async () => {
  const s = await loadStatus(); if (!s) return
  const e = s.engines
  $("#ov-lede").textContent = s.ready ? "Code graph, document graph and both agents are ready." : "Some parts are still starting or need attention; details below."
  const llm = s.llm || {}
  const card = (title, st, lines) => `<div class="card"><h3><span class="dot ${st === "ready" ? "ok" : st === "error" ? "bad" : "warn"}"></span>${title}
    <span class="st ${st}">${STATE_LABEL[st] || st}</span></h3>${lines.map((l) => `<p>${l}</p>`).join("")}</div>`
  const projects = await api("/api/code/projects").catch(() => [])
  const p = s.pipeline || {}
  $("#ov-cards").innerHTML = [
    card("Code graph", e.code.state, [esc(e.code.provider), esc(e.code.detail), `${fmt(projects.reduce((a, x) => a + (x.nodes || 0), 0))} symbols, ${fmt(projects.reduce((a, x) => a + (x.edges || 0), 0))} relationships`]),
    card("Document graph", e.docs.state, [esc(e.docs.provider), esc((e.docs.detail || "").split("\n")[0]), p.busy ? `processing: ${esc(p.message || "")}` : "idle"]),
    card("Corporate API", llm.state || "starting", [`chat: ${esc(s.models.default || "not set")}`, `embedding: ${esc(s.models.embedding || "not set")}${llm.dim ? ` (dim ${llm.dim})` : ""}`,
      `vision: ${esc(s.models.vision || "not set (images skipped)")}`]),
    card("Agents", s.ready ? "ready" : (llm.state === "error" ? "error" : "starting"), [`ask: ${esc(s.models.ask)}`, `enhance: ${esc(s.models.enhance)}`, `requirements: ${esc(s.models.srs)}`, `uptime ${fmt(s.uptime)} s`]),
  ].join("")
  const alerts = []
  for (const [k, v] of Object.entries(e)) if (v.state === "error") alerts.push(`<div class="alert"><b>${k === "code" ? "Code graph" : "Document graph"}:</b> ${esc((v.detail || "").split("\n")[0])}
    ${v.log || (v.detail || "").includes("\n") ? `<details><summary>Details</summary><pre class="code">${esc(v.log || v.detail)}</pre></details>` : ""}
    <div class="row"><button class="ghost small" data-restart="${k}">Restart engine</button><a href="#settings" class="muted">Check settings</a></div></div>`)
  for (const err of llm.errors || []) alerts.push(`<div class="alert"><b>Corporate API:</b> ${esc(err)}</div>`)
  $("#ov-alerts").innerHTML = alerts.join("")
  $$("[data-restart]").forEach((b) => (b.onclick = async () => { await api(`/api/restart/${b.dataset.restart}`, { method: "POST" }); toast("Restarting…"); REFRESH.overview() }))
  const jobs = await api("/api/jobs?limit=12").catch(() => [])
  $("#ov-jobs").innerHTML = jobs.map(jobHtml).join("") || `<p class="muted">Nothing yet.</p>`
  const me = await api("/api/me").catch(() => ({ public_url: location.origin }))
  const url = me.public_url
  $("#ov-mcp").textContent = url + "/mcp"
  $("#ov-connect").textContent =
`# Claude Code
claude mcp add --transport http --scope user brain ${url}/mcp --header "Authorization: Bearer <BRAIN_API_TOKEN>"

# opencode  (~/.config/opencode/opencode.json)
"mcp": { "brain": { "type": "remote", "url": "${url}/mcp", "oauth": false,
                 "headers": { "Authorization": "Bearer <BRAIN_API_TOKEN>" } } }

# pi or any agent / script: REST
curl -H "Authorization: Bearer <BRAIN_API_TOKEN>" -H "Content-Type: application/json" \\
     -d '{"query":"where is VAT applied"}' ${url}/api/search`
}

/* ---------------------------------------------------------- prompt analysis (live, before running) */
function analysisHtml(a) {
  if (!a || !a.terms || !a.terms.length) return ""
  const terms = a.terms.map((t, i) => `<span class="chip k-${esc(t.kind)}" title="${esc(t.kind)} · score ${t.score}">${i < 3 ? "<b>" : ""}${esc(t.term)}${i < 3 ? "</b>" : ""}</span>`).join("")
  const vars = (a.variants || []).map((v) => `<span class="chip var">${esc(v)}</span>`).join("")
  const stops = (a.stop_words || []).map((w) => `<span class="chip stop">${esc(w)}</span>`).join("")
  return `<div class="an-row"><span class="an-l">Key terms${["tr", "en", "mixed"].includes(a.language) ? ` (${esc(a.language)})` : ""}</span>${terms}</div>`
    + (a.concepts && a.concepts.length ? `<div class="an-row"><span class="an-l">Concepts</span>${a.concepts.map((c) => `<span class="chip con">${esc(c)}</span>`).join("")}</div>` : "")
    + (vars ? `<div class="an-row"><span class="an-l">Variants</span>${vars}</div>` : "")
    + (a.expanded && a.expanded.length ? `<div class="an-row"><span class="an-l">Expanded by the model</span>${a.expanded.map((v) => `<span class="chip exp">${esc(v)}</span>`).join("")}</div>` : "")
    + (a.bridged && a.bridged.length ? `<div class="an-row"><span class="an-l">Found via documents</span>${a.bridged.map((v) => `<span class="chip var">${esc(v)}</span>`).join("")}</div>` : "")
    + (stops ? `<div class="an-row"><span class="an-l">Ignored stop-words</span>${stops}</div>` : "")
}
function liveAnalysis(input, out) {
  let t
  input.addEventListener("input", () => { clearTimeout(t); t = setTimeout(async () => {
    const text = input.value.trim()
    if (text.length < 3) { out.innerHTML = ""; return }
    try { out.innerHTML = analysisHtml(await api("/api/analyze", { method: "POST", json: { text } })) } catch {}
  }, 250) })
}

/* ---------------------------------------------------------- results (shared by search and the evidence panels) */
function sourceChips(src) {
  const labels = { "code graph": "Code graph", "code vectors": "Code vectors", "document passages": "Document passages",
    "document entities": "Entities", "document facts": "Facts", "code relations": "Code relations" }
  return Object.entries(src || {}).map(([k, v]) => `<span class="chip src ${v ? "" : "zero"}" title="${esc(k)}">${esc(labels[k] || k)} <b>${v}</b></span>`).join("")
}
function codeHit(h, i) {
  const why = (h.matched || []).map((m) => `<span class="chip why">${esc(m)}</span>`).join("")
  const graph = [h.signature ? `<div><span class="lbl">signature</span><code>${esc(h.signature)}</code></div>` : "",
    h.callers?.length ? `<div><span class="lbl">called by</span>${h.callers.map((x) => `<code>${esc(x)}</code>`).join(" ")}</div>` : "",
    h.callees?.length ? `<div><span class="lbl">calls</span>${h.callees.map((x) => `<code>${esc(x)}</code>`).join(" ")}</div>` : "",
    h.parents?.length ? `<div><span class="lbl">extends</span>${h.parents.map((x) => `<code>${esc(x)}</code>`).join(" ")}</div>` : ""].join("")
  const loc = h.path ? `${h.project}/${h.path}:${h.line1}-${h.line2}` : `${h.project} · ${String(h.label).toLowerCase()}`
  return `<div class="hit"><div class="h"><span class="num">${i + 1}</span><span class="tag">${esc(h.label)}</span><b>${esc(h.name)}</b>
      <span class="muted">${esc(loc)}</span><span class="spacer"></span>${h.similarity != null ? `<span class="tag" title="similarity to the request (multilingual embeddings)">sim ${h.similarity}</span>` : ""}
      <button class="ghost small" data-copy="${esc(loc)}" title="Copy location">Copy</button>
      <button class="ghost small" data-graph="${esc(h.project)}|${h.id}" title="Open this symbol in the code graph">Graph</button></div>
    ${why ? `<div class="why-row">${why}</div>` : ""}${graph ? `<div class="gctx">${graph}</div>` : ""}
    ${h.code ? `<details class="snip" ${i < 3 ? "open" : ""}><summary>source</summary><pre class="code">${esc(h.code)}</pre></details>` : ""}</div>`
}
function renderResults(el, r) {
  const d = r.docs || {}
  const code = r.code || [], chunks = d.chunks || [], ents = d.entities || [], facts = d.relations || []
  el.innerHTML = `<div class="src-row">${sourceChips(r.sources)}${(r.projects || []).length ? `<span class="muted">repositories: ${r.projects.map(esc).join(", ")}</span>` : ""}</div>
  <div class="results">
    <section class="col"><h2 class="sub">Code <span class="muted">(code graph + code vectors)</span></h2>
      ${code.map(codeHit).join("") || `<p class="muted">No code matches.</p>`}
      ${(r.relations || []).length ? `<h3>Relationships</h3><div class="hit rels">${r.relations.slice(0, 30).map((e) => `<div><code>${esc(e.a)}</code> <span class="tag">${esc(e.type)}</span> <code>${esc(e.b)}</code></div>`).join("")}</div>` : ""}
    </section>
    <section class="col"><h2 class="sub">Documents <span class="muted">(document graph)</span></h2>
      ${chunks.map((c) => `<div class="hit"><div class="h"><b>${esc(c.source)}</b>${c.similarity != null ? `<span class="tag">sim ${c.similarity}</span>` : ""}<span class="spacer"></span>
        <button class="ghost small" data-md="${esc(c.source)}">Markdown</button></div><blockquote>${esc(c.content.slice(0, 1500))}</blockquote></div>`).join("") || `<p class="muted">No document passages.</p>`}
      ${ents.length ? `<h3>Entities</h3><div class="hit">${ents.slice(0, 15).map((e) => `<div><span class="tag">${esc(e.type)}</span><b>${esc(e.name)}</b> <span class="muted">${esc((e.description || "").slice(0, 260))}</span></div>`).join("")}</div>` : ""}
      ${facts.length ? `<h3>Facts</h3><div class="hit">${facts.slice(0, 12).map((e) => `<div><b>${esc(e.a)}</b> → <b>${esc(e.b)}</b> <span class="muted">${esc((e.description || "").slice(0, 260))}</span></div>`).join("")}</div>` : ""}
    </section>
  </div>`
  wireResults(el)
}
function wireResults(el) {
  $$("[data-copy]", el).forEach((b) => (b.onclick = () => navigator.clipboard.writeText(b.dataset.copy).then(() => toast("Copied"), () => toast("Copy failed"))))
  $$("[data-graph]", el).forEach((b) => (b.onclick = () => { const [p, id] = b.dataset.graph.split("|"); openInGraph(p, +id) }))
  $$("[data-md]", el).forEach((b) => (b.onclick = async () => {
    try { const r = await api(`/api/docs/markdown?name=${encodeURIComponent(b.dataset.md)}`); viewer(b.dataset.md + " (as Markdown)", r.markdown) }
    catch (err) { toast(err.message) } }))
}
function evidencePanel(el, r) {
  const ev = r.evidence
  if (!ev) { el.innerHTML = ""; return }
  const n = (ev.code || []).length, m = ((ev.docs || {}).chunks || []).length
  const steps = (r.steps || []).map((s, i) => `<li><b>${esc(s.tool)}</b> <span class="muted">${esc(JSON.stringify(s.args || {}).slice(0, 140))} → ${fmt(s.chars)} chars</span></li>`).join("")
  el.innerHTML = `<details class="evidence"><summary>Evidence used: ${n} code locations, ${m} document passages, ${(r.steps || []).length} tool calls · ${esc((ev.pipeline || []).join(" → "))}</summary>
    ${steps ? `<h3>Agent steps</h3><ol class="timeline">${steps}</ol>` : ""}<div class="ev-body"></div></details>`
  renderResults($(".ev-body", el), ev)
}
let PENDING_FOCUS = null
function openInGraph(project, id) { PENDING_FOCUS = { project, id }; location.hash = "#code" }

/* ---------------------------------------------------------- search */
INIT.search = () => {
  seg($("#s-scope")); liveAnalysis($("#s-q"), $("#s-an"))
  $("#s-go").onclick = runSearch
  $("#s-q").addEventListener("keydown", (e) => e.key === "Enter" && runSearch())
}
async function runSearch() {
  const q = $("#s-q").value.trim(); if (!q) return
  $("#s-go").disabled = true; $("#s-meta").textContent = "Searching…"; $("#s-out").innerHTML = ""
  try {
    const r = await api("/api/search", { method: "POST", json: { query: q, scope: segVal($("#s-scope")), target: $("#s-target").value, branch: $("#s-branch").value.trim() || null } })
    const d = r.docs || {}
    $("#s-an").innerHTML = analysisHtml(r.analysis)
    $("#s-meta").innerHTML = `<span class="pipe-line">${(r.pipeline || []).map(esc).join(" → ")}</span> · ${r.code.length} code hits, ${(d.chunks || []).length} passages, ${(d.entities || []).length} entities in ${r.ms} ms`
      + (r.projects.length ? ` · repositories: ${r.projects.map(esc).join(", ")}` : "") + (r.errors.length ? `<div class="alert warn">${r.errors.map(esc).join("<br>")}</div>` : "")
    renderResults($("#s-out"), r)
  } catch (err) { $("#s-meta").innerHTML = `<div class="alert">${esc(err.message)}</div>` } finally { $("#s-go").disabled = false }
}

/* ---------------------------------------------------------- ask + enhance */
function agentMeta(r) {
  const steps = r.steps.length ? `<p class="steps">${r.steps.length} tool calls: ${r.steps.map((s) => esc(s.tool)).join(" → ")} (details under Evidence)</p>` : ""
  const src = r.sources.length ? `<p class="steps">Sources: ${r.sources.slice(0, 12).map((s) => `<code>${esc(s.ref)}</code>`).join(" ")}</p>` : ""
  const errs = r.errors.length ? `<div class="alert warn">${r.errors.map(esc).join("<br>")}</div>` : ""
  const u = r.usage || {}, use = u.calls ? ` · ${u.calls} model calls, ${fmt(u.prompt_tokens)} tokens in, ${fmt(u.completion_tokens)} out` : ""
  return `${errs}${steps}${src}<p class="steps">${r.llm ? `Answered by ${esc(r.model || "the language model")}` : "Language model unavailable: showing grounded results"} in ${(r.ms / 1000).toFixed(1)} s${use}.</p>`
}
INIT.ask = () => { liveAnalysis($("#a-q"), $("#a-an")); $("#a-go").onclick = runAsk; $("#a-q").addEventListener("keydown", (e) => e.key === "Enter" && (e.ctrlKey || e.metaKey) && runAsk()) }
async function runAsk() {
  const q = $("#a-q").value.trim(); if (!q) return
  $("#a-go").disabled = true; $("#a-out").innerHTML = ""; $("#a-meta").innerHTML = ""
  try {
    const { job } = await api("/api/ask", { method: "POST", json: { question: q, target: $("#a-target").value, model: $("#a-model").value || null, branch: $("#a-branch").value.trim() || null, async: true } })
    const r = await followJob(job, $("#a-progress"))
    $("#a-an").innerHTML = analysisHtml(r.analysis); $("#a-out").innerHTML = md(r.answer); $("#a-meta").innerHTML = agentMeta(r); evidencePanel($("#a-ev"), r)
  } catch (err) { $("#a-progress").innerHTML = `<div class="alert">${esc(err.message)}</div>` } finally { $("#a-go").disabled = false }
}
INIT.enhance = () => {
  liveAnalysis($("#e-q"), $("#e-an"))
  $("#e-go").onclick = runEnhance
  $("#e-copy").onclick = () => navigator.clipboard.writeText($("#e-out").dataset.raw || "").then(() => toast("Copied"), () => toast("Copy failed: select the text manually"))
}
async function runEnhance() {
  const q = $("#e-q").value.trim(); if (!q) return
  $("#e-go").disabled = true; $("#e-out").innerHTML = ""; $("#e-meta").innerHTML = ""; $("#e-actions").hidden = true
  const files = $("#e-files").value.split("\n").map((x) => x.trim()).filter(Boolean)
  try {
    const { job } = await api("/api/enhance", { method: "POST", json: { prompt: q, target: $("#e-target").value, model: $("#e-model").value || null, branch: $("#e-branch").value.trim() || null,
      repo: $("#e-repo").value || null, base_commit: $("#e-base").value.trim() || null, changed_files: files.length ? files : null, async: true } })
    const r = await followJob(job, $("#e-progress"))
    $("#e-an").innerHTML = analysisHtml(r.analysis); $("#e-out").dataset.raw = r.enhanced; $("#e-out").innerHTML = md(r.enhanced); $("#e-meta").innerHTML = agentMeta(r); evidencePanel($("#e-ev"), r); $("#e-actions").hidden = false
  } catch (err) { $("#e-progress").innerHTML = `<div class="alert">${esc(err.message)}</div>` } finally { $("#e-go").disabled = false }
}

/* ---------------------------------------------------------- learn a project */
let GUIDE_LAST = ""
const scopeRepos = (t) => { const [k, v] = String(t || "set:all").split(":"); return k === "repo" ? [v] : (SETS[v] || []) }
INIT.learn = () => {
  $("#l-ov").onclick = learnStructure
  $("#l-go").onclick = runGuide
  $("#l-copy").onclick = () => navigator.clipboard.writeText(GUIDE_LAST).then(() => toast("Copied"), () => toast("Copy failed"))
  $("#l-download").onclick = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([GUIDE_LAST], { type: "text/markdown" }))
    a.download = "project-guide.md"; a.click(); URL.revokeObjectURL(a.href) }
  $("#l-publish").onclick = async () => {
    try { await api("/api/docs/text", { method: "POST", json: { name: `Project guide - ${$("#l-target").value.split(":")[1]}.md`, text: GUIDE_LAST } }); toast("Added to the document graph (processing)") }
    catch (err) { toast(err.message) } }
}
async function learnStructure() {
  const names = scopeRepos($("#l-target").value), el = $("#l-struct")
  el.innerHTML = names.length ? `<h2 class="sub">Structure</h2>` + names.map((n) => `<details open class="evidence"><summary>${esc(n)}</summary><pre class="code" data-ov="${esc(n)}">Loading…</pre></details>`).join("")
    : `<p class="muted">No repository in this scope yet.</p>`
  for (const n of names) {
    const pre = $(`[data-ov="${CSS.escape(n)}"]`, el)
    try { pre.textContent = (await api(`/api/code/overview?repo=${encodeURIComponent(n)}&aspects=overview,routes,hotspots`)).text } catch (err) { pre.textContent = err.message }
  }
}
async function runGuide() {
  $("#l-go").disabled = true; $("#l-out").innerHTML = ""; $("#l-meta").innerHTML = ""; $("#l-actions").hidden = true
  try {
    const { job } = await api("/api/guide", { method: "POST", json: { target: $("#l-target").value, topic: $("#l-topic").value.trim(), model: $("#l-model").value || null, async: true } })
    const r = await followJob(job, $("#l-progress"))
    GUIDE_LAST = r.guide; $("#l-out").innerHTML = md(r.guide); $("#l-meta").innerHTML = agentMeta(r); evidencePanel($("#l-ev"), r); $("#l-actions").hidden = false
  } catch (err) { $("#l-progress").innerHTML = `<div class="alert">${esc(err.message)}</div>` } finally { $("#l-go").disabled = false }
}

/* ---------------------------------------------------------- graph helpers */
const KIND = () => ({ Module: css("--ochre"), Route: css("--moss"), Class: css("--teal"), Struct: css("--teal"), Record: css("--teal"), Object: css("--teal"), Type: css("--teal"),
  Interface: css("--plum"), Trait: css("--plum"), Enum: css("--brick"), Method: css("--slate"), Function: css("--slate"), File: css("--ink-2") })
const LINK = () => ({ CALLS: css("--slate"), INHERITS: css("--plum"), IMPLEMENTS: css("--plum"), OVERRIDE: css("--plum"), IMPORTS: css("--ochre"),
  USES: css("--rule"), USAGE: css("--rule"), HTTP_CALLS: css("--moss"), ASYNC_CALLS: css("--moss"), TESTS: css("--brick") })
const PALETTE = () => ["--teal", "--ochre", "--plum", "--slate", "--moss", "--brick"].map(css).concat(["#3E8FB0", "#B36A9A", "#8A7A3C", "#5B8C5A"])
function hashColor(s, pal) { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) | 0; return pal[Math.abs(h) % pal.length] }
function legend(el, entries) { el.innerHTML = entries.map(([k, c]) => `<span><i style="background:${c}"></i>${esc(k)}</span>`).join("") }
function stageMsg(el, html) { el.hidden = !html; el.innerHTML = html ? `<div class="alert warn">${html}</div>` : "" }
function makeGraph(el, { color, size, label, onClick, linkColor }) {
  if (typeof ForceGraph === "undefined") { el.innerHTML = `<div class="alert">Graph library failed to load.</div>`; return null }
  const g = ForceGraph()(el).backgroundColor("rgba(0,0,0,0)").nodeId("id")
    .nodeLabel((n) => `<div style="font:13px sans-serif;padding:2px 4px">${esc(label(n))}</div>`)
    .nodeColor(color).nodeVal(size).nodeRelSize(3.2)
    .linkColor(linkColor).linkWidth((l) => Math.min(3, 0.6 + Math.log2(1 + (l.weight || 1)) * 0.5))
    .linkDirectionalArrowLength(3).linkDirectionalArrowRelPos(1).cooldownTicks(160).d3VelocityDecay(0.3)
    .onNodeClick(onClick).nodeCanvasObjectMode(() => "after")
    .nodeCanvasObject((n, ctx, scale) => {
      if (scale < 1.6 && !n.__big) return
      const t = n.name || label(n); ctx.font = `${11 / scale}px sans-serif`; ctx.fillStyle = css("--ink")
      ctx.textAlign = "center"; ctx.fillText(t.length > 28 ? t.slice(0, 27) + "…" : t, n.x, n.y + 9 / scale + Math.sqrt(size(n)) * 1.8)
    })
  const fit = () => g.width(el.clientWidth).height(el.clientHeight)
  new ResizeObserver(fit).observe(el); fit()
  g.onEngineStop(() => { if (!g.__fitted) { g.zoomToFit(400, 40); g.__fitted = true } })
  g.setData = (d) => { g.__fitted = false; g.graphData(d) }
  return g
}

/* ---------------------------------------------------------- code graph */
let codeG
const proj = () => $("#code-project").value
INIT.code = async () => {
  const K = KIND(), L = LINK()
  legend($("#code-legend"), [["module", K.Module], ["class", K.Class], ["interface", K.Interface], ["enum", K.Enum], ["route", K.Route], ["function", K.Function]])
  codeG = makeGraph($("#code-canvas"), { color: (n) => K[n.kind] || K.File, label: (n) => `${n.kind} ${short(n.qname)}`,
    size: (n) => 1 + Math.min(12, Math.sqrt(n.degree || 1)), linkColor: (l) => L[l.type] || css("--rule"), onClick: (n) => inspectCode(n.id) })
  $("#code-project").addEventListener("change", loadCodeOverview)
  const q = $("#code-q"), box = $("#code-sugg"); let t
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(async () => {
    if (q.value.trim().length < 2) { box.hidden = true; return }
    const rows = await api(`/api/code/find?q=${encodeURIComponent(q.value.trim())}&project=${encodeURIComponent(proj())}`).catch(() => [])
    box.innerHTML = rows.map((r) => `<div data-id="${r.id}">${esc(r.name)}<small>${esc(r.label)} in ${esc(r.file_path)}</small></div>`).join("") || "<div>No symbol with that name</div>"
    box.hidden = false
  }, 180) })
  box.addEventListener("click", (e) => { const d = e.target.closest("[data-id]"); if (d) { box.hidden = true; focusCode(+d.dataset.id) } })
  $("#code-overview").addEventListener("click", loadCodeOverview)
}
REFRESH.code = async () => {
  const ps = await api("/api/code/projects").catch(() => [])
  const sel = $("#code-project"), cur = sel.value
  sel.innerHTML = ps.map((p) => `<option value="${esc(p.name)}">${esc(p.name)} (${fmt(p.nodes)})</option>`).join("")
  if (cur && ps.some((p) => p.name === cur)) sel.value = cur
  if (!ps.length) return stageMsg($("#code-msg"), "No repository is indexed yet. Add one under <a href='#repos'>Repositories</a>; progress shows on the Overview page.")
  stageMsg($("#code-msg"), "")
  if (PENDING_FOCUS && ps.some((p) => p.name === PENDING_FOCUS.project)) {
    sel.value = PENDING_FOCUS.project; const id = PENDING_FOCUS.id; PENDING_FOCUS = null
    if (codeG) { codeG.__loaded = true; return focusCode(id) }
  }
  if (!codeG?.__loaded) loadCodeOverview()
}
async function loadCodeOverview() {
  if (!proj() || !codeG) return
  try {
    const d = await api(`/api/code/graph?project=${encodeURIComponent(proj())}&limit=1200`)
    d.nodes.forEach((n) => (n.__big = n.kind === "Module" || (n.degree || 0) > 40))
    codeG.setData({ nodes: d.nodes, links: d.links }); codeG.__loaded = true
    stageMsg($("#code-msg"), d.nodes.length ? "" : "This project has no classes or modules to draw. Use the search box to open a function's neighbourhood.")
  } catch (err) { stageMsg($("#code-msg"), esc(err.message)) }
}
async function focusCode(id) {
  const d = await api(`/api/code/ego/${id}?project=${encodeURIComponent(proj())}&depth=2`)
  d.nodes.forEach((n) => { n.__big = true; n.degree = n.id === id ? 60 : 3 })
  codeG.setData({ nodes: d.nodes, links: d.links }); inspectCode(id)
}
async function inspectCode(id) {
  const d = await api(`/api/code/node/${id}?project=${encodeURIComponent(proj())}`), el = $("#code-inspector")
  const skip = new Set(["CONTAINS_FILE", "CONTAINS_FOLDER"])
  const rel = (rows, dir) => { rows = rows.filter((r) => !skip.has(r.type)); return rows.length ? `<h4>${dir}</h4><ul>${rows.slice(0, 80).map((r) => `<li><span class="tag">${esc(r.type)}</span><a data-id="${r.id}">${esc(short(r.qname))}</a> <span class="muted">${esc(r.label)}</span></li>`).join("")}</ul>` : "" }
  const props = Object.entries(d.props || {}).filter(([, v]) => v !== false && v !== null && v !== "").map(([k, v]) => `<span class="tag">${esc(k)}: ${esc(Array.isArray(v) ? v.join(", ") : v)}</span>`).join("")
  el.innerHTML = `<button class="ghost close" aria-label="Close">✕</button><span class="tag">${esc(d.label)}</span>${props}
    <h3>${esc(short(d.qualified_name))}</h3><p class="muted">${esc(d.file_path || "")}${d.file_path ? `:${d.start_line}-${d.end_line}` : ""}</p>
    ${d.code ? `<pre class="code">${esc(d.code)}</pre>` : ""}<button class="ghost" id="ego-btn">Show neighbourhood</button> <button class="ghost" id="ask-btn">Ask about this</button>
    ${rel(d.out, "Uses / contains")}${rel(d.in, "Used by")}`
  el.hidden = false
  $(".close", el).onclick = () => (el.hidden = true)
  $("#ego-btn", el).onclick = () => focusCode(id)
  $("#ask-btn", el).onclick = () => {   // research while coding: what does this do, who uses it, which rules apply
    $("#a-q").value = `What does ${d.qualified_name} do, who calls it, and which business rules apply to it?`
    const opt = $(`#a-target option[value="repo:${CSS.escape(proj())}"]`); if (opt) $("#a-target").value = opt.value
    location.hash = "#ask"
  }
  $$("a[data-id]", el).forEach((a) => (a.onclick = () => inspectCode(+a.dataset.id)))
}

/* ---------------------------------------------------------- document graph */
let docG
INIT.docgraph = () => {
  const pal = PALETTE()
  docG = makeGraph($("#doc-canvas"), { color: (n) => hashColor(n.kind, pal), label: (n) => `${n.kind}: ${n.name}`,
    size: (n) => 1 + Math.min(14, n.degree || 1), linkColor: () => css("--ink-2") + "66", onClick: (n) => inspectDoc(n) })
  $("#doc-go").addEventListener("click", loadDocGraph)
  $("#doc-q").addEventListener("keydown", (e) => e.key === "Enter" && loadDocGraph())
  let t; $("#doc-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(async () => {
    const labels = await api(`/api/docs/labels?q=${encodeURIComponent($("#doc-q").value.trim())}`).catch(() => [])
    $("#doc-labels").innerHTML = (labels || []).slice(0, 50).map((l) => `<option value="${esc(l)}">`).join("") }, 250) })
}
REFRESH.docgraph = () => { if (docG && !docG.__loaded) loadDocGraph() }
async function loadDocGraph() {
  if (!docG) return
  try {
    const d = await api(`/api/docs/graph?label=${encodeURIComponent($("#doc-q").value.trim() || "*")}&max_nodes=700`)
    const deg = {}; d.links.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1 })
    d.nodes.forEach((n) => { n.degree = deg[n.id] || 0; n.__big = n.degree > 6 })
    const kinds = [...new Set(d.nodes.map((n) => n.kind))].slice(0, 8), pal = PALETTE()
    legend($("#doc-legend"), kinds.map((k) => [k, hashColor(k, pal)]))
    docG.setData({ nodes: d.nodes, links: d.links }); docG.__loaded = true
    stageMsg($("#doc-msg"), d.nodes.length ? (d.truncated ? "Large graph: showing the most connected part. Search an entity to focus." : "") : "The document graph is empty. Upload documents under <a href='#documents'>Documents</a>.")
  } catch (err) { stageMsg($("#doc-msg"), esc(err.message)) }
}
function inspectDoc(n) {
  const el = $("#doc-inspector"), data = docG.graphData()
  const rel = data.links.filter((l) => (l.source.id || l.source) === n.id || (l.target.id || l.target) === n.id)
  el.innerHTML = `<button class="ghost close" aria-label="Close">✕</button><span class="tag">${esc(n.kind)}</span><h3>${esc(n.name)}</h3>
    <p>${esc(n.description)}</p><button class="ghost" id="doc-focus">Focus on this entity</button>
    <h4>Relations</h4><ul>${rel.slice(0, 60).map((l) => { const s = l.source.id || l.source, t = l.target.id || l.target
      return `<li><b>${esc(s === n.id ? t : s)}</b> <span class="muted">${esc(l.description)}</span></li>` }).join("")}</ul>`
  el.hidden = false
  $(".close", el).onclick = () => (el.hidden = true)
  $("#doc-focus", el).onclick = () => { $("#doc-q").value = n.id; loadDocGraph() }
}

/* ---------------------------------------------------------- documents */
INIT.documents = () => {
  const drop = $("#drop"), input = $("#files")
  drop.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && input.click())
  ;["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over") }))
  ;["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over") }))
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files))
  input.addEventListener("change", () => { upload(input.files); input.value = "" })
  $("#note-add").onclick = async () => {
    const text = $("#note-text").value.trim(); if (!text) return toast("Write something first")
    try { await api("/api/docs/text", { method: "POST", json: { name: $("#note-name").value.trim() || "note.md", text } })
      $("#note-text").value = ""; $("#note-name").value = ""; toast("Note added; processing…"); REFRESH.documents() } catch (err) { toast(err.message) }
  }
}
async function upload(files) {
  if (!files || !files.length) return
  const fd = new FormData(); for (const f of files) fd.append("files", f)
  try {
    const { job } = await api("/api/docs/upload", { method: "POST", body: fd })
    const res = await followJob(job, $("#pipe"))
    const failed = res.filter((r) => r.status === "failure")
    toast(failed.length ? `${failed.length} file(s) failed: ${failed[0].message}` : `${res.length} file(s) queued for processing`)
  } catch (err) { toast(err.message) }
  REFRESH.documents()
}
let docTimer
REFRESH.documents = async () => {
  clearTimeout(docTimer)
  try {
    const d = await api("/api/docs"), p = d.pipeline || {}
    if (!$("#pipe .job.running")) $("#pipe").innerHTML = p.error ? `<div class="alert">${esc(p.error)}</div>` : p.busy ? `<div class="job running"><div class="t"><b>Processing documents</b>
      <span class="muted">${esc(p.job || "")}</span></div><div class="s">${esc(p.message || "")}</div><div class="bar ${p.batches ? "" : "indet"}"><i style="width:${p.batches ? Math.round(100 * (p.batch || 0) / p.batches) : 0}%"></i></div></div>` : ""
    $("#doc-rows").innerHTML = d.documents.map((x) => `<tr><td>${esc(x.name)}${x.error ? `<div class="muted">${esc(x.error).slice(0, 300)}</div>` : ""}</td>
      <td><span class="st ${esc(x.status)}">${esc(x.status)}</span></td><td>${x.chunks ?? ""}</td><td>${ago(x.updated_at)}</td>
      <td><button class="ghost small" data-md="${esc(x.name)}" title="The Markdown this document was converted to">Markdown</button> <button class="del" data-id="${esc(x.id)}" data-name="${esc(x.name)}">Remove</button></td></tr>`).join("") || `<tr><td colspan="5" class="muted">No documents yet.</td></tr>`
    $$("#doc-rows [data-md]").forEach((b) => (b.onclick = async () => {
      try { const r = await api(`/api/docs/markdown?name=${encodeURIComponent(b.dataset.md)}`); viewer(b.dataset.md + " (as Markdown)", r.markdown) } catch (err) { toast(err.message) }
    }))
    $$("#doc-rows .del").forEach((b) => (b.onclick = async () => {
      if (!confirm(`Remove "${b.dataset.name}" and everything extracted from it?`)) return
      try { await api(`/api/docs/${encodeURIComponent(b.dataset.id)}`, { method: "DELETE" }); toast("Removed") } catch (err) { toast(err.message) }
      REFRESH.documents()
    }))
    if (p.busy || d.documents.some((x) => !["processed", "failed"].includes(x.status))) docTimer = setTimeout(() => $("#documents").classList.contains("on") && REFRESH.documents(), 3000)
  } catch (err) { $("#pipe").innerHTML = `<div class="alert">${esc(err.message)}</div>` }
}

/* ---------------------------------------------------------- repositories, sets, per-repository webhooks */
const PROVIDERS = ["", "gitlab", "tfs", "git", "local"]
function editRow(r = {}) {
  const tr = document.createElement("tr")
  tr.innerHTML = `<td><input data-k="name" value="${esc(r.name || "")}" placeholder="billing"></td>
    <td><select data-k="provider">${PROVIDERS.map((p) => `<option value="${p}" ${p === (r.provider || "") ? "selected" : ""}>${p || "auto"}</option>`).join("")}</select></td>
    <td><input data-k="url" value="${esc(r.url || "")}" placeholder="gitlab:group/project · tfs:Project/repo · full URL"></td>
    <td><input data-k="path" value="${esc(r.path || "")}" placeholder="or D:\\src\\billing"></td>
    <td><input data-k="branch" value="${esc(r.branch || "main")}" size="8"></td>
    <td><input data-k="token" type="password" autocomplete="new-password" placeholder="${r.token_set ? "•••• set (type to replace)" : "server token"}"></td>
    <td><button class="del" title="Remove row">✕</button></td>`
  tr.dataset.secret = r.webhook_secret || ""
  $(".del", tr).onclick = () => tr.remove()
  $("#r-edit").appendChild(tr)
}
function setRow(name = "", members = []) {
  const div = document.createElement("div")
  div.className = "set-row box"
  const names = $$("#r-edit tr").map((tr) => $("[data-k=name]", tr).value.trim()).filter(Boolean)
  div.innerHTML = `<div class="row"><label class="inl">Set name <input class="set-name" value="${esc(name)}" placeholder="payments"></label>
      <span class="spacer"></span><button class="del small" title="Remove set">✕</button></div>
    <div class="row">${names.map((n) => `<label class="inl chk"><input type="checkbox" value="${esc(n)}" ${members.includes(n) ? "checked" : ""}> ${esc(n)}</label>`).join("") || "<span class='muted'>Add repositories first.</span>"}</div>`
  $(".del", div).onclick = () => div.remove()
  $("#set-edit").appendChild(div)
}
async function saveReposAndSets() {
  const rows = $$("#r-edit tr").map((tr) => ({ ...Object.fromEntries($$("[data-k]", tr).map((i) => [i.dataset.k, i.value.trim()])), webhook_secret: tr.dataset.secret }))
    .filter((r) => r.name || r.url || r.path)
  const sets = {}
  $$("#set-edit .set-row").forEach((d) => { const n = $(".set-name", d).value.trim(); if (n) sets[n] = $$("input[type=checkbox]:checked", d).map((c) => c.value) })
  try { await api("/api/repos", { method: "PUT", json: { repos: rows, sets } }); toast("Saved. Use 'Update' to index new repositories."); REFRESH.repos(true) } catch (err) { toast(err.message) }
}
INIT.repos = () => {
  $("#r-add").onclick = () => editRow()
  $("#r-save").onclick = saveReposAndSets
  $("#set-save2").onclick = saveReposAndSets
  $("#set-add").onclick = () => setRow()
  $("#repo-set-save").onclick = () => saveSettings("#repo-settings", "#repo-set-msg")
  $("#r-sync-all").onclick = async () => { const r = await api("/api/repos/sync", { method: "POST" }); toast(r.job ? "Update started; see Overview" : "An update was just requested") }
  $("#d-go").onclick = async () => {
    const repo = $("#d-repo").value; if (!repo) return toast("Choose a repository")
    const files = $("#d-files").value.split("\n").map((x) => x.trim()).filter(Boolean)
    $("#d-out").innerHTML = "<p class='muted'>Checking…</p>"
    try { const r = await api("/api/drift", { method: "POST", json: { repo, branch: $("#d-branch").value.trim() || null, base_commit: $("#d-base").value.trim() || null, changed_files: files } })
      $("#d-out").innerHTML = md(r.markdown) } catch (err) { $("#d-out").innerHTML = `<div class="alert">${esc(err.message)}</div>` }
  }
}
function hookCell(r) {
  const w = r.webhook || {}
  if (r.provider === "local") return `<span class="muted">local checkout: re-indexed after every pull of ${esc(r.branch)} (checked every BRAIN_WATCH_LOCAL_SECONDS); no webhook needed</span>`
  return `<div class="hook"><span class="tag">${esc(w.provider)}</span><code class="sel">${esc(w.url)}</code>
    <button class="ghost small" data-copy="${esc(w.url)}">Copy URL</button>
    <button class="ghost small" data-copy="${esc(w.secret)}">Copy secret</button>
    <details><summary class="muted">How to set it up</summary><p class="muted">${esc(w.how)}</p></details></div>`
}
REFRESH.repos = async (rebuild) => {
  await loadRepos()
  $("#r-list").innerHTML = `<table class="tbl"><thead><tr><th>Repository</th><th>Indexed</th><th>Sets</th><th>Webhook (own URL and secret)</th><th>Branch overlays</th><th></th></tr></thead><tbody>${
    REPOS.map((r) => `<tr><td><b>${esc(r.name)}</b> <span class="muted">→ ${esc(r.branch)}</span><div class="muted">${esc(r.remote || r.path)}</div>${r.error ? `<div class="alert">${esc(r.error)}</div>` : ""}</td>
      <td>${r.indexed ? `${fmt(r.nodes)} symbols${r.vectors && r.vectors.symbols ? `<div class="muted">${fmt(r.vectors.symbols)} code vectors</div>` : ""}<div class="muted">${esc((r.commit || "").slice(0, 10))} · ${ago(r.indexed_at)}</div>` : "<span class='st pending'>not yet</span>"}</td>
      <td>${(r.sets || []).map((s) => `<span class="tag">${esc(s)}</span>`).join("")}</td>
      <td>${hookCell(r)}</td>
      <td>${r.branches.map((b) => `<div><code>${esc(b.branch)}</code> <button class="del small" data-rm="${esc(r.name)}|${esc(b.branch)}">✕</button></div>`).join("")}
        <button class="ghost small" data-ov="${esc(r.name)}">Index a branch…</button></td>
      <td><button class="ghost small" data-sync="${esc(r.name)}">Update</button></td></tr>`).join("") || `<tr><td colspan="6" class="muted">No repositories configured. Add one below.</td></tr>`}</tbody></table>`
  $$("[data-copy]").forEach((b) => (b.onclick = () => navigator.clipboard.writeText(b.dataset.copy).then(() => toast("Copied"), () => toast("Copy failed"))))
  $$("[data-sync]").forEach((b) => (b.onclick = async () => { const r = await api(`/api/repos/${b.dataset.sync}/sync`, { method: "POST" }); toast(r.job ? "Update started; progress on Overview" : "Already requested a moment ago") }))
  $$("[data-ov]").forEach((b) => (b.onclick = async () => {
    const br = prompt("Branch to index as an overlay (it must be pushed):"); if (!br) return
    const { job } = await api(`/api/repos/${b.dataset.ov}/branches`, { method: "POST", json: { branch: br } })
    toast("Indexing branch…"); followJob(job, $("#d-out")).then(() => { toast("Branch overlay ready"); REFRESH.repos() }, (e) => toast(e.message))
  }))
  $$("[data-rm]").forEach((b) => (b.onclick = async () => { const [n, br] = b.dataset.rm.split("|")
    try { await api(`/api/repos/${n}/branches/${encodeURIComponent(br)}`, { method: "DELETE" }); toast("Overlay removed"); REFRESH.repos() } catch (err) { toast(err.message) } }))
  if (rebuild || !$("#r-edit").children.length) {
    $("#r-edit").innerHTML = ""; REPOS.forEach(editRow); if (!REPOS.length) editRow()
    $("#set-edit").innerHTML = ""; Object.entries(SETS).filter(([k]) => k !== "all").forEach(([k, v]) => setRow(k, v))
  }
  const st = await api("/api/settings").catch(() => null)
  if (st) renderSettings($("#repo-settings"), st.settings.filter((s) => s.page === "repos"))
  const w = await api("/api/webhooks").catch(() => null)
  if (w) $("#w-info").innerHTML = `<div class="box"><p class="muted">Group-level hooks (one hook for many repositories, matched by URL): GitLab <code>${esc(w.gitlab_url)}</code>
      ${w.gitlab_configured ? "<span class='st ready'>configured</span>" : "<span class='st'>not configured</span>"} · TFS <code>${esc(w.tfs_url)}</code>
      ${w.tfs_configured ? "<span class='st ready'>configured</span>" : "<span class='st'>not configured</span>"} · events: ${esc(w.events)}</p>
    ${w.deliveries.length ? `<table class="tbl"><tbody>${w.deliveries.map((d) => `<tr><td>${ago(d.time)}</td><td>${esc(d.source)}</td>
      <td><span class="st ${d.status < 300 ? "done" : "error"}">${d.status}</span></td><td>${esc(d.repo || "")} ${esc(d.error || d.ignored || (d.accepted ? `update queued (${d.event})` : ""))}</td></tr>`).join("")}</tbody></table>` : "<p class='muted'>No deliveries yet.</p>"}</div>`
}

/* ---------------------------------------------------------- settings (shared renderer) */
function renderSettings(el, items) {
  const groups = {}; items.forEach((s) => (groups[s.group] ||= []).push(s))
  el.innerHTML = Object.entries(groups).map(([g, list]) => `<div class="sgroup"><h2>${esc(g)}</h2><div class="sgrid">${list.map((s) => {
    const id = "set_" + s.key
    const input = s.kind === "choice" ? `<select id="${id}" data-key="${s.key}">${s.choices.map((c) => `<option ${c === (s.value || s.default) ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>`
      : s.kind === "bool" ? `<select id="${id}" data-key="${s.key}">${["true", "false"].map((c) => `<option ${c === String(s.value || s.default).toLowerCase() ? "selected" : ""}>${c}</option>`).join("")}</select>`
      : s.kind === "secret" ? `<input id="${id}" data-key="${s.key}" type="password" autocomplete="new-password" placeholder="${s.is_set ? "•••••• (set; type to replace)" : "not set"}">`
      : `<input id="${id}" data-key="${s.key}" value="${esc(s.value)}" placeholder="${esc(s.default)}">`
    return `<label class="k" for="${id}">${esc(s.key)}${s.restart ? `<small>restarts ${s.restart === "server" ? "server (manual)" : s.restart + " engine"}</small>` : ""}</label>
      <div class="v">${input}<div class="help">${esc(s.help)}</div></div>` }).join("")}</div></div>`).join("")
  $$("[data-key]", el).forEach((i) => i.addEventListener("input", () => i.parentElement.classList.add("changed")))
}
async function saveSettings(box, msg) {
  const changes = {}
  $$(`${box} .changed [data-key]`).forEach((el) => { if (!(el.type === "password" && !el.value)) changes[el.dataset.key] = el.value })
  if (!Object.keys(changes).length) return toast("Nothing changed")
  try {
    const r = await api("/api/settings", { method: "PUT", json: { changes } })
    $(msg).textContent = `Saved ${r.saved.join(", ")}. ${r.jobs.length ? "Engines restarting (see Overview)." : ""} ${r.restart_server ? "Restart the server to apply host/port/TLS/data changes." : ""}`
    $$(`${box} .changed`).forEach((x) => x.classList.remove("changed"))
  } catch (err) { $(msg).textContent = ""; toast(err.message) }
}
REFRESH.settings = async () => {
  const r = await api("/api/settings")
  $("#set-lede").textContent = `Stored in ${r.file}. Changes apply right away; engines restart by themselves when needed. Git servers and webhooks are on the Repositories page.`
  renderSettings($("#set-groups"), r.settings.filter((s) => s.page !== "repos"))
}
INIT.settings = () => { $("#set-save").onclick = () => saveSettings("#set-groups", "#set-msg") }

/* ---------------------------------------------------------- requirements writer */
let SRS_LAST = null
async function loadTemplates() {
  const r = await api("/api/srs/templates").catch(() => ({ templates: ["default"] }))
  const sel = $("#q-template"), cur = sel.value
  sel.innerHTML = r.templates.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("")
  if (cur && r.templates.includes(cur)) sel.value = cur
}
async function loadTemplateInto(name) {
  const r = await api(`/api/srs/templates/${encodeURIComponent(name)}`)
  $("#q-tpl-name").value = r.name; $("#q-tpl-text").value = r.text
}
INIT.srs = () => {
  seg($("#q-mode"), (m) => {   // "something new" uses its own built-in format unless another one was chosen
    const sel = $("#q-template"), want = m === "new" ? "new-feature" : "default"
    if (["default", "new-feature"].includes(sel.value) && $(`option[value="${want}"]`, sel)) sel.value = want
    $("#r-topic").placeholder = m === "new" ? "e.g. customers can pay invoices in instalments / taksitli ödeme" : "e.g. the whole billing system / refunds / müşteri iade süreci"
  })
  $("#q-tpl-box").addEventListener("toggle", () => { if ($("#q-tpl-box").open && !$("#q-tpl-text").value) loadTemplateInto($("#q-template").value || "default") })
  $("#q-tpl-load").onclick = () => loadTemplateInto($("#q-template").value)
  $("#q-tpl-new").onclick = async () => { await loadTemplateInto("default"); $("#q-tpl-name").value = "my-format" }
  $("#q-tpl-save").onclick = async () => {
    try { const r = await api(`/api/srs/templates/${encodeURIComponent($("#q-tpl-name").value.trim())}`, { method: "PUT", json: { text: $("#q-tpl-text").value } })
      toast(`Format "${r.saved}" saved`); await loadTemplates(); $("#q-template").value = r.saved } catch (err) { toast(err.message) }
  }
  $("#q-tpl-del").onclick = async () => {
    const n = $("#q-tpl-name").value.trim(); if (!n || !confirm(`Delete format "${n}"?`)) return
    try { await api(`/api/srs/templates/${encodeURIComponent(n)}`, { method: "DELETE" }); toast("Deleted"); loadTemplates() } catch (err) { toast(err.message) }
  }
  $("#q-go").onclick = async () => {
    const topic = $("#r-topic").value.trim(); if (!topic) return toast("Describe what should be specified")
    $("#q-go").disabled = true; $("#q-out").innerHTML = ""; $("#q-actions").hidden = true
    try {
      const { job } = await api("/api/srs", { method: "POST", json: { topic, mode: segVal($("#q-mode")), target: $("#q-target").value, template: $("#q-template").value,
        language: $("#q-lang").value, model: $("#q-model").value || null, async: true } })
      SRS_LAST = await followJob(job, $("#q-progress"))
      showSrs(SRS_LAST.name, SRS_LAST.markdown, SRS_LAST.errors); evidencePanel($("#q-ev"), SRS_LAST); REFRESH.srs()
    } catch (err) { $("#q-progress").innerHTML = `<div class="alert">${esc(err.message)}</div>` } finally { $("#q-go").disabled = false }
  }
  $("#q-copy").onclick = () => navigator.clipboard.writeText(SRS_LAST?.markdown || "").then(() => toast("Copied"), () => toast("Copy failed"))
  $("#q-download").onclick = () => { if (!SRS_LAST) return
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([SRS_LAST.markdown], { type: "text/markdown" }))
    a.download = `${SRS_LAST.name}.md`; a.click(); URL.revokeObjectURL(a.href) }
  $("#q-publish").onclick = async () => { if (!SRS_LAST) return
    try { await api(`/api/srs/documents/${encodeURIComponent(SRS_LAST.name)}/publish`, { method: "POST" }); toast("Added to the document graph (processing)") } catch (err) { toast(err.message) } }
}
function showSrs(name, markdown, errors) {
  SRS_LAST = { name, markdown }
  $("#q-out").innerHTML = md(markdown); $("#q-actions").hidden = false
  $("#q-note").textContent = errors && errors.length ? `Notes: ${errors.slice(0, 3).join("; ")}` : ""
}
REFRESH.srs = async () => {
  await loadTemplates()
  const r = await api("/api/srs/documents").catch(() => ({ documents: [] }))
  $("#q-docs").innerHTML = r.documents.map((d) => `<tr><td>${esc(d.title)}</td><td>${esc(d.scope || "")}</td><td>${esc(d.template || "")}</td><td>${ago(d.created)}</td>
    <td><button class="ghost small" data-open="${esc(d.name)}">Open</button> <button class="del small" data-del="${esc(d.name)}">✕</button></td></tr>`).join("")
    || `<tr><td colspan="5" class="muted">None yet.</td></tr>`
  $$("#q-docs [data-open]").forEach((b) => (b.onclick = async () => { const d = await api(`/api/srs/documents/${encodeURIComponent(b.dataset.open)}`); showSrs(d.name, d.markdown); window.scrollTo(0, 0) }))
  $$("#q-docs [data-del]").forEach((b) => (b.onclick = async () => { if (!confirm("Delete this specification?")) return
    await api(`/api/srs/documents/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" }); REFRESH.srs() }))
}

/* ---------------------------------------------------------- viewer (converted Markdown) */
function viewer(title, markdown) {
  $("#viewer-title").textContent = title; $("#viewer-body").innerHTML = md(markdown)
  $("#viewer").showModal()
}
$("#viewer-close").onclick = () => $("#viewer").close()

/* ---------------------------------------------------------- logs */
INIT.logs = () => { seg($("#log-pick"), () => REFRESH.logs()); $("#log-refresh").onclick = () => REFRESH.logs() }
REFRESH.logs = async () => { const r = await api(`/api/logs/${segVal($("#log-pick"))}?lines=400`).catch((e) => ({ lines: [e.message] }))
  const el = $("#log-out"); el.textContent = r.lines.join("\n") || "(empty)"; el.scrollTop = el.scrollHeight }

/* ---------------------------------------------------------- boot */
async function boot() {
  try { await api("/api/me") } catch { return }
  showApp(); await loadRepos(); loadModels(); show(location.hash.slice(1) || "overview")
  clearInterval(boot.t)
  boot.t = setInterval(() => { if (document.hidden) return; loadStatus(); if ($("#overview").classList.contains("on")) REFRESH.overview() }, 4000)
}
boot()
