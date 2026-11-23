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

// Cluster Builder: The Gemini panel.
// Classic scripts sharing one global scope, loaded in order by
// templates/cluster_builder/builder.html.

/* ---------------- Gemini panel ---------------- */
// Each turn can offer up to three options (distinct approaches), ask a
// question with answer buttons, or just answer in prose.

// An option as a full configuration. Page-owned gcluster globals (cluster
// name, zone, region) carry over unless Gemini sets them explicitly.
function optionConfig(o) {
  if (!o || !S) return o;
  // Carry the page's globals over, except where they equal the option blueprint's default.
  const target = (BD[o.blueprint] || BD[S.bp]).variables;
  const globals = Object.fromEntries(Object.entries(S.overrides).filter(([k, val]) => {
    const t = target.find(v => v.name === k);
    return (BD[S.bp].variables.find(v => v.name === k) || {}).global && t && !same(parseDefault(t), val);
  }));
  return {...o, overrides: {...globals, ...o.overrides}};
}
const isNoop = p => p.blueprint === S.bp && same(p.overrides, S.overrides) && changesKey(p.changes) === changesKey(S.changes);

// Room in the existing subnet a configuration uses (ofe_agent.toolkit.capacity.check).
function capacityHtml(c) {
  if (!c) return "";
  if (!c.found) return `<div class="text-warning mt-1">Subnet <code>${esc(c.subnet)}</code> was not found in ${esc(c.region)}.</div>`;
  const unknown = c.unknown.length ? ` (plus ${c.unknown.map(esc).join(", ")}, whose size is not known yet)` : "";
  const overlaps = (c.overlaps || []).map(o => `<li><code>${esc(o.module)}.${esc(o.input)}</code> uses ${esc(o.range)}</li>`).join("");
  return `<div class="${c.fits ? "text-muted" : "text-danger"} mt-1">Subnet <code>${esc(c.subnet)}</code> (${esc(c.cidr)}):
    up to ${c.needed} VMs${unknown}; ${c.free} of ${c.usable} addresses free${c.fits ? "" : " — not enough for the cluster at full size"}.</div>
    ${overlaps ? `<div class="text-danger">Overlaps the subnet; one VM's interfaces cannot be on overlapping ranges:<ul class="mb-0">${overlaps}</ul></div>` : ""}`;
}

function optionHtml(turn, i, raw, n) {
  const p = optionConfig(raw), pending = turn.state === "pending", noop = pending && isNoop(p);
  const d = pending && !noop ? lineDiff(depYaml(S.overrides), depYaml(p.overrides)) : null;
  const status = p.valid ? validBadge(true) : (p.missing || []).length ? '<span class="badge badge-warning">needs values</span>' : validBadge(false);
  const footer = turn.state === "applied" ? (turn.applied === p.id ? '<span class="text-success small">&#10003; Applied</span>' : '<span class="text-muted small">Not chosen</span>')
    : turn.state === "rejected" ? '<span class="text-muted small">Not chosen</span>' : noop ? '<span class="text-muted small">Nothing to apply</span>'
    : `<button class="btn btn-sm btn-primary mr-1" data-accept="${i}:${esc(p.id)}">Accept</button><button class="btn btn-sm btn-link float-right" data-preview="${i}:${esc(p.id)}">Show full diff</button>`;
  return `<div class="card mt-2 ${turn.applied === p.id ? "border-success" : ""}"><div class="card-header py-1 small d-flex align-items-center">
      ${turn.result.options.length > 1 ? `<span class="badge badge-light mr-1">Option ${n}</span>` : ""}<strong class="mr-2">${esc(p.title)}</strong>${status}</div>
    <div class="card-body p-2 small">${pending && p.blueprint !== S.bp ? `<div class="mb-1">Switch template to <code>${esc(p.blueprint)}</code>${hasChanges(S.changes) ? " (replaces your module changes)" : ""}</div>` : ""}
      ${p.reason ? `<div class="mb-1">${agentText(p.reason)}</div>` : ""}
      ${changeSummary(p.changes)}${capacityHtml(p.capacity)}
      ${noop ? '<span class="text-muted">No changes to your current configuration.</span>' :
        d && d.some(([t]) => t !== " ") ? `<div class="text-muted">deployment.yaml</div>${diffHtml(d)}` :
        !hasChanges(p.changes) ? '<span class="text-muted">No variable overrides.</span>' : ""}
      ${(p.missing || []).length ? `<div class="text-warning mt-1">You'll need to fill in: ${p.missing.map(m => `<code>${esc(m)}</code>`).join(", ")}</div>` : ""}
      ${!p.valid && !(p.missing || []).length ? `<pre class="small mt-1 mb-0 cb-pre">${esc(p.output.slice(-600))}</pre>` : ""}</div>
    <div class="card-footer py-1">${footer}</div></div>`;
}

function turnHtml(turn, i) {
  const r = turn.result, last = i === turns.length - 1;
  const u = r.usage || {};
  const tools = `<details class="small mb-2"><summary class="text-muted">Tools used (${r.trace.length})${u.seconds ? ` · ${Math.round(u.seconds)}s` : ""}</summary>${stepsHtml(r.trace)}</details>`;
  const options = r.options.map((o, n) => optionHtml(turn, i, o, n + 1)).join("") +
    (turn.state === "pending" && r.options.length ? `<button class="btn btn-sm btn-link px-0" data-reject="${i}">${r.options.length > 1 ? "None of these" : "Reject"}</button>` : "");
  // Approaches are described, not built: choosing one asks Gemini to build it next turn.
  // Approaches: tick any that combine; within an exclusive group pick one (radio). Built together next turn.
  const pickable = last && !turn.answered;
  // A group with one member has nothing to choose between: a plain checkbox.
  const groupOf = a => a.group && (r.approaches || []).filter(x => x.group === a.group).length > 1 ? a.group : "";
  const approachCard = (a, n, g) => {
    const input = pickable ? `<input class="mr-2 mt-1" type="${g ? "radio" : "checkbox"}" ${g ? `name="ap-${i}-${esc(g)}"` : ""} data-ap="${n}" id="ap-${i}-${n}">` : "";
    const chosen = (turn.picked || []).includes(n);
    return `<div class="card mb-1 cb-ap ${chosen ? "border-success" : ""}"><label class="card-body p-2 small mb-0 d-flex" for="ap-${i}-${n}">${input}<div>
      <strong>${esc(a.title)}</strong>${chosen ? ' <span class="badge badge-success">chosen</span>' : ""}
      <div class="mt-1">${agentText(a.description)}</div></div></label></div>`;
  };
  // Alternatives (an exclusive group) in a box of their own; combinable approaches together.
  const sections = [];
  for (const [n, a] of (r.approaches || []).entries()) {
    const g = groupOf(a), key = g ? `g:${g}` : "any";
    let sec = sections.find(x => x.key === key);
    if (!sec) sections.push(sec = {key, g, items: []});
    sec.items.push([a, n]);
  }
  const approaches = sections.length ? `<div class="mt-2">${sections.map(sec => `<div class="border rounded p-2 mb-2 ${sec.g ? "bg-light" : ""}">
      <div class="small text-muted mb-1">${sec.g ? `<b>Choose one</b> · ${esc(sec.g)} <span class="text-muted">(these replace each other)</span>`
        : `<b>${sections.length > 1 ? "Add any of these" : "Pick any"}</b> <span class="text-muted">(they combine)</span>`}</div>
      ${sec.items.map(([a, n]) => approachCard(a, n, sec.g)).join("")}</div>`).join("")}
    ${pickable ? `<button class="btn btn-sm btn-primary" data-build="${i}" disabled>Build selected</button>
      <small class="text-muted ml-2" data-build-count></small>` : ""}</div>` : "";
  const choices = !r.choices.length || !pickable ? "" : r.multi_select
    ? `<div class="mt-1">${r.choices.map((c, n) => `<div class="form-check"><input class="form-check-input" type="checkbox" id="ch-${i}-${n}" data-mchoice="${esc(c)}">
        <label class="form-check-label" for="ch-${i}-${n}">${esc(c)}</label></div>`).join("")}
        <button class="btn btn-sm btn-info mt-1" data-msend disabled>Send</button></div>`
    : `<div class="mt-1">${r.choices.map(c =>
    `<button class="btn btn-sm btn-outline-info mr-1 mb-1" data-choice="${esc(c)}">${esc(c)}</button>`).join("")}</div>`;
  const q = r.question ? `<div class="alert alert-info small mt-2 mb-0">${agentText(r.question)}${choices}</div>` : "";
  return `<div class="d-flex justify-content-end mb-2"><div class="cb-user px-3 py-2 small">${esc(turn.prompt)}</div></div>
    <div class="mb-3">${tools}<div class="small cb-pre">${agentText(r.answer)}</div>${q}${approaches}${options}</div>`;
}

function stepsHtml(steps) {
  return `<ul class="list-unstyled mb-0 mt-1">${steps.map(s =>
    `<li><span class="${s.error ? "text-danger" : "text-success"}">${s.error ? "&#10007;" : "&#10003;"}</span> <code class="small">${esc(stepText(s))}</code></li>`).join("")}</ul>`;
}

// The turn in progress: the steps done so far and what is happening now.
let live = null;
function onProgress(event) {
  if (!live) return;
  if (event.thinking) live.status = event.thinking > 1 ? "Gemini is reading the results…" : "Gemini is thinking…";
  if (event.running) live.status = `${stepText(event.running)}…`;
  if (event.step) live.steps.push(event.step);
  renderChat(live.prompt);
}

function renderChat(busyPrompt) {
  const net = netChoice ? ` on existing subnet <code>${esc(netChoice.name)}</code> (${esc(netChoice.vpc)}, ${esc(netChoice.region)})` : "";
  const intro = `<div class="small text-muted mb-3">Configuring <code>${esc(S.bp)}</code>${net} for: “${esc(workload)}”. Ask Gemini to change settings, add or remove modules, or explain the blueprint.</div>`;
  qs("#chat").innerHTML = intro + turns.map(turnHtml).join("") + (busyPrompt ? `<div class="d-flex justify-content-end mb-2"><div class="cb-user px-3 py-2 small">${esc(busyPrompt)}</div></div>
    <div class="small text-muted mb-2">${live && live.steps.length ? stepsHtml(live.steps) : ""}<div class="mt-1"><span class="spinner-border spinner-border-sm text-info mr-2"></span>${esc(live ? live.status : "Gemini is working…")}</div></div>` : "");
  qs("#chat").scrollTop = 1e6;
  const ref = b => { const [i, id] = b.split(":"); return {turn: +i, id}; };
  qs("#chat").querySelectorAll("[data-accept]").forEach(b => b.onclick = () => { const r = ref(b.dataset.accept); accept(r.turn, r.id); });
  qs("#chat").querySelectorAll("[data-reject]").forEach(b => b.onclick = () => {
    turns[+b.dataset.reject].state = "rejected";
    if (histSel === -2) histSel = HIST.length - 1;
    renderChat(); if (tab === "diff") renderBuilder();
  });
  qs("#chat").querySelectorAll("[data-preview]").forEach(b => b.onclick = async () => {
    const r = ref(b.dataset.preview), o = turns[r.turn].result.options.find(x => x.id === r.id);
    try { await loadBlueprint(o.blueprint); } catch (err) { showError(err); return; }
    previewOpt = r; histSel = -2; tab = "diff"; renderBuilder();
  });
  qs("#chat").querySelectorAll("[data-choice]").forEach(b => b.onclick = () => { turns[turns.length - 1].answered = true; send(b.dataset.choice); });
  const apInputs = [...qs("#chat").querySelectorAll("[data-ap]")], buildBtn = qs("#chat").querySelector("[data-build]");
  apInputs.forEach(el => {
    el.onclick = () => {  // a selected radio clicked again clears it, so a group can be left out
      if (el.type === "radio" && el.dataset.was === "1") el.checked = false;
      apInputs.filter(x => x.type === "radio" && x.name === el.name).forEach(x => x.dataset.was = x.checked ? "1" : "");
      // Highlight what is selected and say how much will be built together.
      apInputs.forEach(x => x.closest(".cb-ap").classList.toggle("border-primary", x.checked));
      const n = apInputs.filter(x => x.checked).length;
      buildBtn.disabled = !n;
      qs("#chat").querySelector("[data-build-count]").textContent = n ? `${n} selected, built together as one proposal` : "";
    };
  });
  if (buildBtn) buildBtn.onclick = () => {
    const t = turns[turns.length - 1], picked = apInputs.filter(x => x.checked).map(x => +x.dataset.ap);
    const chosen = picked.map(n => t.result.approaches[n]);
    t.answered = true; t.picked = picked;
    send(chosen.length === 1 ? `Build this approach: ${chosen[0].title}. ${chosen[0].description}`
      : `Build these approaches together as one proposal:\n${chosen.map(a => `- ${a.title}: ${a.description}`).join("\n")}`);
  };
  const mChoices = [...qs("#chat").querySelectorAll("[data-mchoice]")], mSend = qs("#chat").querySelector("[data-msend]");
  mChoices.forEach(el => el.onchange = () => { mSend.disabled = !mChoices.some(x => x.checked); });
  if (mSend) mSend.onclick = () => {
    turns[turns.length - 1].answered = true;
    send(mChoices.filter(x => x.checked).map(x => x.dataset.mchoice).join("; "));
  };
}

async function accept(i, id) {
  const p = optionConfig(turns[i].result.options.find(o => o.id === id));
  try {
    await loadBlueprint(p.blueprint);
    await Promise.all(p.changes.add_modules.filter(a => !MM[a.source]).map(async a => { MM[a.source] = await api("module", {source: a.source}); }));
    const changedKeys = Object.keys(p.overrides).filter(k => !same(p.overrides[k], S.overrides[k]));
    S = {bp: p.blueprint, overrides: {...p.overrides}, changes: JSON.parse(JSON.stringify(p.changes)), accepted: S.accepted + 1, _flash: changedKeys};
    turns.forEach(t => { if (t.state === "pending") t.state = "rejected"; });
    turns[i].state = "applied"; turns[i].applied = id;
    record("gemini", `${p.title} (${turns[i].prompt})`);
    validation = {valid: p.valid, output: p.output, capacity: p.capacity, key: stateKey(), from: "Gemini"};
    if (changedKeys.length && tab === "config" && !group.startsWith("mod:")) group = groupOfVar(changedKeys[0]);
    renderChat(); renderBuilder();
  } catch (err) { showError(err); }
}

// One chat turn. initial: the tailoring request right after the wizard
// (its text is fixed server-side).
async function send(prompt, initial = false) {
  qs("#chatSend").disabled = true;
  live = {prompt, steps: [], status: "Gemini is thinking…"};
  renderChat(prompt);
  try {
    const result = await apiStream("chat", {...(initial ? {initial: true} : {prompt}), credential_id: credId,
                                            current: {blueprint: S.bp, overrides: S.overrides, changes: S.changes}}, onProgress);
    turns.push({prompt, result, state: result.options.length ? "pending" : "info"});
  } catch (err) { showError(err); }
  live = null;
  qs("#chatSend").disabled = false;
  renderChat();
}
const tailor = () => send(`Tailor this blueprint to: ${workload}`, true);

qs("#chatForm").onsubmit = e => {
  e.preventDefault();
  const prompt = qs("#chatIn").value.trim();
  if (!prompt) return;
  qs("#chatIn").value = "";
  if (turns.length) turns[turns.length - 1].answered = true;
  send(prompt);
};
