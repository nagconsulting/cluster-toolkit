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

// Cluster Builder: Step 1: the workload wizard. Loaded last: it fills the page on load.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- wizard ---------------- */
qs("#examples").innerHTML = PAGE.examples.map(p =>
  `<button type="button" class="list-group-item list-group-item-action small">${esc(p)}</button>`).join("");
document.querySelectorAll("#examples button").forEach(b => b.onclick = () => { qs("#intent").value = b.textContent; qs("#intent").focus(); });
qs("#region").innerHTML = `<option value="">Any</option>` + PAGE.regions.map(r => `<option>${esc(r)}</option>`).join("");
qs("#cred").innerHTML = PAGE.credentials.map(c => `<option value="${c.id}">${esc(c.name)}${c.project ? ` (${esc(c.project)})` : ""}</option>`).join("");
// Existing-network choice: subnets of OFE networks for the chosen credential.
let netChoice = null;
function onNetwork() {
  netChoice = PAGE.subnets.find(s => String(s.id) === qs("#network").value) || null;
  const reg = qs("#region");
  if (netChoice) {
    if (![...reg.options].some(o => o.value === netChoice.region)) reg.append(new Option(netChoice.region, netChoice.region));
    reg.value = netChoice.region;
  }
  reg.disabled = !!netChoice;  // the subnet's region
}
function fillNetworks() {
  const byVpc = {};
  PAGE.subnets.filter(s => String(s.credential) === String((qs("#cred") || {}).value))
    .forEach(s => (byVpc[s.vpc] = byVpc[s.vpc] || []).push(s));
  qs("#network").innerHTML = '<option value="">New network, created with the cluster</option>' +
    Object.entries(byVpc).map(([vpc, subnets]) => `<optgroup label="${esc(vpc)} (${esc(subnets[0].source)})">${subnets.map(s =>
      `<option value="${s.id}">${esc(s.name)} · ${esc(s.region)} · ${esc(s.cidr)}</option>`).join("")}</optgroup>`).join("");
  onNetwork();
}
qs("#network").onchange = onNetwork;
qs("#cred").onchange = fillNetworks;
fillNetworks();
if (!PAGE.credentials.length) {
  qs("#findBtn").disabled = true;
  qs("#cred").outerHTML = `<div class="alert alert-warning mb-0">Add a GCP credential under <a href="${URLS.credentials}">Credentials</a> first.</div>`;
}

function stepText(s) {
  const a = s.args || {};
  const f = {
    find_blueprints: () => `gcluster explain ${(a.specs || []).join(" ")}`,
    list_blueprints: () => "Read catalog.yaml",
    list_modules: () => "Read catalog.yaml module_wiring",
    describe: () => `gcluster explain ${a.path}`,
    read_module_docs: () => `Read ${a.path}/README.md`,
    propose_deployment: () => `gcluster expand ${a.blueprint} -d deployment.yaml${a.changes && a.changes !== "{}" ? " (template copy)" : ""}`,
    offer_option: () => `Offered: ${a.title}`,
    offer_approach: () => `Approach: ${a.title}`,
    ask_user: () => "Asked you a question",
    list_machine_types: () => `List machine types in ${a.zone}${a.prefix ? ` (${a.prefix}*)` : ""}`,
    list_reservations: () => `List reservations in ${a.zone}`,
    list_networks: () => "List OFE networks",
    list_firewall_rules: () => `List firewall rules of ${a.network_name}`,
    list_filesystems: () => "List OFE filesystems",
    machine_prices: () => `Look up prices in ${a.zone}: ${(a.machine_types || []).join(", ")}`,
  }[s.tool];
  return (f ? f() : s.tool) + (s.error ? `  (rejected: ${s.error})` : "") +
    ((s.notes || []).length ? `  (fixed: ${s.notes.join("; ")})` : "");
}

async function loadBlueprint(path) {
  if (!BD[path]) BD[path] = await api("blueprint", {path});
  return BD[path];
}

qs("#findBtn").onclick = async () => {
  const prompt = qs("#intent").value.trim();
  clusterName = qs("#clusterName").value.trim();
  if (!NAME_RE.test(clusterName)) {
    qs("#clusterName").classList.add("is-invalid");
    showError(new Error("Enter a cluster name: lowercase letters, digits, - or _, starting with a letter."));
    return;
  }
  qs("#clusterName").classList.remove("is-invalid");
  regionPref = qs("#region").value;
  if (!prompt) return;
  qs("#errorBox").innerHTML = "";
  qs("#findBtn").disabled = true; qs("#wizBusy").style.display = "";
  try {
    credId = qs("#cred").value;
    const r = await api("rank", {
      prompt, credential_id: credId,
      preferences: {scheduler: document.querySelector('input[name="sched"]:checked').value, region: qs("#region").value,
                    subnet_id: qs("#network").value},
    });
    workload = prompt;
    qs("#cred").disabled = true; qs("#network").disabled = true;
    renderCards(r);
    if (pick) loadBlueprint(pick).catch(() => {});  // prefetch the form for the top pick
  } catch (err) { showError(err); }
  qs("#findBtn").disabled = false; qs("#wizBusy").style.display = "none";
};

// Wizard note for a blueprint that builds a custom image (ofe_agent.toolkit.stages):
// the build runs before the cluster and adds a long first step.
const imageNote = im => `<div class="small mt-2"><span class="badge badge-warning mr-1">Custom image</span>` +
  (im.image_only ? "Builds an image only, no cluster" : "Builds a custom image before the cluster") +
  (im.family ? ` (family <code>${esc(im.family)}</code>)` : "") + ": the image build often takes 30 to 60 minutes.</div>";
function renderCards(r) {
  pick = r.candidates.length ? r.candidates[0].path : null;
  qs("#cards").innerHTML = `<h4>Recommended starting points</h4>${r.summary ? `<p class="text-muted">${esc(r.summary)}</p>` : ""}` +
    (r.candidates.length ? "" : '<div class="alert alert-warning">No matching blueprint. Try describing the workload differently.</div>') +
    r.candidates.map((c, i) => `<label class="card mb-2 d-block" style="cursor:pointer"><div class="card-body d-flex">
      <input type="radio" name="tpl" class="mr-3 mt-1" value="${esc(c.path)}" ${i === 0 ? "checked" : ""}>
      <div class="flex-grow-1">
        <div class="d-flex align-items-center"><code>${esc(c.path)}</code>
          ${i === 0 ? '<span class="badge badge-primary ml-2">Recommended</span>' : ""}
          ${c.scheduler ? `<span class="badge badge-light ml-1">${esc(c.scheduler)}</span>` : ""}
          <span class="ml-auto small text-muted">${c.score}% match</span></div>
        <div class="progress my-1" style="height:4px"><div class="progress-bar" style="width:${c.score}%"></div></div>
        <div>${esc(c.reason)}</div>
        <div class="small text-muted mt-1">${(c.machine_types || []).map(m => `<span class="badge badge-light">${esc(m)}</span>`).join(" ")}</div>
        ${c.image ? imageNote(c.image) : ""}
      </div></div></label>`).join("");
  document.querySelectorAll('input[name="tpl"]').forEach(x => x.onchange = () => { pick = x.value; loadBlueprint(pick).catch(() => {}); });
  qs("#wizActions").style.display = r.candidates.length ? "" : "none";
}

qs("#continueBtn").onclick = async () => {
  qs("#continueBtn").disabled = true;
  try {
    await loadBlueprint(pick);
    S = {bp: pick, overrides: {}, changes: emptyChanges(), accepted: 0};
    validation = null;
    const dn = vars(pick).find(v => v.name === "deployment_name");
    if (dn && !same(parseDefault(dn), clusterName)) S.overrides.deployment_name = clusterName;
    if (netChoice) {  // start in the chosen subnet's region
      if (!ZONES) ZONES = (await api("zones", {credential_id: credId})).regions;
      const zone = vars(pick).find(v => v.name === "zone" && v.global), region = vars(pick).find(v => v.name === "region" && v.global);
      const zones = ZONES[netChoice.region] || [];
      if (zone && zones.length && regionOf(String(current(pick, S.overrides, zone) || "")) !== netChoice.region) S.overrides.zone = zones[0];
      if (region && current(pick, S.overrides, region) !== netChoice.region) S.overrides.region = netChoice.region;
    }
    record("start", `Template ${pick}`);
    qs("#wizard").style.display = "none"; qs("#builder").style.display = "";
    renderChat(); renderBuilder();
    tailor();
  } catch (err) { showError(err); }
  qs("#continueBtn").disabled = false;
};
