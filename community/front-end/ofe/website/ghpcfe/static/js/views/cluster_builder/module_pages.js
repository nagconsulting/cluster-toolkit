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

// Cluster Builder: Builder: the module pages.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- builder: module pages ---------------- */
// Where a module input's value comes from: own (added module) | var | literal | added (promoted) | unset
function inputState(id, inp) {
  const own = addedMod(id);
  if (own) return inp.name in own.settings ? {kind: "own", value: own.settings[inp.name]} : {kind: "unset", own: true};
  const prom = S.changes.promoted.find(p => p.module === id && p.input === inp.name);
  if (prom) return {kind: "added", var: prom.var};
  const set = settingsOf(id), raw = set[inp.name];
  const ref = typeof raw === "string" && raw.match(/^\$\(vars\.([a-z0-9_]+)\)$/);
  if (ref) return {kind: "var", var: ref[1]};
  if (inp.name in set) return {kind: "literal", value: raw};
  return {kind: "unset"};
}

function inputRequired(id, inp) {
  const st = inputState(id, inp), m = modsOf().find(x => x.id === id);
  if (st.var) return isRequiredVar(vars(S.bp).find(x => x.name === st.var));
  return !!(m && m.added && (moduleMeta(m.source).required || []).includes(inp.name));
}
function moduleField(id, inp) {
  const st = inputState(id, inp), c = inputConstraints(inp, null), required = inputRequired(id, inp);
  const v = st.var ? vars(S.bp).find(x => x.name === st.var) : null;
  const value = v ? current(S.bp, S.overrides, v) : (st.kind === "literal" || st.kind === "own") ? st.value : (st.own ? "" : parseDefault(inp));
  const varGroup = st.var && groupOfVar(st.var);
  const setBy = {
    own: "set in this added module",
    var: varGroup === "mod:" + id ? `set through blueprint variable <code>${esc(st.var)}</code> in <code>deployment.yaml</code>`
      : `set by blueprint variable <a href="#" data-g="${esc(varGroup)}"><code>${esc(st.var)}</code></a>`,
    added: `added as variable <code>${esc(st.var)}</code> (template copy)`,
    literal: "hardcoded in the blueprint; editing it creates a template copy",
    unset: st.own ? "not set; the module default applies" : "not set; the module default applies. Setting it creates a template copy",
  }[st.kind];
  return field({
    id: `m-${id}-${inp.name}`, label: label(inp.name), type: inp.type, value, def: showDefault(inp), c, required,
    changed: (v && v.name in S.overrides) || st.kind === "added" || st.kind === "own",
    // A var-backed input takes its value from the blueprint var, so the module default would mislead.
    placeholder: v ? "" : undefined,
    attrs: `data-mod="${esc(id)}" data-input="${esc(inp.name)}" data-t="${esc(inp.type)}"`,
    details: detailsHtml({name: inp.name, type: inp.type, def: inp.default, description: inp.description, setBy, c,
      extra: (st.own || st.kind === "unset" && addedMod(id)) && inp.type === "string" ? "<div>Type <code>$name</code> to use a variable, e.g. <code>$deployment_name-scratch</code>.</div>" : ""}),
    warning: inp.deprecated ? `Deprecated: ${inp.deprecated}` : "",
  });
}

function moduleHtml(id) {
  const m = modsOf().find(x => x.id === id);
  const meta = m && moduleMeta(m.source);
  const removeBtn = `<button class="btn btn-sm btn-outline-danger ml-auto" data-remove="${esc(id)}">Remove module</button>`;
  const head = `<div class="d-flex align-items-center"><h5 class="mb-0">${esc(id)}${m && m.added ? ' <span class="badge badge-info">added</span>' : ""}</h5>${removeBtn}</div>
    <div class="small text-muted mb-3"><code>${esc(m.source)}</code> · uses ${m.use.map(u => `<span class="badge badge-light">${esc(u)}</span>`).join(" ") || "nothing"}
    · used by ${modsOf().filter(x => x.use.includes(id)).map(x => `<span class="badge badge-light">${esc(x.id)}</span>`).join(" ") || "nothing"}</div>`;
  if (!meta) return head + `<p class="text-muted">No local metadata for <code>${esc(m.source)}</code>; see it in the YAML tab.</p>`;
  const configured = [], available = [];
  let hidden = 0;
  for (const inp of meta.inputs) {
    const st = inputState(id, inp);
    if (st.kind !== "unset" || inputRequired(id, inp)) configured.push(inp);  // shown even if deprecated: the blueprint uses it
    else if (inp.deprecated) hidden++;                                  // never offered for new use
    else available.push(inp);
  }
  const shown = available.filter(i => !modFilter || i.name.includes(modFilter) || (i.description || "").toLowerCase().includes(modFilter));
  const auto = meta.auto || [];
  return head + `${hasChanges(S.changes) ? `<div class="alert alert-info small py-2">Changes to modules are saved in a copy, <code>${esc(copyName(S.bp))}</code> (<code>ai_assisted: true</code>); <code>${esc(S.bp)}</code> is never modified.</div>` : ""}
    <h6 class="text-muted text-uppercase small">${m.added ? "Required and set inputs" : "Configured in this blueprint"} (${configured.length})</h6>
    ${configured.map(i => moduleField(id, i)).join("") || '<p class="small text-muted">Nothing set explicitly.</p>'}
    ${embeddedVarsHtml(id)}
    ${auto.length ? `<details class="small text-muted mb-3"><summary>Set automatically (${auto.reduce((n, a) => n + a.inputs.length, 0)})</summary>
      <ul class="mb-0">${auto.map(a => `<li><code>${a.inputs.map(esc).join(", ")}</code> ${esc(a.source)}</li>`).join("")}</ul></details>` : ""}
    <hr>
    <div class="d-flex align-items-center mb-2">
      <h6 class="text-muted text-uppercase small mb-0 mr-3">Available inputs (${available.length})</h6>
      <input class="form-control form-control-sm" id="modFilter" placeholder="Filter" value="${esc(modFilter)}" style="max-width:220px">
    </div>
    <p class="small text-muted">Not set; the module default applies.${m.added ? "" : " Setting one adds it to a template copy."}${hidden ? ` ${hidden} deprecated input(s) hidden.` : ""}</p>
    ${shown.map(i => moduleField(id, i)).join("")}
    <small class="text-muted">${meta.inputs.length} inputs and their rules from <code>gcluster explain ${esc(m.source)} -f json</code>.</small>`;
}

// Vars this module uses inside a setting rather than as a whole input value,
// e.g. sysnet.subnetworks[0].subnet_name: $(vars.subnetwork_name_system).
function embeddedVarsHtml(id) {
  const items = vars(S.bp).filter(v => !v.global && groupOfVar(v.name) === "mod:" + id)
    .map(v => [v, usesOf(v.name).find(u => u.module === id && !u.exact)]).filter(([, u]) => u);
  return items.length ? `<h6 class="text-muted text-uppercase small mt-3">Variables used in this module's settings (${items.length})</h6>
    ${items.map(([v]) => varField(v)).join("")}` : "";
}

function addModuleHtml() {
  if (!MODULES) {
    api("modules", {}).then(r => { MODULES = r.modules; renderBuilder(); }).catch(showError);
    return '<p class="text-muted">Loading modules…</p>';
  }
  const mods = modsOf(), here = new Set(mods.map(m => m.source));
  if (!addSource) {
    // Tabs from Cluster Toolkit's own layout: modules/<category>/<name>.
    const catOf = src => src.split("/").slice(-2, -1)[0];
    const counts = {};
    MODULES.forEach(x => counts[catOf(x.source)] = (counts[catOf(x.source)] || 0) + 1);
    const cats = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
    const list = MODULES.filter(x => (!addCat || catOf(x.source) === addCat) && (!addFilter || x.source.includes(addFilter)));
    return `<h5>Add a module</h5><p class="small text-muted">Modules from the catalog's <code>module_wiring</code>. Adding one makes the cluster use a template copy (<code>ai_assisted: true</code>).
        <b>Ask Gemini</b> explains a module and how it would fit this configuration, without changing anything.</p>
      <ul class="nav nav-pills small mb-2 flex-wrap">${["", ...cats].map(c => `<li class="nav-item"><a href="#" class="nav-link py-1 px-2 ${c === addCat ? "active" : ""}" data-cat="${esc(c)}">${
        c ? esc(c) : "All"} <span class="badge badge-light">${c ? counts[c] : MODULES.length}</span></a></li>`).join("")}</ul>
      <input class="form-control form-control-sm mb-2" id="addFilter" placeholder="Filter, e.g. lustre, filestore, nodeset" value="${esc(addFilter)}">
      <div class="list-group list-group-flush small" style="max-height:50vh;overflow:auto">${list.map(x =>
        `<div class="list-group-item d-flex justify-content-between align-items-start">
          <a href="#" class="flex-grow-1 text-body" data-pick="${esc(x.source)}"><code>${esc(x.source)}</code>${here.has(x.source) ? ' <span class="badge badge-light">in blueprint</span>' : ""}
            ${(x.required_inputs || []).length ? `<div class="text-muted">requires ${x.required_inputs.map(esc).join(", ")}</div>` : ""}</a>
          <button type="button" class="btn btn-sm btn-outline-info ml-2 text-nowrap" data-askmod="${esc(x.source)}">Ask Gemini</button></div>`).join("") ||
        '<div class="list-group-item text-muted">No modules match.</div>'}</div>`;
  }
  const meta = MM[addSource] || moduleMeta(addSource);
  if (!meta) {
    api("module", {source: addSource}).then(r => { MM[addSource] = r; renderBuilder(); }).catch(err => { addSource = null; showError(err); });
    return '<p class="text-muted">Loading module…</p>';
  }
  if (meta.deprecated) return `<div class="alert alert-warning">${esc(addSource)} is deprecated: ${esc(meta.deprecated)}</div><a href="#" data-pick="">Back</a>`;
  const base = addSource.split("/").pop().replace(/-/g, "_");
  let id = base, n = 2;
  while (mods.some(m => m.id === id)) id = `${base}_${n++}`;
  const recUse = new Set(meta.recommended_use || []), consumers = new Set(meta.consumed_by || []);
  const box = (name, m, checked) => `<div class="form-check"><input class="form-check-input" type="checkbox" name="${name}" value="${esc(m.id)}" id="${name}-${esc(m.id)}" ${checked ? "checked" : ""}>
    <label class="form-check-label small" for="${name}-${esc(m.id)}"><code>${esc(m.id)}</code> <span class="text-muted">${esc(m.source)}</span></label></div>`;
  return `<h5>Add <code>${esc(addSource)}</code> <button type="button" class="btn btn-sm btn-outline-info ml-2" data-askmod="${esc(addSource)}">Ask Gemini</button></h5>
    ${meta.required.length ? `<p class="small">Required inputs: ${meta.required.map(r => `<code>${esc(r)}</code>`).join(", ")} (set them on the module page after adding).</p>` : ""}
    <div class="form-group"><label for="newId">Module id</label><input class="form-control" id="newId" value="${esc(id)}" pattern="[a-z][a-z0-9_\-]*"></div>
    <div class="row"><div class="col-md-6"><label>Uses <small class="text-muted">(provides its inputs)</small></label>${mods.map(m => box("use", m, recUse.has(m.source))).join("")}</div>
    <div class="col-md-6"><label>Used by <small class="text-muted">(consumes it)</small></label>${mods.map(m => box("usedby", m, consumers.has(m.source))).join("")}</div></div>
    <small class="text-muted d-block mb-2">Pre-ticked from <code>recommended_use</code> and <code>consumed_by</code> in the catalog.</small>
    <button class="btn btn-primary btn-sm" id="addConfirm">Add module</button> <a href="#" class="btn btn-link btn-sm" data-pick="">Back</a>`;
}

function promote(id, input, literal) {
  const m = templateMods().find(x => x.id === id), inp = inputMeta(m.source, input);
  let name = `${id}_${input}`.replace(/[^a-z0-9_]/g, "_");
  while (vars(S.bp).some(v => v.name === name)) name += "_2";
  const def = literal ? settingsOf(id)[input] : parseDefault(inp);
  S.changes.promoted.push({module: id, input, var: name, type: inp.type, def});
  return name;
}

function removeModule(id) {
  if (addedMod(id)) {
    S.changes.add_modules = S.changes.add_modules.filter(a => a.id !== id);
    S.changes.add_modules.forEach(a => { a.use = a.use.filter(u => u !== id); a.used_by = a.used_by.filter(u => u !== id); });
  } else {
    S.changes.remove_modules.push(id);
    for (const p of S.changes.promoted.filter(p => p.module === id)) delete S.overrides[p.var];
    for (const v of droppedVars(S.bp, S.changes)) delete S.overrides[v];
    S.changes.promoted = S.changes.promoted.filter(p => p.module !== id);
    S.changes.add_modules.forEach(a => { a.use = a.use.filter(u => u !== id); a.used_by = a.used_by.filter(u => u !== id); });
  }
  group = "basics"; changed(); renderBuilder();
}
