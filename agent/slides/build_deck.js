// Builds slides/impress-a-codewalk.pptx.
//
//   python slides/run_model.py                       # regenerate slides/run.json first
//   NODE_PATH=<dir with pptxgenjs> node slides/build_deck.js
//
// Every diagram is native, editable PowerPoint shapes - never an image. One visual
// vocabulary throughout, shared with the designagent deck so the two read as siblings:
//
//   line style = status   solid:  built, runs end to end against something real
//                         dotted: built and tested, never exercised for real
//                         dashed: designed for, not implemented
//   orange = a RADICAL component, wherever it appears.
//
// Numbers come from run.json. Code stats, the mock campaign and the pattern signatures are
// mined live from this checkout; the Delta job figures are transcribed from
// plans/first-real-run.md (the raw logs live on Delta) and the slides say so.
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const R = JSON.parse(fs.readFileSync(path.join(__dirname, "run.json"), "utf8"));
const CODE = R.code, MOCK = R.mock, SHAPE = R.shape, D = R.delta, DONE = R.delta.completed;

const C = {
  ink: "16222B", text: "22303C", muted: "5E6B75", rule: "C9D1D8", panel: "EEF2F5",
  white: "FFFFFF",
  reason: "3B4E8C", reasonTint: "E9EDF7",    // the reasoner / policy layer
  exec: "1E6470", execTint: "E3F0F1",        // the executor / runtime
  compose: "2E7D5B", composeTint: "E4F1EA",  // compose, validate, interlock
  tool: "7A4A8C", toolTint: "F3EAF6",        // tools and task agents
  radical: "D9731A", radicalTint: "FCEBDD",  // RADICAL components
  fail: "C0392B", failTint: "F9E0DD",
  good: "2E7D4F",
};
const HF = "Cambria", BF = "Calibri", MF = "Consolas";
const DASH = { built: "solid", tested: "sysDot", planned: "dash" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "IMPRESS-A: an agent that composes its own workflows";
pres.author = "IMPRESS-A";
const W = 13.333, H = 7.5, M = 0.5;

// ---------------------------------------------------------------- helpers
function text(s, t, x, y, w, h, o = {}) {
  s.addText(t, Object.assign({ x, y, w, h, fontFace: BF, fontSize: 14, color: C.text,
    margin: 0, valign: "top", isTextBox: true }, o));
}
function title(s, t, kicker) {
  if (kicker) text(s, kicker.toUpperCase(), M, 0.35, 9, 0.3,
    { fontSize: 12, bold: true, color: C.exec, charSpacing: 2 });
  text(s, t, M, 0.62, W - 2 * M, 0.8, { fontFace: HF, fontSize: 28, bold: true, color: C.ink });
}
function box(s, x, y, w, h, o = {}) {
  const status = o.status || "built";
  s.addShape(o.round === false ? pres.shapes.RECTANGLE : pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: o.round === false ? undefined : 0.08,
    fill: { color: o.fill || C.white },
    line: { color: o.line || C.muted, width: o.lw || 1.5, dashType: DASH[status] },
  });
  if (o.title || o.sub) {
    const runs = [];
    if (o.title) runs.push({ text: o.title, options: { bold: true, fontSize: o.fs || 14,
      color: o.tc || C.ink, breakLine: !!o.sub } });
    if (o.sub) runs.push({ text: o.sub, options: { fontSize: o.sfs || 10.5,
      color: o.sc || C.muted, fontFace: o.subMono ? MF : BF } });
    text(s, runs, x + 0.08, y + 0.05, w - 0.16, h - 0.1,
      { valign: o.valign || "middle", align: o.align || "center" });
  }
}
function line(s, x1, y1, x2, y2, o = {}) {
  s.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.max(Math.abs(x2 - x1), 0.0001),
    h: Math.max(Math.abs(y2 - y1), 0.0001), flipH: x2 < x1, flipV: y2 < y1,
    line: { color: o.color || C.muted, width: o.w || 1.5, dashType: DASH[o.status || "built"],
      endArrowType: o.noArrow ? undefined : "triangle",
      beginArrowType: o.both ? "triangle" : undefined },
  });
}
function label(s, t, x, y, w, o = {}) {
  text(s, t, x, y, w, o.h || 0.26, Object.assign({ fontSize: 10.5, color: C.muted,
    fontFace: o.mono ? MF : BF, align: o.align || "center", valign: "middle" }, o));
}
function legend(s, x, y, withRadical = true, tw = 3.0) {
  const items = [["built, runs for real", "built"],
                 ["built and tested, never run for real", "tested"],
                 ["designed for, not implemented", "planned"]];
  items.forEach(([t, st], i) => {
    const yy = y + i * 0.25;
    s.addShape(pres.shapes.LINE, { x, y: yy + 0.12, w: 0.42, h: 0,
      line: { color: C.text, width: 1.75, dashType: DASH[st] } });
    text(s, t, x + 0.52, yy, tw, 0.25, { fontSize: 9.5, color: C.muted, valign: "middle" });
  });
  if (withRadical) {
    const yy = y + 3 * 0.25;
    s.addShape(pres.shapes.RECTANGLE, { x: x + 0.08, y: yy + 0.04, w: 0.24, h: 0.16,
      fill: { color: C.radicalTint }, line: { color: C.radical, width: 1.5 } });
    text(s, "RADICAL component", x + 0.52, yy, tw, 0.25,
      { fontSize: 9.5, color: C.radical, bold: true, valign: "middle" });
  }
}
// Code blocks size their own type to the box they were given. A fixed point size silently
// overflows the moment a snippet gains a line, and an overflowing code block on a projector
// is the one failure this deck cannot afford - so the line spacing is solved for, and
// anything that would fall below MIN_PT warns loudly at build time rather than shipping
// clipped.
const MIN_PT = 8.5;
function code(s, lines, x, y, w, h, o = {}) {
  const want = o.ls || 13;
  let ls = Math.min(want, ((h - 0.2) * 72) / lines.length);
  if (ls < MIN_PT) {
    console.warn(`  ! code block at y=${y} needs ${lines.length} lines in ${h}" ` +
      `(${ls.toFixed(1)}pt < ${MIN_PT}pt floor) - shorten it or grow the box`);
    ls = MIN_PT;
  }
  const fs = Math.min(o.fs || 10.5, ls * 0.80);
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h,
    fill: { color: o.fill || C.ink }, line: { color: o.fill || C.ink } });
  text(s, lines.join("\n"), x + 0.11, y + 0.1, w - 0.22, h - 0.2,
    { fontFace: MF, fontSize: fs, color: o.color || "DCE5EC", lineSpacing: ls });
  if (o.anchor) text(s, o.anchor, x, y + h + 0.02, w, 0.2,
    { fontFace: MF, fontSize: 8.5, color: C.muted, align: "right" });
}
function footer(s, t) {
  text(s, t, M, H - 0.4, W - 2 * M, 0.25, { fontSize: 10, color: C.muted, italic: true });
}
function card(s, x, y, w, h, heading, body, o = {}) {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h,
    fill: { color: o.fill || C.panel }, line: { color: o.line || o.fill || C.panel } });
  text(s, heading, x + 0.14, y + 0.09, w - 0.28, 0.3,
    { fontSize: o.hfs || 13, bold: true, color: o.hc || C.ink });
  if (Array.isArray(body)) {
    text(s, body.map((t, j) => ({ text: t,
      options: { bullet: true, breakLine: j < body.length - 1 } })),
      x + 0.14, y + 0.43, w - 0.28, h - 0.52,
      { fontSize: o.fs || 11.5, color: C.text, paraSpaceAfter: 4 });
  } else {
    text(s, body, x + 0.14, y + 0.43, w - 0.28, h - 0.52,
      { fontSize: o.fs || 11.5, color: C.text });
  }
}
function tbl(s, hdr, rows, x, y, cw, o = {}) {
  const mono = o.mono || [], ctr = o.center || [];
  const body = rows.map((r, i) => r.map((c, j) => ({ text: String(c), options: Object.assign({
    fontFace: mono.includes(j) ? MF : BF,
    fontSize: mono.includes(j) ? (o.mfs || 9.5) : (o.fs || 11.5),
    bold: o.boldFirst !== false && j === 0,
    color: mono.includes(j) ? C.muted : C.text,
    align: ctr.includes(j) ? "center" : "left",
    fill: { color: i % 2 ? C.white : C.panel } }, (o.cell && o.cell(i, j, c)) || {}) })));
  const head = hdr.map(h => ({ text: h, options: { bold: true, color: C.white,
    fill: { color: o.hfill || C.exec }, fontSize: o.hfs || 11 } }));
  s.addTable([head].concat(body), { x, y, w: cw.reduce((a, b) => a + b), colW: cw,
    border: { type: "solid", color: C.rule, pt: 0.75 }, fontFace: BF, valign: "middle",
    rowH: o.rowH, margin: o.margin || 0.07 });
}

// ================================================================ 1. Title
{
  const s = pres.addSlide(); s.background = { color: C.ink };

  // Motif, left to right: a reasoner, a gate it must pass, the graph that gets composed,
  // and the orange pool the graph lands on. It is the whole talk in one strip.
  const cx = 8.15, cy = 2.25;
  s.addShape(pres.shapes.OVAL, { x: cx, y: cy, w: 1.15, h: 1.15,
    fill: { color: C.reason }, line: { color: "A8B6DC", width: 1.5 } });
  text(s, "decide", cx, cy, 1.15, 1.15,
    { fontSize: 12, bold: true, color: C.white, align: "center", valign: "middle" });

  const gx = 9.75, gy = 2.05;
  [0, 1, 2, 3, 4].forEach(i =>
    s.addShape(pres.shapes.RECTANGLE, { x: gx + i * 0.17, y: gy, w: 0.1, h: 1.55,
      fill: { color: C.compose }, line: { color: C.compose } }));
  text(s, "5 gates", gx - 0.35, gy + 1.6, 1.6, 0.25,
    { fontSize: 9.5, color: "8FD0B0", align: "center" });
  line(s, cx + 1.17, cy + 0.57, gx - 0.04, cy + 0.57, { color: "A8B6DC" });

  const dx = 10.95, dy = 1.95;
  [0, 1].forEach(l => [0, 1, 2].forEach(k => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: dx + k * 0.66, y: dy + l * 0.82,
      w: 0.46, h: 0.42, rectRadius: 0.06,
      fill: { color: C.tool }, line: { color: "D8BFE2", width: 1 } });
    if (k < 2) line(s, dx + k * 0.66 + 0.47, dy + l * 0.82 + 0.21,
      dx + (k + 1) * 0.66 - 0.02, dy + l * 0.82 + 0.21, { color: "D8BFE2", w: 1, noArrow: true });
  }));
  text(s, "a composed graph,\n2 lineages", dx - 0.1, dy + 1.72, 2.1, 0.5,
    { fontSize: 9.5, color: "C9A8D6", align: "center" });

  [0, 1, 2, 3].forEach(i =>
    s.addShape(pres.shapes.RECTANGLE, { x: 10.4 + i * 0.62, y: 4.55, w: 0.5, h: 0.38,
      fill: { color: C.radical }, line: { color: C.radical } }));
  line(s, dx + 0.75, dy + 1.28, 11.6, 4.5, { color: "E8B98A" });
  text(s, "radical.asyncflow  →  rhapsody  →  Dragon", 9.4, 5.0, 3.6, 0.26,
    { fontSize: 9.5, color: "E8B98A", align: "center" });

  text(s, "IMPRESS-A", M + 0.3, 1.5, 7.0, 0.4,
    { fontSize: 14, bold: true, color: "8FB8C9", charSpacing: 3 });
  text(s, "An agent that composes its own workflows", M + 0.3, 1.95, 7.1, 1.35,
    { fontFace: HF, fontSize: 34, bold: true, color: C.white });
  text(s, "— and what its first completed campaign on Delta did, and did not, prove",
    M + 0.3, 3.5, 7.1, 0.9, { fontSize: 17, color: "D5DEE5" });
  text(s, `Job ${DONE.job}: six stages, 6/6 tasks ok in ${DONE.wall}, admitted on the first ` +
    `attempt, a one-node Pareto front carrying all four objectives`,
    M + 0.3, 4.6, 7.1, 0.7, { fontSize: 13, color: "9FB0BD" });
  text(s, `Lab code walk · main @ ${CODE.head} · ${(CODE.src_total / 1000).toFixed(1)}k lines of ` +
    `source, ${CODE.tests_collected} tests, ${CODE.n_tools} tools in 5 toolkits`,
    M + 0.3, 6.45, 8.5, 0.3, { fontSize: 12, color: "7E8F9C" });
  s.addNotes(
`[0:45] A code walk, not a results talk. IMPRESS-A runs protein design campaigns on HPC: you give it a goal and a budget, and it decides what experiment to run next, composes a workflow out of a tool registry, runs it through asyncflow and rhapsody, and updates a population of candidates.

The word doing the work is composes. There is no fixed pipeline anywhere in this repository. Every experiment is a new graph no human has reviewed, and most of the code I will show you exists because of that one fact.

When some of you last saw this, nothing real had ever run. Since then a six-stage campaign completed on Delta. I will walk the seam, show what four jobs cost us, and be precise about how little one completed campaign proves.`);
}

// ================================================================ 2. What it does
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "One goal, a campaign of composed experiments", "What it does");

  const steps = [
    ["goal", "campaign YAML:\nobjectives · budget", C.muted],
    ["decide", "a reasoner picks the\nnext experiment", C.reason],
    ["compose", "abstract intent →\na typed DAG", C.compose],
    ["admit", "5 gates · interlock\ndry-run · reserve", C.compose],
    ["execute", "asyncflow → rhapsody\nconcurrent or Dragon", C.radical],
    ["absorb", "QC · Pareto tree\nprovenance · trust", C.exec],
  ];
  const sw = 1.93, gap = 0.11;
  steps.forEach(([h, b, col], i) => {
    const x = M + i * (sw + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.55, w: sw, h: 1.15, rectRadius: 0.08,
      fill: { color: C.white }, line: { color: col, width: 2 } });
    text(s, h, x, 1.63, sw, 0.3, { fontSize: 12, bold: true, color: col, align: "center" });
    text(s, b, x + 0.06, 1.94, sw - 0.12, 0.7,
      { fontSize: 10, color: C.text, align: "center" });
    if (i < steps.length - 1)
      line(s, x + sw + 0.01, 2.12, x + sw + gap - 0.01, 2.12, { w: 1.25 });
  });
  // the two edges that make it a loop rather than a pipeline
  line(s, M + 3.5 * (sw + gap), 2.76, M + 1.55 * (sw + gap), 2.76, { color: C.compose, w: 1.5 });
  label(s, "rejected → a structured reason, and another attempt",
    M + 1.4 * (sw + gap), 2.78, 4.3, { fs: 9.5, color: C.compose, align: "center" });
  line(s, M + 5.5 * (sw + gap), 3.02, M + 1.5 * (sw + gap), 3.02, { color: C.exec, w: 1.5 });
  label(s, "the next decision sees every result so far",
    M + 2.3 * (sw + gap), 3.04, 4.3, { fs: 9.5, color: C.exec, align: "center" });

  const m = DONE.metrics;
  card(s, M, 3.5, 6.25, 2.25, `What came back, for real — job ${DONE.job}`, [
    "rfd3_design → ligandmpnn_design → packmin → fastrelax → filter_shape → boltz_predict, " +
      `6/6 tasks ok in ${DONE.wall}`,
    `all four campaign objectives valued: total_score ${m.total_score}, ` +
      `shape_complementarity ${m.shape_complementarity}, complex_plddt ${m.complex_plddt}, ` +
      `ligand_iptm ${m.ligand_iptm}`,
    `admitted on the first attempt, ${DONE.cost.gpu_hours} GPU-h and ` +
      `${DONE.cost.cpu_hours} CPU-h charged against the ledger`,
    "per-tool cost measured for all six, and the specs corrected from it",
  ], { fill: C.panel, fs: 11 });

  card(s, M + 6.58, 3.5, 6.25, 2.25, "And what one completed campaign is not", [
    "One lineage, one cycle, one draw. replicas > 1 has never executed, so the independence " +
      "invariant is unexercised.",
    `The node is ${DONE.qc}, not pass — the composition pattern is provisional. Nothing has ever ` +
      "been promoted on Delta, so the trusted path has never run.",
    "No measurement has ever superseded a prediction, so the calibration machinery is untested " +
      "against reality.",
  ], { fill: C.failTint, hc: C.fail, fs: 11 });

  text(s, [
    { text: "Read it as a floor, not a result. ", options: { bold: true, color: C.ink } },
    { text: "The engineering claim is that a machine-composed workflow survived contact with " +
      "real tools on real hardware and was caught, costed and recorded on the way through. " +
      "The science is one design." },
  ], M, 5.95, 12.33, 0.6, { fontSize: 13 });
  footer(s, "Numbers from slides/run.json. Delta figures transcribed from plans/first-real-run.md; " +
    "the raw logs live under $WORK_DIR on Delta.");
  s.addNotes(
`[1:05] The shape of a campaign, and then what one actually produced.

Across the top: a goal, a reasoner that decides, a composer that turns that into a typed DAG, admission, execution, absorption. Two edges make it a loop rather than a pipeline — a rejected graph comes back with a structured reason and another attempt, and every decision after the first sees every result so far.

Left card, all measured. Six stages end to end in under three minutes: diffusion, sequence design, two Rosetta stages, a shape filter, a Boltz prediction. All four objectives came back with real values, admitted on the first attempt, cost measured per stage.

Right card, because you would ask and I would rather say it first. One lineage, one cycle, one draw. Replicas greater than one has never run. The node is marked suspect rather than pass, because the pattern is still provisional — the interlock working, not a failure. And no measurement has ever superseded a prediction.

Treat it as a floor. What it proves is that the plumbing survives contact with real tools.`);
}

// ================================================================ 3. The constraint
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Two facts set the whole design", "Why it looks like this");

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 1.5, w: 12.33, h: 0.95,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, [
    { text: "A machine composes workflows nobody has reviewed — ", options: { bold: true, color: "F0C898" } },
    { text: "out of scientific tools that fail ", options: { color: "DCE5EC" } },
    { text: "silently", options: { bold: true, color: "F09A8C" } },
    { text: " far more often than they crash. A generator returns a structure with no secondary " +
      "structure, a confident designability score, and exit code 0.", options: { color: "DCE5EC" } },
  ], M + 0.22, 1.63, 11.9, 0.7, { fontSize: 16.5, valign: "middle" });

  const rows = [
    ["A policy emits intent, never a DAG",
     "ExperimentIntent is a list of tool ids and parameters. Turning it into a graph is the composer's job, so control models stay interchangeable — and the import contract forbids the edge.",
     "policy/base.py · core/decision.py:21"],
    ["Composition-time validation, then a dry-run",
     "Five gates, then every task agent parameterizes without executing. Rejection is cheap and structured, so free composition is affordable to get wrong.",
     "compose/validate.py:30, :143"],
    ["Trust is scored on shape, and earned",
     "A novel graph shape runs under a cost cap, a forced dry-run, and is marked suspect whatever it scores. Promotion is N consecutive clean runs; demotion is immediate.",
     "compose/interlock.py:146"],
    ["Exit code is never evidence",
     "Every non-P6 tool declares mandatory QC gates, and a node whose verdict is FAIL is never eligible for the Pareto front, whatever it scored.",
     "tools/agent.py:110 · core/pareto.py:56"],
    ["One writer, and it decides termination",
     "The executor owns all campaign state; every mutating block is await-free, so an observation is never taken mid-absorb. Budget and stagnation are facts a reasoner cannot see.",
     "runtime/executor.py:242"],
  ];
  tbl(s, ["consequence", "what it means in the code", "where"], rows, M, 2.68,
    [3.3, 6.75, 2.28], { mono: [2], mfs: 9, fs: 11.5,
      rowH: [0.3, 0.66, 0.6, 0.62, 0.56, 0.66], margin: 0.08 });

  text(s, [
    { text: "The flip side, said plainly: ", options: { bold: true, color: C.ink } },
    { text: "if a human reviewed every graph before it ran, you would not build most of this. " +
      "You would write the DAG down once and schedule it." },
  ], M, 6.5, 12.33, 0.6, { fontSize: 13 });
  s.addNotes(
`[1:00] If you keep one slide, keep this one. Everything after it is a consequence rather than a preference.

Two facts. A machine composes workflows no human has reviewed. And the tools those workflows call fail silently far more often than they crash — a generator hands back a structure with no secondary structure, a confident designability number, and exit code zero.

Five things fall out. A policy emits abstract intent, not a DAG, so control models stay swappable. Everything is validated before it executes: five gates, then a dry-run where every agent parameterizes without running. Trust is scored on shape and has to be earned. Exit code is never evidence, so a QC-failed node can never reach the front whatever it scored. And exactly one component writes state and decides when to stop.

The honest flip side is at the bottom. If a person reviewed every graph before it ran, you would write the DAG down once and schedule it, and most of this would stop paying for itself.`);
}

// ================================================================ 4. The loop (F1)
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Two coroutines, one writer", "The loop · F1");

  // Two lanes with the session as a band between them. Never draw the policy inside the
  // executor's frame - that is the old architecture, and this room would catch it.
  const lw = 3.5, rw = 4.9, ly = 1.5, sx = M + lw + 0.55, sw = 1.55;
  const rx = sx + sw + 0.55;

  const band = (t, x, w, color, fs = 12) => {
    s.addShape(pres.shapes.RECTANGLE, { x, y: ly, w, h: 0.38,
      fill: { color }, line: { color } });
    text(s, t, x + 0.1, ly, w - 0.2, 0.38,
      { fontSize: fs, bold: true, color: C.white, valign: "middle" });
  };
  band("REASONER — coroutine 1", M, lw, C.reason);
  band("SESSION", sx, sw, C.muted, 11);
  band("EXECUTOR — coroutine 2 · the ONLY writer", rx, rw, C.exec);
  label(s, "policy/driver.py or any conduct()", M, ly + 0.4, lw, { fs: 9, mono: true });
  label(s, "core/session.py", sx, ly + 0.4, sw, { fs: 9, mono: true });
  label(s, "runtime/executor.py", rx, ly + 0.4, rw, { fs: 9, mono: true });

  const steps = [
    ["OBSERVE", "", "OBSERVE  ::observe:215", "read-only, await-free", "CampaignObservation", "left"],
    ["DECIDE", "the one swappable block", "", "", "", null],
    ["SUBMIT", "_submit_with_retry:84", "ADMIT  ::_admit_once:304", "compose → gates → interlock\n→ dry-run → reserve", "ExperimentIntent", "right"],
    ["", "", "DISPATCH  Dispatcher.submit:165", "returns a handle, does not await", "", null],
    ["WAIT", "result() / as_completed()", "REAP  ::pump:744 → _reap:629", "collect · QC · _absorb:242\nterminate?", "RunOutcome", "left"],
  ];
  // Explicit tops and heights rather than an accumulator: the gap under SUBMIT has to hold
  // the rejection edge and its label, and solving that by hand is how the rows crept into
  // the cards the first time.
  const tops = [2.25, 2.92, 3.86, 4.95, 5.62];
  const hs = [0.55, 0.60, 0.70, 0.55, 0.66];
  steps.forEach(([lt, ls2, rt, rs, arrow, dir], i) => {
    const y = tops[i], h = hs[i];
    if (lt) box(s, M, y, lw, h, { title: lt, sub: ls2 ? "\n" + ls2 : "",
      line: i === 1 ? C.reason : C.muted, fill: i === 1 ? C.reasonTint : C.white,
      fs: i === 1 ? 14 : 12.5, sfs: 9, lw: i === 1 ? 2.5 : 1.5, subMono: i !== 1 });
    if (rt) box(s, rx, y, rw, h, { title: rt.split("  ")[0],
      sub: "  " + rt.split("  ").slice(1).join("  ") + (rs ? "\n" + rs : ""),
      line: C.exec, fill: C.execTint, fs: 12.5, sfs: 9, align: "left" });
    if (arrow) {
      const ay = y + h / 2;
      if (dir === "right") line(s, M + lw + 0.03, ay, rx - 0.03, ay, { color: C.exec, w: 1.75 });
      else line(s, rx - 0.03, ay, M + lw + 0.03, ay, { color: C.exec, w: 1.75 });
      label(s, arrow, sx - 0.45, ay - 0.25, sw + 0.9, { fs: 8.5, mono: true, color: C.exec });
    }
    if (i === 1) {
      label(s, "A agentic · B oracle · C external · D explicit", M, y + h + 0.01, lw,
        { fs: 9, color: C.reason });
    }
  });
  // the rejection edge, the one people miss — it lives in the widened gap under SUBMIT
  label(s, "SubmissionRejected(ValidationFailure) → on_rejected → retry, ≤ max_attempts",
    M + 0.2, 4.60, 11.0, { fs: 9, color: C.fail, bold: true, align: "center" });
  line(s, rx - 0.03, 4.84, M + lw + 0.03, 4.84, { color: C.fail, w: 2 });

  card(s, M, 6.42, 6.2, 0.8, "Why the split exists", [
    "The old manager awaited the whole graph where it submitted it, so the policy could not be " +
      "consulted until the slowest lineage finished.",
  ], { fill: C.reasonTint, hc: C.reason, fs: 10.5 });
  card(s, M + 6.5, 6.42, 6.33, 0.8, "What keeps it honest", [
    "Every mutating block in the executor is await-free. Adding an await inside observe or " +
      "_absorb reintroduces torn reads — a discipline, not something Python enforces.",
  ], { fill: C.execTint, hc: C.exec, fs: 10.5 });
  s.addNotes(
`[1:15] Two coroutines meeting at a session, and the asymmetry between them is the point.

Left, a reasoner: observe, decide, submit, wait. Two ways to be one — implement decide and let a driver play the loop, which is what models A through D do; or implement conduct and drive yourself, submitting as many experiments as you like and collecting them in the order they finish. The second is what makes a federation of agents generating an ensemble in parallel expressible at all.

Right, the executor: admit, dispatch, reap, absorb. It is the only writer of campaign state. Note what it is not — it is not the loop body with a policy called inside it. The reasoner is a peer.

The red arrow is the one people miss. A rejected submission does not burn the experiment: the policy gets a structured reason and another attempt, bounded by max_attempts and independently capped in the executor, because a conduct reasoner is under no obligation to honour anything the driver promises.

Two rules hold it together. One writer, and every mutating block is await-free, so an observation is never taken halfway through absorbing a run. And the executor decides termination, because budget and stagnation are facts a reasoner cannot see.`);
}

// ================================================================ 5. Architecture (F2)
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Layers, and the four arrows that are not there", "Architecture · F2");

  // Geometry note: the band column, the forbidden-edge gutter and the right rail have to
  // share 12.3 inches. The rail is what suffers first, so it is sized last and generously.
  const lx = M, lbw = 1.1, cx = lx + lbw + 0.08, cw = 5.95;
  const bands = [
    ["control/", 1.42, 0.52, C.exec, "CampaignControlPlane · in-process ✔  HTTP+SSE ✔  MCP ╌ not built"],
    ["policy/", 2.00, 0.62, C.reason, "A agentic · B oracle · C external · D explicit · wrappers · driver"],
    ["manager.py", 2.68, 0.4, C.reason, "a facade: starts the executor and the reasoner, first to finish ends it"],
    ["runtime/", 3.14, 0.62, C.exec, "executor.py — sole state owner · session.py · runservice.py"],
    ["compose/", 3.82, 0.62, C.compose, "composer · graph · validate (5 gates) · interlock (trust)"],
    ["tools/", 4.50, 0.62, C.tool, "spec · registry · agent (4 phases) · gates · the real adapters"],
    ["exec/", 5.18, 0.62, C.radical, "backend · dispatch · ledger · resources ╌ no caller"],
    ["core/", 5.86, 0.50, C.muted, "tree · pareto · qc · budget · decision · session · results · provenance"],
  ];
  bands.forEach(([t, y, h, col, body]) => {
    s.addShape(pres.shapes.RECTANGLE, { x: lx, y, w: lbw, h,
      fill: { color: col }, line: { color: col } });
    text(s, t, lx, y, lbw, h, { fontSize: 11, bold: true, color: C.white,
      align: "center", valign: "middle", fontFace: MF });
    box(s, cx, y, cw, h, { title: body, line: col, fill: C.white, fs: 10,
      align: "left", round: false, lw: 1.25 });
  });
  box(s, cx, 6.44, cw, 0.50, { title: "radical.asyncflow.WorkflowEngine → rhapsody backend",
    sub: "\n   concurrent · dragon · radical · dask — chosen BY NAME from the campaign spec",
    line: C.radical, fill: C.radicalTint, fs: 10, sfs: 8.5, tc: C.radical,
    align: "left", round: false });
  line(s, cx + 0.9, 5.80, cx + 0.9, 6.41, { color: C.radical });

  // the forbidden edges — drawn, because an edge that is merely absent reads as an oversight
  const fx = cx + cw + 0.1;
  [["policy ✗ tools", 2.12], ["policy ✗ exec", 2.36], ["policy ✗ runtime", 2.60],
   ["compose ✗ exec", 3.95]].forEach(([t, y]) => {
    text(s, t, fx, y, 1.45, 0.24, { fontSize: 9, color: C.fail, bold: true,
      fontFace: MF, valign: "middle" });
  });

  const rx = fx + 1.5, rwd = W - M - rx;
  card(s, rx, 1.45, rwd, 1.85, "The two rules that carry weight", [
    "policy ↛ tools | exec | runtime — a policy that can reach a tool adapter stops emitting " +
      "abstract intent, and control models stop being swappable.",
    "compose ↛ exec — validation stays testable with no backend at all. That is the entire " +
      "laptop test tier.",
  ], { fill: C.reasonTint, hc: C.reason, fs: 10 });
  card(s, rx, 3.45, rwd, 1.7, "Asserted, not reviewed", [
    "tests/test_layering.py walks the source with ast and checks every internal import " +
      "against one table.",
    "ast.walk deliberately: adapters defer science imports into run() bodies, and a deferred " +
      "cross-layer import is exactly as fatal as one at the top.",
  ], { fill: C.composeTint, hc: C.compose, fs: 10 });
  card(s, rx, 5.3, rwd, 1.78, "What writing it found", [
    "Two undocumented edges — manager → tools, and cli / __main__ in no row at all. Both are " +
      "recorded now: a contract with undocumented edges is not a contract.",
  ], { fill: C.panel, fs: 10 });

  footer(s, "policy → core is the edge that forced core/session.py and core/results.py to exist: " +
    "a reasoner may hold a RunOutcome, so RunOutcome cannot live in exec/.");
  s.addNotes(
`[1:00] Eight layers, and the thing worth looking at is in red.

Control plane at the top, one protocol with two transports shipped. Then the policy layer, the swappable one. A thin manager facade, the runtime that owns state, composition and validation, tools, exec, and at the bottom core, which imports nothing internal.

The red marks are four arrows that do not exist. A policy may not import tools, exec or runtime; compose may not import exec. I draw them because an edge that is merely absent reads as an oversight, and this room will ask whether the rule is enforced or merely intended.

It is enforced. A test walks the package with ast and checks every internal import against one table — ast.walk rather than module-level imports, because the real adapters defer their science imports into run bodies on purpose, and a deferred cross-layer import is exactly as fatal as one at the top.

Writing that test found two edges nobody had documented. Both are in the table now.`);
}

// ================================================================ 6. One experiment, typed
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "One experiment, and the type at every hop", "Data flow · cuttable");

  const hops = [
    ["CampaignObservation", "front · population · budget\ntools · last rejection", C.exec, "executor.py:215"],
    ["Decision", "ComposeAndRun | Backtrack\nRequestHuman | Stop", C.reason, "policy/*.py"],
    ["ExperimentIntent", "tool ids + params + replicas\nABSTRACT — never a DAG", C.reason, "core/decision.py:21"],
    ["TaskGraph", "typed nodes, deps, per-lineage\nseed — plain data", C.compose, "composer.py:36"],
    ["DispatchHandle", "futures + gather,\nNOT awaited", C.radical, "dispatch.py:165"],
    ["RunOutcome", "serializable, core-typed,\nwritten to the ledger", C.exec, "dispatch.py:91"],
  ];
  const hw = 1.95, hg = 0.13;
  hops.forEach(([t, b, col, anchor], i) => {
    const x = M + i * (hw + hg);
    box(s, x, 1.5, hw, 1.25, { title: t, sub: "\n" + b, line: col, fill: C.white,
      fs: 10, sfs: 9, lw: 2 });
    label(s, anchor, x, 2.78, hw, { fs: 8, mono: true });
    if (i < hops.length - 1) line(s, x + hw + 0.01, 2.12, x + hw + hg - 0.01, 2.12, { w: 1.25 });
  });

  const adm = MOCK.admissions;
  const rej = adm.filter(a => a.rejected);
  code(s, [
    `$ impress-a run campaigns/mock-stabilize.yaml --model D`,
    ``,
    `  campaign : ${MOCK.campaign}`,
    `  cycles   : ${MOCK.cycles}`,
    `  stop     : ${MOCK.stop}`,
    `  nodes    : ${MOCK.nodes.length}  front: ${MOCK.front.length}`,
  ], M, 3.3, 6.2, 1.35, { anchor: "run.json — mined from a real run, this checkout", fs: 10 });

  tbl(s, ["run", "shape", "nodes", "est. gpu-h", "admitted?"],
    adm.map(a => [a.run, a.signature.slice(0, 8) + "…", a.nodes,
      a.estimate.gpu_hours.toFixed(3),
      a.rejected ? "refused — " + a.rejected.gate : "yes"]),
    M, 5.0, [0.8, 1.35, 0.75, 1.15, 2.15],
    { mono: [1], center: [2, 3], fs: 10.5, hfs: 10, rowH: 0.3,
      cell: (i, j, c) => (j === 4 && String(c).startsWith("refused"))
        ? { color: C.fail, bold: true } : (j === 4 ? { color: C.good } : {}) });

  card(s, M + 6.5, 3.3, 6.33, 1.6, "What the first row is", [
    `${rej.length ? rej[0].rejected.reason : "—"}`,
    "The policy answered by shrinking from 3 lineages to 2 and resubmitting. That is " +
      "on_rejected doing its job: a refusal costs an attempt, not the experiment.",
  ], { fill: C.failTint, hc: C.fail, fs: 10.5 });
  card(s, M + 6.5, 5.05, 6.33, 1.55, "And what the rest of the run shows", [
    `${MOCK.nodes.length} design nodes over ${MOCK.cycles} cycles, every one marked ` +
      `${MOCK.nodes[0].qc} — the pattern was provisional until the third clean run promoted it ` +
      `(${MOCK.promoted.length} promotion, in trust_events).`,
    `Front of ${MOCK.front.length}; the campaign stopped on "${MOCK.stop}" rather than on budget.`,
  ], { fill: C.panel, fs: 10.5 });

  footer(s, "The whole slide is one laptop run against the mock toolkit: real manager, real " +
    "policies, real composer and validator, stubbed science.");
  s.addNotes(
`[1:00] One experiment, left to right, naming the type at each hop — the types are the contract between layers.

The executor builds an observation. The policy returns a decision carrying an experiment intent: tool ids, parameters, a replica count. It is abstract, there is no DAG in it. The composer turns it into a typed graph, which is plain data. Dispatch registers that graph and hands back a handle without awaiting. What comes back is a run outcome, serializable and core-typed, so a reasoner in another process can hold it.

Underneath is an actual run on this laptop. Four admissions over three cycles. The first row was refused by the interlock — a provisional pattern is capped at ten percent of available budget and three lineages did not fit. The policy shrank to two and resubmitted. That is the retry doing its job: a refusal costs an attempt, not the experiment.

Six design nodes, every one marked suspect, because the shape stayed provisional until the third clean run promoted it.`);
}

// ================================================================ 7. Admission
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Admission: five gates, an interlock, and a reservation", "Admission");

  const gates = [
    ["1 type", "an edge whose producer type does not unify with the consumer's", ":38"],
    ["2 structure", "cycles, empty graphs, a tool composed without its QC gates", ":70"],
    ["3 parameter", "out of range, unknown, or declared frozen", ":86"],
    ["4 resource", "a SCHEDULED P6, oversize shapes, unproven GPU API, external submission", ":103"],
    ["5 budget", "an estimate exceeding remaining budget in any dimension", ":134"],
  ];
  tbl(s, ["gate", "rejects", "line"], gates, M, 1.5, [1.5, 5.4, 0.65],
    { mono: [2], fs: 11, hfs: 10.5, rowH: 0.34, center: [2] });

  const after = [
    ["INTERLOCK", "one instance in flight for an untrusted shape; a cost cap for a provisional one — both transient", "executor.py:331, :337"],
    ["DRY-RUN", "every task agent parameterizes WITHOUT executing", "validate.py:143"],
    ["RESERVE", "re-check against AVAILABLE budget — remaining less what in-flight runs hold", "executor.py:355"],
  ];
  tbl(s, ["then", "what it does", "where"], after, M, 3.75, [1.5, 4.2, 1.85],
    { mono: [2], mfs: 8.5, fs: 10.5, hfs: 10.5, rowH: [0.3, 0.46, 0.34, 0.46],
      hfill: C.compose });

  text(s, [
    { text: "Why RESERVE is last: ", options: { bold: true, color: C.ink } },
    { text: "the dry-run awaits. By the time it returns, another submission may have claimed " +
      "the budget gate 5 saw, so reserve re-checks and is the authoritative decision." },
  ], M, 5.5, 7.6, 0.6, { fontSize: 11.5 });

  // the trust loop, drawn beside the chain rather than inside it
  const tx = M + 7.85, tw = W - M - tx;
  card(s, tx, 1.5, tw, 1.05, "A pattern is the graph's SHAPE", [
    "tool ids plus typed edges, hashed. Parameter values are excluded, so tuning a parameter " +
      "does not reset accumulated trust.",
  ], { fill: C.composeTint, hc: C.compose, fs: 10.5 });

  const sc = [
    ["cost ceiling", "normal", "10% of available"],
    ["dry-run", "skipped", "forced"],
    ["result", "its QC verdict", "SUSPECT anyway"],
    ["in flight", "many", "one"],
  ];
  tbl(s, ["", "trusted", "provisional"], sc, tx, 2.75, [1.35, 1.3, 1.85],
    { fs: 10, hfs: 10, rowH: 0.3, center: [1, 2], hfill: C.compose,
      cell: (i, j) => j === 2 ? { color: C.fail } : (j === 1 ? { color: C.good } : {}) });

  card(s, tx, 4.5, tw, 1.55, "Promotion is mechanical", [
    "N consecutive clean runs promote; any failure demotes immediately and resets the counter.",
    "An untrusted shape may have only ONE instance in flight — N concurrent copies are one " +
      "draw sampled N times, not N pieces of evidence.",
  ], { fill: C.panel, fs: 10 });

  text(s, [
    { text: "Be honest about the limit: ", options: { bold: true, color: C.fail } },
    { text: "the interlock buys examination and delay, not soundness. A " },
    { text: "consistent", options: { italic: true } },
    { text: " novel silent failure promotes." },
  ], M, 6.15, 12.33, 0.5, { fontSize: 12.5 });
  footer(s, "All of it is one method — runtime/executor.py::_admit_once:304 — and it dispatches " +
    "nothing. Admission is synchronous everywhere, including over HTTP.");
  s.addNotes(
`[1:15] This is the answer to "you let a machine invent workflows?"

Five gates, in order, first refusal wins. Gate two rejects a tool composed without its QC gates, so you cannot compose your way out of quality control. Gate four rejects a P6 tool somebody tried to schedule — those are meant to be inlined, and a scheduled one is a composer bug.

Then three things that are not gates. The interlock. A dry-run, where every agent parameterizes without executing — that catches a graph that type-checks but cannot be turned into a command line. And a reservation.

Reserve is last for a reason: the dry-run awaits, and by the time it returns another submission may have claimed the budget gate five saw. Reserve re-checks against available budget and is the authoritative decision.

On the right, the trust half. A pattern is the graph's shape — tool ids and typed edges, hashed, parameter values deliberately excluded so tuning a parameter does not reset trust. A provisional shape is capped, forced through a dry-run, marked suspect whatever it scores, and may have only one instance in flight, because promotion counts consecutive clean runs and N concurrent copies are one draw sampled N times.

The limit, from our own limitations doc: this buys examination and delay, not soundness. A consistent novel silent failure promotes.`);
}

// ================================================================ 8. The seam: dispatch
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "★ One generic factory, and a submit that does not await", "The seam · 1 of 2");

  code(s, [
    'def _make_task(self, node_id, tool_id, params, invocation="", seed=None):',
    '    """ONE generic factory for every node in every graph."""',
    '    reg, spec = self.reg, self.reg.get(tool_id)',
    '    agent_cls = reg.agent_for(tool_id)',
    '    workdir = self.workdir      # bind locally: the closure is PICKLED',
    '',
    '    async def _run(*deps):',
    '        agent = agent_cls(spec)',
    '        req = TaskRequest(tool=tool_id, params=params, seed=seed, ...)',
    '        res = await agent(req)',
    '        return {"tool": ..., "metrics": ..., "qc": ..., "cost": ...}',
    '',
    '    _run.__name__ = node_id   # asyncflow reads the name from __name__',
    '    return self.flow.function_task(_run)',
  ], M, 1.5, 7.15, 2.0, { anchor: "exec/dispatch.py:144–163  ·  EDITED — annotations elided", fs: 10 });

  code(s, [
    'for tid in g.topo_order():                 # edges via unawaited futures',
    '    deps = [futures[d] for d in g.nodes[tid].deps]',
    '    futures[tid] = tasks[tid](*deps, workflow_id=run_id)',
    '',
    '# one bad task must not cancel its siblings',
    'gather = asyncio.gather(*futures.values(), return_exceptions=True)',
    'return DispatchHandle(run_id=run_id, graph_id=g.id,',
    '                      futures=futures, gather=gather)   # NOT awaited',
  ], M, 3.75, 7.15, 1.4, { anchor: "exec/dispatch.py:182–190  ·  EDITED — see CODE_FOR_DECK.md", fs: 10 });

  card(s, M, 5.35, 7.15, 1.6, "Two asyncflow idioms, not interchangeable", [
    "An unawaited future passed as an argument expresses a DAG edge.",
    "asyncio.gather groups INDEPENDENT work — the replica lineages. The executor, not the " +
      "dispatcher, decides when to wait on it, racing every in-flight gather with FIRST_COMPLETED.",
  ], { fill: C.radicalTint, hc: C.radical, fs: 10.5 });

  const rx = M + 7.45, rwd = W - M - rx;
  card(s, rx, 1.5, rwd, 1.75, "The bet, and it held twice", [
    "A DAG described as data dispatches with one generic factory — no codegen, no AST work, " +
      "no templating.",
    "And the same factory survived going non-blocking unchanged: submit builds the gather and " +
      "hands it back instead of awaiting it.",
  ], { fill: C.panel, fs: 10.5 });
  card(s, rx, 3.4, rwd, 1.5, "Three findings in four lines", [
    "The task decorators take no name= kwarg — setting __name__ first is what lets one factory " +
      "serve every node.",
    "workflow_id tags every task, but no lookup API exists, so the handle is the run's own index.",
  ], { fill: C.execTint, hc: C.exec, fs: 10.5 });
  card(s, rx, 5.05, rwd, 1.9, "Cancellation is advisory", [
    "Measured, not assumed: Future.cancel() returns False once a callable has started, and " +
      "asyncflow discards that answer. Queued work is reclaimed, running work is not, and you " +
      "cannot learn which happened.",
    "So a run's terminal state always comes from collecting it. Backtracking sidesteps this by " +
      "branching the tree; reclaiming a GPU from an abandoned run is unsolved.",
  ], { fill: C.failTint, hc: C.fail, fs: 10.5 });
  s.addNotes(
`[1:20] The slide I would defend hardest, and it is four lines of real code.

A task graph is plain data. To run it, one generic factory builds a closure per node, sets its dunder-name to the node id, and hands it to asyncflow's function_task decorator. That is the whole adapter — no codegen, no AST rewriting, no templating. And setting dunder-name first is not a trick: the decorators take no name keyword, so this is precisely what lets one factory serve every node of every graph.

The closure binds workdir to a local rather than reaching through self, because it gets pickled to a process pool and self would drag the dispatcher, and the engine's futures, along with it.

Second block, submission. Walk the graph in topological order, pass each dependency's unawaited future as an argument — that is how you express an edge. Build a gather with return_exceptions, and return without awaiting. That one change is what let the reasoner stop being the loop body.

Two idioms, not interchangeable: unawaited futures as arguments are edges, gather is independent work.

Right-hand side, measured rather than assumed. Cancellation is advisory. Cancel returns False once a callable has started, asyncflow throws that answer away, so queued work is reclaimed, running work is not, and nobody tells you which happened. A run's terminal state always comes from collecting it.`);
}

// ================================================================ 9. The seam: the engine
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "★ Building the engine on the loop that will use it", "The seam · 2 of 2");

  code(s, [
    'async def make_engine_bounded(kind, config, timeout_s, heartbeat_s):',
    '    if timeout_s <= 0 or kind.lower() in _CHEAP_KINDS:',
    '        return await make_engine(kind, config)',
    '',
    '    # ONLY the synchronous construction leaves this loop.',
    '    threading.Thread(target=_construct_backend_in_thread,',
    '                     args=(kind, config, fut), daemon=True).start()',
    '    be = await asyncio.wait_for(asyncio.shield(async_fut), timeout_s)',
    '',
    '    async def _finish():                   # on OUR loop, deliberately',
    '        backend = await _init_backend(be)  # __await__ registers states',
    '        return await WorkflowEngine.create(backend=backend), backend',
  ], M, 1.5, 7.3, 1.85, { anchor: "exec/backend.py:128–176  ·  EDITED — condensed, see CODE_FOR_DECK.md", fs: 10 });

  const rows = [
    ["Backends are awaitable, and must be awaited",
     "__await__ triggers _async_init(), which registers task states. Constructing synchronously appears to work, then fails later with \"Backend 'x' not registered. Available backends: []\"."],
    ["The engine must be built on the loop that will submit to it",
     "WorkflowEngine.__init__ captures the running loop and puts its run-component dispatch task on it. Build one on a throwaway loop and you get an engine that looks fine and dispatches nothing — silently."],
    ["Real backends live in rhapsody, not asyncflow",
     "asyncflow exports only Noop and Local. Everything real resolves by NAME through rhapsody.backends.get_backend(), from the campaign spec — so no backend class is named outside one module."],
    ["Dragon empties the root logger",
     "Pool()/ProcessGroup() call setup_BE_logging, which clears root handlers. A run configured with logging.basicConfig alone goes mute the moment the backend comes up."],
  ];
  let y = 3.62;
  rows.forEach(([h, b], i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: M, y, w: 7.3, h: 0.78,
      fill: { color: i % 2 ? C.white : C.panel }, line: { color: C.rule } });
    text(s, [{ text: h + "  ", options: { bold: true, color: C.ink } }, { text: b }],
      M + 0.12, y + 0.06, 7.06, 0.66, { fontSize: 9.5 });
    y += 0.78;
  });

  const rx = M + 7.6, rwd = W - M - rx;
  s.addShape(pres.shapes.RECTANGLE, { x: rx, y: 1.5, w: rwd, h: 0.4,
    fill: { color: C.fail }, line: { color: C.fail } });
  text(s, "What each lesson cost", rx + 0.12, 1.5, rwd - 0.24, 0.4,
    { fontSize: 13, bold: true, color: C.white, valign: "middle" });

  const costs = [
    ["22328172\n22328262", "two full allocations", "the engine was built on a throwaway loop via asyncio.run on a helper thread — every submitted task hung"],
    ["22318678", "one 2-hour allocation,\nin full", "Dragon's Batch() builds synchronously with no await points. No heartbeat, no campaign log, nothing, until the wall clock killed it"],
    ["22491438", "~64 GPU-hours,\n37% of the bill", "flow.shutdown() never returned after the science finished. Teardown is the more expensive end"],
  ];
  y = 2.05;
  costs.forEach(([job, cost, why]) => {
    s.addShape(pres.shapes.RECTANGLE, { x: rx, y, w: rwd, h: 1.15,
      fill: { color: C.failTint }, line: { color: C.failTint } });
    text(s, job, rx + 0.1, y + 0.08, 0.95, 0.5,
      { fontFace: MF, fontSize: 9, color: C.fail, bold: true });
    text(s, cost, rx + 0.1, y + 0.6, 1.15, 0.45, { fontSize: 9, color: C.fail, bold: true });
    text(s, why, rx + 1.35, y + 0.08, rwd - 1.45, 1.0, { fontSize: 9.5, color: C.text });
    y += 1.22;
  });
  card(s, rx, 5.75, rwd, 1.2, "Both ends are bounded now", [
    "backend_startup_timeout_s / _heartbeat_s and backend_shutdown_timeout_s. A stuck teardown " +
      "is abandoned with a warning, never raised — results are already durable by then.",
  ], { fill: C.panel, fs: 10 });
  footer(s, "The reference IMPRESS pipeline declined the teardown fix and relies on an operator " +
    "watching the log. We do not.");
  s.addNotes(
`[1:25] The second half of the seam is construction, and this is where the expensive lessons are.

Three things in make_engine_bounded are load-bearing. Only the synchronous construction goes to a helper thread — a dedicated daemon thread, not the default executor, because a stuck call on a pooled thread would hang interpreter shutdown too. The backend's async init and the engine are built back on the caller's own loop. And that await is not politeness: rhapsody's backends are awaitable, and awaiting registers the task states. Construct one synchronously and it appears to work, then fails much later with "backend not registered, available backends: empty list".

The right column is what each cost. Two full allocations went to an engine built on a throwaway loop — asyncflow's engine captures the running loop in its constructor and puts its dispatch task on it, so an engine built on a closed loop looks fine and dispatches nothing. Every submitted task just hangs.

One two-hour allocation went entirely to Dragon's Batch constructor, which blocks the event loop, so our own heartbeat never fired once in two hours.

And the most expensive item is teardown, not startup: on the reference pipeline, shutdown never returned after the science finished and the job sat an hour before someone cancelled it — sixty-four GPU-hours, thirty-seven percent of that job's bill.

Both ends are bounded now, and a stuck teardown is abandoned with a warning rather than raised: results are already durable, and raising would report a campaign that succeeded as failed.`);
}

// ================================================================ 10. Tools are data
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "A tool is a spec file, and loading it is validating it", "Tools · cuttable");

  code(s, [
    'id: filter_shape',
    'pattern: P2                 # compute pattern — normative, see docs',
    'entry: impress_a.tools.rosetta_agents.FilterShapeAgent',
    'resources: {cores: 2, walltime_s: 120}',
    'inputs:   {structure: {type: Complex}}',
    'outputs:  {structure: {type: Complex}}',
    'metrics:  [shape_complementarity]',
    'qc_gates:',
    '  - {id: output_present,  params: {key: result}}',
    '  - {id: metric_in_range, params: {metric: shape_complementarity,',
    '                                   min: 0.55, max: 1.0}}',
    'cost_model: {unit: invocation, cost: {cpu_hours: 0.01}}',
  ], M, 1.5, 6.3, 1.9, { anchor: "toolkits/rosetta/tools/filter_shape/spec.yaml  ·  EDITED", fs: 10 });

  const phases = [["pre_process", ":55"], ["parameterize", ":58"], ["run", ":79"],
                  ["post_process", ":110"]];
  const pw = 1.45;
  phases.forEach(([t, l], i) => {
    const x = M + i * (pw + 0.15);
    box(s, x, 3.75, pw, 0.6, { title: t, sub: "\n" + l, line: C.tool, fill: C.toolTint,
      fs: 10.5, sfs: 8.5, subMono: true });
    if (i < 3) line(s, x + pw + 0.01, 4.05, x + pw + 0.14, 4.05, { w: 1.25 });
  });
  text(s, [
    { text: "post_process ENFORCES the spec's qc_gates", options: { bold: true, color: C.ink } },
    { text: " — never skippable, and execute() is not overridable by an adapter: pattern " +
      "dispatch belongs to the exec layer." },
  ], M, 4.45, 6.3, 0.45, { fontSize: 10.5 });

  card(s, M, 5.0, 6.3, 1.45, "Loading is validating", [
    "A default outside its own range, an unknown QC gate id, a P1 tool declaring no GPU, a " +
      "SKILL.md missing a required section — all are load-time errors.",
    "A toolkit that fails anywhere registers NOTHING, never a partial set.",
  ], { fill: C.composeTint, hc: C.compose, fs: 10.5 });

  const rx = M + 6.6, rwd = W - M - rx;
  s.addShape(pres.shapes.RECTANGLE, { x: rx, y: 1.5, w: rwd, h: 0.4,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, "The suite manufactures the failure mode", rx + 0.12, 1.5, rwd - 0.24, 0.4,
    { fontSize: 13, bold: true, color: C.white, valign: "middle" });
  code(s, [
    'class NoodleAgent(TaskAgent):',
    '    """A tool that LIES.',
    '',
    '    Completes successfully, returns confident-looking numbers,',
    '    and produces a structure with no secondary structure.',
    '    """',
    '    async def run(self, req, params):',
    '        return {"result": "backbone", ...,',
    '                "outputs": {"designs": "noodle"},',
    '                "metrics": {"ss_fraction": 0.02, "designability": 0.91}}',
  ], rx, 2.0, rwd, 1.55, { anchor: "tools/mock_agents.py:73–84  ·  EDITED", fs: 10 });
  code(s, [
    'assert not res.failures, "the tool must SUCCEED - that is',
    '                          what makes it silent"',
    'assert res.merged_metrics()["designability"] > 0.9',
    'assert res.merged_qc().verdict is QCVerdict.FAIL',
  ], rx, 3.90, rwd, 0.85,
    { anchor: "test_campaign.py:81–83  ·  EDITED (one string wrapped)", fs: 10,
      fill: "243240" });

  card(s, rx, 5.05, rwd, 2.0, "Where this defence is still thin", [
    "mock_noodle exists so the QC layer is tested at campaign scale against a tool that lies. " +
      "The real toolkits have no equivalent.",
    "Their gates are almost entirely metric_in_range against a number the tool chose to report " +
      "about itself — which is exactly what a confidently-wrong tool passes.",
    "No structural gates: nothing checks the ligand is in the output complex, that there are no " +
      "chain breaks, or that sequence length matches the contig.",
    "RFD3 already reports ligand_clashes in a sidecar JSON we now open and do not read. That is " +
      "the cheapest real structural gate available, and it is backlog B1/G2.",
  ], { fill: C.failTint, hc: C.fail, fs: 10 });
  s.addNotes(
`[1:10] Adding a tool is a YAML file plus a subclass, never a change to the composer, validator or manager. If you have to touch those, the layering is wrong.

The spec declares typed ports, which is what gate one checks edges against; a compute pattern; resources; the metrics it reports; mandatory QC gates resolved by id from a shared library; and a cost model that feeds gate five.

Loading is validating. A default outside its own range, an unknown gate id, a skill document missing a section — all load-time errors. And a toolkit that fails anywhere registers nothing, never a partial set, because a half-registered toolkit is how you get a campaign that silently composes around the missing piece.

Four phases, and post_process is where QC is enforced — not skippable, not overridable by an adapter.

On the right, the tool that lies: it succeeds, reports designability of 0.91, and emits a structure with two percent secondary structure. One test asserts all three at once — the tool succeeded, the numbers look great, QC caught it anyway.

And the honest gap. The real toolkits have no equivalent. Their gates are thresholds on each tool's own opinion of itself, which is precisely what a confidently-wrong tool passes.`);
}

// ================================================================ 11. Four jobs (F3)
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, `Four jobs to one completed campaign`, "Measured · F3");

  const SC = { rfd3_design: C.radical, ligandmpnn_design: C.reason, packmin: C.exec,
               fastrelax: C.compose, filter_shape: C.tool, boltz_predict: "8C6D1F" };
  const ORDER = ["rfd3_design", "ligandmpnn_design", "packmin", "fastrelax", "filter_shape",
                 "boltz_predict"];

  // Stacked bars, one row per run, on a shared seconds axis. The HDD baseline is drawn
  // first because the comparison is the point of the figure.
  const base = D.hdd_baseline_22675512;
  const rows = [
    ["22675512 · HDD", { rfd3_design: base.rfd3_design, ligandmpnn_design: base.ligandmpnn_design },
     "packmin could not finish `import pyrosetta` in 300 s — nothing downstream ran"],
    ["22684607 · NVMe", D.jobs[2].stages, "5/5 ok · boltz truncated off the chain by a cost cap"],
    ["22692304 · NVMe", D.jobs[3].stages, `6/6 ok in ${DONE.wall} · the first completed campaign`],
  ];
  const gx = M + 1.75, gw = 7.2, span = 520;
  const sx = v => gx + (v / span) * gw;
  let y = 1.62;
  rows.forEach(([name, stages, note]) => {
    text(s, name, M, y, 1.7, 0.3, { fontSize: 10.5, bold: true, color: C.text,
      align: "right", valign: "middle", fontFace: MF });
    let acc = 0;
    ORDER.forEach(st => {
      const v = stages[st];
      if (typeof v !== "number") return;
      s.addShape(pres.shapes.RECTANGLE, { x: sx(acc), y: y + 0.03, w: (v / span) * gw, h: 0.26,
        fill: { color: SC[st] }, line: { color: SC[st] } });
      if (v > 35) text(s, v.toFixed(0), sx(acc), y + 0.03, (v / span) * gw, 0.26,
        { fontSize: 8, color: C.white, align: "center", valign: "middle" });
      acc += v;
    });
    text(s, `${acc.toFixed(0)} s of tool time`, sx(acc) + 0.06, y + 0.03, 1.5, 0.26,
      { fontSize: 8.5, color: C.muted, valign: "middle" });
    text(s, note, M + 1.75, y + 0.33, 9.0, 0.24, { fontSize: 9, color: C.muted, italic: true });
    y += 0.68;
  });
  // axis
  const ay = y - 0.05;
  line(s, gx, ay, gx + gw, ay, { noArrow: true, color: C.rule, w: 1 });
  [0, 100, 200, 300, 400, 500].forEach(v => {
    line(s, sx(v), ay, sx(v), ay + 0.07, { noArrow: true, color: C.rule, w: 1 });
    label(s, `${v}s`, sx(v) - 0.25, ay + 0.08, 0.5, { fs: 8 });
  });
  // stage legend
  ORDER.forEach((st, i) => {
    const x = M + i * 1.42;
    s.addShape(pres.shapes.RECTANGLE, { x, y: ay + 0.42, w: 0.18, h: 0.13,
      fill: { color: SC[st] }, line: { color: SC[st] } });
    text(s, st, x + 0.23, ay + 0.38, 1.19, 0.22,
      { fontSize: 7.5, color: C.muted, fontFace: MF, valign: "middle" });
  });

  const rx = M + 9.15, rwd = W - M - rx;
  card(s, rx, 1.6, rwd, 2.05, "Where the bytes live", [
    `import pyrosetta off HDD-backed Lustre: ${D.import_cost_s.pyrosetta_hdd} s, a 598 MB ` +
      "rosetta.so demand-paged. import torch: ~" + D.import_cost_s.torch_hdd + " s.",
    "On NVMe both are seconds. That single variable is the whole difference between rows one " +
      "and two.",
  ], { fill: C.failTint, hc: C.fail, fs: 10 });
  card(s, rx, 3.8, rwd, 1.75, "Wall time is not stable", [
    `rfd3_design took ${D.jobs[2].stages.rfd3_design} s in 22684607 and ` +
      `${D.jobs[3].stages.rfd3_design} s in 22692304 — same campaign, same allocation shape, ` +
      "same parameters, 3.2× apart.",
  ], { fill: C.panel, fs: 10 });
  card(s, rx, 5.7, rwd, 1.25, "So do not tune cost models to it", [
    "They feed gate 5 and the untrusted cap, which REFUSE graphs. They sit a few multiples above " +
      "measurement on purpose.",
  ], { fill: C.composeTint, hc: C.compose, fs: 10, hfs: 11.5 });

  footer(s, "Durations transcribed from plans/first-real-run.md — the raw logs live under " +
    "$WORK_DIR/impress_a_runs on Delta. Bars are tool time; campaign wall clock is slightly longer.");
  s.addNotes(
`[1:15] Four jobs to a completed campaign, and the figure is really about one variable.

Top row, the HDD baseline. Diffusion 137 seconds, sequence design 293, and then packmin could not finish importing PyRosetta inside its three-hundred-second budget, so nothing downstream ran at all.

Middle row, the same campaign with one thing changed: the virtual environment moved from HDD-backed Lustre to NVMe. Sequence design went from 293 seconds to 18, packmin from not finishing to sixteen.

The reason is on the right. Importing PyRosetta off that filesystem costs 471 seconds — a 598-megabyte shared object, demand-paged. Torch is another 280. On NVMe both are seconds. That was the single largest cost this project was paying, and it was invisible because it looked like a tool timing out.

It nearly caused a second bug, which is the more useful half. The queued fix was to raise three walltimes six-fold, which would have hidden the real cost behind timeouts far too large.

Bottom right, the caveat for anyone reading our cost models. Diffusion took 146 seconds in one job and 45 in the next — same campaign, same parameters. These numbers feed gates that refuse graphs, so they sit deliberately above measurement and must not be tightened toward equality.`);
}

// ================================================================ 12. Four defects
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Four defects that reached real hardware", "What a dry run cannot see");

  const defects = [
    ["What a tool writes",
     "The *.cif.gz glob selected a diffusion TRAJECTORY, not the design — same extension, and `denoised` sorts first. A 5.7 MB multi-frame stack went downstream as the backbone, against a 19 KB design.",
     "Discovery goes through the sidecar *_model_*.json now, and an out_dir it cannot identify a design in raises rather than guessing."],
    ["Whether a tool can import",
     "LigandMPNN died in run.py's MODULE-LEVEL imports, before parsing an argument: a missing ml_collections, then np.int, removed in numpy 1.24 and still used by its vendored openfold.",
     "It runs through MPNN_SHIM now — the shim restores the aliases and hands off via runpy — never run.py directly."],
    ["Where the bytes live",
     "import pyrosetta cost 471 s off HDD, so packmin could not finish starting inside its 300 s budget. The queued fix was to raise three walltimes 6×, which would have hidden the real cost.",
     "WORK_DIR on NVMe; `impress-a preflight` now flags a venv still on slow storage."],
    ["An estimate that refuses work",
     "cost_model figures were literature guesses 6–69× over measurement. The inflated GPU side summed past the untrusted cap, the chain was refused, and the policy truncated boltz_predict off the end — silently.",
     "Costs corrected from measurement, and _objectives_without_a_producer now WARNs. It is a heuristic, not a gate."],
  ];
  let y = 1.5;
  defects.forEach(([h, what, fix], i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: M, y, w: 12.33, h: 1.18,
      fill: { color: i % 2 ? C.white : C.panel }, line: { color: C.rule } });
    text(s, `${i + 1}`, M + 0.1, y + 0.08, 0.35, 0.4,
      { fontSize: 18, bold: true, color: C.fail, fontFace: HF, align: "center" });
    text(s, h, M + 0.5, y + 0.1, 2.5, 0.45, { fontSize: 12.5, bold: true, color: C.ink });
    text(s, what, M + 3.1, y + 0.08, 5.6, 1.02, { fontSize: 9.5, color: C.text });
    text(s, [{ text: "now:  ", options: { bold: true, color: C.good } }, { text: fix }],
      M + 8.85, y + 0.08, 3.35, 1.02, { fontSize: 9.5, color: C.text });
    y += 1.22;
  });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 6.38, w: 12.33, h: 0.62,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, [
    { text: "Two things to carry away.  ", options: { bold: true, color: "F0C898" } },
    { text: "\"Checked against the binary\" is not \"executed\" — numbers 1 and 2 were both " +
      "invisible to every contract check we had. And a plausible explanation is not a diagnosis: " +
      "the trajectory bug was a convincing cause for a LigandMPNN failure it had nothing to do with.",
      options: { color: "DCE5EC" } },
  ], M + 0.2, 6.45, 11.95, 0.5, { fontSize: 12 });
  s.addNotes(
`[1:20] Four defects reached real hardware, each invisible to a dry run. The pattern across them is more useful than any one.

What a tool writes. Our glob for the diffusion output picked a trajectory rather than the design — same extension, and "denoised" sorts before the design's own name. A five-megabyte multi-frame stack went downstream as the backbone instead of a nineteen-kilobyte design.

Whether a tool can import. LigandMPNN died in its module-level imports, before parsing a single argument we passed it. No flag or path we sent could ever have been read.

Where the bytes live — the storage story from the last slide.

And the subtle one: an estimate that refuses work. Our cost models were literature guesses six to sixty-nine times over reality, and gate five and the interlock cap refuse graphs against those numbers. The inflated GPU side summed past the cap, the chain was refused, and the policy truncated the last stage off — which happened to be the only producer of two of the four campaign objectives. The run was unwinnable from the moment it was admitted, and nothing said so.

Two things to carry away. Checked against the binary is not executed. And a plausible explanation is not a diagnosis — the trajectory bug was a convincing cause for a failure it had nothing to do with, and only recovering the real stderr separated them.`);
}

// ================================================================ 13. The trust ledger
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "The ledger that forgot — and what it still forgets", "Trust");

  // --- top half: A12, the ledger that reset every job
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 1.45, w: 12.33, h: 0.38,
    fill: { color: C.exec }, line: { color: C.exec } });
  text(s, "1 · Promotion was structurally unreachable on Delta, and it looked exactly like " +
    "\"not enough runs yet\"", M + 0.12, 1.45, 12.1, 0.38,
    { fontSize: 12.5, bold: true, color: C.white, valign: "middle" });

  code(s, [
    '# executor.py loaded the ledger from Path(spec.root) / "_trust",',
    '# and spec.root defaults to the RELATIVE "campaigns/_runs".',
    '# delta_gpu_run.sh cds into $WORK_DIR/impress_a_runs/$SLURM_JOB_ID:',
    '',
    '  22684607/campaigns/_runs/_trust/cuda.jsonl    0 clean',
    '  22692304/campaigns/_runs/_trust/cuda.jsonl    1 clean',
  ], M, 1.95, 6.3, 1.1, { anchor: "fixed in 52332c6 — CampaignSpec.trust_root", fs: 9.5 });

  card(s, M + 6.6, 1.95, 6.23, 1.1, "promote_after = 3 counts within ONE file", [
    "Two more jobs would have produced three files holding one run each, a pattern still " +
      "untrusted, and two allocations spent for nothing.",
  ], { fill: C.failTint, hc: C.fail, fs: 10.5 });

  text(s, [
    { text: "How it hid: ", options: { bold: true, color: C.ink } },
    { text: "nothing ever logged where the ledger was, so a file that silently reset looked " +
      "identical to one that had not earned promotion yet — and it was reported that way. " +
      "Campaign start now prints the absolute path with a pattern and trusted count. It had " +
      "been true since the first Delta job, so " },
    { text: "the trusted code path has never executed", options: { bold: true, color: C.fail } },
    { text: ": no pattern has ever skipped the forced dry-run, and the 10% cap has applied to " +
      "every graph ever composed on real hardware." },
  ], M, 3.2, 12.33, 0.75, { fontSize: 11.5 });

  // --- bottom half: the new finding
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 3.98, w: 12.33, h: 0.38,
    fill: { color: C.fail }, line: { color: C.fail } });
  text(s, "2 · And a pattern's identity includes its BREADTH — found while building this deck",
    M + 0.12, 3.98, 12.1, 0.38, { fontSize: 12.5, bold: true, color: C.white, valign: "middle" });

  code(s, [
    'parts = sorted(                       # ONE string per NODE',
    '    f"{n.tool}<-{\',\'.join(sorted(self.nodes[d].tool for d in n.deps))}"',
    '    for n in self.nodes.values()',
    ')',
    'return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]',
  ], M, 4.45, 6.3, 0.95, { anchor: "compose/graph.py:51  ·  VERBATIM + one added comment", fs: 9.5 });

  text(s, "N lineages give N duplicate parts, so the hash changes with the replica count — " +
    "the way it deliberately does not change with a parameter:",
    M, 5.56, 6.3, 0.44, { fontSize: 10, color: C.text });

  tbl(s, ["the real six-stage chain", "nodes", "signature"],
    [[`replicas: 1`, SHAPE["1"].nodes, SHAPE["1"].signature],
     [`replicas: 2`, SHAPE["2"].nodes, SHAPE["2"].signature],
     [`replicas: 4`, SHAPE["4"].nodes, SHAPE["4"].signature],
     [`replicas: 1, num_designs: 3`, SHAPE["1_tuned_params"].nodes,
      SHAPE["1_tuned_params"].signature + "  ← unchanged"]],
    M + 6.6, 4.45, [2.6, 0.7, 2.93],
    { mono: [2], mfs: 9, fs: 10.5, hfs: 10, rowH: 0.3, center: [1], hfill: C.fail,
      cell: (i, j) => (i === 3 && j === 2) ? { color: C.good, bold: true } : {} });

  card(s, M, 6.08, 7.7, 0.95, "What that costs, concretely", [
    `Backlog A10's cheapest route — promote at replicas: 1, then run replicas: 4 — does not ` +
      `work. That is a different, untrusted pattern: still capped, refused at ` +
      `${D.untrusted_cap.replicas4_gpu_h} vs ${D.untrusted_cap.cap} gpu-h, and on_rejected ` +
      `would silently shrink it to three lineages.`,
  ], { fill: C.failTint, hc: C.fail, fs: 10 });
  card(s, M + 8.0, 6.08, 4.83, 0.95, "The question for the room", [
    "Is trust earned at one lineage evidence about four, when the cap it would lift exists to " +
      "bound blast radius?",
  ], { fill: C.panel, fs: 10 });
  footer(s, "Signatures computed live by slides/run_model.py against this checkout — the mock run " +
    "on slide 6 shows the same shape, the shrink from 3 lineages to 2 producing a new pattern.");
  s.addNotes(
`[1:35] Two findings about the trust ledger, and the second is new as of building this deck.

The first. The executor loaded the ledger from a path relative to the campaign root, and the Delta launcher changes directory into a per-job working directory before starting. So the ledger resolved inside each job and started empty every time. Two real runs left two files — one with zero clean runs, one with one — and promotion counts three consecutive clean runs within one file.

What is worth your time is how it hid. Nothing ever logged where the ledger was, so a file that silently reset looks exactly like one that has not earned promotion yet — and I reported it that way. It had been true since the first Delta job, which means the trusted code path has never executed, and the ten percent cap has applied to every graph ever composed on real hardware. That cap is exactly what truncated the last stage off the chain twice.

The second I hit while generating the numbers for this deck, and I have not changed the code. The signature emits one string per node and hashes the sorted join, so N lineages give N duplicate parts and the hash changes with the replica count — even though it deliberately does not change when you tune a parameter. The table shows the same chain hashing three ways at one, two and four replicas.

The cost is concrete. The cheapest route to exercising four independent lineages was to promote the pattern with a one-replica campaign, then run four. It does not work: four replicas is a different, untrusted pattern, still capped, still refused, and the policy would quietly shrink it to three and run a weaker check than the one we asked for.

So, genuinely open: is trust earned at one lineage evidence about four, when the cap it would lift exists to bound blast radius?`);
}

// ================================================================ 14. Running it
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Running it, and what the test tiers actually cover", "How to run it");

  code(s, [
    'source .venv/bin/activate          # NOT system python — see CLAUDE.md',
    'pip install -e ".[dev]"',
    '',
    `pytest tests -q                    # ${CODE.tests_collected} tests, no allocation`,
    'impress-a tools                    # list the registered tools',
    'impress-a preflight campaigns/<spec>.yaml      # BEFORE sbatch',
    'impress-a run campaigns/mock-stabilize.yaml --model D',
    '#   --model A|B|C|D|null|replay    --no-guard  drops the correction wrapper',
  ], M, 1.5, 7.1, 1.6, { fs: 10 });

  const tiers = [
    ["test_core.py", "pure logic — tree, Pareto, budget, QC"],
    ["test_validation.py", "the five gates, the interlock, the trust ledger"],
    ["test_campaign.py", "full campaigns on a concurrent backend with mock tools"],
    ["test_real_toolkits.py", "the real specs, without executing any real binary"],
    ["test_backend_bound.py", "startup timeout/heartbeat against a fake backend that blocks its own thread's loop the way Dragon's Batch() does"],
    ["test_http_adapter.py", "a campaign driven end to end over a loopback socket"],
    ["test_remote_session.py", "a reasoner in another process, over the control plane"],
    ["test_layering.py", "the import contract, walked with ast rather than trusted to review"],
    ["test_gate_fixtures.py", "each real tool's gates against its known-bad fixtures, and the registry against the directories on disk"],
  ];
  tbl(s, ["file", "what it covers"], tiers, M, 3.35, [2.35, 4.75],
    { mono: [0], mfs: 9, fs: 9.5, hfs: 10, rowH: 0.3, margin: 0.06 });

  const rx = M + 7.4, rwd = W - M - rx;
  card(s, rx, 1.5, rwd, 1.6, "The whole local tier runs on a laptop", [
    "A complete campaign — real manager, real policies, real composer and validator, stubbed " +
      "science. HPC iteration is slow and expensive, so almost everything is verifiable locally.",
    "The corollary: everything only verifiable on HPC is unverified.",
  ], { fill: C.execTint, hc: C.exec, fs: 10.5 });
  card(s, rx, 3.25, rwd, 1.75, "Two conventions worth stealing", [
    "Counts are not restated in prose. test_gate_fixtures derives the tool count from the " +
      "directories rather than asserting a number.",
    "A magic number in a test is often a bug report: stagnation_limit = 10_000 appeared in three " +
      "tests before anyone noticed the defect was in the executor, not the setup.",
  ], { fill: C.panel, fs: 10.5 });
  card(s, rx, 5.15, rwd, 1.8, "A 20-second demo, if the room wants it", [
    "pytest tests -q -k lying — the bundled tool that succeeds, reports 0.91 designability, and " +
      "is failed by QC anyway.",
    "impress-a run campaigns/delta-small-molecule-smoke.yaml --model D must compose rfd3_design…, " +
      "never mock_… — that confusion is the bug that made the smoke campaign necessary.",
  ], { fill: C.composeTint, hc: C.compose, fs: 10.5 });
  s.addNotes(
`[0:45] The command worth pointing at is preflight: it checks the container path, the checkpoints, the Boltz cache, whether PyRosetta imports, and whether the virtual environment is still on slow storage — all on a login node, before you spend a queue slot.

The split that matters is that the entire local tier runs on a laptop in about fifteen seconds with no allocation: a complete campaign with a real manager, real policies, a real composer and validator, stubbed science. That is deliberate, because HPC iteration is slow and expensive. The corollary is the uncomfortable half, which is the next slide.

One convention I would steal for other projects: a magic number in a test is often a bug report. A stagnation limit of ten thousand appeared in three separate tests before anyone noticed the defect was in the engine, not the test setup.`);
}

// ================================================================ 15. Status
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "What is real, and what is not", "Status");

  const real = [
    "A six-stage real-toolkit campaign ran end to end on Delta: 6/6 tasks, four objectives, a front.",
    "The engine — compose, five gates, interlock, Pareto tree, provenance, durable run ledger.",
    "Four control models, plus conduct() reasoners, over one shared executor.",
    "Control plane: in-process and HTTP+SSE, with synchronous admission, covered end to end.",
    "A reasoner in another process, driving a campaign over the HTTP plane.",
    "Dragon startup AND teardown bounded; both measured against real lost allocations.",
    "Per-tool cost measured for all six real tools, and the specs corrected from measurement.",
  ];
  const notreal = [
    "replicas > 1 has NEVER executed. The independence invariant is the one most likely to be " +
      "silently wrong, and it is unexercised.",
    "Nothing has ever been promoted by the trust ledger, so the trusted path has never run.",
    "No measurement has superseded a prediction — the calibration machinery is untested.",
    "No structural QC gate exists for any real tool; every real gate is a threshold on a " +
      "self-reported number.",
    "No resume: the ledger and reattach() exist, nothing resumes from them.",
    "impress-a serve / reason do not exist, so --model C fails open and reports a model-D " +
      "campaign as model C.",
    "sites/*.yaml is read by no code. MCP is designed, not built.",
  ];
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 1.45, w: 6.1, h: 0.42,
    fill: { color: C.good }, line: { color: C.good } });
  text(s, "Runs, for real", M + 0.14, 1.45, 5.8, 0.42,
    { fontSize: 13.5, bold: true, color: C.white, valign: "middle" });
  s.addShape(pres.shapes.RECTANGLE, { x: M + 6.33, y: 1.45, w: 6.0, h: 0.42,
    fill: { color: C.fail }, line: { color: C.fail } });
  text(s, "Has never run", M + 6.47, 1.45, 5.7, 0.42,
    { fontSize: 13.5, bold: true, color: C.white, valign: "middle" });

  let y = 2.0;
  real.forEach((t, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: M, y, w: 6.1, h: 0.62,
      fill: { color: i % 2 ? C.white : "F0F6F2" }, line: { color: C.rule } });
    text(s, t, M + 0.12, y + 0.05, 5.86, 0.52, { fontSize: 10, color: C.text });
    y += 0.66;
  });
  y = 2.0;
  notreal.forEach((t, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: M + 6.33, y, w: 6.0, h: 0.62,
      fill: { color: i % 2 ? C.white : C.failTint }, line: { color: C.rule } });
    text(s, t, M + 6.45, y + 0.05, 5.76, 0.52, { fontSize: 10, color: C.text });
    y += 0.66;
  });

  text(s, [
    { text: "One campaign has completed. ", options: { bold: true, color: C.ink } },
    { text: "One lineage, one cycle, one draw — and the node it produced is marked suspect, " +
      "which is the interlock working rather than a defect." },
  ], M, 6.62, 12.33, 0.5, { fontSize: 12.5 });
  s.addNotes(
`[1:00] I will not compress this slide, because an audience that catches you overclaiming stops believing everything else you said.

Left, what genuinely runs. A real six-stage campaign on Delta. The engine — composition, gates, interlock, Pareto tree, provenance, a durable ledger. Four control models over one shared executor. The control plane in two transports, including a reasoner driving a campaign from another process. Both ends of the Dragon lifecycle bounded, each against a real lost allocation.

Right, what has never run. Replicas greater than one — the invariant most likely to be silently wrong, because N replicas are supposed to be N independent lineages with different seeds, and the only evidence the seed plumbing does anything is that the nodes carry different metrics. Nothing has ever been promoted by the trust ledger. No measurement has superseded a prediction. No structural QC gate exists for any real tool. There is no resume. The headless control model fails open and reports itself as the wrong model.

One campaign has completed. One lineage, one cycle, one draw.`);
}

// ================================================================ 16. Asks
{
  const s = pres.addSlide(); s.background = { color: C.ink };
  text(s, "DISCUSSION", M, 0.5, 6, 0.35,
    { fontSize: 13, bold: true, color: "8FB8C9", charSpacing: 3 });
  text(s, "Six things I would like this room's opinion on", M, 0.85, 12.33, 0.7,
    { fontFace: HF, fontSize: 28, bold: true, color: C.white });

  const asks = [
    ["1", "rhapsody's monitor loop drops a whole sweep",
     "A worker exception that cannot be unpickled takes out every completion in that sweep. " +
       "batch_task.get() is guarded; the follow-up get_stdout(block=False) re-reads the same " +
       "entry and catches only OSError. Our half is fixed (SubprocessError.__reduce__). Should " +
       "that handler catch Exception and fail the ONE task?", C.radical],
    ["2", "Why does Dragon's Batch() stall?",
     "Bounded now, but not diagnosed. Job 22318678 produced only infra-connect lines for two " +
       "hours. Best guess: GPU-affinity worker rendezvous, or OFI/libfabric negotiation under " +
       "single-node mode. We now fail fast enough to iterate — what should we instrument?", C.radical],
    ["3", "Can a running task's GPU ever be reclaimed?",
     "Future.cancel() returns False once started and asyncflow discards the answer, so we " +
       "cannot even learn which happened. Is cooperative cancellation inside the task the only " +
       "route, or is there a backend-level kill we should be using?", C.radical],
    ["4", "workflow_id tags tasks but nothing looks them up",
     "So \"which tasks belong to run R\" is answered by our own handle, which cancellation and " +
       "draining both need. Is a lookup API wanted upstream, or is the tag meant to stay a label?",
     C.radical],
    ["5", "Does breadth belong in a pattern's identity?",
     "Slide 13. Parameters are deliberately excluded from the signature; replica count is not. " +
       "Is trust earned at one lineage evidence about four, when the cap it would lift exists to " +
       "bound blast radius?", C.compose],
    ["6", "What is the cheapest real structural gate?",
     "Every real gate today is a threshold on a number the tool reports about itself. RFD3 gives " +
       "us ligand_clashes and per-residue clash counts in a sidecar JSON we already open. For " +
       "the Rosetta stages, upstream gates on interaction_energy, which we do not compute. Where " +
       "would you start?", C.tool],
  ];
  let y = 1.75;
  asks.forEach(([n, h, b, col], i) => {
    const x = i < 3 ? M : M + 6.3;
    const yy = i < 3 ? 1.75 + i * 1.72 : 1.75 + (i - 3) * 1.72;
    s.addShape(pres.shapes.RECTANGLE, { x, y: yy, w: 6.03, h: 1.58,
      fill: { color: "1E2C36" }, line: { color: "2E414F" } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: yy, w: 0.06, h: 1.58,
      fill: { color: col }, line: { color: col } });
    text(s, n, x + 0.18, yy + 0.08, 0.3, 0.35,
      { fontFace: HF, fontSize: 15, bold: true, color: col });
    text(s, h, x + 0.55, yy + 0.1, 5.35, 0.35,
      { fontSize: 12.5, bold: true, color: C.white });
    text(s, b, x + 0.55, yy + 0.48, 5.35, 1.0, { fontSize: 9.5, color: "B8C6D1" });
  });

  text(s, "Everything above is reproducible from this checkout, and every file:line on these " +
    "slides is greppable from your laptop while I talk.",
    M, 6.95, 12.33, 0.35, { fontSize: 11, color: "7E8F9C", italic: true });
  s.addNotes(
`[1:20] I would rather end on questions than a summary, and these are the six I actually want answers to.

The first four are for the middleware authors. One: a worker exception that cannot be unpickled takes out a whole monitor sweep rather than one task, so a failing run reaches no terminal state and sits in flight until the wall clock. Our half is fixed, but the handler around get_stdout catches only OSError, and I think it wants to catch Exception and fail the single task.

Two: Batch stalled for two full hours and we still do not know why. It is bounded now, so we fail in minutes rather than losing an allocation — which means we can finally iterate. What should we instrument?

Three: can a running task's GPU ever be reclaimed? Four: workflow_id tags every task but nothing looks tasks up by it, so our own handle stays the only answer to what belongs to a run.

Five is for everyone — the one from slide thirteen. Does breadth belong in a pattern's identity?

Six is for the domain people. Every real gate we have is a threshold on a number the tool reports about itself. RFD3 hands us clash counts in a file we already open; for Rosetta, upstream gates on an interaction energy we do not compute. If you were adding one structural gate, where would you start?`);
}

// ================================================================ B1. Backup: control plane
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Backup — the control plane and the remote reasoner", "Backup");

  box(s, M, 1.5, 12.33, 0.82, { title: "CampaignControlPlane — one protocol, adapters translate transport only",
    sub: "\nobserve · events · steer · pause · resume · stop · artifacts · provenance · ingest_measurement · status · inflight · backtrack · request_human · submit_run · list_runs · run_result · await_run_result · cancel_run",
    line: C.exec, fill: C.execTint, fs: 12.5, sfs: 9, align: "left" });

  const adapters = [
    ["in-process", "control/plane.py::InProcessControlPlane", "built", C.exec],
    ["HTTP + SSE", "control/http.py::ControlPlaneServer", "built", C.exec],
    ["MCP", "the same protocol, a third transport", "planned", C.muted],
  ];
  adapters.forEach(([t, sub, st, col], i) =>
    box(s, M + i * 4.17, 2.48, 3.99, 0.72, { title: t, sub: "\n" + sub, line: col,
      fill: C.white, status: st, fs: 12, sfs: 9, subMono: true }));

  card(s, M, 3.4, 6.1, 1.7, "observe() returns what a policy sees", [
    "The same CampaignObservation object a policy's decide() receives — informed monitoring " +
      "means parity of evidence, not a progress bar.",
    "Admission is synchronous even over HTTP: 202 with a run id, or 409 with the gate and the " +
      "reason that refused it.",
  ], { fill: C.execTint, hc: C.exec, fs: 10.5 });
  card(s, M + 6.33, 3.4, 6.0, 1.7, "Why admission cannot be deferred", [
    "Accept-then-reject-later would sever a rejection from the request that caused it.",
    "And it cannot work anyway: the dry-run instantiates task agents, so admission has to happen " +
      "where the toolkit is installed.",
  ], { fill: C.panel, fs: 10.5 });

  card(s, M, 5.25, 12.33, 1.75, "What is still missing — backlog C5, C6, C7", [
    "RemoteSession and the routes it needs are covered end to end, but only tests/ ever " +
      "constructs a server. There is no impress-a serve and no impress-a reason, so the split is " +
      "reachable from the suite and not from a shell.",
    "Because of that, --model C builds an ExternalPolicy whose inbox can never be filled: it " +
      "times out every 5 s and silently runs the model-D policy instead, while reporting itself " +
      "as model C. It should refuse.",
    "And where the plane should live relative to the allocation is undecided — http.py is " +
      "loopback, single trusted client, no auth, no TLS.",
  ], { fill: C.failTint, hc: C.fail, fs: 10.5 });
  s.addNotes(
`[0:45] One protocol, nineteen operations, and adapters that translate transport only.

The design decision worth stating is that observe returns the same observation object a policy's decide receives. Informed monitoring means parity of evidence, not a progress bar — whatever a control model is allowed to reason about, a human watching is allowed to see.

Admission is synchronous even over HTTP: you get a 202 with a run id, or a 409 with the gate and the reason. That is not a style choice. Accepting and rejecting later would sever a rejection from the request that caused it, and it cannot work anyway, because the dry-run instantiates task agents and therefore has to run where the toolkit is installed.

The gap is honest and annoying: all of this is reachable from the test suite and not from a shell. There is no serve command and no reason command. One consequence is that model C — the headless, externally-steered mode — fails open: it builds a policy whose inbox nothing can fill, times out every five seconds, and silently runs the model-D rule cascade while reporting itself as model C.`);
}

// ================================================================ B2. Backup: control models
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Backup — four control models over one executor", "Backup");

  const models = [
    ["A", "Four-node agentic loop", "autonomous", "A LangGraph graph: hypothesize → parameterize, auditable node by node", "policy/agentic.py"],
    ["B", "Heavyweight LLM oracle", "autonomous", "One structured call over rich campaign state", "policy/oracle.py"],
    ["C", "External caller steering", "headless", "Blocks on the control plane for a directive", "policy/external.py"],
    ["D", "Explicit policy", "autonomous", "Rules, bandit, Bayesian optimization, or replay — fully reproducible", "policy/explicit.py"],
  ];
  tbl(s, ["", "model", "mode", "how decide() works", "file"], models, M, 1.5,
    [0.5, 2.8, 1.5, 5.3, 2.23],
    { mono: [4], mfs: 9, fs: 11, rowH: 0.42, hfill: C.reason, center: [0] });

  card(s, M, 3.7, 6.1, 1.6, "They compose rather than inherit", [
    "RuleCorrectionsPolicy wraps any policy in an unconditional external guard; LoggingPolicy " +
      "wraps any policy for provenance. Decorators, not subclasses.",
    "Writing a fifth is subclassing BasePolicy and implementing one method.",
  ], { fill: C.reasonTint, hc: C.reason, fs: 10.5 });
  card(s, M + 6.33, 3.7, 6.0, 1.6, "The claim the whole design rests on", [
    "Everything below the policy layer is byte-identical across A, B, C and D. A campaign run by " +
      "a hand-written rule cascade exercises the same machinery as one steered by a frontier LLM.",
  ], { fill: C.panel, fs: 10.5 });

  card(s, M, 5.5, 12.33, 1.5, "One editorial point, since Flowgentic's authors are here", [
    "The outer loop is still ours, deliberately — it is just two coroutines now instead of one. " +
      "Ceding it to a framework pushes the validation gates, the dry-run and the interlock into " +
      "awkward places.",
    "Flowgentic's own README reaches the same conclusion: it recommends the augmented rung — the " +
      "application owns the loop, agents are bound at decision points — over the fully agentic one.",
  ], { fill: C.composeTint, hc: C.compose, fs: 10.5 });
  s.addNotes(
`[0:40] Four control models, exactly one active per campaign, fixed at launch.

A is a four-node LangGraph loop, auditable node by node. B is a single heavyweight structured call over rich campaign state. C is headless — it blocks on the control plane for a directive from outside. D is explicit: rules, a bandit, Bayesian optimization, or replay, and fully reproducible.

They compose rather than inherit. You can wrap any of them in a rule-corrections policy for an unconditional external guard, or a logging policy for provenance, and those are decorators rather than subclasses. Writing a fifth is one method.

The claim everything rests on is that below the policy layer, all four are byte-identical. A campaign run by a hand-written rule cascade exercises exactly the same machinery as one steered by a frontier model, which is what makes comparing them meaningful at all.

And one editorial point, since Flowgentic's authors are in the room: the outer loop is still ours on purpose. It is just two coroutines now rather than one. We looked at ceding it to a framework and it pushes the gates, the dry-run and the interlock into awkward places — and Flowgentic's own README reaches the same conclusion, recommending the augmented rung over the fully agentic one. Worth saying out loud, with credit.`);
}

pres.writeFile({ fileName: path.join(__dirname, "impress-a-codewalk.pptx") })
  .then(f => console.log("wrote", f));
