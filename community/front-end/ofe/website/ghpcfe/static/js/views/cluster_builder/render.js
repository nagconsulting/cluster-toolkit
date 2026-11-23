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

// Cluster Builder: Builder: rendering the tabs (configuration, YAML, changes).
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- builder: render ---------------- */
function renderBuilder() {
  if (validation && validation.key !== stateKey()) validation = null;
  schedulePreview();
  qs("#bpChip").textContent = bpFile();
  qs("#equiv").innerHTML = `Equivalent: <code>gcluster expand ${esc(bpFile())} -d deployment.yaml</code>`;
  renderCost(); renderDefinition();
  document.querySelectorAll("#tabs .nav-link").forEach(a => a.classList.toggle("active", a.dataset.tab === tab));
  const body = qs("#tabBody");
  const copyPending = textFor(S) === undefined;
  if (tab === "yaml") {
    const name = bpFile().split("/").pop();
    const files = [["blueprint", name], ["defaults", "Defaults"], ["dep", "deployment.yaml"], ["expanded", "expanded.yaml"]];
    let text, note, fileName = null, html = null;
    if (yamlFile === "defaults") {
      html = defaultsHtml();
      note = `The blueprint's <code>vars:</code>: each default, with the template's notes. ` +
        "The downloaded blueprint keeps these as its defaults; values in deployment.yaml replace them.";
    } else if (yamlFile === "dep") {
      text = deploymentText(); fileName = "deployment.yaml";
      note = "Every value for this cluster: yours, plus the cluster name, location and any values OFE fills in. Passed to gcluster with <code>-d</code>.";
    } else if (yamlFile === "expanded") {
      text = validation && validation.expanded;
      note = "Output of <code>gcluster expand</code> for exactly these values.";
      if (text) fileName = "expanded.yaml"; else text = "# Click Validate to run gcluster expand and see the expanded blueprint.";
    } else {
      text = copyPending ? "# Building the template copy…" : textFor(S).view;
      if (!copyPending) fileName = copyName(S.bp).split("/").pop();
      note = (hasChanges(S.changes) ? `Copy of <code>${esc(S.bp)}</code> with your module changes. ` : "") +
        "Shown without its <code>vars:</code> (see Defaults; your values are in deployment.yaml). " +
        `The download includes them, without the example's comments, and is marked <code>ai_assisted: true</code>. <code>${esc(S.bp)}</code> itself is never modified.`;
    }
    const dlText = yamlFile === "blueprint" && !copyPending ? textFor(S).clean : text;
    body.innerHTML = `<div class="d-flex align-items-center mb-2"><div class="btn-group btn-group-sm">${files.map(([k, l]) =>
        `<button class="btn btn-outline-secondary ${yamlFile === k ? "active" : ""}" data-f="${k}">${esc(l)}</button>`).join("")}</div>
        ${fileName ? `<button class="btn btn-sm btn-link ml-auto" id="dlBtn">Download</button>` : ""}</div>
      <p class="small text-muted">${note}</p>${html != null ? html : `<pre class="bg-light border rounded p-2 mb-0 small" style="max-height:60vh">${esc(text)}</pre>`}`;
    body.querySelectorAll("[data-f]").forEach(b => b.onclick = () => { yamlFile = b.dataset.f; renderBuilder(); });
    if (fileName) qs("#dlBtn").onclick = () => download(fileName, dlText);
  } else if (tab === "diff") {
    body.innerHTML = historyHtml();
    body.querySelectorAll("[data-step]").forEach(a => a.onclick = e => { e.preventDefault(); histSel = +a.dataset.step; renderBuilder(); });
    const first = body.querySelector(".cb-diff .a, .cb-diff .d");
    if (first) first.parentElement.scrollTop = first.offsetTop - 40;
  } else if (tab === "wiring") {
    const mods = modsOf();
    body.innerHTML = `<p class="small text-muted">Module connections (<code>use:</code>).</p>
      <table class="table table-sm small mb-0"><thead><tr><th>Module</th><th>Source</th><th>Uses</th><th>Used by</th></tr></thead><tbody>${mods.map(m =>
        `<tr><td><code>${esc(m.id)}</code>${m.added ? ' <span class="badge badge-info">added</span>' : ""}</td><td class="text-muted">${esc(m.source)}</td><td>${m.use.map(u => `<span class="badge badge-light">${esc(u)}</span>`).join(" ") || "—"}</td><td>${mods.filter(x => x.use.includes(m.id)).map(x => `<span class="badge badge-light">${esc(x.id)}</span>`).join(" ") || "—"}</td></tr>`).join("")}
        ${S.changes.remove_modules.filter(id => !isReplaced(id)).map(id => `<tr class="cb-removed"><td><code>${esc(id)}</code> <span class="badge badge-danger">removed</span></td><td colspan="3"></td></tr>`).join("")}</tbody></table>`;
  } else {
    const gs = groups(), mods = modsOf(), missing = new Set(missingValues());
    if (!gs.find(g => g[0] === group) && group !== "add" && !(group.startsWith("mod:") && mods.some(m => "mod:" + m.id === group))) group = "basics";
    const cur = gs.find(g => g[0] === group);
    const navItem = (k, l, nChanged, nMissing, extra = "") => `<a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center ${k === group ? "active" : ""} ${extra}" data-g="${esc(k)}">${l}<span>${nMissing ? `<span class="badge badge-danger" title="Required values missing">${nMissing}</span> ` : ""}${nChanged ? `<span class="badge badge-${k === group ? "light" : "primary"}">${nChanged}</span>` : ""}</span></a>`;
    body.innerHTML = `<div class="row"><div class="col-md-4"><div class="list-group list-group-flush small">${gs.map(([k, l, vs]) =>
        navItem(k, esc(l), vs.filter(v => v.name in S.overrides).length, vs.filter(v => missing.has(v.name)).length,
          k !== group && S._flash && vs.some(v => S._flash.includes(v.name)) ? "cb-flash" : "")).join("")}
      <div class="list-group-item small font-weight-bold text-muted bg-light">Modules (${mods.length})</div>
      ${mods.map(m => navItem("mod:" + m.id, `<code class="${"mod:" + m.id === group ? "text-white" : ""}">${esc(m.id)}</code>${m.added ? " +" : ""}`, 0,
          [...missing].filter(x => x.startsWith(m.id + ".") || groupOfVar(x) === "mod:" + m.id).length, "py-1")).join("")}
      ${S.changes.remove_modules.map(id => `<div class="list-group-item py-1 d-flex justify-content-between"><code class="cb-removed">${esc(id)}</code><a href="#" data-restore="${esc(id)}">restore</a></div>`).join("")}
      <a href="#" class="list-group-item list-group-item-action py-1 ${group === "add" ? "active" : ""}" data-g="add">+ Add module</a>
      </div></div>
      <div class="col-md-8">${cur ? `<h5>${esc(cur[1])}</h5>
        ${group === "added" ? `<div class="alert alert-info small">These inputs aren't exposed by <code>${esc(S.bp)}</code>, so the cluster uses a copy, <code>${esc(copyName(S.bp))}</code> (<code>ai_assisted: true</code>). Each one is a variable whose default is the module default (or the value the template hardcoded); your value goes in <code>deployment.yaml</code>.</div>` : ""}
        ${cur[2].map(v => varField(v)).join("")}
        <small class="text-muted">Fields generated from <code>gcluster explain ${esc(S.bp)} -f json</code>.</small>`
        : group === "add" ? addModuleHtml() : moduleHtml(group.slice(4))}</div></div>`;
    wireConfigure(body);
    S._flash = null;
  }
  const missing = missingValues();
  if (validation || missing.length) {
    qs("#term").style.display = "";
    qs("#term").innerHTML = (missing.length ? `<span class="text-warning">Required values missing: ${esc(missing.join(", "))}</span>\n` : "") +
      (validation ? `<span class="text-info">$ gcluster expand ${esc(bpFile())} -d deployment.yaml</span>${validation.from ? ` <span class="text-muted">(run by ${esc(validation.from)})</span>` : ""}\n${esc(validation.output)}` : "");
  } else qs("#term").style.display = "none";
}

// Changes tab: each step (start, Gemini proposals, your edits) as a diff of
// the entire blueprint, effective values included, changes highlighted.
function overrideChanges(from, to) {
  const keys = [...new Set([...Object.keys(from.overrides), ...Object.keys(to.overrides)])];
  return keys.filter(k => !same(from.overrides[k], to.overrides[k])).map(k =>
    `<code>${esc(k)}</code>: ${k in from.overrides ? esc(fmt(from.overrides[k])) : "<i>default</i>"} → ${k in to.overrides ? `<b>${esc(fmt(to.overrides[k]))}</b>` : "<i>default</i>"}`);
}
function historyHtml() {
  const pending = previewOpt && turns[previewOpt.turn] && turns[previewOpt.turn].state === "pending"
    ? optionConfig(turns[previewOpt.turn].result.options.find(o => o.id === previewOpt.id)) : null;
  if (histSel === -2 && !pending) histSel = HIST.length - 1;
  if ((histSel < 0 && histSel !== -2) || histSel >= HIST.length) histSel = HIST.length - 1;
  const steps = HIST.map((h, i) => ({i, h})).slice(1);
  let from, to;
  if (histSel === -2) { from = snapshot(); to = {bp: pending.blueprint, overrides: pending.overrides, changes: pending.changes}; }
  else { from = histSel === 0 ? HIST[0].state : HIST[histSel - 1].state; to = HIST[histSel === 0 ? HIST.length - 1 : histSel].state; }
  [from, to].forEach(st => ensurePreview(st));
  const a = viewText(from), b = viewText(to);
  const nav = `<div class="list-group list-group-flush small">
    ${pending ? `<a href="#" class="list-group-item list-group-item-action ${histSel === -2 ? "active" : ""}" data-step="-2"><span class="badge badge-warning mr-1">Proposed</span>${esc(pending ? pending.title : "")}: not applied yet</a>` : ""}
    <a href="#" class="list-group-item list-group-item-action ${histSel === 0 ? "active" : ""}" data-step="0">All changes since the template</a>
    ${steps.map(({i, h}) => `<a href="#" class="list-group-item list-group-item-action ${histSel === i ? "active" : ""}" data-step="${i}">
      <span class="badge badge-${h.by === "gemini" ? "info" : "secondary"} mr-1">${h.by === "gemini" ? "Gemini" : "You"}</span>${esc(h.label.length > 60 ? h.label.slice(0, 57) + "…" : h.label)}</a>`).join("")
      || '<div class="list-group-item text-muted">No changes yet.</div>'}</div>`;
  let main;
  if (a === undefined || b === undefined) main = '<p class="text-muted">Building the template copy…</p>';
  else {
    const d = lineDiff(a.replace(/^(#.*\n)+\s*/, ""), b.replace(/^(#.*\n)+\s*/, ""));
    const ov = overrideChanges(from, to), mods = changeSummary(diffChanges(from.changes, to.changes));
    main = `${from.bp !== to.bp ? `<p class="small">Template switched: <code>${esc(from.bp)}</code> → <code>${esc(to.bp)}</code></p>` : ""}
      ${mods}${ov.length ? `<ul class="list-unstyled small mb-2">${ov.map(l => `<li>${l}</li>`).join("")}</ul>` : ""}
      ${d.some(([t]) => t !== " ") ? "" : '<p class="small text-muted">No differences in this step.</p>'}
      <div style="max-height:65vh;overflow:auto">${diffHtml(d)}</div>
      <small class="text-muted">Entire blueprint (values are listed above and kept in deployment.yaml); highlighted lines ${histSel === -2 ? "would change if you accept this option (in the Gemini panel)" : "changed in this step"}.</small>`;
  }
  return `<div class="row"><div class="col-md-4">${nav}</div><div class="col-md-8">${main}</div></div>`;
}
// Module-level changes made between two change sets (for the step summary).
function diffChanges(a, b) {
  const pk = p => `${p.module}.${p.input}`;
  return {
    add_modules: b.add_modules.filter(x => !a.add_modules.some(y => y.id === x.id)),
    remove_modules: b.remove_modules.filter(x => !a.remove_modules.includes(x)),
    promoted: b.promoted.filter(x => !a.promoted.some(y => pk(y) === pk(x))),
    settings: (b.settings || []).filter(x => !(a.settings || []).some(y => pk(y) === pk(x) && same(y.value, x.value))),
  };
}

function changeSummary(ch) {
  const lines = [
    ...ch.add_modules.map(a => ch.remove_modules.includes(a.id) ? `~ module <code>${esc(a.id)}</code> replaced by ${esc(a.source)}`
      : `+ module <code>${esc(a.id)}</code> (${esc(a.source)})${a.used_by.length ? `, used by ${a.used_by.map(esc).join(", ")}` : ""}`),
    ...ch.remove_modules.filter(id => !ch.add_modules.some(a => a.id === id)).map(id => `− module <code>${esc(id)}</code>`),
    ...(ch.settings || []).map(x => `~ input <code>${esc(x.module)}.${esc(x.input)}</code> set to <code>${esc(JSON.stringify(x.value))}</code>`),
    ...ch.promoted.map(p => p.link ? `~ input <code>${esc(p.module)}.${esc(p.input)}</code> ← variable <code>${esc(p.var)}</code> (passed through)`
      : `~ input <code>${esc(p.module)}.${esc(p.input)}</code> → variable <code>${esc(p.var)}</code>${p.required ? " (you fill it in)" : ""}`),
  ];
  return lines.length ? `<ul class="list-unstyled small mb-2">${lines.map(l => `<li>${l}</li>`).join("")}</ul>` : "";
}

function wireConfigure(body) {
  body.querySelectorAll("[data-g]").forEach(a => a.onclick = e => { e.preventDefault(); group = a.dataset.g; if (group === "add") addSource = null; renderBuilder(); });
  body.querySelectorAll("[data-det]").forEach(a => a.onclick = e => {
    e.preventDefault();
    const id = a.dataset.det, d = document.getElementById("det-" + id);
    openDet.has(id) ? openDet.delete(id) : openDet.add(id);
    d.classList.toggle("d-none"); a.textContent = openDet.has(id) ? "hide details" : "details";
  });
  body.querySelectorAll("[data-n]").forEach(el => {
    const v = vars(S.bp).find(x => x.name === el.dataset.n);
    el.onchange = () => setVar(el); el.oninput = () => liveCheck(el, varConstraints(el.dataset.n), isRequiredVar(v));
  });
  body.querySelectorAll("[data-suggest]").forEach(b => b.onclick = () => { applyVar(b.dataset.suggest, b.dataset.value); renderBuilder(); });
  body.querySelectorAll("[data-unlink]").forEach(a => a.onclick = e => {
    e.preventDefault();
    const [module, input] = a.dataset.unlink.split("|");
    S.changes.promoted = S.changes.promoted.filter(p => !(p.link && p.module === module && p.input === input));
    changed(); renderBuilder();
  });
  body.querySelectorAll("[data-link]").forEach(b => b.onclick = () => {
    const [module, input, v] = b.dataset.link.split("|");
    const src = templateMods().find(m => m.id === module).source;
    S.changes.promoted.push({module, input, var: v, type: inputMeta(src, input).type, link: true});
    if (b.dataset.value) S.overrides[v] = b.dataset.value;
    changed(); renderBuilder();
  });
  const zs = body.querySelector("[data-zone]");
  if (zs) zs.onchange = () => {
    applyVar("zone", zs.value);
    if (vars(S.bp).some(x => x.name === "region")) applyVar("region", regionOf(zs.value));
    renderBuilder();
  };
  body.querySelectorAll("[data-mod]").forEach(el => {
    const m = modsOf().find(x => x.id === el.dataset.mod), inp = inputMeta(m.source, el.dataset.input);
    const req = inputRequired(m.id, inp);
    el.onchange = () => setModuleInput(el, inputConstraints(inp, null), req); el.oninput = () => liveCheck(el, inputConstraints(inp, null), req);
  });
  body.querySelectorAll("[data-rm]").forEach(a => a.onclick = e => {
    e.preventDefault(); S.changes.promoted = S.changes.promoted.filter(p => p.var !== a.dataset.rm); delete S.overrides[a.dataset.rm]; changed(); renderBuilder();
  });
  body.querySelectorAll("[data-remove]").forEach(b => b.onclick = () => { if (confirm(`Remove module ${b.dataset.remove}? Modules that use it lose that connection.`)) removeModule(b.dataset.remove); });
  body.querySelectorAll("[data-restore]").forEach(a => a.onclick = e => {
    e.preventDefault(); S.changes.remove_modules = S.changes.remove_modules.filter(x => x !== a.dataset.restore);
    S.changes.add_modules = S.changes.add_modules.filter(x => x.id !== a.dataset.restore);  // drop its replacement
    changed(); renderBuilder();
  });
  body.querySelectorAll("[data-pick]").forEach(a => a.onclick = e => { e.preventDefault(); addSource = a.dataset.pick || null; renderBuilder(); });
  body.querySelectorAll("[data-cat]").forEach(a => a.onclick = e => { e.preventDefault(); addCat = a.dataset.cat; renderBuilder(); });
  body.querySelectorAll("[data-askmod]").forEach(b => b.onclick = () => {
    if (qs("#chatSend").disabled) return;  // a turn is running
    if (turns.length) turns[turns.length - 1].answered = true;
    send(`Explain the module ${b.dataset.askmod}: what it does and what it needs, and whether and how it could be added to this configuration (which modules it would use and be used by, and the settings it would need). Do not change anything yet.`);
  });
  const af = qs("#addFilter"); if (af) af.oninput = () => { addFilter = af.value.toLowerCase(); renderBuilder(); const f = qs("#addFilter"); f.focus(); f.setSelectionRange(f.value.length, f.value.length); };
  const mf = qs("#modFilter"); if (mf) mf.oninput = () => { modFilter = mf.value.toLowerCase(); renderBuilder(); const f = qs("#modFilter"); f.focus(); f.setSelectionRange(f.value.length, f.value.length); };
  const ac = qs("#addConfirm");
  if (ac) ac.onclick = () => {
    const id = qs("#newId").value.trim();
    if (!/^[a-z][a-z0-9_-]{0,62}$/.test(id) || modsOf().some(m => m.id === id)) { showError(new Error(`Choose a unique module id (lowercase, digits, _ or -): ${id}`)); return; }
    const checked = n => [...document.querySelectorAll(`input[name="${n}"]:checked`)].map(x => x.value);
    if (!MM[addSource]) MM[addSource] = moduleMeta(addSource);
    S.changes.add_modules.push({id, source: addSource, use: checked("use"), used_by: checked("usedby"), settings: {}});
    addSource = null; group = "mod:" + id; changed(); renderBuilder();
  };
}

const fieldVal = el => el.dataset.t === "bool" ? el.checked : el.dataset.t === "number" ? (el.value === "" ? null : +el.value) : el.value;
function liveCheck(el, c, required) {
  const err = el.dataset.t === "bool" ? null : checkValue(c, fieldVal(el), required);
  el.classList.toggle("is-invalid", !!err);
  const fb = el.closest(".form-group").querySelector(".invalid-feedback"); if (fb) fb.textContent = err || "";
  return err;
}
function applyVar(name, val) {
  const v = vars(S.bp).find(x => x.name === name);
  const dflt = v.type === "expression" ? "" : parseDefault(v);
  if (val === null || val === "" && v.type === "expression" || same(val, dflt)) delete S.overrides[name];
  else S.overrides[name] = val;
  changed();
}
function setVar(el) {
  const v = vars(S.bp).find(x => x.name === el.dataset.n);
  if (liveCheck(el, varConstraints(el.dataset.n), isRequiredVar(v) && fieldVal(el) !== "")) return;  // invalid values never reach deployment.yaml
  applyVar(el.dataset.n, fieldVal(el)); renderBuilder();
}
function setModuleInput(el, c, required) {
  if (liveCheck(el, c, required) && fieldVal(el) !== "") return;
  const id = el.dataset.mod, m = modsOf().find(x => x.id === id), inp = inputMeta(m.source, el.dataset.input);
  const st = inputState(id, inp), val = fieldVal(el);
  const own = addedMod(id);
  if (own) {  // an added module's settings live in the copy directly
    if (val === "" || val === null) delete own.settings[inp.name]; else own.settings[inp.name] = toLong(val);
    changed(); renderBuilder(); return;
  }
  let name = st.var;
  if (!name) {
    const was = st.kind === "literal" ? st.value : parseDefault(inp);
    if (same(val, was) || (val === "" && was == null)) return;
    name = promote(id, inp.name, st.kind === "literal");
  }
  applyVar(name, val); renderBuilder();
}
