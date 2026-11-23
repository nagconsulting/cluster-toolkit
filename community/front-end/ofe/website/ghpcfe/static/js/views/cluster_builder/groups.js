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

// Cluster Builder: Builder: the variable groups.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- builder: variable groups ---------------- */
// Variable groups. Vars used by a single module are edited on that module's page instead.
function groups() {
  const all = vars(S.bp), by = k => all.filter(v => groupOfVar(v.name) === k);
  return [["basics", "Cluster basics", by("basics")], ["shared", "Shared variables", by("shared")],
          ["other", "Other variables", by("other")], ["added", "Added inputs", by("added")]]
    .filter(([k, , vs]) => k === "basics" || vs.length);
}

const regionOf = z => z.replace(/-[a-z]$/, "");
function zoneField(v) {
  if (!ZONES) {
    api("zones", {credential_id: credId}).then(r => { ZONES = r.regions; renderBuilder(); }).catch(err => { ZONES = {}; showError(err); });
    return '<div class="form-group"><label>Zone</label><p class="text-muted small">Loading zones…</p></div>';
  }
  const cur = current(S.bp, S.overrides, v), regions = Object.keys(ZONES);
  if (regionPref) regions.sort((a, b) => (b === regionPref) - (a === regionPref));
  const required = isRequiredVar(v) && !(v.name in S.overrides);
  return `<div class="form-group"><label for="v-zone">Zone</label>${required ? ' <span class="text-danger">*</span>' : ""}
    <select class="form-control ${required ? "is-invalid" : ""}" id="v-zone" data-zone="1">${cur ? "" : '<option value="">Choose a zone</option>'}
    ${regions.map(r => `<optgroup label="${esc(r)}">${ZONES[r].map(z => `<option ${z === cur ? "selected" : ""}>${esc(z)}</option>`).join("")}</optgroup>`).join("")}</select>
    <small class="form-text text-muted">Zones available to the credential ${esc(credential().name || "")}. Sets <code>zone</code> and <code>region</code>; check the blueprint's machine types are offered there.</small></div>`;
}
// A value for a name-like input, from the cluster name: its longest prefix
// (other characters as "-") that the input's pattern accepts, or null.
function fitName(name, pattern) {
  let re;
  try { re = new RegExp(pattern); } catch (e) { return null; }
  const base = String(name || "").toLowerCase().replace(/[^a-z0-9-]/g, "-");
  for (let n = base.length; n > 0; n--) {
    const s = base.slice(0, n).replace(/-+$/, "");
    if (s && re.test(s)) return s;
  }
  return null;
}

// A var is labelled after the module input it sets as a whole (what it means
// to this cluster); a var only embedded in a larger value (e.g. one entry of
// configure_ssh_host_patterns, a script's args) keeps its own name, with
// where it is used shown under the field.
function varField(v) {
  const use = usesOf(v.name).find(u => u.exact) || null;
  if (v.name === "project_id")
    return `<div class="form-group"><label>Project</label><input class="form-control" value="${esc(credential().project || "")}" disabled><small class="form-text text-muted">From the credential ${esc(credential().name || "")}.</small></div>`;
  if (v.global && v.name === "zone") return zoneField(v);
  if (v.global && v.name === "region" && vars(S.bp).some(x => x.name === "zone" && x.global))
    return `<div class="form-group"><label>Region</label><input class="form-control" value="${esc(current(S.bp, S.overrides, v) ?? "")}" disabled><small class="form-text text-muted">Derived from the zone.</small></div>`;
  const c = varConstraints(v.name), w = wiring()[v.name] || [];
  // What the var is for: the description of the first module input it feeds (gcluster explain).
  const about = (w.map(x => inputMeta(x.source, x.input)).find(i => i && i.description) || {}).description || "";
  const expr = v.type === "expression";
  const required = isRequiredVar(v), generated = genSuffix(v.name) !== undefined;
  // Named after where the blueprint uses it, e.g. subnetworks[0].subnet_name -> "Subnet name".
  const fieldLabel = v.global && v.name === "deployment_name" ? "Cluster name" : label(use ? use.input : v.name);
  const embedded = use || v.global ? [] : usesOf(v.name);
  const suggest = required && !(v.name in S.overrides) && v.type === "string" && c.pattern ? fitName(clusterName, c.pattern) : null;
  // A module input of the same name this var could also set (BD.unwired, from the blueprint and explain).
  const linkTo = (((BD[S.bp] || {}).unwired || {})[v.name] || [])
    .filter(t => !isRemoved(t.module) && !S.changes.promoted.some(p => p.module === t.module && p.input === t.input));
  const offer = linkTo.map(t => {
    const src = (templateMods().find(m => m.id === t.module) || {}).source, inp = src && inputMeta(src, t.input);
    const fitted = !(v.name in S.overrides) && inp && (inp.constraints || {}).pattern ? fitName(clusterName, inp.constraints.pattern) : null;
    return `<div class="alert alert-info small py-1 px-2 mt-1 mb-0"><code>${esc(t.module)}</code> sets its own <code>${esc(t.input)}</code>
      because this blueprint doesn't pass this variable to it, so the two can differ.
      <button type="button" class="btn btn-sm btn-outline-primary ml-1" data-link="${esc(t.module)}|${esc(t.input)}|${esc(v.name)}"
        data-value="${esc(fitted || "")}">Pass it to ${esc(t.module)}${fitted ? ` and use “${esc(fitted)}”` : ""}</button></div>`;
  }).join("");
  return field({
    id: "v-" + v.name, label: fieldLabel, type: v.type, value: current(S.bp, S.overrides, v), suggest, name: v.name,
    def: expr ? exprDisplay(v.default) : v.default,
    placeholder: expr ? exprDisplay(v.default) : generated ? genName(v.name) : showDefault(v),
    c, required, changed: v.name in S.overrides || !!v.promoted,
    hint: expr ? `Derived from other variables by default; leave empty to keep ${exprDisplay(v.default)}.`
      : generated && !(v.name in S.overrides) ? `Named from the cluster name: ${genName(v.name)}. Type a name to use your own.`
      : (required ? about : ""),
    usedIn: embedded.map(u => `${u.module}.${u.path}`),
    offer: offer + S.changes.promoted.filter(p => p.link && p.var === v.name).map(p =>
      `<small class="form-text text-muted">Also passed to <code>${esc(p.module)}.${esc(p.input)}</code>.
        <a href="#" data-unlink="${esc(p.module)}|${esc(p.input)}">Stop passing it</a></small>`).join(""),
    attrs: `data-n="${esc(v.name)}" data-t="${expr ? "string" : esc(v.type)}"`,
    details: detailsHtml({name: v.name, type: v.type, def: expr ? exprDisplay(v.default) : v.default, c,
      description: required ? "" : about,
      setBy: v.promoted ? `added from <code>${esc(v.promoted.module)}.${esc(v.promoted.input)}</code>` : v.global ? "gcluster global variable" : "blueprint variable",
      sets: usesOf(v.name).map(u => `<code>${esc(u.module)}.${esc(u.path)}</code>`).join(", "),
      extra: v.promoted ? `<div><a href="#" data-rm="${esc(v.name)}">Remove this added input</a></div>` : ""}),
  });
}
