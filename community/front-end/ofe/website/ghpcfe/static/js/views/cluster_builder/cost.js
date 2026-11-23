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

// Cluster Builder: The cost panel (cloud_info pricing).
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- cost (cloud_info pricing) ---------------- */
// The server lists the configuration's VMs (every module with a machine type,
// set or the module default; ofe_agent.toolkit.capacity.vms) and prices them.
const COSTS = {};  // stateKey + zone -> cost API result, or "loading"
let costTimer = null;
function renderCost() {
  const zoneVar = vars(S.bp).find(v => v.name === "zone");
  const zone = (zoneVar && current(S.bp, S.overrides, zoneVar)) || "";
  const key = stateKey() + "|" + zone, r = COSTS[key];
  if (r === undefined) {
    COSTS[key] = "loading";
    clearTimeout(costTimer);
    costTimer = setTimeout(async () => {
      try { COSTS[key] = await api("cost", {blueprint: S.bp, overrides: S.overrides, changes: S.changes, zone, credential_id: credId}); }
      catch (err) { COSTS[key] = {error: err.message}; }
      if (S && stateKey() + "|" + zone === key) renderCost();
    }, 300);
  }
  if (!r || r === "loading") { qs("#cost").innerHTML = '<div class="small text-muted mt-1">Working out the VMs…</div>'; return; }
  if (r.error) { qs("#cost").innerHTML = `<div class="small text-muted mt-1">No estimate: ${esc(r.error)}</div>`; return; }
  if (!r.vms.length) { qs("#cost").innerHTML = '<div class="small mt-1">No module in this configuration runs VMs with a machine type.</div>'; return; }
  const price = mt => (r.prices || {})[mt];
  let always = 0, peak = 0, complete = true;
  const rows = r.vms.map(v => {
    const p = price(v.machine_type), n0 = v.static || 0, n1 = v.dynamic_max || 0;
    if (typeof p === "number") { always += p * n0; peak += p * (n0 + n1); } else complete = false;
    const count = [n0 ? `${n0}` : "", n1 ? `up to ${n1}` : ""].filter(Boolean).join(" + ") || (v.static === null ? "?" : "0");
    return `<div class="d-flex justify-content-between small"><span><code>${esc(v.module)}</code>: ${esc(count)} × ${esc(v.machine_type)}${
      v.machine_type_default ? ' <span class="text-muted">(module default)</span>' : ""}${v.spot ? ' <span class="badge badge-warning">Spot</span>' : ""}</span><b>${
      typeof p === "number" ? "$" + (p * (n0 + n1)).toFixed(2) + "/hr" : r.zone ? "n/a" : ""}</b></div>`;
  }).join("");
  qs("#cost").innerHTML = r.zone
    ? `<div class="h4 mb-0">$${always.toFixed(2)}/hr <small class="text-muted">always on</small></div>
       <div class="mb-1">up to $${peak.toFixed(2)}/hr at full scale${complete ? "" : ' <small class="text-muted">(partial)</small>'}</div>
       <div class="small text-muted mb-1">On-demand prices in ${esc(r.zone)}; autoscaled nodes cost nothing when idle; Spot is cheaper.</div>${rows}`
    : rows + '<div class="small text-muted">Set a zone to see prices.</div>';
}

function renderDefinition() {
  const st = validation ? validBadge(validation.valid) : '<span class="badge badge-secondary">not run</span>';
  const missing = missingValues().length;
  qs("#definition").innerHTML = `<div class="d-flex justify-content-between"><span class="text-muted">Template</span><code>${esc(bpFile().split("/").pop())}</code></div>
    <div class="d-flex justify-content-between"><span class="text-muted">Modules</span><b>${modsOf().length}${hasChanges(S.changes) ? ` <small class="text-muted">(+${S.changes.add_modules.length} / −${S.changes.remove_modules.length})</small>` : ""}</b></div>
    <div class="d-flex justify-content-between"><span class="text-muted">Overrides</span><b>${Object.keys(S.overrides).length}</b></div>
    <div class="d-flex justify-content-between"><span class="text-muted">Required values missing</span><b class="${missing ? "text-danger" : ""}">${missing}</b></div>
    <div class="d-flex justify-content-between"><span class="text-muted">Gemini changes accepted</span><b>${S.accepted}</b></div>
    <div class="d-flex justify-content-between"><span class="text-muted">Validation</span>${st}</div>
    ${validation ? `<div class="small">${capacityHtml(validation.capacity)}</div>` : ""}`;
}

document.querySelectorAll("#tabs .nav-link").forEach(a => a.onclick = e => { e.preventDefault(); tab = a.dataset.tab; renderBuilder(); });
