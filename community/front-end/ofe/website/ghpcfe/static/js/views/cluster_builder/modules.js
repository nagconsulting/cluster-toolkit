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

// Cluster Builder: The modules in the current configuration.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- modules in the current configuration ---------------- */
const templateMods = () => (BD[S.bp] || {}).modules || [];
const addedMod = id => S.changes.add_modules.find(a => a.id === id);
const isRemoved = id => S.changes.remove_modules.includes(id);
// Replaced: removed and added back under the same id (its users keep it).
const isReplaced = id => isRemoved(id) && !!addedMod(id);
// Effective module list: template modules (minus removed) plus added ones, with merged use: lists.
function modsOf() {
  const used = id => S.changes.add_modules.filter(a => a.used_by.includes(id)).map(a => a.id);
  const added = a => ({id: a.id, source: a.source, use: [...a.use, ...used(a.id)], added: true});
  return [  // a replacement takes the replaced module's place
    ...templateMods().filter(m => !isRemoved(m.id) || isReplaced(m.id)).map(m => isReplaced(m.id) ? added(addedMod(m.id))
      : {...m, use: [...m.use.filter(u => !isRemoved(u) || isReplaced(u)), ...used(m.id)]}),
    ...S.changes.add_modules.filter(a => !isRemoved(a.id)).map(added),
  ];
}
// A module's settings: an added module's own, else the template's with any list/object values set by changes.settings.
const settingsOf = id => addedMod(id) ? addedMod(id).settings : Object.assign({}, ((BD[S.bp] || {}).module_settings || {})[id] || {},
  Object.fromEntries((S.changes.settings || []).filter(x => x.module === id).map(x => [x.input, x.value])));
const moduleMeta = source => ((BD[S.bp] || {}).module_meta || {})[source] || MM[source];
const inputMeta = (source, name) => ((moduleMeta(source) || {}).inputs || []).find(i => i.name === name);
// Where each var is used (from the blueprint itself, see tools.var_uses):
// [{module, input, path, exact}], plus added modules and promoted inputs.
function usesOf(name) {
  const out = (((BD[S.bp] || {}).uses || {})[name] || []).filter(u => !isRemoved(u.module));
  for (const a of S.changes.add_modules) for (const [k, v] of Object.entries(a.settings))
    if (typeof v === "string" && v.includes(`$(vars.${name})`)) out.push({module: a.id, input: k, path: k, exact: v === `$(vars.${name})`});
  for (const p of S.changes.promoted) if (p.var === name) out.push({module: p.module, input: p.input, path: p.input, exact: true});
  return out;
}
// var name -> [{id, input, source}] where the var is the whole value of an input (its rules apply)
function wiring() {
  const out = {}, src = id => (modsOf().find(m => m.id === id) || {}).source;
  for (const v of vars(S.bp)) for (const u of usesOf(v.name))
    if (u.exact && src(u.module)) (out[v.name] = out[v.name] || []).push({id: u.module, input: u.input, source: src(u.module)});
  return out;
}
const varModules = name => [...new Set(usesOf(name).map(u => u.module))];
// The Configure page a var is edited on: gcluster globals in Cluster basics, a var used by one module on that module's page.
function groupOfVar(name) {
  const v = vars(S.bp).find(x => x.name === name);
  if (!v || v.global) return "basics";
  if (v.promoted) return "added";
  const mods = varModules(name);
  return mods.length === 1 ? "mod:" + mods[0] : mods.length ? "shared" : "other";
}
// Vars that only name networks the blueprint creates (BD.generated, from
// ofe_agent.toolkit.blueprint.generated_names): OFE names them from the
// deployment name unless the user types a name, so they are never required.
const genSuffix = name => ((BD[S.bp] || {}).generated || {})[name];
function genName(name) {  // kept in step with blueprint.generated_value
  const dn = vars(S.bp).find(x => x.name === "deployment_name");
  const base = S.overrides.deployment_name ?? (dn && parseDefault(dn)) ?? clusterName;
  return `${base || ""}${genSuffix(name)}`.toLowerCase().replace(/[^a-z0-9-]/g, "-").slice(0, 63).replace(/-+$/, "");
}
const isRequiredVar = v => !!v && v.required && v.name !== "project_id" && genSuffix(v.name) === undefined;
// Required values the form still needs: template vars without defaults and required inputs of added modules.
function missingValues() {
  const out = vars(S.bp).filter(v => isRequiredVar(v) && !(v.name in S.overrides)).map(v => v.name);
  for (const a of S.changes.add_modules) {
    const meta = MM[a.source];
    if (meta) out.push(...meta.required.filter(n => !(n in a.settings)).map(n => `${a.id}.${n}`));
  }
  return out;
}
