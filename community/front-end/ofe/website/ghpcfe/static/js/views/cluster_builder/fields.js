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

// Cluster Builder: Input constraints from gcluster explain, and the one renderer for every field.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- constraints (from gcluster explain) ---------------- */
// An input's `constraints` (allowed_values, min/max, pattern and their
// flags): limits every value Terraform and gcluster accept meets.
const NO_LIMITS = {allowed: null, ci: false, min: null, minEx: false, max: null, maxEx: false, pattern: null};
const inputConstraints = (i, at) => {
  const k = i.constraints || {};
  return {
    allowed: k.allowed_values || null, ci: !!k.case_insensitive,
    min: k.min ?? null, minEx: !!k.min_exclusive, max: k.max ?? null, maxEx: !!k.max_exclusive,
    pattern: k.pattern || null,
    validations: (i.validations || []).map(text => ({text, at})),
  };
};
function varConstraints(name) {
  // A var wired to several inputs meets all their limits; the last stated one is kept per kind.
  const c = {...NO_LIMITS, validations: []};
  for (const w of wiring()[name] || []) {
    const i = inputMeta(w.source, w.input); if (!i) continue;
    const ic = inputConstraints(i, `${w.id}.${w.input}`);
    if (ic.allowed) { c.allowed = ic.allowed; c.ci = ic.ci; }
    if (ic.min != null) { c.min = ic.min; c.minEx = ic.minEx; }
    if (ic.max != null) { c.max = ic.max; c.maxEx = ic.maxEx; }
    c.pattern = ic.pattern || c.pattern;
    c.validations.push(...ic.validations);
  }
  return c;
}
function checkValue(c, val, required) {
  if (val === "" || val == null) return required ? "Required" : null;
  if (typeof val === "string" && /\$[a-z]/.test(val)) return null;  // references are checked by gcluster
  const fold = s => c.ci ? String(s).toLowerCase() : String(s);
  if (c.allowed && !c.allowed.map(fold).includes(fold(val))) return `Must be one of: ${c.allowed.join(", ")}`;
  if (typeof val === "number" && c.min != null && (c.minEx ? val <= c.min : val < c.min))
    return `Must be ${c.minEx ? "more than" : "at least"} ${c.min}`;
  if (typeof val === "number" && c.max != null && (c.maxEx ? val >= c.max : val > c.max))
    return `Must be ${c.maxEx ? "less than" : "at most"} ${c.max}`;
  if (typeof val === "string" && c.pattern && !new RegExp(c.pattern).test(val)) return `Must match ${c.pattern}`;
  return null;
}
// A validation rule's message (variables.tf validation or metadata.yaml
// validator, as `gcluster explain` lists them) and the module input it is on.
const ruleHtml = v => `<li>${esc(v.text)}${v.at ? ` <span class="text-muted">· ${esc(v.at)}</span>` : ""}</li>`;
const validBadge = v => v ? '<span class="badge badge-success">valid</span>' : '<span class="badge badge-danger">invalid</span>';

/* ---------------- one renderer for every field ---------------- */
// f: {id, label, type, value, def, placeholder, c, changed, required, hint, attrs, details, warning}
function field(f) {
  const scalar = ["string", "number", "bool", "expression"].includes(f.type);
  const err = scalar && f.type !== "bool" ? checkValue(f.c, f.value, f.required) : null;
  const open = openDet.has(f.id);
  const toggle = `<a href="#" class="small ml-2" data-det="${f.id}">${open ? "hide details" : "details"}</a>`;
  const badge = (f.required ? ' <span class="text-danger" title="Required">*</span>' : "") +
    (f.changed ? ' <span class="badge badge-primary">changed</span>' : "") +
    (f.warning ? ' <span class="badge badge-warning">deprecated</span>' : "");
  const below = (f.warning ? `<small class="form-text text-warning">${esc(f.warning)}</small>` : "") +
    ((f.usedIn || []).length ? `<small class="form-text text-muted">Used in ${f.usedIn.map(p => `<code>${esc(p)}</code>`).join(", ")}</small>` : "") +
    (f.hint ? `<small class="form-text text-muted">${esc(f.hint)}</small>` : "") +
    (f.suggest ? `<button type="button" class="btn btn-sm btn-outline-secondary mt-1" data-suggest="${esc(f.name)}" data-value="${esc(f.suggest)}">Use “${esc(f.suggest)}” (from the cluster name)</button>` : "") +
    (f.offer || "");
  const details = `<div class="cb-det text-muted border-left pl-2 mt-1 ${open ? "" : "d-none"}" id="det-${f.id}">${f.details}</div>`;
  if (f.type === "bool")
    return `<div class="form-group form-check ${f.changed ? "cb-mod" : ""}"><input type="checkbox" class="form-check-input" id="${f.id}" ${f.value ? "checked" : ""} ${f.attrs}>
      <label class="form-check-label" for="${f.id}">${esc(f.label)}</label>${badge}${toggle}${below}${details}</div>`;
  let control;
  if (!scalar) {
    control = `<textarea class="form-control form-control-sm text-monospace" rows="2" disabled>${esc(f.value == null ? "" : JSON.stringify(f.value))}</textarea><small class="form-text text-muted">${esc(f.type)}: edit in YAML</small>`;
  } else if (f.c.allowed && f.type === "string") {
    const opts = f.c.allowed.map(String);
    if (f.value != null && f.value !== "" && !opts.includes(String(f.value))) opts.unshift(String(f.value));
    control = `<select class="form-control ${err ? "is-invalid" : ""}" id="${f.id}" ${f.attrs}>${f.value == null || f.value === "" ? '<option value="">(not set)</option>' : ""}${opts.map(o => `<option ${String(f.value) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  } else {
    const num = f.type === "number";
    control = `<input class="form-control ${err ? "is-invalid" : ""}" id="${f.id}" type="${num ? "number" : "text"}" ${num ? 'step="any"' : ""} value="${esc(toShort(f.value) ?? "")}"
      placeholder="${esc(f.placeholder ?? f.def ?? "")}" ${f.c.min != null && !f.c.minEx ? `min="${f.c.min}"` : ""} ${f.c.max != null && !f.c.maxEx ? `max="${f.c.max}"` : ""} ${f.attrs}>`;
  }
  return `<div class="form-group ${f.changed ? "cb-mod" : ""}"><label for="${f.id}" class="mb-1">${esc(f.label)}</label>${badge}${toggle}
    ${control}<div class="invalid-feedback">${esc(err || "")}</div>${below}${details}</div>`;
}
function detailsHtml({name, type, def, description, setBy, sets, c, extra}) {
  return `${description ? `<div>${esc(description)}</div>` : ""}
    <div><code>${esc(name)}</code> · ${esc(type)}${def !== undefined ? ` · default <code>${esc(def)}</code>` : ""}${setBy ? ` · ${setBy}` : ""}</div>
    ${sets ? `<div>Sets ${sets}</div>` : ""}
    ${c && c.validations.length ? `<ul class="list-unstyled mb-0 mt-1">${c.validations.map(ruleHtml).join("")}</ul>` : ""}${extra || ""}`;
}
