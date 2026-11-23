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

// Cluster Builder: Validate and the Create dialog.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- validate / create ---------------- */
qs("#validateBtn").onclick = async () => {
  const btn = qs("#validateBtn"); btn.disabled = true; btn.textContent = "Validating…";
  try {
    const r = await api("validate", {blueprint: S.bp, overrides: S.overrides, changes: S.changes, credential_id: credId});
    (r.dropped || []).forEach(k => delete S.overrides[k]);  // e.g. a value equal to the default
    validation = {...r, key: stateKey()};
    renderBuilder();
  } catch (err) { showError(err); }
  btn.disabled = false; btn.textContent = "Validate";
};
qs("#createBtn").onclick = () => {
  const ok = validation && validation.valid && validation.deployment_yaml;
  const missing = missingValues();
  qs("#createTitle").textContent = `Create cluster from ${bpFile().split("/").pop()}?`;
  qs("#createBody").innerHTML = `<dl class="row small mb-0">
    <dt class="col-sm-4">Blueprint</dt><dd class="col-sm-8"><code>${esc(bpFile())}</code>${hasChanges(S.changes) ? ` (copy of <code>${esc(S.bp)}</code>)` : ""}</dd>
    <dt class="col-sm-4">Project</dt><dd class="col-sm-8">${esc(credential().project || "")}</dd>
    <dt class="col-sm-4">Module changes</dt><dd class="col-sm-8">${changeSummary(S.changes) || "None"}</dd>
    <dt class="col-sm-4">Overrides</dt><dd class="col-sm-8"><pre class="bg-light border rounded p-2 mb-0">${esc(depYaml(S.overrides))}</pre></dd>
    <dt class="col-sm-4">Validation</dt><dd class="col-sm-8">${ok ? validBadge(true) : missing.length ? `<span class="badge badge-warning">fill in ${esc(missing.join(", "))}</span>` : '<span class="badge badge-warning">click Validate first</span>'}</dd>
    <dt class="col-sm-4">Provenance</dt><dd class="col-sm-8"><span class="badge badge-info">ai_assisted: true</span> · ${S.accepted} Gemini change(s) accepted</dd>
  </dl>
  <p class="small text-muted mt-3 mb-2">Deploying from the Cluster Builder isn't available yet. Download the validated files to deploy with <code>gcluster deploy</code>.</p>
  ${ok ? `<button class="btn btn-sm btn-outline-secondary mr-2" id="dlDep">deployment.yaml</button><button class="btn btn-sm btn-outline-secondary" id="dlBp">${esc(copyName(S.bp).split("/").pop())}</button>` : ""}`;
  if (ok) {
    qs("#dlDep").onclick = () => download("deployment.yaml", validation.deployment_yaml);
    qs("#dlBp").onclick = () => download(copyName(S.bp).split("/").pop(), validation.blueprint_yaml);
  }
  jQuery("#createModal").modal("show");
};
