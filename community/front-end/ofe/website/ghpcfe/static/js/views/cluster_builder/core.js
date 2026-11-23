/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Cluster Builder: Page data, API calls, the builder's state and shared helpers.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

const PAGE = JSON.parse(document.getElementById("cb-page").textContent);
// URLS and CSRF come from the template (builder.html).
const qs = s => document.querySelector(s);  // not $: that is jQuery on this page
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// Gemini's text: escaped, with `inline code` shown as code (the only markup it uses).
const agentText = s => esc(s).replace(/`([^`\n]+)`/g, "<code>$1</code>");

async function api(name, body) {
  const r = await fetch(URLS[name], {
    method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": CSRF}, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({error: `HTTP ${r.status}`}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
// A streamed endpoint (newline-delimited JSON): calls onProgress for each
// {"progress"} line and returns the data of the final {"status", "data"} line.
async function apiStream(name, body, onProgress) {
  const r = await fetch(URLS[name], {
    method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": CSRF}, body: JSON.stringify(body),
  });
  if (!r.ok || !r.body) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${r.status}`);
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    buf += value;
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const event = JSON.parse(buf.slice(0, nl));
      buf = buf.slice(nl + 1);
      if ("status" in event) {
        if (event.status !== 200) throw new Error(event.data.error || `HTTP ${event.status}`);
        return event.data;
      }
      onProgress(event.progress);
    }
  }
  throw new Error("The connection closed before Gemini finished; try again.");
}
function showError(err) {
  qs("#errorBox").innerHTML = `<div class="alert alert-danger alert-dismissible">${esc(err.message || err)}<button type="button" class="close" data-dismiss="alert">&times;</button></div>`;
  window.scrollTo(0, 0);
}

let tab = "config", group = "basics", yamlFile = "blueprint", modFilter = "", addFilter = "", addCat = "";
// Current configuration. changes mirrors ofe_agent.tools.check_changes:
// promoted [{module, input, var, type, def, required}], add_modules [{id, source, use, used_by, settings}], remove_modules [id]
let S = null;           // {bp, overrides, changes, accepted}
let validation = null;  // last Validate/proposal result for the current state (key = stateKey())
const PREVIEWS = {};    // changesKey -> server-built ai_assisted copy {view, clean}
const HIST = [];        // [{by: "start"|"gemini"|"you", label, state: {bp, overrides, changes}}]
let histSel = -1;       // Changes tab: step index, 0 for "all changes since the template", -2 for a pending proposal
let previewOpt = null;  // {turn, id}: the pending option the Changes tab shows (histSel -2)
let pick = null, credId = null, workload = "", clusterName = "", regionPref = "";
let ZONES = null;       // {region: [zones]} for the credential, from cloud_info
const NAME_RE = /^[a-z][-_a-z0-9]{0,62}$/;  // deployment_name is a GCP label value
let addSource = null;   // module source being added on the "Add module" page
const BD = {};          // blueprint path -> data from the blueprint API
const MM = {};          // module source -> data from the module API (modules not in the template)
let MODULES = null;     // catalog module_wiring list, for "Add module"
const turns = [];       // [{prompt, result, state: "pending"|"applied"|"rejected"|"info"}]
const openDet = new Set();

/* ---------------- helpers ---------------- */
const credential = () => PAGE.credentials.find(c => String(c.id) === String(credId)) || {};
const emptyChanges = () => ({promoted: [], add_modules: [], remove_modules: [], settings: []});
const hasChanges = ch => !!ch && (ch.promoted.length || ch.add_modules.length || ch.remove_modules.length || (ch.settings || []).length);
const parseDefault = v => { try { return JSON.parse(v.default); } catch (e) { return v.default; } };
// A default as people read it: strings unquoted, everything else as JSON.
const showDefault = v => { const d = parseDefault(v); return d == null ? "" : typeof d === "string" ? d : JSON.stringify(d); };
// required: added by Gemini as an input only the user knows (no default).
// A linked entry (link: true) points an existing var at an input, so it adds no var.
const promotedVars = pr => pr.filter(x => !x.link).map(x => ({name: x.var, type: x.type, promoted: x,
  ...(x.required ? {required: true} : {default: JSON.stringify(x.def)})}));
// Vars only removed modules use are dropped from the copy (mirrors tools._orphaned_vars).
function droppedVars(bp, ch) {
  if (!ch.remove_modules.length) return new Set();
  const uses = (BD[bp] || {}).uses || {}, tplVars = JSON.stringify((BD[bp] || {}).variables || []);
  const added = JSON.stringify(ch.add_modules.map(a => a.settings));
  return new Set(Object.entries(uses).filter(([v, us]) => us.length && us.every(u => ch.remove_modules.includes(u.module))
    && !added.includes(`$(vars.${v})`) && !tplVars.includes(`var.${v}`)).map(([v]) => v));
}
const vars = bp => {
  if (!(S && S.bp === bp)) return BD[bp] ? BD[bp].variables : [];
  const dropped = droppedVars(bp, S.changes);
  return [...BD[bp].variables.filter(v => !dropped.has(v.name)), ...promotedVars(S.changes.promoted)];
};
const copyName = bp => bp.replace(/\.yaml$/, "-ai.yaml");
const bpFile = () => hasChanges(S.changes) ? copyName(S.bp) : S.bp;
const current = (bp, ov, v) => (v.name in ov) ? ov[v.name] : (v.type === "expression" ? "" : parseDefault(v));
const label = n => n.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const changesKey = ch => JSON.stringify([ch.promoted.map(p => [p.module, p.input, p.var, !!p.required, !!p.link]), ch.add_modules, ch.remove_modules, ch.settings || []]);
const stateKey = () => JSON.stringify([S.bp, S.overrides, changesKey(S.changes)]);
const snapshot = () => JSON.parse(JSON.stringify({bp: S.bp, overrides: S.overrides, changes: S.changes}));
function record(by, label) { HIST.push({by, label, state: snapshot()}); histSel = HIST.length - 1; }
// Manual edits since the last Gemini change are one "Your edits" step.
const changed = () => {
  validation = null;
  const last = HIST[HIST.length - 1];
  if (last && last.by === "you") last.state = snapshot(); else record("you", "Your edits");
};
const declaredVarNames = () => new Set(vars(S.bp).map(v => v.name));
// "$name" in the UI <-> "$(vars.name)" in blueprints, for declared vars only.
const toShort = s => typeof s === "string" ? s.replace(/\$\(vars\.([a-z0-9_]+)\)/g, "$$$1") : s;
const toLong = s => typeof s === "string" ? s.replace(/\$([a-z][a-z0-9_]*)/g, (m, n) => declaredVarNames().has(n) ? `$(vars.${n})` : m) : s;
// explain renders an expression default such as $(vars.deployment_name)-lustre as (("${var.deployment_name}-lustre")).
function exprDisplay(d) {
  let s = String(d ?? "").replace(/^\(\(/, "").replace(/\)\)$/, "");
  if (/^".*"$/.test(s)) s = s.slice(1, -1);
  return s.replace(/\$\{var\.([a-z0-9_]+)\}/g, "$$$1").replace(/\bvar\.([a-z0-9_]+)/g, "$$$1");
}
function fmt(v) { return typeof v === "string" ? (v === "" || /[:#{}\[\],]/.test(v) ? JSON.stringify(v) : v) : (v && typeof v === "object" ? JSON.stringify(v) : String(v)); }
function depYaml(overrides) {
  const L = ["ai_assisted: true", "vars:", `  project_id: ${credential().project || "(from credential)"}`];
  for (const [k, v] of Object.entries(overrides)) L.push(`  ${k}: ${fmt(v)}`);
  return L.join("\n");
}
// The page's deployment.yaml: every runtime value, as the server builds it
// (ofe_agent.toolkit.deployment.implied_vars): gcluster's globals, vars only
// the example deployment file sets, generated network names, then the
// user's overrides. The blueprint keeps its own defaults.
function deploymentVars() {
  const bd = BD[S.bp] || {}, dropped = droppedVars(S.bp, S.changes), out = {};
  for (const v of vars(S.bp)) {
    const x = v.global && v.name !== "project_id" ? current(S.bp, S.overrides, v) : null;
    if (x != null && x !== "") out[v.name] = x;
  }
  for (const [k, x] of Object.entries(bd.deployment_defaults || {})) if (!dropped.has(k)) out[k] = x;
  for (const k of Object.keys(bd.generated || {})) if (!dropped.has(k)) out[k] = genName(k);
  return Object.assign(out, S.overrides);
}
const deploymentText = () => depYaml(deploymentVars());
// The YAML tab's Defaults view: the blueprint's vars: as a table, since the
// blueprint view leaves them out. Each default, what kind of var it is,
// and whether deployment.yaml replaces it.
function defaultsHtml() {
  const bd = BD[S.bp] || {}, dep = deploymentVars();
  // Vars only the image build uses (modules in image or image-support groups).
  const imageMods = new Set((bd.stages || []).filter(g => g.role !== "cluster").flatMap(g => g.modules));
  const imageOnly = v => { const u = (bd.uses || {})[v.name] || []; return u.length && u.every(x => imageMods.has(x.module)); };
  const kind = v => v.promoted ? '<span class="badge badge-info">added</span>'
    : imageOnly(v) ? '<span class="badge badge-warning" title="used only by the custom image build">image</span>'
    : v.global ? '<span class="badge badge-secondary" title="gcluster global, set in Cluster basics">global</span>'
    : v.type === "expression" ? '<span class="badge badge-light" title="computed from other vars; not set directly">derived</span>' : "";
  const value = v => v.type === "expression" ? `<code>${esc(toShort(exprDisplay(v.default)))}</code>`
    : v.required && v.default === undefined ? '<span class="text-muted">none (required)</span>'
    : `<code>${esc(showDefault(v))}</code>`;
  const rows = vars(S.bp).filter(v => v.name !== "project_id").map(v => {
    const set = v.name in dep ? `<code>${esc(fmt(dep[v.name]))}</code>` : '<span class="text-muted">default</span>';
    return `<tr><td><code>${esc(v.name)}</code> ${kind(v)}</td><td>${value(v)}</td><td>${set}</td></tr>`;
  });
  return `<div class="table-responsive" style="max-height:60vh"><table class="table table-sm small mb-0">
    <thead><tr><th>Variable</th><th>Default</th><th>deployment.yaml</th></tr></thead>
    <tbody>${rows.join("")}</tbody></table></div>`;
}
function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: "text/yaml"}));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}
function lineDiff(a, b) {
  const A = a.split("\n"), B = b.split("\n"), n = A.length, m = B.length;
  const dp = Array.from({length: n + 1}, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push([" ", A[i++]]); j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(["-", A[i++]]);
    else out.push(["+", B[j++]]);
  }
  while (i < n) out.push(["-", A[i++]]); while (j < m) out.push(["+", B[j++]]);
  return out;
}
// ctx = lines of context around changes (null = whole file); module headers
// ("- id:" and the source line after it) are always kept for orientation.
function diffHtml(d, ctx = null) {
  const keep = d.map(() => ctx == null);
  if (ctx != null) d.forEach(([t], i) => {
    if (t === " ") return;
    for (let k = Math.max(0, i - ctx); k <= Math.min(d.length - 1, i + ctx); k++) keep[k] = true;
    for (let k = i; k >= 0; k--) if (/^\s*- id:/.test(d[k][1])) { keep[k] = true; if (d[k + 1]) keep[k + 1] = true; break; }
  });
  let h = "", gap = false;
  d.forEach(([t, l], i) => {
    if (!keep[i]) { if (!gap) h += '<span class="text-muted text-center">⋯</span>'; gap = true; return; }
    gap = false;
    h += `<span class="${t === "+" ? "a" : t === "-" ? "d" : ""}">${t === " " ? "  " : t + " "}${esc(l)}</span>`;
  });
  return `<pre class="cb-diff border rounded small py-1 mb-0">${h}</pre>`;
}

// Blueprint texts for a configuration, of the template or of its server-built
// copy when there are changes (undefined until fetched, see ensurePreview):
// view, as the YAML and Changes tabs show it (no vars:, whose defaults are in
// the Defaults view and values in deployment.yaml), and clean, as downloaded
// (vars: kept, without the example's comments; ofe_agent.toolkit.view).
const textFor = st => {
  if (hasChanges(st.changes)) return PREVIEWS[st.bp + changesKey(st.changes)];
  const bd = BD[st.bp];
  return bd && {view: bd.template_view, clean: bd.template_clean};
};
const viewText = st => (textFor(st) || {}).view;
const pendingPreviews = new Set();
function ensurePreview(st, delay = 0) {
  const key = st.bp + changesKey(st.changes);
  if (!hasChanges(st.changes) || PREVIEWS[key] !== undefined || pendingPreviews.has(key)) return;
  pendingPreviews.add(key);
  const body = {blueprint: st.bp, changes: st.changes};
  setTimeout(async () => {
    try { const r = await api("preview", body); PREVIEWS[key] = {view: r.view_yaml, clean: r.clean_yaml}; }
    catch (err) { showError(err); }
    pendingPreviews.delete(key);
    if (S && tab !== "config") renderBuilder();
  }, delay);
}
const schedulePreview = () => ensurePreview(S, 300);
