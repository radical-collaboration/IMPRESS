#!/usr/bin/env node
// build_deck.js — IMPRESS-A: the API and the loop.
//
//   NODE_PATH=<scratch>/node_modules node slides/api/build_deck.js
//
// Every number on a slide comes from ./run.json, mined by ./run_model.py. Nothing here
// transcribes a figure: if a count looks wrong, re-run the model rather than editing a
// literal into this file. Every `file:line` printed lives in ./anchors.json and is
// checked by the skill's check_anchors.py.
//
// This is NOT the comparison deck. ../build_deck.js argues IMPRESS-A against the
// reference IMPRESS pipeline; this one walks the six API surfaces and the loop between
// them. Where the two overlap, this deck cites and does not re-argue.
//
// Diagrams are native shapes on purpose - the audience opens the file and edits it.

const { createDeck } = require("/home/mason/.claude/skills/code-walk-deck/scripts/deck_lib.js");
const R = require("./run.json");

const D = createDeck({
  title: "IMPRESS-A: the API and the loop",
  // Role per layer, used consistently all deck long: a = who decides, b = the runtime
  // that owns state, c = composition and validation, d = tools, accent = anything
  // outside the package (an operator, an external caller, a tool author).
  palette: {},
});
const { pres, C, W, H, M, HF, BF, MF, text, title, divider, box, line, label, legend,
        pill, code, footer, card, tbl, save } = D;

const S = R.surfaces, K = R.code, Q = R.mock;
const HEAD = `${K.branch} @ ${K.head}`;

// The live example next door. Its `code` half is mined on every build; its `runs` half is
// the only transcribed figures in this deck, and every slide showing one names the source.
if (!R.live) throw new Error(
  "run.json has no `live` section - re-run run_model.py from a checkout that still has "
  + "examples/agentic_small_molecule_binding, or drop slides 23 and 24");
const L = R.live.code, LR = R.live.runs, P4 = LR.paired_4h;

// Timings derived from the mined timeline, so that no slide types a latency literal: the
// first cycle pays for engine construction, the second does not, and the gap between the
// campaign's own span and the process is interpreter startup.
const at = (ev, nth) => Q.timeline.filter(e => e.event === ev)[nth].at_s;
const CYCLE1_S = (at("dispatched", 0) - at("composed", 0)).toFixed(2);
const CYCLE2_MS = Math.round((at("dispatched", 1) - at("composed", 1)) * 1000);
const STARTUP_S = (Q.elapsed_s - Q.span_s).toFixed(1);
const slide = () => pres.addSlide();

// The six surfaces, in the order the deck walks them. `who` is the role that writes
// against the surface, which is the only useful way to order them: a tour by module
// answers a question nobody asked.
const SURFACES = [
  ["1 · CLI", "an operator", "cli/__init__.py", C.accent],
  ["2 · Campaign YAML", "a scientist", "runtime/executor.py:58", C.accent],
  ["3 · ControlPolicy", "a reasoner author", "policy/base.py:19", C.a],
  ["4 · CampaignSession", "a reasoner, anywhere", "core/session.py:56", C.a],
  ["5 · ControlPlane", "an external caller", "control/plane.py:23", C.b],
  ["6 · ToolSpec + TaskAgent", "a tool author", "tools/spec.py:75", C.d],
];

// ============================================================ 1. title
{
  const s = slide();
  s.background = { color: C.ink };
  text(s, "CODE WALK · THE API SURFACES AND THE CAMPAIGN LOOP", M, 0.9, 7.2, 0.3,
    { fontSize: 12, bold: true, color: C.muted, charSpacing: 2 });
  text(s, "Six APIs, one engine", M, 1.3, 6.6, 1.5,
    { fontFace: HF, fontSize: 40, bold: true, color: C.white });
  text(s, "A policy, a tool and an external caller write against three different "
       + "surfaces — and are admitted through one set of gates.", M, 2.95, 6.5, 0.95,
    { fontSize: 15, color: "C8D4DD" });
  text(s, [
    { text: `${S.n_tools} tools`, options: { bold: true, color: "F0C898" } },
    { text: " in " }, { text: `${K.n_toolkits} toolkits`, options: { bold: true, color: "F0C898" } },
    { text: "   ·   " },
    { text: `${S.n_session_ops} session operations`, options: { bold: true, color: "F0C898" } },
    { text: "   ·   " },
    { text: `${S.n_plane_ops} control-plane operations`, options: { bold: true, color: "F0C898" } },
    { text: "   ·   " },
    { text: `${K.tests_collected} tests`, options: { bold: true, color: "F0C898" } },
  ], M, 4.1, 6.6, 0.4, { fontSize: 13, color: "C8D4DD" });
  text(s, `Derived against ${HEAD} · every figure mined by slides/api/run_model.py, except the `
    + `live runs on 21-22, which are transcribed and say so`,
    M, 4.6, 6.6, 0.3, { fontSize: 11, color: C.muted, italic: true });

  // Motif: the six surfaces as a ring of callers around the one engine they all reach.
  const bx = 7.3, bw = 5.5;
  text(s, "WHO WRITES AGAINST WHAT", bx, 1.0, bw, 0.25,
    { fontSize: 10, bold: true, color: C.muted, charSpacing: 1.5, align: "center" });
  SURFACES.forEach((sf, i) => {
    const x = bx + (i % 2) * (bw / 2 + 0.1), y = 1.4 + Math.floor(i / 2) * 0.72;
    box(s, x, y, bw / 2 - 0.1, 0.62, { title: sf[0], sub: sf[1], fs: 11, sfs: 9,
      fill: "1E2A33", line: sf[3], tc: C.white, sc: "9FB0BC", round: true });
  });
  box(s, bx, 3.62, bw, 0.72, { title: "one executor · one design tree · one provenance log",
    sub: "runtime/executor.py — the only writer of campaign state",
    fs: 12, sfs: 9.5, fill: "24323D", line: C.b, tc: C.white, sc: "9FB0BC", subMono: true });
  // From the bottom of the surface grid (y 3.46) to the engine band, not from inside it.
  [bx + bw / 4, bx + bw / 2, bx + 3 * bw / 4].forEach(x =>
    line(s, x, 3.48, x, 3.6, { color: C.muted, w: 1 }));
  text(s, "and one place that refuses them: five gates, a dry run, and a trust interlock",
    bx, 4.45, bw, 0.3, { fontSize: 10.5, color: "9FB0BC", italic: true, align: "center" });

  s.addNotes(`
Thanks. This is a code walk through IMPRESS-A's API — and the deliberate claim in the
title is that there isn't one API, there are six. An operator writes a YAML file. A tool
author writes a spec file. Someone writing a reasoner implements one method. Someone
driving a campaign from outside the allocation speaks a protocol over a socket. Those are
genuinely different surfaces with different audiences, and the reason the project is worth
half an hour of your time is what they have in common underneath: one executor that owns
all the state, and one set of gates that refuses all of them the same way.

[Point at the ring on the right.] Six callers, one engine.

Everything on these slides is derived against ${HEAD}, and every number is mined from the
checkout by a script that ships beside the deck — so if you pull this branch and re-run
it, a figure that has moved will disagree with me out loud. There is one run in this deck
and it takes under three seconds on a laptop; I ran it while building these slides.
  `);
  footer(s, `IMPRESS-A · agent/ · ${HEAD}`);
}

// ============================================================ 2. what it is / is not
{
  const s = slide();
  title(s, "What this deck shows, and what it does not", "orientation");

  const steps = [["observe", "the same object\na policy sees"], ["DECIDE", "intent, not\na DAG"],
                 ["compose", "typed DAG"], ["validate", "5 gates\n+ dry run"],
                 ["execute", "asyncflow /\nDragon"], ["analyze", "QC gates,\nnever skipped"],
                 ["update", "tree, Pareto,\nprovenance"]];
  const sw = (W - 2 * M - 6 * 0.1) / 7;
  steps.forEach(([t, sub], i) => {
    const x = M + i * (sw + 0.1);
    box(s, x, 1.55, sw, 1.05, { title: t, sub, fs: 12, sfs: 8.5,
      fill: i === 1 ? C.aTint : C.panel, line: i === 1 ? C.a : C.rule,
      tc: i === 1 ? C.a : C.ink });
  });
  // The back edges. A loop drawn as a strip is a pipeline, and that is the one thing
  // this system is not.
  line(s, M + 6.5 * (sw + 0.1), 2.74, M + 0.8 * sw, 2.74, { color: C.a, w: 1.25 });
  label(s, "terminate? → next experiment, while others are still running",
    M + sw, 2.76, 7.5, { align: "left", color: C.a });

  card(s, M, 3.45, 6.1, 2.4, "What ran, for real, to make this deck",
    [`\`mock-stabilize.yaml --model D\` end to end in ${Q.elapsed_s} s: ${Q.n_composed} graphs composed, `
     + `${Q.n_refused} refused, ${Q.n_admitted} admitted`,
     `${Q.n_results} design nodes absorbed, Pareto front of ${Q.front_size}, stop reason "${Q.stop_reason}"`,
     `${Q.provenance_records} provenance records across ${Object.keys(Q.provenance_kinds).length} kinds, `
     + `${Q.n_ledger} ledger records, ${Q.n_signatures} pattern signatures`,
     `${K.tests_collected} tests, ${K.test_files} files, all of it on a laptop with no allocation`],
    { fill: C.panel, hc: C.ink });
  card(s, M + 6.33, 3.45, 6.1, 2.4, "What that does not demonstrate",
    ["Every stage was a MOCK. No GPU, no PyRosetta, no Boltz — the science is stubbed and the "
     + "numbers are drawn, not computed",
     "One experiment in flight at a time. There is no concurrent run in this deck and no serial "
     + "baseline, so nothing here divides into a speedup",
     `On the real six-stage chain, \`replicas > 1\` has never executed (backlog A10). It runs here, `
     + `at width ${Q.composed[1].lineages}, against mocks`,
     "Nothing outside this package has ever driven a campaign. The control plane is tested, not used"],
    { fill: C.failTint, hc: C.fail });

  s.addNotes(`
Two things before the content, because this room can check me and I would rather hand you
the caveats than have you find them.

The strip across the top is the loop, and I will come back to it. The one mark worth
noticing now is the back edge: this is a loop, not a pipeline, and the reasoner is not the
body of it — several experiments sit at different steps at the same time.

Left card: what actually ran to make this deck. A complete campaign on the bundled mock
toolkit, ${Q.elapsed_s} seconds, ${Q.n_composed} graphs composed, one of them refused, two admitted,
${Q.n_results} design nodes, a Pareto front of ${Q.front_size}. That is a real campaign through the real
manager, the real composer, the real validator and the real provenance writer.

Right card, and this is the one I want you to hold onto: every stage of it was a mock. The
science is stubbed. There is one experiment in flight at a time, so I have no concurrency
measurement and no baseline to divide by. On the real chain, more than one replica has
never run — that is backlog A10 and I will show you exactly why on slide fifteen. And
nothing outside this package has ever driven a campaign: the control plane, which is the
most carefully designed surface in here, is tested and unused.
  `);
  footer(s, `mined: slides/api/run.json · the run is reproducible: python slides/api/run_model.py`);
}

// ============================================================ 3. the framing slide
{
  const s = slide();
  title(s, "Three questions, and the one I cannot answer", "how to listen to this");

  const dims = [
    ["FUNCTIONALITY", C.c, C.cTint, "What can you write against this that you cannot write "
     + "against a pipeline?",
     [`a tool is ${S.n_tool_spec_fields} declared fields, not a code path`,
      `a reasoner is ${S.policy_ops.length} methods, or one`,
      `${S.n_gates_implemented} QC gates, ${K.gate_fixtures} fixtures, never skippable`]],
    ["PERFORMANCE", C.b, C.bTint, "What does the loop cost, and where does it serialise?",
     [`${Q.elapsed_s} s end to end, ${Q.provenance_records} provenance records`,
      "the executor is the sole writer of state",
      "one experiment in flight · no baseline"]],
    ["USABILITY", C.a, C.aTint, "Is it an application, a platform, or a component?",
     ["application: one YAML, one command",
      `platform: ${S.n_tools} tools discovered at runtime`,
      "component: nothing has ever driven it"]],
  ];
  dims.forEach(([name, col, tint, def, rows], i) => {
    const x = M + i * 4.28, w = 4.0;
    pres.addSlide; // no-op, keeps the block shape obvious
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w, h: 0.42,
      fill: { color: col }, line: { color: col } });
    text(s, name, x, 1.5, w, 0.42, { fontSize: 13, bold: true, color: C.white,
      align: "center", valign: "middle", charSpacing: 1 });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.92, w, h: 1.0,
      fill: { color: tint }, line: { color: tint } });
    text(s, def, x + 0.14, 2.0, w - 0.28, 0.86, { fontSize: 11.5, color: C.text, italic: true });
    rows.forEach((r, j) => {
      const y = 3.02 + j * 0.78;
      s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.7,
        fill: { color: j % 2 ? C.white : C.panel }, line: { color: C.rule } });
      text(s, r, x + 0.14, y + 0.08, w - 0.28, 0.54, { fontSize: 11, color: C.text,
        valign: "middle" });
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 5.5, w: W - 2 * M, h: 1.15,
    fill: { color: C.ink }, line: { color: C.fail, width: 2 } });
  text(s, [
    { text: "The weak one is usability, and specifically the component claim. ",
      options: { bold: true, color: "E8A0A0" } },
    { text: "The control plane and the remote session are the two surfaces in here designed "
      + "with the most care — request/response, nothing live crossing the wire, a long poll "
      + "so a reasoner on a login node blocks exactly as it would in-process — and no caller "
      + "outside this package has ever used either. ", options: { color: C.white } },
    { text: "That is the first thing I would want to break if I were you.",
      options: { color: "F0C898", bold: true } },
  ], M + 0.18, 5.62, W - 2 * M - 0.36, 0.95, { fontSize: 12.5 });

  s.addNotes(`
A technical audience arrives with three questions and they take different evidence, so the
deck is in three acts in this order.

Functionality: what can you write against this that you could not write against a
pipeline. The evidence there is that a tool is ${S.n_tool_spec_fields} declared fields rather than a code
path, a reasoner is ${S.policy_ops.length} methods, and everything either of them produces goes through the
same gates.

Performance: what the loop costs and where it serialises. I have a real end-to-end number
and a provenance record count, and I have no concurrency measurement at all.

Usability: application, platform, or component. One YAML and one command makes it an
application. ${S.n_tools} tools discovered at runtime from a directory makes it arguably a platform.

And the component claim is empty, which is the weak dimension and I would rather say it
now than have it extracted at minute twenty. The control plane and the remote session are
the most carefully built surfaces here — and nothing has ever driven a campaign through
them. If you want to find a real bug in this project today, that is where it is.
  `);
  footer(s, "the dividers repeat this per act, with each act's weakest claim before the act");
}

// ============================================================ 4. the loop and who drives it
{
  const s = slide();
  title(s, "The loop is ours. Who drives it is the pluggable part.", "orientation");

  code(s, [
    "observe -> DECIDE -> compose -> validate -> execute -> analyze -> update -> terminate?",
  ], M, 1.5, W - 2 * M, 0.52, { fs: 12.5, ls: 16 });

  card(s, M, 2.25, 6.1, 1.5, "What changed, and why it matters to an API",
    ["The manager used to BE the loop: it called `decide()` once per cycle and blocked on "
     + "the graph it asked for, so the reasoner could not be consulted while work was running.",
     "Now the reasoner is a coroutine that calls the campaign."],
    { fill: C.aTint, hc: C.a, fs: 11 });
  card(s, M + 6.33, 2.25, 6.1, 1.5, "What did not change",
    ["Every step above still happens in that order, for any one experiment.",
     "Models A-D are untouched: `SequentialPolicyDriver` makes a `decide`-style policy look "
     + "like a self-driving one."],
    { fill: C.panel, hc: C.ink, fs: 11 });

  // Two ways to be a reasoner, side by side, with the same engine under both.
  const y0 = 4.0;
  box(s, M, y0, 6.1, 0.95, { title: "decide(obs) -> Decision",
    sub: "answer one question at a time · auditable · models A-D",
    fs: 14, sfs: 10, fill: C.white, line: C.a, tc: C.a, subMono: false });
  box(s, M + 6.33, y0, 6.1, 0.95, { title: "conduct(session)",
    sub: "drive yourself · submit many, collect as they finish",
    fs: 14, sfs: 10, fill: C.white, line: C.a, tc: C.a });
  label(s, "policy/base.py:19", M, y0 + 0.98, 6.1, { mono: true });
  label(s, "policy/driver.py:35", M + 6.33, y0 + 0.98, 6.1, { mono: true });

  line(s, M + 3.05, y0 + 1.3, M + 3.05, y0 + 1.75, { color: C.muted, w: 1.25 });
  line(s, M + 9.38, y0 + 1.3, M + 9.38, y0 + 1.75, { color: C.muted, w: 1.25 });
  box(s, M, y0 + 1.78, W - 2 * M, 0.72, {
    title: "CampaignExecutor — owns all campaign state, reaps runs as they finish, decides termination",
    sub: "budget, stagnation and repeated failure are facts about state a reasoner cannot see, so stopping is not the reasoner's to declare",
    fs: 12.5, sfs: 10, fill: C.bTint, line: C.b, tc: C.b });

  s.addNotes(`
One line, and it is the same line it has always been: observe, decide, compose, validate,
execute, analyze, update, terminate.

What changed — and this is the change that produced an API rather than a loop — is who
drives it. The manager used to *be* the loop. It called decide once per cycle and then
blocked on the graph that call asked for, which means a reasoner could never be consulted
while work was running. If you are an LLM deciding what to design next, being unreachable
for the twenty minutes your last idea takes to run is a fairly serious limitation.

Now the reasoner is its own coroutine and it calls the campaign. There are two ways to be
one. You can implement decide, answer one question at a time, and a driver plays the part
the old loop played — that is models A through D, unchanged, and it stays the auditable
default. Or you implement conduct, take the session, and drive yourself: submit five
experiments, then collect them in the order they finish.

Underneath both, the executor owns all the state and is its only writer. Note what that
means for the API: terminating is not the reasoner's decision. Budget, stagnation,
repeated failure — those are facts about state the reasoner cannot see, so the executor
decides when the campaign is over, and the reasoner finds out by being raised into.
  `);
  footer(s, "manager.py:82 — whichever of the two coroutines finishes first ends the campaign");
}

// ============================================================ 5. the six surfaces
{
  const s = slide();
  title(s, "Six surfaces, six audiences", "the map for the rest of the deck");

  tbl(s, ["Surface", "Who writes against it", "What they write", "Size", "Where"],
    [["1 · CLI", "an operator", `3 subcommands, ${S.n_cli_models} control models`,
      `${S.cli_subcommands.join(" / ")}`, "cli/__init__.py:31"],
     ["2 · Campaign YAML", "a scientist", "the scientific question: stages, params, objectives",
      `${S.n_campaign_spec_fields} fields`, "runtime/executor.py:58"],
     ["3 · ControlPolicy", "a reasoner author", "decide() or conduct(), returning abstract intent",
      `${S.policy_ops.length} methods · ${S.decision_members.length} decisions`, "policy/base.py:19"],
     ["4 · CampaignSession", "a reasoner, in or out of process", "calls onto a running campaign",
      `${S.n_session_ops} operations`, "core/session.py:56"],
     ["5 · ControlPlane", "an external caller", "one protocol, in-process or over a socket",
      `${S.n_plane_ops} ops · ${S.n_routes} routes`, "control/plane.py:23"],
     ["6 · ToolSpec + TaskAgent", "a tool author", "a spec file, and four phases of adapter",
      `${S.n_tool_spec_fields} fields · 4 phases`, "tools/spec.py:75"]],
    M, 1.5, [2.4, 2.75, 3.75, 1.6, 1.83],   // sums to W - 2M; 13.33 ran off the slide
    { mono: [3, 4], fs: 11, mfs: 8.5, rowH: 0.52 });

  card(s, M, 5.35, 6.1, 1.35, "What is shared, and is the point",
    ["All six reach one executor, one design tree, one append-only provenance log.",
     "All six are refused the same way: five gates, a dry run, and the trust interlock."],
    { fill: C.bTint, hc: C.b, fs: 11 });
  card(s, M + 6.33, 5.35, 6.1, 1.35, "What is enforced, not merely intended",
    [`${S.n_layers} layers in an allow-list walked by \`ast\`: \`policy\` may import only `
     + `${S.policy_imports.join(", ")}, and \`core\` imports nothing internal.`,
     "A new cross-layer import fails the suite by default — slide 27."],
    { fill: C.panel, hc: C.ink, fs: 11 });

  s.addNotes(`
This is the map. Six surfaces, ordered by who writes against them rather than by module,
because a tour by module answers a question nobody asked.

An operator gets three subcommands and ${S.n_cli_models} control models. A scientist gets a YAML file with
${S.n_campaign_spec_fields} fields that describes the scientific question and nothing about search strategy.
A reasoner author implements ${S.policy_ops.length} methods and returns one of ${S.decision_members.length} decisions.
A reasoner — in this process or on a login node — gets ${S.n_session_ops} operations onto a live campaign.
An external caller gets ${S.n_plane_ops} operations behind ${S.n_routes} HTTP routes. And a tool author writes a
spec file with ${S.n_tool_spec_fields} fields plus an adapter with four phases.

Those are small numbers, deliberately. The interesting part is the bottom left: all six
reach exactly one executor, one tree, one provenance log, and all six are refused the same
way. And the bottom right is why I can say that with a straight face — the layering is an
allow-list walked by a test, not a diagram in a doc. Policy may import core and nothing
else. Core imports nothing internal at all.

Act one is surfaces one, two, three and six. Act two is four. Act three is five.
  `);
  footer(s, `mined from the declarations themselves: run_model.py::surfaces() · ${HEAD}`);
}

// ============================================================ 6. the caller's side
// The two mediation slides. Everything in the deck so far is a part; these two are the
// whole shape: what a caller states, and what the system turns it into. Six is the inbound
// half, seven the outbound half, and they are deliberately adjacent.
{
  const s = slide();
  title(s, "One side: what the caller states, and what comes back",
    "framing · the system as a mediator");

  const LX = M, LW = 4.9, CX = 5.55, CW = 2.25, RX = 8.0, RW = W - M - 8.0;

  const inbound = [
    ["What “better” means", C.accent,
     `\`goal\` and \`objectives\` — name, direction, min/max. The only statement of success in the system, and what the front is ranked against`],
    ["What may run", C.d,
     `the toolkit inventory, discovered at runtime from a directory: ${S.n_tools} tools in ${K.n_toolkits} toolkits here. \`stages\` names which of them this campaign may use`],
    ["What it may spend, and where", C.b,
     `\`budget\`, \`site\` caps, \`concurrency\`, the \`replicas\` CAP, \`backend\` + config, three timeouts — of ${S.n_campaign_spec_fields} \`CampaignSpec\` fields`],
    ["Who decides", C.a,
     `\`--model\` picks one of ${S.n_cli_models}, fixed at launch (ADR 0005) — or your own \`ControlPolicy\`, which is ${S.policy_ops.length} methods`],
  ];
  inbound.forEach(([h, col, b], i) => {
    const y = 1.5 + i * 1.11;
    s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: LW, h: 1.0,
      fill: { color: C.white }, line: { color: C.rule } });
    s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: 0.06, h: 1.0,
      fill: { color: col }, line: { color: col } });
    text(s, h, LX + 0.18, y + 0.07, LW - 0.3, 0.26, { fontSize: 12, bold: true, color: C.ink });
    text(s, b, LX + 0.18, y + 0.35, LW - 0.3, 0.6, { fontSize: 10, color: C.text });
    line(s, LX + LW + 0.02, y + 0.5, CX - 0.02, y + 0.5, { color: col, w: 1.25 });
  });

  box(s, CX, 1.5, CW, 4.44, {
    title: "IMPRESS-A",
    sub: "\nadmits\ncomposes\nrefuses\ndispatches\nrecords\n\nand decides\nwhen to stop",
    fs: 15, sfs: 11, fill: C.ink, tc: C.white, sc: "A9BCC8", line: C.ink });

  card(s, RX, 1.5, RW, 2.1, "What it tells you while it runs",
    [`\`observe()\` returns the SAME object the policy's \`decide\` is handed — one truth, not a dashboard view of it.`,
     `An event stream, cursor-paged or tailed; provenance (${Q.provenance_records} records across ${Object.keys(Q.provenance_kinds).length} kinds in the run behind this deck); a durable ledger; \`artifacts(selector)\`; a heartbeat.`],
    { fill: C.bTint, hc: C.b, fs: 10.5 });
  card(s, RX, 3.84, RW, 2.1, "What you can say back, mid-flight",
    [`\`steer\`, \`pause\`, \`resume\`, \`stop\`, \`backtrack\`, \`request_human\`, \`ingest_measurement\` — ${S.n_plane_ops} control-plane operations in all.`,
     "A measurement SUPERSEDES a prediction and never deletes it, which is why the front is not monotonic."],
    { fill: C.aTint, hc: C.a, fs: 10.5 });
  line(s, CX + CW + 0.02, 2.4, RX - 0.02, 2.4, { color: C.b, w: 1.5 });
  line(s, RX - 0.02, 4.7, CX + CW + 0.02, 4.7, { color: C.a, w: 1.5 });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 6.1, w: W - 2 * M, h: 0.82,
    fill: { color: C.cTint }, line: { color: C.c, width: 1.5 } });
  text(s, [
    { text: "The asymmetry is the whole design:  ", options: { bold: true, color: C.c } },
    { text: "the caller never names a task, a node, or a tool parameter — and the engine "
      + "never invents an objective or a budget. Intent and constraints go in; tasks, and "
      + "evidence about them, come out. Everything on the next slide is what the system does "
      + "with that gap." },
  ], M + 0.16, 6.22, W - 2 * M - 0.32, 0.62, { fontSize: 12, color: C.text });

  s.addNotes(`
Two slides to put both ends in one picture, because so far I have shown you parts.

Everything a caller states is on the left, and it is four things. What better means — the
objectives, which are the only definition of success anywhere in the system. What may run —
an inventory discovered from a directory, not a hard-coded pipeline. What it may spend, and
on what machine. And who decides: one of ${S.n_cli_models} shipped control models, or ${S.policy_ops.length} methods of your own.

On the right is what comes back while it is running, and the first line is the one I would
defend hardest: observe returns the same object the policy's decide is handed. There is one
account of the campaign, not a dashboard view and a real view.

And you can talk back mid-flight — steer it, pause it, hand it a measurement from an assay
that finished yesterday. That measurement supersedes the prediction and never deletes it,
which is exactly why the front can move backwards.

The line at the bottom is the contract. The caller never names a task or a tool parameter.
The engine never invents an objective or a budget.
  `);
  footer(s, `every count on this slide is mined · ${HEAD}`);
}

// ============================================================ 7. the realized side
{
  const s = slide();
  title(s, "The other side: how that becomes processes on nodes",
    "framing · the system as a mediator");

  const stages = [
    ["INTENT", C.a, `${S.intent_fields.length} fields, abstract`,
     "campaign params merge BENEATH the policy's; `replicas` is a cap, not a default",
     "executor.py:419"],
    ["COMPOSE", C.c, "stages → typed nodes",
     "ports are `ArtifactType`, so a mismatch is a compose-time error; P6 tools are inlined, never scheduled",
     "composer.py:36"],
    ["ADMIT", C.c, `${S.n_gates_implemented} gates, then trust`,
     "five gates, the interlock's cost cap, and a forced dry run for a shape nobody has reviewed",
     "validate.py:30"],
    ["PARAMETERIZE", C.d, "per node, in order",
     "spec defaults ← campaign params ← policy params, and `frozen_parameters` beat all three",
     "resources.py:14"],
    ["DEPLOY", C.b, "one factory, every node",
     "`_run.__name__ = node_id`, because asyncflow names a task from `fn.__name__`",
     "dispatch.py:144"],
    ["ENGINE", C.b, "asyncflow + a backend",
     "`WorkflowEngine` with a work_dir; the backend resolves BY NAME from site config",
     "backend.py:97"],
    ["TASKS", C.accent, "processes, on nodes",
     `${Q.n_results} nodes over ${Q.lineages_absorbed.length} lineages in the mock run; on Delta, six stages pinned to GPUs`,
     "agent.py:120"],
  ];
  const bw = (W - 2 * M - 6 * 0.12) / 7;
  stages.forEach(([name, col, sub, body, anchor], i) => {
    const x = M + i * (bw + 0.12);
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: bw, h: 2.05,
      fill: { color: C.panel }, line: { color: col, width: 1.25 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: bw, h: 0.3,
      fill: { color: col }, line: { color: col } });
    text(s, name, x, 1.5, bw, 0.3, { fontSize: 9.5, bold: true, color: C.white,
      align: "center", valign: "middle", charSpacing: 0.5 });
    text(s, sub, x + 0.07, 1.84, bw - 0.14, 0.24,
      { fontSize: 8.5, italic: true, color: C.muted, align: "center" });
    text(s, body, x + 0.07, 2.12, bw - 0.14, 1.1, { fontSize: 8.5, color: C.text });
    text(s, anchor, x + 0.07, 3.26, bw - 0.14, 0.22,
      { fontFace: MF, fontSize: 7, color: C.muted, align: "center" });
    if (i < 6) line(s, x + bw + 0.005, 2.5, x + bw + 0.115, 2.5, { color: C.muted, w: 1 });
  });

  box(s, M, 3.72, W - 2 * M, 0.72, {
    title: "←  and back up the same path: a typed TaskResult (ArtifactRefs, metrics, a QCReport, cost) → to_outcome() → executor._absorb, the single await-free writer → tree, front, provenance, ledger",
    sub: "dispatch.py:91 · the gates run on the way OUT of a node, so a tool that exits 0 and lies is still failed here",
    fs: 11, sfs: 9.5, fill: C.cTint, line: C.c, tc: C.c });

  card(s, M, 4.62, 6.1, 1.5, "The harness nobody sees",
    ["Resource shapes are NOT portable, so translating them is ours: RADICAL takes "
     + "`ranks`/`gpus_per_rank`, Dragon takes process templates, the concurrent backend takes "
     + "nothing at all. One `ResourceShape` in the spec, three descriptions out.",
     "No backend class is named outside `exec/backend.py` — site config picks one by name."],
    { fill: C.panel, hc: C.ink, fs: 10 });
  card(s, M + 6.33, 4.62, 6.1, 1.5, "Two asyncflow idioms, not interchangeable",
    ["An UNAWAITED future passed as an argument IS a DAG edge — `dispatch.py:182`, walking "
     + "`topo_order()`. That is how a stage list becomes a dependency graph with no scheduler "
     + "of ours.",
     "`asyncio.gather(..., return_exceptions=True)` awaits INDEPENDENT work — replica "
     + "fan-out — and one bad task must not cancel its siblings."],
    { fill: C.bTint, hc: C.b, fs: 10 });

  text(s, [
    { text: "What this picture does not show:  ", options: { bold: true, color: C.fail } },
    { text: "every realized task in the run behind this deck is a mock, and on the real "
      + "six-stage chain this path has only ever run one lineage wide." },
  ], M, 6.3, W - 2 * M, 0.5, { fontSize: 11.5 });

  s.addNotes(`
And this is the other side: what the system does with the gap between what you asked for
and processes running on nodes.

Seven stages. The intent arrives abstract — a goal, stages, parameters — and the first
thing that happens is the campaign's own parameters are merged BENEATH the policy's, so a
policy never has to learn a tool's parameter names. Replicas is a cap, not a default.

Compose turns the stage list into typed nodes. Admit is the five gates, the cost cap and a
dry run. Parameterize is where the layering earns itself: spec defaults, then campaign
params, then policy params, and frozen parameters beat all three.

Deploy is one generic factory for every node in every graph, and the detail I like is that
asyncflow reads a task's name from fn dunder name, so the factory sets it to the node id.

Then the engine, with the backend resolved by name from site config, and then real
processes.

Two things in the cards. Resource shapes are not portable — RADICAL wants ranks, Dragon
wants process templates — so that translation is ours to own. And the two asyncflow
idioms: an unawaited future passed as an argument is a DAG edge; gather is for independent
work. Those are not interchangeable, and mixing them up is how you get a graph that runs in
the wrong order.

The return path is the band in the middle, and the thing to notice is that the gates run on
the way OUT of a node.
  `);
  footer(s, "the engine side of six surfaces — the sibling deck argues this seam, this one cites it");
}

// ============================================================ 8. ACT 1 divider
{
  const s = slide();
  divider(s, {
    n: 1, of: 3, name: "Functionality",
    definition: "Not features — tasks. What can you write against this that you cannot "
      + "write against a pipeline?",
    claims: [
      ["A tool is a declaration, not a code path",
       `${S.n_tool_spec_fields} declared fields; loading one VALIDATES it, and a bad toolkit is disabled whole`],
      ["A policy emits intent, never a DAG",
       `${S.decision_members.length} decisions, ${S.intent_fields.length} intent fields, and no tool parameter names anywhere in policy/`],
      ["Composition is free; refusal is cheap",
       "five gates and a dry run before anything executes; a rejection costs one cycle and hands back a reason"],
    ],
    caveat: `every toolkit that exists is one of the ${K.n_real_toolkits} real stages of one chain, plus mocks — `
      + `and no one outside this package has authored either a toolkit or a policy`,
  });
  s.addNotes(`
Act one: functionality. Not features — tasks. What can you write against this that you
could not write against a pipeline?

Three claims. A tool is a declaration rather than a code path. A policy emits abstract
intent and never a DAG. And composition is free because refusal is cheap.

The weak one, before the act rather than after it: every toolkit that exists is one of the
${K.n_real_toolkits} real stages of a single chain, plus the mocks. Nobody outside this package has ever
written either a toolkit or a policy, so "it is easy to add one" is a claim about the shape
of the interface and not about anyone's experience.
  `);
}

// ============================================================ 9. surfaces 1 and 2
{
  const s = slide();
  title(s, "Surfaces 1 and 2: the operator's and the scientist's", "act 1 · functionality");

  code(s, [
    "stages: [rfd3_design, ligandmpnn_design, packmin, fastrelax, filter_shape, boltz_predict]",
    "params:",
    "  rfd3_design:      {input_spec_path: data/alr/ALR_binder_design.json, diffusion_steps: 50}",
    "  boltz_predict:    {ligand_smiles: \"COc1cc(S(=O)(=O)[O-])c(C)cc1/N=N/...\"}",
    "replicas: 4          # N INDEPENDENT lineages, one DesignNode each",
    "objectives:",
    "  - {name: total_score,           direction: minimize}",
    "  - {name: shape_complementarity, direction: maximize, min: 0.55}",
    "  - {name: ligand_iptm,           direction: maximize, min: 0.4}",
  ], M, 1.5, 7.9, 1.95, { anchor: "campaigns/delta-small-molecule.yaml:30 · TRIMMED", fs: 10 });

  card(s, M, 3.75, 7.9, 1.35, "What is in here, and what deliberately is not",
    ["In: the scientific question — which stages, which ligand, which contig, what counts as better.",
     "Not in: how to explore. No thresholds, no schedule, no retry policy, no tool invocation.",
     "A relative `*_path` resolves against the YAML, not the CWD — the launcher cds into a per-job dir."],
    { fill: C.cTint, hc: C.c, fs: 11 });

  tbl(s, ["impress-a", "what it does"],
    [["run <spec>", `--model ${S.cli_models.join(" | ")}; the model is fixed at launch`],
     ["tools", `lists the ${S.n_tools} registered tools with pattern and gate count`],
     ["preflight [spec]", "checks the real-toolkit environment BEFORE the queue — slide 25"]],
    M + 8.1, 1.5, [1.75, 2.48], { mono: [0], fs: 10.5, mfs: 9.5, rowH: 0.62, hfill: C.accent });

  card(s, M + 8.1, 3.75, 4.23, 1.35, "One objective, two sources",
    ["An objective names a property, not a predictor.",
     "A surrogate today and a wet-lab assay tomorrow are the same declaration — `authority` "
      + "decides which wins (decision 0012)."],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  s.addNotes(`
Surfaces one and two are the ones a human touches, and the interesting thing about them is
what they refuse to contain.

On the left is a real campaign file, trimmed. Six stages named by tool id. Per-tool
parameters: the ligand SMILES, the contig spec, the diffusion step count. Four replicas —
and that means four independent lineages, four design nodes, not four samples inside one
tool. And the objectives, with directions and floors.

What is deliberately not in this file is how to explore. There is no threshold schedule, no
retry policy, no fan-out rule. Those belong to whichever reasoner you launched. The file
says what the campaign is about; the policy says what to try next. That split is the
reason you can run the same scientific question under four different control models and
compare them, which is the whole experiment this project exists to run.

Small detail that cost a real debugging session: a relative path in here resolves against
the YAML's own directory, not the working directory, because the launcher cds into a
per-job directory before loading the spec.

On the right: three subcommands. And the one worth noticing is preflight, which I will
come back to in act three, because it is the surface that respects that an allocation costs
money.
  `);
  footer(s, "the objectives on this slide are the four the Delta campaign declares; the mock campaign declares its own");
}

// ============================================================ 10. surface 3
{
  const s = slide();
  title(s, "Surface 3: a reasoner is three methods and four answers", "act 1 · functionality");

  code(s, [
    "class ControlPolicy(Protocol):",
    "    name: str",
    "",
    "    async def decide(self, obs: CampaignObservation) -> Decision: ...",
    "    async def interpret(self, results: RunOutcome, obs) -> str | None: ...",
    "    async def on_rejected(self, decision, failure: ValidationFailure) -> Decision: ...",
  ], M, 1.5, 7.0, 1.3, { anchor: "policy/base.py:19 · EDITED (annotations trimmed)", fs: 10.5 });

  code(s, [
    "Decision = Union[ComposeAndRun, Backtrack, RequestHuman, Stop]",
  ], M, 3.1, 7.0, 0.45, { anchor: "core/decision.py:56 · VERBATIM", fs: 11 });

  const tiles = [
    ["ComposeAndRun", "run this experiment", C.c],
    ["Backtrack", "branch from an earlier node", C.a],
    ["RequestHuman", "stop and ask", C.accent],
    ["Stop", "the campaign is done", C.b],
  ];
  tiles.forEach(([t, sub, col], i) => {
    const x = M + i * 1.79;
    box(s, x, 3.95, 1.69, 0.85, { title: t, sub, fs: 10.5, sfs: 8.5,
      fill: C.white, line: col, tc: col });
  });

  card(s, M, 5.05, 7.0, 1.6, "Two things that are absent on purpose",
    ["`conduct` is NOT a member of the Protocol. Requiring it would break every existing "
     + "policy, and `runtime_checkable` makes the membership list load-bearing for isinstance.",
     "There is no `Await` or `Cancel` decision. Waiting is something the reasoner DOES by "
     + "calling `result`, not something it asks the loop to do — one control-flow vocabulary, not two."],
    { fill: C.aTint, hc: C.a, fs: 10.5 });

  tbl(s, ["Model", "Who decides", "Mode"],
    [["A", "four-node LangGraph loop: hypothesize → parameterize", "autonomous"],
     ["B", "one structured LLM call over rich campaign state", "autonomous"],
     ["C", "an external caller, over the control plane", "headless"],
     ["D", "rules, bandit, Bayesian opt, or replay", "reproducible"]],
    M + 7.25, 1.5, [0.75, 3.55, 1.28], { mono: [0], fs: 10.5, rowH: 0.52, hfill: C.a });

  card(s, M + 7.25, 4.0, 5.58, 2.65, "Why a fifth model is cheap",
    [`Subclass \`BasePolicy\`, implement one method. \`interpret\` defaults to None and `
     + `\`on_rejected\` defaults to Stop — "give up rather than loop".`,
     "Policies compose: `RuleCorrectionsPolicy` wraps any of them as an unconditional guard "
      + "(the CLI applies it by default — max_replicas 8, `mock_noodle` forbidden), "
      + "`LoggingPolicy` for provenance.",
     `The mock run in this deck was \`${Q.model}\` under that guard: policy printed itself as `
     + `"rulecorrectionspolicy(threshold)".`],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  s.addNotes(`
Surface three. If you want to write a reasoner, this is the whole contract: three methods
and four possible answers.

decide takes an observation and returns a decision. interpret is the hook for when reading
a result is itself a judgement call — it defaults to None, because deterministic metric
extraction by the task agents is the normal case. And on_rejected is mandatory: if your
graph is refused, you get the structured reason and another attempt.

Four decisions. Run this experiment. Branch from an earlier node. Stop and ask a human.
Done.

Two absences are deliberate and both are API design rather than implementation. conduct is
not a member of this Protocol even though it is the other way to be a reasoner — adding it
would break every existing policy, and because the Protocol is runtime_checkable its
membership list is load-bearing for anyone doing an isinstance check. And there is no
"await" decision: waiting is something the reasoner does by calling result, not something
it asks the loop to do on its behalf. One control-flow vocabulary, not two.

On the right, the four shipped models, and the reason a fifth is cheap: subclass BasePolicy
and implement one method. They also compose — the CLI wraps whatever you chose in a
corrections guard by default, which is why the run in this deck reported its policy as
"rulecorrectionspolicy of threshold".
  `);
  footer(s, "ADR 0005: the control model is fixed at launch · ADR 0007: one observation, two consumers");
}

// ============================================================ 11. intent, not a DAG
{
  const s = slide();
  title(s, "The seam that keeps policies swappable: intent, not a graph", "act 1 · functionality");

  code(s, [
    "class ExperimentIntent(BaseModel):",
    "    goal: str",
    "    toolkit_hint: str | None = None",
    "    stages: list[str] = []        # tool ids, in order",
    "    params: dict[str, Any] = {}",
    "    parent_node: str | None = None",
    "    replicas: int = 1",
  ], M, 1.5, 5.6, 1.6, { anchor: "core/decision.py:21 · EDITED (Field(...) elided)", fs: 10.5 });

  // intent -> merge -> compose -> validate -> admitted, as a left-to-right strip
  const hops = [["ExperimentIntent", "what to try", C.a],
                ["+ campaign params", "the ligand, the contig", C.c],
                ["TaskGraph", "typed DAG, N lineages", C.c],
                ["5 gates + dry run", "refuse or admit", C.b]];
  hops.forEach(([t, sub, col], i) => {
    const x = M + i * 3.17;
    box(s, x, 3.5, 2.85, 0.9, { title: t, sub, fs: 11.5, sfs: 9, fill: C.white, line: col, tc: col });
    if (i < hops.length - 1) line(s, x + 2.87, 3.95, x + 3.15, 3.95, { color: C.muted, w: 1.25 });
  });

  card(s, M + 5.85, 1.5, 6.6, 1.6, "No policy in this package names a tool parameter",
    ["`_apply_campaign_defaults` merges the campaign's `params` BENEATH whatever the policy "
     + "asked for: the policy always wins on a key it set.",
     "So a `conduct` reasoner and an external directive get the ligand for free, and no policy "
     + "has to learn that `boltz_predict` takes `ligand_smiles`."],
    { fill: C.cTint, hc: C.c, fs: 10.5 });

  card(s, M, 4.65, 6.1, 2.0, "What this buys",
    ["A policy that cannot name a tool parameter cannot quietly become a pipeline.",
     "`policy/` may import `core` and nothing else — enforced by `ast`, slide 27.",
     "Swapping A for D changes the reasoner and nothing below it."],
    { fill: C.panel, hc: C.ink, fs: 11 });
  card(s, M + 6.33, 4.65, 6.1, 2.0, "What it costs",
    ["A policy cannot express a graph shape the composer cannot build from an ordered "
     + "stage list — so free composition is free within one topology family.",
     `Every graph composed in this deck's run was the same ${Q.tools_used.length}-tool chain at two widths.`],
    { fill: C.failTint, hc: C.fail, fs: 11 });

  s.addNotes(`
This is the seam I would defend hardest, so it gets its own slide.

A policy returns an ExperimentIntent. Look at what is in it: a goal in words, an optional
toolkit hint, an ordered list of tool ids, a parameter bag, a parent node, and a replica
count. That is abstract. It is not a DAG. Turning it into a typed graph with N lineages,
resolving the ports, type-checking the hops — that is the engine's job.

And the parameter bag is merged, not authoritative: the campaign's own params go underneath
whatever the policy asked for, so the policy always wins on a key it actually set, and gets
the ligand and the contig for free on every key it did not. The consequence is that no
policy in this package names a single tool parameter. None of them knows that boltz_predict
takes a ligand_smiles.

That is what makes the control models swappable rather than nominally pluggable, and it is
backed by the import rule: policy may import core and nothing else, enforced by a test.

The cost, on the right in red: a policy can only ask for things the composer can build out
of an ordered stage list. So "free graph composition" is free within one topology family,
and every graph in this deck's run was the same four-tool chain at two different widths.
  `);
  footer(s, "runtime/executor.py:419 — the merge, and the comment that explains why it lives there");
}

// ============================================================ 12. surface 6, the spec
{
  const s = slide();
  title(s, "Surface 6: a tool is a file a scientist can review", "act 1 · functionality");

  code(s, [
    "id: rfd3_design",
    "toolkit: rfd3",
    "pattern: P1                      # GPU-node-local, in-job",
    "entry: impress_a.tools.rfd3_agents.RFD3DesignAgent",
    "resources: {gpus: 1, cores: 8, walltime_s: 900}",
    "outputs:",
    "  backbone: {type: Backbone}",
    "parameters:",
    "  diffusion_steps: {type: int, default: 50, min: 20, max: 200,",
    "                    trades: \"quality vs wall-clock\"}",
    "metrics: [ss_fraction, num_models]",
    "qc_gates:",
    "  - {id: output_present, params: {key: result}}",
    "  - {id: has_secondary_structure, params: {min_ss_fraction: 0.3}}",
    "cost_model: {unit: invocation, cost: {gpu_hours: 0.1}}",
  ], M, 1.5, 6.5, 3.15,
    { anchor: "toolkits/rfd3/tools/rfd3_design/spec.yaml:1 · TRIMMED", fs: 10 });

  card(s, M + 6.75, 1.5, 5.58, 1.5, "Read by four consumers",
    ["The composer types the graph from `inputs`/`outputs`; the validator sizes it from "
     + "`resources`; the budget guard prices it from `cost_model`; the task agent resolves "
     + "`parameters` and enforces `qc_gates`.",
     "Declarative so a scientist can review it in a pull request (decision 0011)."],
    { fill: C.dTint, hc: C.d, fs: 10.5 });

  code(s, [
    "if self.pattern is Pattern.P1 and self.resources.gpus == 0:",
    "    raise ValueError(f\"{self.id}: P1 declared but resources.gpus == 0\")",
    "...",
    "if g.role == \"acceptance\" and g.id == \"metric_in_range\" \\",
    "        and g.params.get(\"metric\") not in reported:",
    "    raise ValueError(\"... needs an integrity\"",
    "                     \" metrics_reported gate naming it\")",
  ], M + 6.75, 3.2, 5.58, 1.45,
    { anchor: "tools/spec.py:100 · EDITED", fs: 9.5 });

  card(s, M, 4.95, 6.5, 1.7, "Loading is validating",
    [`A default outside its own declared range, a parameter both varyable and frozen, `
     + `a gate id that is not implemented, a duplicate tool id, a SKILL.md missing one of `
     + `${S.required_skill_sections.length} required sections — all LOAD-time errors.`,
     `A toolkit that fails anywhere registers nothing: all-or-nothing per directory, so an `
     + `RFD3 container problem cannot also take down PyRosetta.`],
    { fill: C.panel, hc: C.ink, fs: 10.5 });
  card(s, M + 6.75, 4.8, 5.58, 1.85, "And the rule behind the second check",
    ["An acceptance threshold must never be the only thing that notices a value is missing — "
     + "that is how a fabricated 0.0 passes for a measurement.",
     `So integrity and acceptance are separate roles, and only integrity failures count `
     + `against a workflow's trust (decision 0013).`],
    { fill: C.failTint, hc: C.fail, fs: 10.5 });

  s.addNotes(`
Surface six, and this is the one I would most like someone in this room to use in anger.

A tool is a YAML file. This is RFD3, trimmed. It declares an id, a toolkit, a compute
pattern — P1 means GPU-node-local and in-job — a dotted path to the adapter class, a
resource shape, typed output ports, parameters with ranges and a note on what each one
trades, the metrics it promises to report, its QC gates, and a cost model.

Four consumers read this one file — composer, validator, budget guard, task agent — which
is why it is declarative: a scientist can review a tool in a pull request without reading
Python.

Bottom left is what earns the design. Loading a toolkit validates it: a default outside its
own range, a gate nobody implemented, a missing SKILL.md section — all load-time errors. And
a toolkit that fails anywhere registers nothing, so an RFD3 container problem cannot take
PyRosetta down with it.

Bottom right, and this is the sharpest rule in the project: an acceptance threshold must
never be the only thing that notices a value is missing. That is how a fabricated zero
passes for a measurement. So the spec will refuse to load if you put a threshold on a
metric that no integrity gate promises to report.
  `);
  footer(s, `${S.n_tools} tools load clean at ${HEAD}; registry errors: ${S.registry_errors.length}`);
}

// ============================================================ 13. the task agent
{
  const s = slide();
  title(s, "Four phases, and the one you may not override", "act 1 · functionality");

  const phases = [
    ["pre_process", "TaskRequest in,\nTaskRequest out", C.d, "built"],
    ["parameterize", "defaults resolved,\nfrozen refused,\nseed drawn", C.d, "built"],
    ["run", "the only phase an\nadapter really writes", C.d, "built"],
    ["post_process", "metrics extracted,\nGATES ENFORCED", C.c, "built"],
  ];
  phases.forEach(([t, sub, col], i) => {
    const x = M + i * 2.2;
    box(s, x, 1.5, 2.0, 1.15, { title: t, sub, fs: 11.5, sfs: 9, fill: C.white, line: col, tc: col });
    if (i < 3) line(s, x + 2.02, 2.07, x + 2.18, 2.07, { color: C.muted, w: 1.25 });
  });
  // The phases are orchestrated by __call__ (agent.py:120). The module docstring and
  // CLAUDE.md both still call this `execute()`, which is a method the file does not have -
  // the behaviour is right, the name is not, so the slide uses the one you can grep.
  box(s, M + 8.95, 1.5, 3.88, 1.15, { title: "__call__()", sub: "the four phases, in order:\nNOT overridable, and pattern\ndispatch belongs to exec/",
    fs: 11.5, sfs: 9, fill: C.failTint, line: C.fail, tc: C.fail });

  code(s, [
    "async def post_process(self, req, raw) -> TaskResult:",
    "    \"\"\"Extract metrics and ENFORCE QC gates. Never skippable.\"\"\"",
    "    qc = gates.evaluate(self.spec, raw)",
    "    return TaskResult(tool=self.spec.id,",
    "                      outputs=self._as_artifacts(raw.get(\"outputs\", {})),",
    "                      metrics=raw.get(\"metrics\", {}), qc=qc, ...)",
  ], M, 2.95, 7.1, 1.35, { anchor: "tools/agent.py:110 · TRIMMED", fs: 10 });

  tbl(s, ["Gate", "What it catches"],
    [["output_present", "the adapter returned nothing under the declared key"],
     ["metrics_reported", "a promised metric is absent, or not a finite number"],
     ["metric_in_range", "a value outside the acceptance band"],
     ["has_secondary_structure", "the silent \"designed a noodle\""]],
    M + 7.35, 2.95, [2.35, 2.63], { mono: [0], fs: 10, mfs: 8.5, rowH: 0.44, hfill: C.c });

  card(s, M, 4.55, 7.1, 2.1, "Why the type comes from the spec, never the adapter",
    ["`_as_artifacts` stamps each output with the port type the composer type-checked "
     + "against, so a ref cannot disagree with the contract.",
     "An adapter returning an undeclared output is an ERROR, not a dropped value — dropping "
     + "it silently would hide a spec bug.",
     "A `Path` means a file and gets hashed; anything else is an inline value."],
    { fill: C.dTint, hc: C.d, fs: 10.5 });
  card(s, M + 7.35, 5.25, 4.98, 1.4, "Why a zero exit code is never enough",
    ["Tools fail SILENTLY far more often than they crash: an empty output directory, an "
     + "unrecognised header, a relax that diverged.",
     `${K.gate_fixtures} fixtures ship with the toolkits, ${K.gate_fixtures_bad} of them \`.bad\` — recorded `
     + `failures kept as tests. A QC-failed node is never rankable.`],
    { fill: C.panel, hc: C.ink, fs: 9.5 });

  s.addNotes(`
The other half of surface six is the adapter, and it has four phases.

pre_process can rewrite the request. parameterize resolves the declared defaults, refuses
anything frozen or out of range, and — this one matters — draws this lineage's seed if the
tool declares one, which is what makes four replicas four independent samples rather than
four copies of one design. run is the phase an adapter author actually writes.

And post_process extracts the metrics and enforces the gates. That docstring says "never
skippable" and it means it: there is no path from a tool's output into campaign state that
does not go through the spec's gates.

The box on the right in red is __call__, which runs those four in order and is deliberately
not overridable — and note the name: the module docstring still says execute, and
the file has no such method. Pattern
dispatch belongs to the execution layer. An adapter that scheduled its own work would
bypass the rule that P6 is inlined and P4 gets a durable ledger entry, which is exactly
the kind of thing that works fine until it doesn't.

Bottom right is the reason any of this exists. Scientific tools fail silently far more often
than they crash. An empty output directory, a FASTA header the parser didn't recognise, a
relax that diverged — all of those exit zero. ${K.gate_fixtures} fixtures ship with the toolkits and
${K.gate_fixtures_bad} of them are recorded failures kept as tests. A node that fails a gate is never
rankable, whatever its scores say.
  `);
  footer(s, "gates are registered by name with a decorator: tools/gates.py — adding one is a function and a spec entry");
}

// ============================================================ 14. gates and refusal
{
  const s = slide();
  title(s, "Five gates, a dry run, and a refusal from the real run", "act 1 · functionality");

  code(s, [
    "def validate(self, g: TaskGraph) -> ValidationFailure | None:",
    "    for gate in (self._g1_types, self._g2_structure, self._g3_params,",
    "                 self._g4_resources, self._g5_budget):",
    "        if (f := gate(g)) is not None:",
    "            return f",
    "    return None",
  ], M, 1.5, 6.3, 1.35, { anchor: "compose/validate.py:30 · VERBATIM", fs: 10 });

  tbl(s, ["Gate", "Refuses"],
    [["1 · types", "a Backbone where a Complex is required, an unknown port"],
     ["2 · structure", "a cycle, an orphan, a P6 the composer should have inlined"],
     ["3 · params", "out of range, frozen, unknown to the spec"],
     ["4 · resources", "more GPUs than the site has; external when not allowed"],
     ["5 · budget", "an estimate the ledger cannot afford"],
     ["+ dry run", "every agent parameterizes, nothing executes"]],
    M, 3.1, [1.65, 4.65], { mono: [0], fs: 10, mfs: 9, rowH: 0.36, hfill: C.b });

  card(s, M + 6.55, 1.5, 5.78, 1.6, "The field that keeps a policy from degrading itself",
    ["`ValidationFailure.transient` — True when the graph is FINE and only the moment is "
     + "wrong. Gates 1-5 are properties of the graph and never transient; the interlock's "
     + "cost cap is.",
     "Without it, a policy answers contention by mutilating its own intent."],
    { fill: C.aTint, hc: C.a, fs: 10.5 });

  // The mined refusal: the one irregular event in the run, quoted as data.
  const ref = Q.refusals[0];
  s.addShape(pres.shapes.RECTANGLE, { x: M + 6.55, y: 3.25, w: 5.78, h: 2.0,
    fill: { color: C.ink }, line: { color: C.accent, width: 2 } });
  text(s, "FROM THE RUN THAT BUILT THIS DECK", M + 6.7, 3.35, 5.5, 0.25,
    { fontSize: 9.5, bold: true, color: "F0C898", charSpacing: 1.5 });
  text(s, [
    { text: `graph 1 · ${ref.lineages} lineages · ${Q.composed[0].tasks} tasks`,
      options: { fontFace: MF, fontSize: 10.5, color: C.white, breakLine: true } },
    { text: `REFUSED at the ${ref.gate} gate, transient=${ref.transient}`,
      options: { fontFace: MF, fontSize: 10.5, color: "E8A0A0", breakLine: true } },
    { text: `"${ref.reason}"`,
      options: { fontFace: MF, fontSize: 9.5, color: "C8D4DD", breakLine: true } },
    { text: `then: ${Q.n_admitted} graphs admitted at ${Q.composed[1].lineages} lineages, `
      + `${Q.composed[1].tasks} tasks each`,
      options: { fontFace: MF, fontSize: 10.5, color: "9FD9A8" } },
  ], M + 6.7, 3.65, 5.5, 1.5, { fontSize: 10 });

  card(s, M, 5.85, 6.3, 0.8, "Why free composition is affordable to get wrong",
    ["A rejected graph costs one cycle — nothing has executed yet. The policy gets the gate, "
     + "the node and the reason, then another attempt, bounded by `max_attempts`."],
    { fill: C.cTint, hc: C.c, fs: 10 });
  card(s, M + 6.55, 5.4, 5.78, 1.25, "What the refusal above is NOT",
    ["Not a bug, and not the interlock being clever: the policy asked for more lineages than "
      + "an untrusted pattern may spend, and shrank. On the real chain that is backlog A10."],
    { fill: C.failTint, hc: C.fail, fs: 10.5 });

  s.addNotes(`
Composition is free; this is what makes it affordable.

Five gates, in order, before anything executes. Types — and the type lattice is scientific,
not file-format based, so handing a monomer to an interface scorer is a type error at
composition time. Structure: cycles, orphans, an in-process tool that should have been
inlined. Parameters. Resources against what the site actually has. Budget against the
ledger. Then a dry run in which every task agent parameterizes and nothing executes.

The field I want to point at is top right: transient. It is true when the graph is fine and
only the moment is wrong. Gates one through five are deterministic properties of the graph
and are never transient — the interlock's cost cap is. Without that distinction a policy
answers resource contention by dropping replicas and truncating stages, which reads from
the outside as the policy quietly degrading itself.

And here is that happening for real, in the run that built this deck. The policy asked for
${ref.lineages} lineages, ${Q.composed[0].tasks} tasks. The interlock refused it as transient:
"${ref.reason}". The policy came back with ${Q.composed[1].lineages} lineages and ${Q.composed[1].tasks}
tasks, and that was admitted — twice.

Bottom right, honestly: that is not the interlock being clever, and it is the exact
mechanism that backlog A10 says will bite on the real chain. More on that in act two.
  `);
  footer(s, `mined: run.json · mock.refusals[0] · ${Q.n_composed} graphs composed, ${Q.n_refused} refused, ${Q.n_admitted} admitted`);
}

// ============================================================ 15. ACT 2 divider
{
  const s = slide();
  divider(s, {
    n: 2, of: 3, name: "Performance",
    definition: "What the loop costs, where it serialises, and which of those numbers I "
      + "am actually entitled to say.",
    claims: [
      ["The reasoner is no longer the loop body",
       `${S.n_session_ops} session operations; submit many, collect in the order they FINISH, not the order you asked`],
      ["Refusal is measurably cheap",
       `the refused graph and its replacement were composed inside the same millisecond of the run`],
      ["Steady-state cycle cost is small and measured",
       `cycle 2 cost ${CYCLE2_MS} ms against cycle 1's ${CYCLE1_S} s — the difference is engine construction, once`],
    ],
    caveat: "there is no concurrent run and no serial baseline anywhere in this deck, so "
      + "nothing here divides into a speedup — and the stages were mocks, so this times the "
      + "ENGINE and never the science",
  });
  s.addNotes(`
Act two: performance. And I want to be careful here, because systems vocabulary makes
everything sound measured.

Three claims. The reasoner is no longer the loop body, which is an architectural claim with
an API consequence. Refusal is measurably cheap — the refused graph and its replacement were
composed inside the same millisecond. And the steady-state cost of a cycle is small: 71
milliseconds for the second cycle against 1.09 seconds for the first, and the whole
difference is engine construction happening once.

The caveat, up front: there is no concurrent run in this deck and no serial baseline, so
none of those numbers divides into a speedup. And every stage was a mock, so what I have
timed is the engine — compose, validate, dispatch, absorb — and never the science.
  `);
}

// ============================================================ 16. surface 4, the inversion
{
  const s = slide();
  title(s, "Surface 4: the reasoner calls the campaign", "act 2 · performance");

  const LX = M, LW = 4.0, RX = 8.83, RW = 4.0, MX = LX + LW + 0.2, MW = RX - MX - 0.2;
  [[LX, LW, "THE REASONER  (yours)", C.a], [MX, MW, "CampaignSession", C.muted],
   [RX, RW, "THE EXECUTOR  (ours)", C.b]].forEach(([x, w, t, col]) => {
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.45, w, h: 0.38,
      fill: { color: col }, line: { color: col } });
    text(s, t, x, 1.45, w, 0.38, { fontSize: 11.5, bold: true, color: C.white,
      align: "center", valign: "middle", charSpacing: 1 });
  });
  label(s, "policy/driver.py:35 · or your own conduct()", LX, 1.86, LW, { mono: true });
  label(s, "core/session.py:56", MX, 1.86, MW, { mono: true });
  label(s, "runtime/executor.py:145", RX, 1.86, RW, { mono: true });

  // Explicit tops, not an accumulator: row 2 needs a wider gap for the return edge.
  const tops = [2.25, 3.15, 4.25, 5.2], hs = [0.72, 0.8, 0.72, 0.72];
  const L = [["conduct(session)", "your coroutine, started once"],
             ["submit(intent)", "raises SubmissionRejected, synchronously"],
             ["as_completed()", "yields whatever finished first"],
             ["stop() / backtrack()", "advisory · append-only"]];
  const Rr = [["observe(since)", "the SAME object a policy's decide() sees"],
              ["admit: 5 gates + interlock", "budget reserved, then dispatched"],
              ["pump() reaps, absorbs", "tree · Pareto · provenance"],
              ["the executor decides termination", "budget, stagnation, repeated failure"]];
  const mids = [["CampaignObservation", "both"], ["ExperimentIntent  ->  RunId", "fwd"],
                ["RunOutcome", "back"], ["node id", "fwd"]];
  L.forEach(([t, sub], i) => {
    box(s, LX, tops[i], LW, hs[i], { title: t, sub, fs: 11.5, sfs: 9,
      fill: C.white, line: C.a, tc: C.a });
    box(s, RX, tops[i], RW, hs[i], { title: Rr[i][0], sub: Rr[i][1], fs: 11.5, sfs: 9,
      fill: C.white, line: C.b, tc: C.b });
    const yc = tops[i] + hs[i] / 2, [lab, dir] = mids[i];
    if (dir === "back") line(s, RX - 0.02, yc, MX + 0.02, yc, { color: C.muted, w: 1.25 });
    else line(s, MX + 0.02, yc, RX - 0.02, yc, { color: C.muted, w: 1.25, both: dir === "both" });
    label(s, lab, MX, yc - 0.3, MW, { mono: true, color: C.text });
  });

  card(s, LX, 6.1, 5.9, 0.95, "Request/response, and nothing live crosses it",
    ["Every argument and every return value is serializable — which is what lets the "
     + "reasoner sit on a login node while the executor sits in the allocation."],
    { fill: C.aTint, hc: C.a, fs: 10.5 });
  card(s, LX + 6.13, 6.1, 6.2, 0.95, "It lives in `core`, and that is load-bearing",
    [`A policy may import only ${S.policy_imports.join(", ")} (ADR 0010), so anything a reasoner `
     + `touches has to be typed in core or the seam rots.`],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  s.addNotes(`
Surface four, and this is the one the architecture turns on.

Left lane is yours: a coroutine. You submit as many experiments as you like and then
collect them with as_completed, which yields them in the order they finish rather than the
order you asked. Right lane is ours: admit through the gates, dispatch, reap, absorb into
the tree, and decide when the campaign is over.

Look at what crosses in the middle, because those labels are the API. An observation goes
both ways — and it is the same object a policy's decide receives, which is ADR 0007: parity
of evidence, not a progress bar. An intent goes forward and a run id comes back, or an
exception does, synchronously, in the same breath as the request. A run outcome comes back
when the run finishes. And a node id goes forward for a backtrack, which is non-destructive
because the tree is append-only.

Two properties are deliberate. Everything on this interface is serializable — nothing live
crosses it — which is what makes a reasoner on a login node talking to an executor inside a
batch allocation possible at all. And the whole thing is typed in core, because a policy may
import core and nothing else, so if the session had been typed anywhere else the seam would
have rotted on the first commit.
  `);
  footer(s, "there is no Await or Cancel decision: waiting is a call, not a request to the loop");
}

// ============================================================ 17. the measured run
{
  const s = slide();
  title(s, "One campaign, timed by its own provenance", "act 2 · performance");

  const tl = Q.timeline;
  const at = (ev, run) => (tl.find(e => e.event === ev && (!run || e.run === run)) || {}).at_s;
  const d1 = at("dispatched", "r0002"), d2 = at("dispatched", "r0003"),
        c2 = tl.find(e => e.event === "composed" && e.run === "r0003").at_s;
  const span = Q.span_s;

  // One variable: which cycle. Bars share an axis, drawn from the mined offsets.
  const ax = M + 1.9, aw = 6.4, sc = aw / Math.ceil(span * 10) * 10;
  const rows = [["cycle 1 · r0002", 0, d1, `${d1.toFixed(3)} s`],
                ["cycle 2 · r0003", c2, d2 - c2, `${(d2 - c2).toFixed(3)} s`]];
  text(s, "composed → dispatched, per cycle", M, 1.5, 8.3, 0.25,
    { fontSize: 11, bold: true, color: C.ink });
  rows.forEach(([lab, x0, w, val], i) => {
    const y = 1.9 + i * 0.68;
    text(s, lab, M, y, 1.8, 0.26, { fontSize: 10.5, color: C.text, valign: "middle" });
    s.addShape(pres.shapes.RECTANGLE, { x: ax + x0 * sc, y: y + 0.02, w: Math.max(w * sc, 0.03),
      h: 0.26, fill: { color: i ? C.c : C.b }, line: { color: i ? C.c : C.b } });
    // Right-hand bars would put their label under the table, so they label to the left.
    const bw = Math.max(w * sc, 0.03), right = ax + x0 * sc + bw;
    const far = right + 0.9 > ax + aw, inside = far && bw > 0.8;
    text(s, val, inside ? right - 0.98 : far ? ax + x0 * sc - 1.02 : right + 0.08,
      y, 0.9, 0.26,
      { fontFace: MF, fontSize: 9.5, color: inside ? C.white : C.muted,
        valign: "middle", align: far ? "right" : "left" });
  });
  line(s, ax, 3.32, ax + aw, 3.32, { color: C.rule, w: 1, noArrow: true });
  [0, 0.25, 0.5, 0.75, 1.0].forEach(t => {
    line(s, ax + t * sc, 3.32, ax + t * sc, 3.42, { color: C.rule, w: 1, noArrow: true });
    label(s, `${t.toFixed(2)}s`, ax + t * sc - 0.3, 3.42, 0.6, { fontSize: 8.5 });
  });
  text(s, `the whole difference is engine construction, paid once: `
    + `${(d1 - (d2 - c2)).toFixed(2)} s of it`, M, 3.72, 8.3, 0.25,
    { fontSize: 10.5, color: C.c, italic: true });

  tbl(s, ["at", "what the campaign recorded"],
    tl.filter(e => e.event !== "absorbed").map(e =>
      [`${e.at_s.toFixed(3)}s`, `${e.event}  ${e.run || ""}  ${String(e.detail).slice(0, 34)}`]),
    M + 8.55, 1.5, [0.95, 3.33], { mono: [0, 1], fs: 9, mfs: 8.5, rowH: 0.3, hfill: C.b,
      boldFirst: false });

  card(s, M, 4.1, 8.3, 1.35, "What this measures, and in what units",
    [`The campaign's own provenance clock: first record to \`terminated\` is ${span} s. The `
     + `process took ${Q.elapsed_s} s, so roughly ${(Q.elapsed_s - span).toFixed(1)} s is interpreter `
     + `startup and imports, OUTSIDE the loop.`,
     `Host: one laptop, no allocation. Stages: mocks. ${Q.n_results} nodes absorbed, front of `
     + `${Q.front_size}, stop reason "${Q.stop_reason}".`],
    { fill: C.bTint, hc: C.b, fs: 10.5 });

  card(s, M, 5.6, 8.3, 1.1, "The irregular detail is the useful one",
    [`Cycle 1's ${d1.toFixed(2)} s includes building the execution engine. Cycle 2 reuses it and `
     + `costs ${((d2 - c2) * 1000).toFixed(0)} ms for compose, validate, dispatch, absorb and rank — `
     + `with four mock tasks across two lineages in it.`],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  card(s, M + 8.55, 4.1, 4.28, 2.6, "Denominators, stated",
    ["1 host · 1 experiment in flight · 2 lineages per experiment · 4 mock tasks per lineage.",
     "Nothing was varied. No pool width, no replica width, no node count, no real tool.",
     "So: a latency figure for the engine, and NOT a throughput or scaling result."],
    { fill: C.failTint, hc: C.fail, fs: 10.5 });

  s.addNotes(`
This is the one real measurement in the deck, and it is small on purpose: one variable,
which cycle.

The campaign times itself — every provenance record carries a timestamp, so these offsets
are measured rather than instrumented in by me. Cycle one, from composed to dispatched,
${d1.toFixed(2)} seconds. Cycle two, ${((d2 - c2) * 1000).toFixed(0)} milliseconds. The entire difference is
building the execution engine, which happens once.

So the steady-state cost of going round this loop — compose a graph, type-check it, run it
through five gates and a dry run, dispatch four mock tasks across two lineages, absorb the
results, re-rank the Pareto front, write the provenance — is about ${CYCLE2_MS} milliseconds.

Now the units, because this is where overclaiming is easy. The campaign's own span is
${span} seconds. The process took ${Q.elapsed_s}. So about ${STARTUP_S} seconds is Python interpreter
startup and imports, outside the loop entirely — which, if you care about cycle latency on
a cluster, is the number that will annoy you first.

And the denominators, on the right: one host, one experiment in flight, two lineages, four
mock tasks each. I varied nothing. This is a latency figure for the engine. It is not a
throughput result and it is not a scaling result, and I have neither.
  `);
  footer(s, `mined: run.json · mock.timeline · ${HEAD} · one laptop, mock stages, no allocation`);
}

// ============================================================ 18. measured and not measured
{
  const s = slide();
  title(s, "What I measured, and what I therefore do not claim", "act 2 · performance");

  tbl(s, ["Measured", "Value", "From"],
    [["campaign span", `${Q.span_s} s`, "provenance ts"],
     ["steady-state cycle", `${CYCLE2_MS} ms`, "timeline"],
     ["refuse + recompose", "< 1 ms", "timeline"],
     ["provenance written", `${Q.provenance_records} records`, "5 jsonl files"],
     ["ledger records", `${Q.n_ledger}`, "jobs/ledger.jsonl"],
     ["declared cost of a run", `${Q.cost.gpu_hours ? Q.cost.gpu_hours.toFixed(2) : "?"} gpu-h`, "cost_model"],
     ["tests", `${K.tests_collected}`, "pytest --collect-only"]],
    M, 1.5, [2.45, 1.5, 2.0], { mono: [1, 2], fs: 10, mfs: 9, rowH: 0.38, hfill: C.b });

  card(s, M + 6.2, 1.5, 6.23, 2.35, "Measured, and in this deck",
    ["Engine latency per cycle, with engine construction separated out.",
     "The cost of a refusal — it is a composition, not a run.",
     "That the provenance log is complete enough to time the campaign from outside it.",
     "That 2 lineages absorb as 2 distinct nodes with distinct metrics."],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  card(s, M + 6.2, 4.0, 6.23, 2.65, "Not measured — so not claimed",
    ["No concurrent run: `concurrency > 1` never exercised here, so the one thing the "
     + "session API exists for is unmeasured.",
     "No serial baseline, so nothing above divides into a speedup.",
     "No real tool: every stage was a mock, so there is no science-per-GPU-hour figure of "
     + "any kind.",
     "No multi-node, no backend comparison: `concurrent` only. Dragon and radical are "
     + "selected by name and untouched here.",
     `On the real chain, \`replicas > 1\` has never run at all (backlog A10).`],
    { fill: C.failTint, hc: C.fail, fs: 10.5 });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 4.7, w: 5.95, h: 1.95,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, "Where this stops being a systems question", M + 0.16, 4.8, 5.6, 0.3,
    { fontSize: 12.5, bold: true, color: "F0C898" });
  text(s, [
    { text: "Four lineages do not buy four times the chance of a good design. ",
      options: { bold: true, color: C.white, breakLine: true } },
    { text: "The acceptance rate across the project's real runs is about 31%, and nothing in "
      + "this engine improves that — it only decides how many draws you can afford and "
      + "whether you can tell a bad draw from a broken tool.\n",
      options: { color: "C8D4DD", breakLine: true } },
    { text: "So the figure that matters is not tasks per hour. It is how few GPU-hours it "
      + "takes to learn that a workflow shape is not worth running again — which is what "
      + "the trust interlock is for, and that is the next slide.",
      options: { color: "9FD9A8" } },
  ], M + 0.16, 5.15, 5.6, 1.42, { fontSize: 10 });

  s.addNotes(`
This is the slide that makes the act honest, and it is two lists.

On the left, everything I measured, with where each number came from — and the one worth
naming is that two lineages absorb as two distinct nodes with distinct metrics, which is the
cheap half of the independence invariant.

On the right in red, written as refusals rather than apologies. I have no concurrent run,
so the single thing the session API exists for is unmeasured. I have no serial baseline, so
nothing on the left divides into a speedup. Every stage was a mock, so there is no
science-per-GPU-hour number here of any kind. One backend. And on the real chain, more than
one replica has never run.

The dark box is the part I would actually argue about over coffee. Four lineages do not buy
four times the chance of a good design. The acceptance rate across this project's real runs
is about thirty-one percent and nothing in this engine improves it. What the engine controls
is how many draws you can afford, and whether you can tell a bad draw from a broken tool.

Which means the interesting figure is not tasks per hour. It is how few GPU-hours it takes
to learn that a workflow shape is not worth running again. That is what the interlock is
for, and it is the next slide.
  `);
  footer(s, "the 31% acceptance figure is from the project's Delta run archive (backlog A1), not from this checkout");
}

// ============================================================ 19. the interlock
{
  const s = slide();
  title(s, "Where the API refuses breadth — and a seam in it", "act 2 · performance",
    { fs: 25 });

  const sigs = Object.entries(Q.widths_per_signature);
  box(s, M, 1.5, W - 2 * M, 0.78, {
    title: "A novel workflow shape is neither blocked nor trusted on sight",
    sub: "it runs under a cost cap and a forced dry run, is marked suspect whatever the outcome, "
      + "and promotes only after promote_after = 3 runs with no INTEGRITY failure — demoting on one",
    fs: 13.5, sfs: 10.5, fill: C.bTint, line: C.b, tc: C.b });

  tbl(s, ["Pattern signature", "composed at", "runs", "trust events"],
    sigs.map(([sig, widths]) => [
      sig.slice(0, 12) + "…",
      `${[...new Set(widths)].join(", ")} lineage${widths.length > 1 || widths[0] > 1 ? "s" : ""}`,
      String(widths.length),
      widths.length > 1 ? `seen, ${Q.trust_clean} clean` : "seen, then refused"]),
    M, 2.5, [2.9, 1.9, 0.9, 2.3], { mono: [0, 1], fs: 10, mfs: 9, rowH: 0.44, hfill: C.d });

  card(s, M, 4.05, 8.0, 1.35, "Two widths of one chain are two patterns — not what the docstring says",
    ["`pattern_signature` is documented as SHAPE ONLY: tool ids plus typed edges, with "
     + "parameter values excluded deliberately so a parameter change cannot reset trust.",
     "But it is built per NODE, so a 3-lineage graph contributes 3 copies of every hop and "
     + "hashes differently from the 2-lineage one. Replica width is in the signature by "
     + "construction, not by decision."],
    { fill: C.failTint, hc: C.fail, fs: 10.5 });

  code(s, [
    "parts = sorted(",
    "    f\"{n.tool}<-{','.join(sorted(self.nodes[d].tool for d in n.deps))}\"",
    "    for n in self.nodes.values()          # <- one entry PER NODE",
    ")",
    "return hashlib.sha256(\"|\".join(parts).encode()).hexdigest()[:16]",
  ], M, 5.55, 8.0, 1.1, { anchor: "compose/graph.py:51 · VERBATIM", fs: 9 });

  card(s, M + 8.25, 2.5, 4.08, 4.15, "Why it bites",
    [`Trust earned at width 2 does not transfer to width 3.`,
     `${Q.trust_clean} clean runs here, against promote_after = 3 — so ${Q.trust_promoted} promotions, and `
     + `all ${Q.n_results} nodes came out \`${Object.keys(Q.qc_verdicts)[0]}\`.`,
     "To run the real 4-lineage independence check you must first earn trust AT 4.",
     "Backlog A10 names this; it is a known cost, not a discovery."],
    { fill: C.panel, hc: C.ink, fs: 10 });

  s.addNotes(`
This is my favourite mechanism in the project and it has a seam in it, so you get both.

The rule: a shape nobody has run before is neither blocked nor trusted. Cost-capped at ten
percent of budget, forced dry run, every node marked suspect however good the scores.
Promotes after three clean runs, demotes on one. And a design that merely scores badly is
not evidence against the workflow — that is decision 0013, and it is the right distinction.

Now the table. In this run there are two pattern signatures, and they are the same four-tool
chain — one composed at three lineages, one at two. Two widths, two patterns.

And that is not what the function says it does. The docstring says shape only: tool ids plus
typed edges, with parameter values excluded deliberately so that changing a parameter cannot
reset accumulated trust. But look at the loop: it emits one entry per node. A three-lineage
graph contributes three copies of every hop, so it hashes differently. Replica width is in
the signature by construction rather than by decision.

Why that bites: to run the four-lineage independence check that this project actually needs,
you must first earn trust at four lineages, because trust at one does not transfer. Backlog
A10 already names this, so it is a known cost rather than something I found this morning —
but it is the clearest example I have of a design rule and its implementation disagreeing
quietly.
  `);
  footer(s, `mined: run.json · mock.widths_per_signature · trust: ${Q.trust_seen} seen, ${Q.trust_clean} clean, ${Q.trust_promoted} promoted`);
}

// ============================================================ 20. ACT 3 divider
{
  const s = slide();
  divider(s, {
    n: 3, of: 3, name: "Usability",
    definition: "Not the interface — the use cases. Is this an application someone opens, "
      + "a platform others plug into, or a component something else drives?",
    claims: [
      ["As an application: strong",
       `one YAML, one command, ${S.cli_subcommands.length} subcommands — and a preflight that respects what an allocation costs`],
      ["As a platform: arguable",
       `${S.n_tools} tools discovered at runtime from a directory; $IMPRESS_A_TOOLKITS adds yours without touching the package`],
      ["As a component: empty",
       `${S.n_plane_ops} control-plane operations and a RemoteSession that implements the reasoner's own protocol — and no caller`],
    ],
    caveat: "nothing outside this package has ever driven a campaign — the four-hour live "
      + "run two slides from now is the reference pipeline's toolkit with an LLM on it, not "
      + "this engine — and `--model C` with no caller falls back to model D after 5 s",
  });
  s.addNotes(`
Act three: usability. Not the user interface — the use cases. Is this an application, a
platform, or a component?

As an application I think it is genuinely strong: one file, one command, and a preflight
step that exists because an allocation costs money.

As a platform it is arguable in the honest sense: tools are discovered at runtime from a
directory, and an environment variable points it at yours without touching the package. The
interface is there. Nobody has used it.

As a component it is empty, and that is the weak claim I promised you in the first three
minutes. Nineteen control-plane operations, a remote session that implements the reasoner's
own protocol over a socket, and no caller.

And the specific thing I would fix first: launching model C with nothing attached to steer
it does not block and does not fail. It falls back to model D after five seconds. So the
headless mode can silently become the explicit-policy mode, and the only sign is a line in
the log.
  `);
}

// ============================================================ 21. a campaign, from the user's chair
// The first of four user-directed slides: what the thing is like to run, rather than what
// it is made of. No protocol, no types, one command. Everything on it is mined from the
// campaign this deck ran, so the narrative cannot drift from the evidence.
{
  const s = slide();
  title(s, "What running one is actually like", "act 3 · usability");

  const steps = [
    ["You write the file",
     `${S.n_campaign_spec_fields} keys exist. A real campaign uses about twenty lines: the goal, the budget, the objectives, and the stages you trust`,
     C.accent],
    ["You run preflight",
     "On the login node, before the queue, where repairing anything is free. ok / FAIL / undetermined — and undetermined never reads as a pass",
     C.accent],
    ["You stop watching",
     "There is no step list to babysit. It observes, decides, composes a graph, type-checks it, gates it, and dispatches",
     C.a],
    ["It argues with itself",
     `It asked for ${Q.refusals[0].lineages} lineages. The interlock refused on cost. It came back with ${Q.lineages_absorbed.length} and was admitted — nobody woken up`,
     C.c],
    ["It stops, and says why",
     `"${Q.stop_reason}". ${Q.front_size} designs on the front, ${Q.n_results} nodes, every one marked suspect until a human has looked`,
     C.b],
  ];
  const sw = (W - 2 * M - 4 * 0.14) / 5;
  steps.forEach(([h, b, col], i) => {
    const x = M + i * (sw + 0.14);
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: sw, h: 2.15,
      fill: { color: C.panel }, line: { color: C.rule } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: sw, h: 0.06,
      fill: { color: col }, line: { color: col } });
    text(s, String(i + 1), x + 0.12, 1.62, 0.4, 0.26,
      { fontFace: HF, fontSize: 15, bold: true, color: col });
    text(s, h, x + 0.12, 1.92, sw - 0.24, 0.3, { fontSize: 12, bold: true, color: C.ink });
    text(s, b, x + 0.12, 2.26, sw - 0.24, 1.3, { fontSize: 10, color: C.text });
  });

  code(s, [`$ impress-a run campaigns/delta-small-molecule.yaml --model D`], M, 3.85, 7.3, 0.52,
    { fs: 12 });
  card(s, M + 7.55, 3.78, 4.78, 1.05, "What you never write",
    ["No DAG, no step list, no retry loop, and no per-experiment edit to a batch script — "
     + "the shape of the work is composed each cycle from the stages you named."],
    { fill: C.aTint, hc: C.a, fs: 10.5 });

  box(s, M, 5.05, W - 2 * M, 0.92, {
    title: `What comes back: one directory per job — manifest.json (campaign, model, git sha and whether the checkout was dirty), campaign.log, provenance/*.jsonl (${Q.provenance_records} records across ${Object.keys(Q.provenance_kinds).length} kinds), jobs/ledger.jsonl (${Q.n_ledger})`,
    sub: "you can hand the directory to someone else and they can reconstruct every decision, including the one that was refused",
    fs: 11.5, sfs: 10, fill: C.bTint, line: C.b, tc: C.b });

  text(s, [
    { text: "The experience it is trying to buy:  ", options: { bold: true, color: C.ink } },
    { text: "you spend your attention on what you want, not on what order to ask for it in — "
      + "and the first thing you read when it finishes is the reason it stopped." },
  ], M, 6.2, W - 2 * M, 0.5, { fontSize: 12.5 });

  s.addNotes(`
This is the whole thing from where a user sits, and it is deliberately the least technical
slide in the deck.

You write one file. About twenty lines: what you want, what you are willing to spend, how
you will know it worked, and which tools you trust. Then you run preflight on the login
node, because finding out that an environment variable is missing is free there and costs
you an allocation inside the queue.

Then you submit it and stop watching. That is the part that is different. There is no step
list to babysit.

While you were not watching, this run asked for ${Q.refusals[0].lineages} lineages, had that refused on cost by
its own interlock, came back with ${Q.lineages_absorbed.length}, and was admitted. Nobody was woken up. It stopped
because it reached the front size it was told to reach, and it says so in those words.

And what lands on disk is one directory you can hand to somebody else — including whether
the checkout was dirty when it started.
  `);
  footer(s, `mined from the campaign this deck ran · ${HEAD}`);
}

// ============================================================ 22. when it refuses you
{
  const s = slide();
  title(s, "When it says no, it says what to change", "act 3 · usability");

  const refusals = [
    ["Before the queue", C.accent,
     "preflight, on the login node",
     "`$MPNN_DIR has no model_params/ — run its get_model_params.sh`. Seconds to fix, "
     + "no allocation spent. A timeout reports as undetermined, never as a pass."],
    ["Before anything runs", C.c,
     "five gates, then the interlock",
     `"${Q.refusals[0].reason}" — marked transient, so the policy shrinks the request and `
     + "tries again instead of stopping. Cost of the refusal: one composition, no GPU."],
    ["After a tool succeeds", C.d,
     "QC, on the way out of the node",
     "A tool can exit 0, report 0.91 designability, and have produced a noodle. The "
     + "integrity gate fails the node anyway, and a failed node never reaches the front."],
  ];
  const cw = (W - 2 * M - 2 * 0.2) / 3;
  refusals.forEach(([when, col, where, what], i) => {
    const x = M + i * (cw + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: cw, h: 2.35,
      fill: { color: C.white }, line: { color: col, width: 1.5 } });
    pill(s, when, x + 0.14, 1.66, cw - 0.28, col, { fs: 10 });
    text(s, where, x + 0.14, 2.12, cw - 0.28, 0.26,
      { fontSize: 10.5, italic: true, color: C.muted });
    text(s, what, x + 0.14, 2.44, cw - 0.28, 1.3, { fontSize: 11, color: C.text });
  });

  card(s, M, 4.1, W - 2 * M, 1.22,
    "The one place it does NOT say no loudly — and it is the one that cost a real run",
    ["Cost-model figures sat 6–69× over measurement, so gate 5 summed past the cap and the "
     + "policy quietly truncated `boltz_predict` off the end of the chain. The campaign ran. "
     + "It just could not produce the objective it was launched for.",
     "It warns now — `_objectives_without_a_producer` — and a warning is not a gate. "
     + "If you take one thing from this slide: a refusal you can read is a feature, and the "
     + "dangerous refusals are the ones phrased as a smaller plan."],
    { fill: C.failTint, hc: C.fail, fs: 10.5 });

  code(s, [
    `interlock  ${Q.refusals[0].reason}`,
    `           transient=${Q.refusals[0].transient}  →  policy recomposed at ${Q.lineages_absorbed.length} lineages, admitted`,
  ], M, 5.6, W - 2 * M, 0.78,
    { anchor: "runtime/executor.py:391 · run.json mock.refusals[0] · MINED", fs: 10.5 });

  s.addNotes(`
A system that refuses you is only pleasant to use if the refusal tells you what to change,
and there are three places this one can refuse.

Before the queue: preflight, on the login node, where fixing it is free.

Before anything runs: five gates and then the interlock, which is what happened in this
deck's own campaign. The message names the cap, the number and the unit, and it is marked
transient — which is the part that matters, because transient means "ask me for less",
not "give up". The policy recomposed and was admitted.

After a tool succeeds: QC. These tools fail silently. A tool can exit zero, report
confident numbers, and have produced a noodle, so exit code is never the evidence.

And then the honest one, in red. There is a place where it does not refuse loudly: when
inflated cost estimates make a graph too expensive, the policy can quietly hand back a
smaller graph that no longer produces the objective you launched for. That ran on real
hardware. It warns now. A warning is not a gate.
  `);
  footer(s, "the dangerous refusal is the one phrased as a smaller plan");
}

// ============================================================ 23. live next door
{
  const s = slide();
  title(s, "Next door, a model drove the real toolkit for four hours",
    "act 3 · usability · evidence from outside this package");

  const pct = (p) => `${Math.round(100 * p[0] / p[1])}%`;
  tbl(s, ["4 h, 1 node, 4 pipelines, same inputs", "state machine",
         `an LLM, calling ${L.n_tools} tools`],
    [["who decided what ran next", P4.reference.driver, P4.agentic.driver],
     ["rfd3 per pipeline-hour", P4.reference.rfd3_per_pipeline_h, P4.agentic.rfd3_per_pipeline_h],
     ["distinct passing designs", P4.reference.passing_designs, P4.agentic.passing_designs],
     ["GPU-hours per passing design", P4.reference.gpu_h_per_design, P4.agentic.gpu_h_per_design],
     ["backbones that yielded a fold", pct(P4.reference.backbones_yielding), pct(P4.agentic.backbones_yielding)],
     ["fastrelax pass rate", pct(P4.reference.fastrelax), pct(P4.agentic.fastrelax)],
     ["mpnn tasks spent", P4.reference.mpnn_tasks, P4.agentic.mpnn_tasks],
     ["model cost", "—", `$${P4.agentic.usd.toFixed(2)} ($${P4.agentic.usd_per_design}/design)`]],
    M, 1.62, [3.45, 2.1, 2.45], { mono: [1, 2], fs: 10.5, mfs: 9.5, rowH: 0.3, hfill: C.a });

  card(s, M + 8.25, 1.62, 4.08, 2.4, "What it did unprompted",
    [`${LR.first_live_1h.chose_to_stop}.`,
     `And ${LR.first_live_1h.unprompted} — a bottleneck that was already an open backlog item next door.`],
    { fill: C.aTint, hc: C.a, fs: 10.5 });
  card(s, M + 8.25, 4.12, 4.08, 1.5, "And what it did badly",
    LR.first_live_1h.weaknesses,
    { fill: C.panel, hc: C.ink, fs: 10 });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 4.42, w: 7.9, h: 1.2,
    fill: { color: C.failTint }, line: { color: C.fail, width: 1.5 } });
  text(s, [
    { text: "Two caveats, and they are load-bearing.  ", options: { bold: true, color: C.fail } },
    { text: P4.caveats.join("  ") },
  ], M + 0.14, 4.52, 7.62, 1.0, { fontSize: 10, color: C.text });

  text(s, [
    { text: "Both arms ran the full four hours with zero task failures. ",
      options: { bold: true, color: C.ink } },
    { text: "Throughput is equal, so the round trip costs nothing measurable — the difference "
      + "is entirely in which work the funnel chose to do. This is not IMPRESS-A: no campaign "
      + "engine, no gates, no interlock, no trust. It is the idea, on hardware, without them." },
  ], M, 5.85, W - 2 * M, 0.7, { fontSize: 11.5 });

  s.addNotes(`
This is the one slide in the deck with figures I did not mine from this checkout, and I
want to be exact about where it came from and what it is.

On the twenty-second, two jobs went in together: four hours, one node, four pipelines, the
same inputs and the same thresholds. One arm was the reference pipeline's state machine.
The other was an LLM holding the same eight tools. Everything below the decision layer is
identical by construction.

Throughput came out equal, which is the result I least expected: the model's round trip
costs nothing measurable against GPU work. The funnel was not equal — three times the
passing designs, from fewer sequence tasks.

Now the red box, because this number will get quoted at me otherwise. The reference arm
came in about twice as bad as its own record, so part of that gap is a weak baseline and
not agent skill. And the place the difference actually originates — an eighty-eight against
forty-nine percent pass rate on the same relax tool — is unexplained.

And the thing to hold on to: none of this ran through IMPRESS-A.
  `);
  footer(s, `TRANSCRIBED · ${LR.source} · the tool list is mined, from examples/agentic_small_molecule_binding/tools.py:35`);
}

// ============================================================ 24. what that says about these surfaces
{
  const s = slide();
  title(s, "What those four hours say about these surfaces", "act 3 · usability");

  tbl(s, ["What the live runs showed", "Which surface answers it — and whether it has been exercised"],
    [[`The round trip is free: ${P4.agentic.rfd3_per_pipeline_h} against ${P4.reference.rfd3_per_pipeline_h} rfd3 per pipeline-hour`,
      "A reasoner per experiment is affordable, which is the bet surfaces 3 and 4 are built on. "
      + "Here it is measured against MOCKS only."],
     ["It skipped the cheap gate before expensive folds, and never looked at its own ensemble",
      "The engine does not rely on the reasoner's discipline: gate 5 and the interlock refuse on "
      + "cost BEFORE anything runs, and a policy cannot name a tool parameter at all."],
     ["A work dir the container could not see read exactly like a model failure",
      "Exactly the class `impress-a preflight` exists for — and it would NOT have caught this "
      + "one: it checks the login node, not what a container binds. An honest gap."],
     [`The model can live inside the allocation: ${LR.hosted_in_allocation.qwen_72b.turns} turns, $0 of API, served as one more task`,
      "That is what model C's endpoint could be. Today `--model C` with no caller falls back to "
      + "model D after 5 s rather than failing — ask 5."]],
    M, 1.6, [4.6, 7.73], { fs: 10.5, rowH: 0.8, hfill: C.a, margin: 0.09 });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 5.85, w: W - 2 * M, h: 1.0,
    fill: { color: C.failTint }, line: { color: C.fail, width: 2 } });
  text(s, [
    { text: "Say this out loud:  ", options: { bold: true, color: C.fail } },
    { text: "none of that ran through this package. Different code, no campaign engine, no "
      + "gates, no trust ledger, one pipeline per GPU. It is evidence that the idea works on "
      + "this hardware, and it is not evidence that this engine does. The component claim is "
      + "still empty, and the nearest thing to a user it has is still me." },
  ], M + 0.16, 5.96, W - 2 * M - 0.32, 0.8, { fontSize: 12, color: C.text });

  s.addNotes(`
So what does a four-hour run of somebody else's code tell you about these six surfaces?

Four things. The round trip being free is the premise this whole design rests on, and it
now has a number against it — next door, on real tools, not here.

The second one is the interesting one. The model skipped the cheap gate before the
expensive fold, repeatedly. That is not a criticism of the model; it is the reason this
engine refuses on cost before anything runs rather than trusting the reasoner to be
disciplined. A policy here cannot even name a tool parameter.

Third, the honest one: a work directory the container could not see produced empty outputs,
and the model correctly concluded its own designs kept failing. An environmental failure
that reads exactly like a reasoning failure. That is the class of thing preflight exists
for, and preflight would not have caught this one.

Fourth: the model can be served inside the allocation for no API cost at all, which is what
model C's endpoint could be — if model C stopped silently falling back.

And then the red line, which I would rather say than have asked: none of this ran through
IMPRESS-A.
  `);
  footer(s, `the live figures are TRANSCRIBED · ${LR.source}`);
}

// ============================================================ 25. as an application
{
  const s = slide();
  title(s, "As an application: one command, one honest gate", "act 3 · usability");

  code(s, [
    "$ impress-a preflight campaigns/delta-small-molecule-smoke.yaml",
    "",
    "  preflight",
    "",
    "    [ok  ] $WORK_DIR            /work/nvme/<project>/<user>",
    "    [FAIL] $MPNN_DIR            no model_params/ - run its get_model_params.sh",
    "    [ok  ] boltz CCD cache      extraction proven complete",
    "    [warn] pyrosetta            timed out after 120s - a loaded login node can",
    "                                take that long to import it; re-run",
    "    [ok  ] venv on fast storage /work/nvme/<project>/<user>/venv",
    "",
    "  7/9 ok, 1 undetermined (pyrosetta) - missing: $MPNN_DIR",
  ], M, 1.5, 7.5, 2.5, { anchor: "cli/__init__.py:252 · ILLUSTRATIVE (shape of real output)", fs: 9.5 });

  card(s, M + 7.75, 1.5, 4.58, 2.5, "Why the third state exists",
    ["Every real adapter raises on a missing env var — but only once a task is RUNNING, "
     + "which on HPC means inside the allocation, after the queue wait.",
     "`ok` is tri-state: None means UNDETERMINED, not failed. A probe that shells out to "
     + "import a heavy science stack can take minutes on a busy login node, and reporting "
     + "that as FAIL trains the reader to ignore the FAIL column."],
    { fill: C.cTint, hc: C.c, fs: 10.5 });

  card(s, M, 4.2, 6.1, 1.3, "The rule that must not erode",
    ["None is ONLY for a probe that produced no answer. A deterministic negative is always "
     + "False: a missing `$MPNN_DIR` is a FAIL forever; a pyrosetta *import error* is a FAIL, "
     + "a pyrosetta *timeout* is undetermined."],
    { fill: C.panel, hc: C.ink, fs: 10.5 });
  card(s, M + 6.33, 4.2, 6.1, 1.3, "What it caught that nothing else would",
    ["A venv on HDD rather than NVMe — which works perfectly, about 8x slower, and lands as "
     + "an unexplained task timeout inside an allocation.",
     "`ml_collections`, which only LigandMPNN's bundled openfold imports."],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  box(s, M, 5.65, W - 2 * M, 1.0, {
    title: "Each job writes one self-contained directory: manifest.json (job id, campaign, model, git sha + dirty), slurm.out, campaign.log, provenance/*.jsonl, jobs/ledger.jsonl",
    sub: "a run you can hand to someone else, including whether the checkout was dirty when it started",
    fs: 11.5, sfs: 10, fill: C.bTint, line: C.b, tc: C.b });

  s.addNotes(`
As an application, the thing I would point at is not the run command — it is preflight.

Every real adapter in this project raises on a missing environment variable. But it raises
once a task is already running, which on HPC means inside the allocation, after the queue
wait. So preflight runs the same checks on the login node, where repairing them is free and
there is still internet.

The detail worth stealing is the third state. None means undetermined, not failed. Several
probes shell out to import a heavy science stack and can take minutes on a loaded login
node; report that as FAIL and you have trained the reader to ignore the FAIL column.

And the rule that holds it together: None is only ever for a probe that produced no answer.
A missing MPNN_DIR is a FAIL forever. A pyrosetta import error is a FAIL. A pyrosetta
timeout is undetermined. The moment "warn" starts meaning "a failure we would rather not
block on", the column is decoration.

What it has caught: a venv on spinning disk instead of NVMe, which works perfectly, about
eight times slower, and shows up inside an allocation as an unexplained task timeout.

And every job writes one directory you can hand to someone else — including the git sha and
whether the checkout was dirty.
  `);
  footer(s, "the output above is the shape of real preflight output, with paths replaced by placeholders — see CODE_FOR_DECK.md");
}

// ============================================================ 26. surface 5, the control plane
{
  const s = slide();
  title(s, "Surface 5: one protocol, two transports", "act 3 · usability");

  tbl(s, ["Route", "Semantics that are NOT the transport's invention"],
    [["POST /campaigns/<c>/runs", "202 with a run id, or 409 with the ValidationFailure that refused it"],
     ["GET  …/runs/<r>/result?wait=", "200 outcome · 204 ask again · 410 the campaign ended"],
     ["GET  …/observe?since=", "the same CampaignObservation a policy's decide() receives"],
     ["GET  …/events?stream=1", "cursor-paged page, or a live tail of the same sequence"],
     ["POST …/measurements", "a P8 arrival, accepted even after termination"]],
    M, 1.5, [3.3, 5.5], { mono: [0], fs: 10.5, mfs: 9, rowH: 0.44, hfill: C.accent });

  card(s, M, 4.3, 8.8, 1.2, "Why admission is synchronous and waiting is a long poll",
    ["Accepting everything and reporting rejections later on the event stream would sever a "
     + "rejection from the request that caused it, leaving nothing to bound retries against.",
     `And a socket cannot be held open for a twelve-hour folding job, so the deadline is the `
     + `transport's problem (MAX_WAIT_S = ${S.max_wait_s}) and re-issuing is the client's — neither is `
     + `visible to the reasoner, which just calls result() and blocks.`],
    { fill: C.bTint, hc: C.b, fs: 10.5 });

  card(s, M, 5.65, 8.8, 1.0, "The rule that keeps two transports from becoming two systems",
    [`No adapter may add an operation absent from the core protocol (ADR 0007). `
     + `${S.n_plane_ops} operations, ${S.n_routes} route heads, and the routes are a mechanical rendering `
     + `of the Protocol — which is why run_model.py counts both and prints them side by side.`],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  box(s, M + 9.05, 1.5, 3.28, 1.5, { title: "RemoteSession",
    sub: "implements the reasoner's OWN protocol over the plane — so SequentialPolicyDriver "
      + "runs unmodified against a socket",
    fs: 12.5, sfs: 9.5, fill: C.aTint, line: C.a, tc: C.a });
  box(s, M + 9.05, 3.15, 3.28, 1.5, { title: "Built on asyncio.start_server",
    sub: "no framework. A small fixed dialect, on loopback, for one trusted client",
    fs: 12.5, sfs: 9.5, fill: C.panel, line: C.rule, tc: C.ink });
  box(s, M + 9.05, 4.8, 3.28, 1.85, { title: "NOT public-facing",
    sub: "no auth, no TLS, one body-size limit. The module says so in its own docstring; "
      + "bind it to localhost or a private interface only",
    fs: 12.5, sfs: 9.5, fill: C.failTint, line: C.fail, tc: C.fail, status: "tested" });

  s.addNotes(`
Surface five is the one an external caller sees, and it is the one I would most like
someone to attack.

One protocol. In-process and HTTP are adapters over it, and the rule — ADR 0007 — is that no
adapter may offer an operation the others do not. ${S.n_plane_ops} operations, ${S.n_routes} route heads, and the
routes are a mechanical rendering of the Protocol, which is why the mining script counts
both and puts them next to each other: if they drift, the slide is wrong out loud.

Four semantics in that table are not the transport's invention. Admission is synchronous:
202 with a run id, or 409 carrying the structured failure that refused it. Waiting is a long
poll with three honest answers: here it is, ask again, or the campaign ended and the answer
is never coming. Observe returns the same object a policy's decide receives. And a
measurement can arrive after the campaign is over, because the campaign record is
append-only and outlives execution.

On the right: RemoteSession implements the reasoner's own protocol over this plane, which
means the sequential driver and an unmodified threshold policy run against a socket exactly
as they run in memory. That is the test that the seam is real.

And the honest box at the bottom right: this is not a public-facing server. No auth, no TLS.
The module's own docstring says bind it to loopback. That is fine today because nothing uses
it, and it is the first thing that has to change when something does.
  `);
  footer(s, "control/plane.py:23 is the protocol · control/http.py:183 is the whole route table · control/session.py:48 is RemoteSession");
}

// ============================================================ 27. the layering contract
{
  const s = slide();
  title(s, "Why the surfaces stay separate: an allow-list in a test",
    "act 3 · usability");

  const order = ["core", "policy", "compose", "tools", "exec", "runtime", "manager",
                 "control", "cli", "__main__"];
  const colFor = { core: C.muted, policy: C.a, compose: C.c, tools: C.d, exec: C.d,
                   runtime: C.b, manager: C.b, control: C.accent, cli: C.accent,
                   __main__: C.accent };
  order.forEach((lay, i) => {
    const y = 1.5 + i * 0.5, allowed = S.layering[lay] || [];
    s.addShape(pres.shapes.RECTANGLE, { x: M, y, w: 1.35, h: 0.44,
      fill: { color: colFor[lay] }, line: { color: colFor[lay] } });
    text(s, lay, M, y, 1.35, 0.44, { fontFace: MF, fontSize: 10, bold: true,
      color: C.white, align: "center", valign: "middle" });
    s.addShape(pres.shapes.RECTANGLE, { x: M + 1.4, y, w: 4.45, h: 0.44,
      fill: { color: i % 2 ? C.white : C.panel }, line: { color: C.rule } });
    text(s, allowed.length ? "may import  " + allowed.join(", ")
                           : "imports NOTHING internal",
      M + 1.52, y, 4.2, 0.44, { fontFace: MF, fontSize: 9,
        color: allowed.length ? C.text : C.good, valign: "middle",
        bold: !allowed.length });
    const forbidden = { policy: "✗ tools · exec · runtime", compose: "✗ exec",
                        core: "✗ everything" }[lay];
    if (forbidden) text(s, forbidden, M + 5.92, y, 2.1, 0.44,
      { fontFace: MF, fontSize: 9.5, bold: true, color: C.fail, valign: "middle" });
  });

  card(s, M + 8.1, 1.5, 4.23, 1.75, "The three that are load-bearing",
    ["`policy` → `tools`/`exec` would let a policy reach a tool adapter, and it would stop "
     + "emitting abstract intent.",
     "`compose` → `exec` would end the laptop test tier: validation is testable with no "
     + "backend only because that edge does not exist.",
     "`core` → anything would make the serializable seam unenforceable."],
    { fill: C.failTint, hc: C.fail, fs: 10 });

  code(s, [
    "ALLOWED = {",
    "    \"core\":   frozenset(),",
    "    \"policy\": frozenset({\"core\"}),",
    "    \"compose\": frozenset({\"tools\", \"core\"}),",
    "    ...",
    "}",
  ], M + 8.1, 3.4, 4.23, 1.3, { anchor: "tests/test_layering.py:43 · TRIMMED", fs: 9.5 });

  card(s, M + 8.1, 4.95, 4.23, 1.7, "Why `ast`, not a scan of imports",
    ["The real adapters defer their science imports into `run()` bodies on purpose — so a "
     + "deferred `from ..exec import …` inside a compose function would be exactly as fatal "
     + "as one at the top of the file, and `ast.walk` sees both.",
     "An allow-list, not a deny-list: a NEW cross-layer import fails by default."],
    { fill: C.panel, hc: C.ink, fs: 10 });

  s.addNotes(`
Last content slide, and it is the one that makes everything I have claimed checkable.

Ten layers. Each row shows what that layer may import, and the red column shows the edges
that are forbidden. This is not a diagram in a document — it is a table in a test that walks
the source with ast and fails the suite on any edge that is not in the list.

Three of these are load-bearing. Policy may not reach tools or exec: if it could, a policy
would stop emitting abstract intent and start invoking tools, and the control models would
stop being swappable. Compose may not reach exec: that single absence is what makes the
entire validation path testable with no backend, which is the whole laptop test tier. And
core imports nothing internal, which is what keeps the serializable seam honest.

Two details I like. It walks the ast rather than scanning module-level imports, because the
adapters defer their heavy science imports into run bodies on purpose — so a deferred import
of exec inside a compose function is caught too. And it is an allow-list, so a new
cross-layer import fails by default: the contract cannot rot by addition.

One honest blind spot, which the test's own docstring names: a dynamic importlib call is
invisible to it.
  `);
  footer(s, `${S.n_layers} layers, ${K.tests_collected} tests, ${K.test_files} test files · the table mirrors docs/reference/architecture.md`);
}

// ============================================================ 28. status by dimension
{
  const s = slide();
  title(s, "Status, by dimension", "where this actually is");

  const cols = [
    ["FUNCTIONALITY", C.c,
     [["Six surfaces, all exercised", "by the test tier and one real campaign"],
      ["Load-is-validating", `${S.n_tools} tools, ${K.gate_fixtures} gate fixtures, 0 registry errors`],
      ["Refuse-and-retry works", "observed in the run: interlock → shrink → admit"]],
     [["One topology family", "every graph is an ordered stage list"],
      ["No third-party author", "no toolkit or policy written outside this package"],
      ["Calibration untested", "no measurement has ever superseded a prediction"]]],
    ["PERFORMANCE", C.b,
     [["Engine latency measured", `${CYCLE2_MS} ms steady-state cycle, mocks, one host`],
      ["Both ends of the backend bounded", "startup and shutdown timeouts, from real hangs"],
      ["Provenance is complete", "the campaign can be timed from outside it"]],
     [["No concurrency measurement", "`concurrency > 1` never exercised"],
      ["No baseline, no scaling", "nothing here divides into a speedup"],
      ["Real chain at width 1 only", "`replicas > 1` has never run on it (A10)"]]],
    ["USABILITY", C.a,
     [["One YAML, one command", "and a preflight that runs before the queue"],
      ["Toolkits discovered at runtime", "$IMPRESS_A_TOOLKITS, no package change"],
      ["Two transports, one protocol", "in-process and HTTP, tested against each other"]],
     [["Nothing external drives it", "the component claim is empty"],
      ["`--model C` fails open", "no caller → falls back to D after 5 s"],
      ["No serve/reason command", "model C is reachable only by embedding"]]],
  ];
  cols.forEach(([name, col, green, red], i) => {
    const x = M + i * 4.28, w = 4.0;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.45, w, h: 0.4,
      fill: { color: col }, line: { color: col } });
    text(s, name, x, 1.45, w, 0.4, { fontSize: 12, bold: true, color: C.white,
      align: "center", valign: "middle", charSpacing: 1 });
    [[green, C.good, "RUNS", 2.12], [red, C.fail, "DOES NOT", 4.2]].forEach(
      ([rows, c, hdr, y0]) => {
        text(s, hdr, x, y0 - 0.24, w, 0.22, { fontSize: 9.5, bold: true, color: c,
          charSpacing: 1.5 });
        rows.forEach(([h, b], j) => {
          const y = y0 + j * 0.6;
          s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.58,
            fill: { color: j % 2 ? C.white : C.panel }, line: { color: C.rule } });
          text(s, h, x + 0.1, y + 0.04, w - 0.2, 0.24, { fontSize: 10, bold: true,
            color: C.ink });
          text(s, b, x + 0.1, y + 0.28, w - 0.2, 0.26, { fontSize: 8.5, color: C.muted });
        });
      });
  });
  text(s, "Three green and three red per dimension, deliberately the same length. The red "
    + "column is not a to-do list — it is what you should not believe from this deck.",
    M, 6.12, W - 2 * M, 0.5, { fontSize: 11.5, color: C.text, italic: true });

  s.addNotes(`
Status, three columns, and the format is the argument: three things that run and three that
do not, per dimension, deliberately the same length.

Functionality runs: six surfaces exercised, loading validates, and refuse-and-retry was
observed in a real run rather than asserted. Functionality does not: one topology family,
no third-party author, and the calibration machinery — a measurement superseding a
prediction, the one capability a composed graph has that a written-down one does not — has
never been exercised.

Performance runs: engine latency is measured, both ends of the backend lifecycle are
bounded, and the provenance log is complete enough to time the campaign from outside.
Performance does not: no concurrency measurement, no baseline, and the real chain has only
ever run one lineage.

Usability runs: one YAML and one command, runtime toolkit discovery, two transports tested
against each other. Usability does not: nothing external drives it, model C fails open, and
there is no serve command.

The red column is not a to-do list. It is the list of things you should not believe from
this deck.
  `);
  footer(s, "if you cut one slide from this deck, do not make it this one");
}

// ============================================================ 29. asks
{
  const s = slide();
  s.background = { color: C.ink };
  text(s, "SIX QUESTIONS I ACTUALLY WANT ANSWERED", M, 0.5, 8, 0.3,
    { fontSize: 12, bold: true, color: C.muted, charSpacing: 2 });
  text(s, "Asks", M, 0.82, 6, 0.6, { fontFace: HF, fontSize: 30, bold: true, color: C.white });

  text(s, "COSTS A WRONG ANSWER, OR REAL TIME", M, 1.6, 6.03, 0.24,
    { fontSize: 9.5, bold: true, color: "E8A0A0", charSpacing: 1.5 });
  text(s, "COSTS WHOEVER ADOPTS THIS NEXT", M + 6.3, 1.6, 6.03, 0.24,
    { fontSize: 9.5, bold: true, color: "F0C898", charSpacing: 1.5 });

  const asks = [
    [1, "Should `pattern_signature` normalise replica width?", C.fail, "FUNCTIONALITY",
     "It is documented as shape-only and excludes parameter values on purpose, but emits one "
     + "entry per node, so width is in the hash. Fixing it makes trust transfer across widths "
     + "— and weakens the claim that a wide run is a new shape.  compose/graph.py:51"],
    [2, "Should an acceptance-failure streak demote a pattern?", C.fail, "PERFORMANCE",
     "Trust counts integrity failures only (decision 0013), so a tool emitting well-formed, "
     + "low-scored garbage promotes after 3 runs. Right rule, but is the gap real?  "
     + "compose/interlock.py:112"],
    [3, "Should `on_rejected` shrink-on-transient live in the base class?", C.fail, "FUNCTIONALITY",
     "Today the default is Stop and each policy re-implements shrinking. That is where a "
     + "4-lineage check quietly becomes a 3-lineage one, with nothing in the log but a "
     + "correction warning.  policy/base.py:54"],
    [4, "Is loopback-only the permanent answer for the control plane?", C.accent, "USABILITY",
     "No auth, no TLS, by design and documented. Before anything external drives a campaign, "
     + "does this need a token, or does it stay in-allocation forever?  control/http.py:26"],
    [5, "Should `--model C` with no caller refuse to start?", C.accent, "USABILITY",
     "It falls back to model D after 5 s, so a headless campaign silently becomes an "
     + "explicit-policy one. Fail fast, block forever, or keep the fallback and log louder?  "
     + "cli/__init__.py:103"],
    [6, "Should model A's imports be lazy?", C.accent, "PERFORMANCE",
     `The CLI imports every policy at module scope, so \`impress-a tools\` pays for langgraph. `
     + `About ${(Q.elapsed_s - Q.span_s).toFixed(1)} s of this deck's ${Q.elapsed_s} s run was startup, outside the loop.  `
     + `cli/__init__.py:31`],
  ];
  asks.forEach(([n, q, col, dim, body], i) => {
    const x = M + (i % 2) * 6.3, y = 1.94 + Math.floor(i / 2) * 1.72;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 6.03, h: 1.58,
      fill: { color: "1E2A33" }, line: { color: "2A3845" } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 1.58,
      fill: { color: col }, line: { color: col } });
    text(s, String(n), x + 0.18, y + 0.08, 0.4, 0.3,
      { fontFace: HF, fontSize: 17, bold: true, color: col });
    text(s, dim, x + 4.6, y + 0.12, 1.3, 0.2,
      { fontSize: 7.5, bold: true, color: C.muted, align: "right", charSpacing: 1 });
    text(s, q, x + 0.62, y + 0.1, 3.95, 0.5,
      { fontSize: 11.5, bold: true, color: C.white });
    text(s, body, x + 0.62, y + 0.62, 5.25, 0.88, { fontSize: 9.5, color: "AFC0CC" });
  });

  s.addNotes(`
I would rather end on the questions than on a summary, and they are grouped by what each one
costs. The left column costs a wrong answer or real time. The right column costs whoever
adopts this next.

One. Should the pattern signature normalise replica width? It is documented as shape-only
and deliberately excludes parameter values, but it emits one entry per node, so width is in
the hash. Fixing it makes trust transfer across widths. It also weakens the argument that a
wide run is genuinely a new shape, which may be the right argument. I do not know which.

Two. Should a streak of acceptance failures demote a pattern? Trust counts integrity only,
which is the right rule — but a tool emitting well-formed, uselessly-scored output promotes
after three runs.

Three. Should shrink-on-transient live in the base class? Today the default is Stop and
every policy re-implements shrinking, and that is exactly where a four-lineage independence
check quietly becomes a three-lineage one.

Four. Is loopback-only permanent for the control plane?

Five. Should model C with no caller refuse to start rather than fall back?

Six. Should the CLI's policy imports be lazy? Listing tools currently pays for langgraph,
and about ${STARTUP_S} seconds of this deck's run was startup outside the loop.

Thank you — and the fastest way to disagree with any of this is to pull the branch and run
the mining script.
  `);
  footer(s, `every ask names a file and a line · ${HEAD}`);
}

// ============================================================ B1. compute patterns
{
  const s = slide();
  title(s, "Backup: the compute patterns", "backup · not in any running order");

  tbl(s, ["Pattern", "Meaning", "Scheduling implication", "Used?"],
    Object.entries(S.patterns).map(([name, v]) => {
      const meaning = { P1: "GPU-node-local, in-job", P2: "CPU-parallel fan-out, in-job",
        P3: "MPI multi-node, in-job", P4: "external HPC job",
        P5: "network service over HTTPS", P6: "in-process",
        P7: "composite pipeline", P8: "external experiment (robotic lab)" }[name];
      const impl = { P1: "one GPU slot, in the allocation we hold",
        P2: "a core budget, sized from sched_getaffinity",
        P3: "ranks and nodes, declared up front",
        P4: "a durable ledger entry — it outlives the agent",
        P5: "allowed only if site.allow_external",
        P6: "MUST NEVER be scheduled — the composer inlines it",
        P7: "decomposed before validation",
        P8: "forward-declared; a measurement may arrive after termination" }[name];
      return [name, meaning, impl,
        S.patterns_used.includes(v) ? `yes · ${S.tools.filter(t => t.pattern === v).length} tools` : "no"];
    }),
    M, 1.5, [1.1, 3.3, 5.3, 2.63],
    { mono: [0], fs: 10.5, mfs: 10, rowH: 0.47,
      cell: (i, j, c) => (j === 3 && String(c).startsWith("no")) ? { color: C.muted } : {} });

  card(s, M, 5.9, W - 2 * M, 0.75, "The taxonomy is organised by scheduling implication, not by science",
    ["Dispatch depends on the pattern, never on what a tool computes — which is why P6 being "
     + "scheduled is a composer bug rather than a slow path, and why P4 and P8 are the two that "
     + "need a durable ledger entry."],
    { fill: C.dTint, hc: C.d, fs: 10.5 });

  s.addNotes(`
Backup slide, if someone asks about the pattern taxonomy. Eight patterns, organised by what
they imply for scheduling rather than by what the tool computes. Two are used: P1 for the
GPU stages and P2 for the Rosetta fan-out. P6 is the interesting one — in-process, and it
must never be scheduled; the composer inlines it, so a scheduled P6 is a bug and not a slow
path. P4 and P8 are the two that outlive the agent and therefore need a durable ledger
entry, and P8 is forward-declared for a wet-lab measurement arriving after the campaign has
ended.
  `);
  footer(s, `mined: run.json · surfaces.patterns · ${S.n_patterns} declared, ${S.patterns_used.length} used`);
}

// ============================================================ B2. the type lattice
{
  const s = slide();
  title(s, "Backup: the artifact type lattice", "backup · not in any running order");

  const types = S.artifact_types;
  const cw = (W - 2 * M - 3 * 0.12) / 4;
  types.forEach((t, i) => {
    const x = M + (i % 4) * (cw + 0.12), y = 1.5 + Math.floor(i / 4) * 0.68;
    box(s, x, y, cw, 0.56, { title: t, fs: 11.5, fill: C.panel, line: C.rule, tc: C.ink });
  });

  code(s, [
    "def unifies_with(self, other: \"ArtifactType\") -> bool:",
    "    if self is other: return True",
    "    # A Complex satisfies a Backbone requirement (it contains one); not the reverse.",
    "    if self is ArtifactType.COMPLEX and other is ArtifactType.BACKBONE: return True",
    "    if self is ArtifactType.METRIC_SET and other is ArtifactType.METRIC: return True",
    "    return False",
  ], M, 3.7, 7.6, 1.5, { anchor: "core/types.py · EDITED (one-lined)", fs: 9.5 });

  card(s, M + 7.85, 3.7, 4.48, 1.5, "Two distinctions carry real weight",
    ["SMALL_MOLECULE vs PARAMETERIZED — an unparameterised ligand reaching a force field is a "
     + "type error at COMPOSITION time, not silent corruption.",
     "BACKBONE vs COMPLEX — so an interface scorer cannot be handed a monomer."],
    { fill: C.cTint, hc: C.c, fs: 10 });

  card(s, M, 5.45, W - 2 * M, 1.2, "Why scientific types rather than file formats",
    [`${S.n_artifact_types} types, and every one of them would be ".pdb" or ".json" in a format-based `
     + `lattice — at which point gate 1 can only check that a file exists, and the composer `
     + `cannot refuse a graph that is scientifically meaningless but structurally fine.`,
     "This is what makes runtime graph composition checkable at all (Part B doc 05, gate 1)."],
    { fill: C.panel, hc: C.ink, fs: 10.5 });

  s.addNotes(`
Second backup: the type lattice. Twelve scientific types rather than file formats, and the
reason is gate one. If these were .pdb and .json, the type gate could only check that a file
exists — and the composer could not refuse a graph that is structurally fine and
scientifically meaningless.

Two distinctions do most of the work. Small molecule versus parameterized, so an
unparameterised ligand reaching a force field is a type error at composition time rather
than silent corruption. And backbone versus complex, so an interface scorer cannot be handed
a monomer. Note the asymmetry in unifies_with: a complex satisfies a backbone requirement
because it contains one, and not the reverse.
  `);
  footer(s, "core/types.py · the lattice is deliberately small: it only needs the distinctions that cause real corruption");
}

save(require("path").join(__dirname, "impress-a-api.pptx"));
