// Builds slides/impress-a-codewalk.pptx.
//
//   PYTHONPATH=src python3 slides/run_model.py       # regenerate slides/run.json first
//   NODE_PATH=<dir with pptxgenjs> node slides/build_deck.js
//   soffice --headless --convert-to pdf --outdir slides slides/impress-a-codewalk.pptx
//
// Neither node nor LibreOffice is on Delta: `pixi exec --spec nodejs` provides node, and
// docker://linuxserver/libreoffice under apptainer provides soffice. The deck's Calibri /
// Cambria / Consolas are absent on Linux, so the PDF pins them with a fontconfig alias to
// DejaVu Sans / Serif / Sans Mono - the substitution the first PDF was rendered with. Without
// it the container picks Noto and every slide's metrics shift.
//
// Shared machinery lives in the code-walk-deck skill's deck_lib.js - the same library the
// sibling IMPRESS performance deck is built on, so the two read as siblings. Only
// project-specific figures are local to this file. Every diagram is native, editable
// PowerPoint shapes; never an image.
//
//   line style = status   solid:  built, runs end to end against something real
//                         dotted: built and tested, never exercised for real
//                         dashed: designed for, not implemented
//   orange = a RADICAL component, wherever it appears.
//
// THREE ACTS, and the deck is ordered by them rather than by module: functionality (6-12),
// performance (13-20), usability (21-23). Each opens with a divider that makes three claims
// and names the weakest of them in red BEFORE the act. deck.json carries the acts and the
// running orders; make_script.py reads it.
//
// The whole deck is an argument against a baseline, not a tour: the reference IMPRESS
// pipeline already does adaptive protein design at a scale this project has not touched, so
// every claim here is "what composing a graph buys over writing one down". Numbers come from
// run.json, in four labelled kinds:
//
//   R.code/mock/patterns/shape   mined from this checkout on every build
//   R.analysis                   our own twelve-section performance analysis, transcribed:
//                                recomputable, but only from the run archive
//   R.baseline.code              mined from the reference pipeline's checkout
//   R.baseline.measured          transcribed from the reference pipeline's own report
//   R.delta                      the Delta jobs, transcribed from plans/
//
// Any slide showing a transcribed figure repeats its source in the footer. A fabricated zero
// is worse than a missing number, so an absent reference checkout renders as a sentence
// saying so.
const path = require("path");
const fs = require("fs");
const os = require("os");
const { createDeck } = require(process.env.DECK_LIB || path.join(
  os.homedir(), ".claude/skills/code-walk-deck/scripts/deck_lib.js"));

const R = JSON.parse(fs.readFileSync(path.join(__dirname, "run.json"), "utf8"));
const CODE = R.code, MOCK = R.mock, SHAPE = R.shape, D = R.delta, DONE = R.delta.completed;
const TRUST = R.delta.trust;
const A = R.analysis;                      // our measured run analysis
const BL = R.baseline.measured;            // the reference pipeline, measured
const BC = R.baseline.code;                // the reference pipeline, mined (null if absent)
const OURG = R.baseline.our_rosetta_gates; // our side of the shared-stage gate comparison
const A_SRC = "source: " + A.source;
const BL_SRC = "source: " + BL.source;
// Rows are [run, admitted, tasks, qc, failed_gates, ledger]. The deck never restates a
// count the table itself carries.
const TRUSTED_NODES = ["22726105", "22728140"]
  .flatMap(j => TRUST[j].rows).filter(r => r[1] === "trusted").length;

// One palette for the whole deck, by ROLE rather than by hue, layered over the library's
// base so C.ink / C.panel / C.fail / C.good keep their shared values.
const DECK = createDeck({
  title: "IMPRESS-A: composing the pipeline instead of writing it down",
  author: "IMPRESS-A",
  palette: {
    reason: "3B4E8C", reasonTint: "E9EDF7",    // the reasoner / policy layer
    exec: "1E6470", execTint: "E3F0F1",        // the executor / runtime
    compose: "2E7D5B", composeTint: "E4F1EA",  // compose, validate, interlock
    tool: "7A4A8C", toolTint: "F3EAF6",        // tools and task agents
    radical: "D9731A", radicalTint: "FCEBDD",  // RADICAL components
    base: "8A6A3B", baseTint: "F5EEE2",        // the reference pipeline, wherever it appears
  },
});
const { pres, C, W, H, M, HF, BF, MF, DASH, MIN_PT,
        text, title, divider, box, line, label, legend, pill, code, footer, card, tbl } = DECK;

const f1 = (v) => Number(v).toFixed(1);
const f2 = (v) => Number(v).toFixed(2);
const pct = (v) => `${Math.round(Number(v) * 100)}%`;

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
  text(s, "Composing the pipeline instead of writing it down", M + 0.3, 1.95, 7.1, 1.35,
    { fontFace: HF, fontSize: 34, bold: true, color: C.white });
  text(s, "— what that buys over an adaptive pipeline that already works, what it costs, " +
    "and which of the three I cannot yet show you", M + 0.3, 3.5, 7.1, 0.9,
    { fontSize: 17, color: "D5DEE5" });
  text(s, `Job ${DONE.job}: six stages, 6/6 tasks ok in ${DONE.wall}, admitted on the first ` +
    `attempt, all four objectives valued. Job 22728140: the same shape promoted, then ` +
    `${TRUST["22728140"].trusted_cycles} consecutive trusted cycles with no demotion`,
    M + 0.3, 4.6, 7.1, 0.7, { fontSize: 13, color: "9FB0BD" });
  text(s, `Lab code walk, in three acts · main @ ${CODE.head} · ` +
    `${(CODE.src_total / 1000).toFixed(1)}k lines of source, ${CODE.tests_collected} tests, ` +
    `${CODE.n_tools} tools in ${CODE.n_toolkits} toolkits`,
    M + 0.3, 6.45, 8.5, 0.3, { fontSize: 12, color: "7E8F9C" });
  s.addNotes(
`[1:00] A code walk, not a results talk. IMPRESS-A runs protein design campaigns on HPC: you give it a goal and a budget, and it decides what experiment to run next, composes a workflow out of a tool registry, runs it through asyncflow and rhapsody, and updates a population of candidates.

The word doing the work is composes — there is no fixed pipeline anywhere in this repository, and most of the code I will show you exists because of that one fact. But "no fixed pipeline" is only interesting against something, and the something is in this room: the reference IMPRESS pipeline, which is adaptive, which works, and which has run at a scale we have not. The comparison all the way through is against a pipeline that is written down, not against no framework.

Three acts: what you can ask for, what it costs, and what it is usable as. I will name the weakest of the three in the next three minutes.`);
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
    `Every run so far is ONE lineage, on ONE of four GPUs. The reference pipeline's comparable ` +
      `runs carry 16 to ${BL.quota_failure.pipelines} concurrent pipelines, so this is not a ` +
      "scale result and nothing here is a throughput comparison.",
    `No node has reached plain pass. This one is ${DONE.qc} because its pattern was still ` +
      `provisional; all ${TRUSTED_NODES} trusted nodes since missed an acceptance threshold ` +
      "instead.",
    "No measurement has ever superseded a prediction, so the calibration machinery — the one " +
      "thing a composed graph gets that a written-down one does not — is untested against reality.",
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
`[1:10] The shape of a campaign, and then what one actually produced.

A goal, a reasoner that decides, a composer that turns that into a typed DAG, admission, execution, absorption. Two edges make it a loop rather than a pipeline — a rejected graph comes back with a structured reason and another attempt, and every decision after the first sees every result so far.

Left card, all measured: six stages end to end in under three minutes, all four objectives with real values, admitted on the first attempt, cost measured per stage.

Right card, because you would ask and I would rather say it first. Every run we have ever done is a single lineage on one of four GPUs — their comparable runs carry sixteen to two hundred and fifty-six pipelines, so nothing in this deck is a throughput comparison. This node is suspect rather than pass because its pattern was provisional — the interlock working, not a failure. And no measurement has ever superseded a prediction, which is the one capability a composed graph has that a written-down one does not.

Read it as a floor. What it proves is that the plumbing survives contact with real tools.`);
}

// ================================================================ 3. The baseline

{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "The baseline is not a blank page", "What we are compared against",
    { kickerColor: C.base });

  // ---- band A: what it already does, measured by its own report
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 1.38, w: 12.33, h: 1.76,
    fill: { color: C.baseTint }, line: { color: C.base, width: 1.5 } });
  text(s, "IMPRESS, the reference adaptive pipeline — what it already does", M + 0.16, 1.45,
    7.6, 0.3, { fontSize: 13, bold: true, color: C.base });
  text(s, BL.hardware, M + 7.9, 1.45, 4.3, 0.3,
    { fontSize: 10, color: C.muted, align: "right", italic: true });
  const stats = [
    [BL.scale.task_dirs.toLocaleString(), `task directories, ${BL.scale.jobs} campaigns`],
    [String(BL.scale.passing_folds_clean), `passing folds, ${BL.scale.task_failures_clean} task failures`],
    [f1(BL.scale.gpu_h_billed), "GPU-hours billed"],
    [pct(BL.packing.k8.gpu), `GPU busy at 8 pipelines per GPU (${pct(BL.packing.k1.gpu[1])} at one)`],
    [String(BL.packing.k8.gpu_h_per_fold), `GPU-h per passing fold (from ${BL.packing.k1.gpu_h_per_fold})`],
  ];
  const sw = 2.38;
  stats.forEach(([v, l], i) => {
    const x = M + 0.16 + i * sw;
    text(s, v, x, 1.8, sw - 0.14, 0.42,
      { fontFace: HF, fontSize: 22, bold: true, color: C.base });
    text(s, l, x, 2.22, sw - 0.14, 0.5, { fontSize: 9.5, color: C.text });
  });
  text(s, [
    { text: "Its orchestration is not the overhead either: ", options: { bold: true } },
    { text: `the adaptive callback is ${pct(BL.manager.occupancy[0])}–` +
      `${pct(BL.manager.occupancy[1])} of the manager's wall clock and backend dispatch has a ` +
      `median of ${BL.manager.dispatch_median_s}s, and its pipelines are busy ` +
      `${pct(BL.busy_share[0])}–${pct(BL.busy_share[1])} of the time.` },
  ], M + 0.16, 2.58, 12.0, 0.46, { fontSize: 10, color: C.text });

  // ---- band B: what it costs to CHANGE it, mined from its own checkout
  const where = BC ? [
    ["the stage graph", `${BC.next_step_sites} next_step assignments in one ` +
      `${BC.decision_fn_lines}-line decision function, over ${BC.steps.length} STEP_ constants`,
     "run_small_molecule_binding.py:210"],
    ["the thresholds", `a PROD dataclass in the runner — fa_rep < ${BC.prod.fastrelax_max_fa_rep}` +
      `, total_score < ${BC.prod.fastrelax_max_score}, interaction_energy < ` +
      `${BC.prod.fastrelax_max_interact}`, "…:63"],
    ["the QC verdict", "computed inside the coroutine that parses the output, then read back " +
      "out of pipeline.state", "small_molecule_binding.py:1154"],
    ["the adaptive hook", "a plain Python closure with full object access, defined in the " +
      "runner script", "briefs/impress.md:112"],
  ] : [["the reference checkout is not on this machine",
        "run_model.py found no IMPRESS checkout, so this half is null rather than guessed",
        "run.json: baseline.code"]];
  text(s, [
    { text: "And what it costs to change it: ", options: { bold: true, color: C.ink } },
    { text: BC ? `one use case is a ${BC.lines.pipeline.toLocaleString()}-line pipeline class ` +
      `plus a ${BC.lines.runner}-line runner; its non-adaptive variant is ` +
      `${BC.lines.nonadaptive} lines.` : "the reference checkout is absent.",
      options: { color: C.text } },
  ], M, 3.22, 12.33, 0.26, { fontSize: 12 });
  tbl(s, ["where the pipeline's shape lives", "what is actually written down", "file"],
    where, M, 3.56, [2.5, 7.35, 2.48],
    { mono: [2], mfs: 8.5, fs: 10, hfill: C.base,
      rowH: [0.26, 0.28, 0.28, 0.28, 0.28], margin: 0.06 });

  // ---- band C: the two measured facts that argue for composition
  card(s, M, 5.3, 6.08, 1.18, "Its adaptivity is a re-sampler, not a ratchet", [
    `A guided child against its OWN parent fold: ΔpLDDT ${BL.guided.d_plddt > 0 ? "+" : ""}` +
      `${BL.guided.d_plddt}, better in ${pct(BL.guided.better_share)} of ${BL.guided.pairs} ` +
      `pairs, p = ${BL.guided.p}. Depth plateaus by the middle third ` +
      `(${BL.depth.plddt_terciles.join(" → ")}). Still worth having: ` +
      `${BL.guided.tasks_per_fold.guided} tasks per fold against ` +
      `${BL.guided.tasks_per_fold.scratch} from scratch.`,
  ], { fill: C.baseTint, hc: C.base, fs: 9.5, hfs: 11.5 });
  card(s, M + 6.25, 5.3, 6.08, 1.18, "And its yield needs a novelty haircut", [
    `${BL.novelty.folds} passing folds are ${BL.novelty.clusters_90pct} clusters at ≥90% ` +
      `identity — ${BL.novelty.folds_per_cluster} folds each. Between different pipelines, ` +
      `median identity ${BL.novelty.cross_pipeline_identity[0]}. Width buys independent ` +
      "searches; depth refines one. That is the argument for lineages and a front, and act 2 " +
      "says what we have run.",
  ], { fill: C.baseTint, hc: C.base, fs: 9.5, hfs: 11.5 });

  text(s, [
    { text: "Said plainly, because it is owed: ", options: { bold: true, color: C.ink } },
    { text: "it paid for lessons we inherited for free, including the NVMe fix this project " +
      "ported out of its PR #67. Nothing here divides its numbers by ours." },
  ], M, 6.62, 12.33, 0.3, { fontSize: 11.5 });
  footer(s, `${BL_SRC}; structural counts mined from that checkout at ${BC ? BC.head : "absent"}.`);
  s.addNotes(
`[1:35] What this is compared against. Not a blank page.

The reference IMPRESS pipeline does adaptive protein design at a scale we have not touched — twenty-four thousand task directories, nine hundred passing folds, no task failures on the clean runs. It also solved the thing we have not: eight pipelines per GPU takes utilisation from twelve percent to seventy and cuts cost per fold threefold. And its orchestration is not the overhead, at under two percent of the manager's wall clock.

So the question is not whether an adaptive pipeline works. It does. The question is what it costs to change one — the middle band, mined from their checkout rather than quoted. The shape of the graph is nineteen assignments to next_step inside one decision function; the thresholds are a dataclass in the runner; the QC verdict is computed inside the coroutine that parses the output; the hook is a plain closure with full object access and no schema. One use case is fourteen hundred lines plus a runner — and the non-adaptive version of the same science is a hundred-line routing table, which is what a declarative rewrite actually looks like.

The bottom cards are why I think composition is worth the trouble, and they are their numbers. Their guided feedback, against its own parent fold, is flat — plus nought point nought one one pLDDT, p of nought point eight five. A cheap re-sampler, not a ratchet — and still worth having at four times cheaper per fold. And eight hundred passing folds are five hundred and ninety-six clusters: width buys independent searches, depth refines one.

The last line is owed rather than implied — that pipeline paid for lessons we inherited for free, including the storage fix in act two.`);
}

// ================================================================ 4. Three dimensions

{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Three dimensions, and the one I have least evidence for", "How to read this deck");

  const cols = [
    { name: "Functionality", col: C.compose, tint: C.composeTint,
      def: "What specific tasks can you ask for that an adaptive pipeline cannot be asked? " +
        "Not features — tasks, carried end to end with no human in the middle.",
      cap: "what it answers",
      rows: [["Composed per cycle, not written down",
              "five gates and a dry-run before anything executes"],
             [`${CODE.n_tools} tools, zero composer edits`,
              "a tool is a spec.yaml, a task agent and mandatory gates"],
             ["Four control models, one executor",
              "byte-identical below the policy layer, which is what makes them comparable"]] },
    { name: "Performance", col: C.exec, tint: C.execTint,
      def: "What does composing, validating and scoring a graph cost — in wall clock, in " +
        "hardware, and in scientific yield? Those three are not linear in each other.",
      cap: "what it answers · and what it does not",
      rows: [[`Overhead ${A.scrutiny.overhead_s[1]}s of a ${Math.round(A.scrutiny.run_s[1])}s run`,
              `and scrutiny itself costs ${A.scrutiny.overhead_s[2].toFixed(1)}s`],
             [`GPU ≤${pct(A.allocation.gpu_share_max[1])}, tasks ` +
              `${pct(A.allocation.task_share_trust[1])} of elapsed`,
              "one GPU works, three idle — we have never packed one"],
             [`${A.diversity.designs} designs in ${A.diversity.seeds} seed groups`,
              "and no node has ever reached a plain pass"]] },
    { name: "Usability", col: C.tool, tint: C.toolTint,
      def: "Not the interface — the use cases. Is this an application someone opens, a " +
        "platform other people plug into, or a component something else drives?",
      cap: "what it answers",
      rows: [["As an application — yes",
              `one YAML, one command, ${CODE.tests_collected} tests with no allocation`],
             ["As a platform — yes",
              "runtime-discovered toolkits, and a control plane in two transports"],
             ["As a component — no evidence",
              "nothing else has ever driven it, and there is no resume"]] },
  ];

  cols.forEach((c, i) => {
    const x = M + i * 4.28;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 4.0, h: 0.42,
      fill: { color: c.col }, line: { color: c.col } });
    text(s, c.name.toUpperCase(), x + 0.14, 1.5, 3.72, 0.42,
      { fontSize: 13, bold: true, color: C.white, valign: "middle", charSpacing: 1 });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.92, w: 4.0, h: 1.04,
      fill: { color: c.tint }, line: { color: c.tint } });
    text(s, c.def, x + 0.14, 1.99, 3.72, 0.92, { fontSize: 10.5, color: C.text });
    text(s, c.cap, x + 0.14, 3.0, 3.72, 0.24,
      { fontSize: 9, color: c.col, italic: true, bold: true });
    c.rows.forEach(([h, b], j) => {
      const y = 3.3 + j * 0.78;
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.0, h: 0.72,
        fill: { color: j % 2 ? C.white : C.panel }, line: { color: C.rule } });
      text(s, h, x + 0.12, y + 0.04, 3.76, 0.3, { fontSize: 10.5, bold: true, color: C.ink });
      text(s, b, x + 0.12, y + 0.34, 3.76, 0.34, { fontSize: 9.5, color: C.muted });
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 5.78, w: 12.33, h: 1.05,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, [
    { text: "The weak column is the middle one, and specifically performance at scale.  ",
      options: { bold: true, color: "F09A8C" } },
    { text: `Every figure in it comes from one lineage on one GPU: ${TRUST.acceptance_rate.of} ` +
      "complete six-stage runs, all of them serial. replicas > 1 has never executed, so the " +
      "invariant that N lineages must produce N independent nodes is unexercised — and it is " +
      "the one most likely to be silently wrong. There is no head-to-head against the reference " +
      "pipeline and I am not going to construct one.", options: { color: "DCE5EC" } },
  ], M + 0.2, 5.88, 11.95, 0.88, { fontSize: 12.5 });
  footer(s, "Each dimension gets an act, in this order, and each act names its own weakest " +
    "claim before it rather than after.");
  s.addNotes(
`[0:50] Three dimensions, because this audience arrives with three questions and each takes a different kind of evidence. The deck is three acts in that order: what you can ask for, what it costs in hardware and in yield, and what it is usable as.

I would rather name the weak one now than have it extracted at minute twenty-five. It is the middle column, and specifically performance at scale. Every performance number here comes from one lineage on one GPU — sixteen complete runs, all serial. Replicas greater than one has never executed, so the invariant that N lineages give N independent results is the piece most likely to be silently wrong.

And there is no head-to-head. I have their numbers and ours, on different hardware at different scales, and I will not divide one by the other.`);
}

// ================================================================ 5. The constraint
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
     "A novel graph shape runs under a cost cap, a forced dry-run, and is marked suspect whatever it scores. Promotion is N consecutive integrity-clean runs; demotion is immediate.",
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
    { text: "if a human reviewed every graph before it ran, you would not build most of this — " +
      "you would write the DAG down once and schedule it. That is the right answer under " +
      `review, and next door it is ${BC ? BC.lines.pipeline.toLocaleString() : "~1,450"} lines ` +
      "of pipeline class per use case. Everything in act 1 is what you get for not writing it " +
      "down; everything in act 2 is what that costs." },
  ], M, 6.46, 12.33, 0.64, { fontSize: 13 });
  s.addNotes(
`[1:05] If you keep one slide, keep this one. Everything after it is a consequence rather than a preference.

Two facts. A machine composes workflows no human has reviewed. And the tools those workflows call fail silently far more often than they crash — a generator hands back a structure with no secondary structure, a confident designability number, and exit code zero.

Five things fall out, each with the file that implements it. A policy emits abstract intent, not a DAG. Everything is validated before it executes. Trust is scored on shape and has to be earned. Exit code is never evidence. And exactly one component writes state and decides when to stop.

The flip side at the bottom is the hinge of the talk. If a person reviewed every graph before it ran, you would write the DAG down once and schedule it, and most of this would stop paying for itself. That is not a strawman — it is the right answer under review, and next door it is fourteen hundred lines of pipeline class per use case that works. Act one is what you get for not writing it down; act two is what that costs.`);
}

// ================================================================ 6. ACT 1 - Functionality

{
  const s = pres.addSlide();
  divider(s, {
    n: 1, of: 3, name: "Functionality",
    definition: "What specific tasks can you ask for that an adaptive pipeline cannot be asked?",
    claims: [
      ["You state a goal, not a pipeline",
       `An ExperimentIntent is a list of tool ids; the composer types it, five gates check it, ` +
       `and a dry-run parameterizes every stage before anything executes. The reference ` +
       `pipeline's shape lives in ${BC ? BC.next_step_sites : "~19"} next_step assignments ` +
       `inside one decision function.`],
      ["A tool is a spec file, and QC is part of the spec",
       `${CODE.n_tools} tools in ${CODE.n_toolkits} toolkits, each a spec.yaml plus an agent. ` +
       "Adding one never edits the composer, the validator or the manager - and gates are " +
       "mandatory, shared by id, and not written by whoever parses the output."],
      ["The control model is swappable, and the layer below it does not know which one ran",
       "Four models plus conduct() reasoners over one executor, byte-identical below the " +
       "policy layer - which is what makes comparing an LLM against a rule cascade mean " +
       "anything at all."],
    ],
    caveat: "every graph we have ever composed is the same six-stage chain the reference " +
      "pipeline already had. Free composition is real in the code and unexercised in the evidence.",
  });
  s.addNotes(
`[0:20] Act one: functionality. Not features — tasks. What can you ask this thing that you cannot ask an adaptive pipeline?

A goal rather than a pipeline. A tool that is a spec file, with its gates part of the spec. A control model you can swap without the layer below knowing.

The weakest claim in red, before the act rather than after it: every graph we have composed is the six-stage chain the reference pipeline already ran.`);
}

// ================================================================ 7. The loop (F1)
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
    ["SUBMIT", "_submit_with_retry:98", "ADMIT  ::_admit_once:304", "compose → gates → interlock\n→ dry-run → reserve", "ExperimentIntent", "right"],
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
`[1:10] Two coroutines meeting at a session, and the asymmetry between them is the point.

Left, a reasoner: observe, decide, submit, wait. Two ways to be one — implement decide and let a driver play the loop, which is what models A through D do, or implement conduct and drive yourself, collecting experiments in the order they finish. The second is what makes a federation of agents generating an ensemble in parallel expressible at all.

Right, the executor: admit, dispatch, reap, absorb, and the only writer of campaign state. Note what it is not: not the loop body with a policy called inside it. The reasoner is a peer.

The red arrow is the one people miss. A rejected submission does not burn the experiment — the policy gets a structured reason and another attempt, bounded twice, because a conduct reasoner is under no obligation to honour anything the driver promises.

Two rules hold it together: one writer, with every mutating block await-free so an observation is never taken mid-absorb; and the executor decides termination, because budget and stagnation are facts a reasoner cannot see.`);
}

// ================================================================ 8. Architecture (F2)
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
`[0:55] Eight layers, and the thing worth looking at is in red: four arrows that do not exist. A policy may not import tools, exec or runtime; compose may not import exec. I draw them because an edge that is merely absent reads as an oversight, and this room will ask whether the rule is enforced or intended.

It is enforced. A test walks the package with ast and checks every internal import against one table — ast.walk rather than module-level imports, because the real adapters defer their science imports into run bodies on purpose, and a deferred cross-layer import is exactly as fatal as one at the top. Writing that test found two edges nobody had documented.`);
}

// ================================================================ 9. Admission
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
    "N consecutive integrity-clean runs promote; any integrity failure demotes and resets the counter.",
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

Five gates, first refusal wins. Gate two rejects a tool composed without its QC gates, so you cannot compose your way out of quality control. Gate four rejects a P6 tool somebody tried to schedule.

Then three things that are not gates: the interlock; a dry-run where every agent parameterizes without executing, which catches a graph that type-checks but cannot be turned into a command line; and a reservation. Reserve is last because the dry-run awaits, and by then another submission may have claimed the budget gate five saw.

The trust half on the right is the part a written-down pipeline has no need for. A pattern is the graph's shape, hashed, with parameter values deliberately excluded so tuning a parameter does not reset trust. A provisional shape is capped, forced through a dry-run, marked suspect whatever it scores, and may have only one instance in flight — promotion counts consecutive clean runs, and N concurrent copies are one draw sampled N times. Clean means no integrity gate failed; a design that merely scores badly fails its node but is not evidence against the shape. Counting it was why our five-cycle trust run promoted nothing.

And the limit, from our own limitations doc: this buys examination and delay, not soundness.`);
}

// ================================================================ 10. Tools are data
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "A tool is a spec file, and QC is part of the spec", "Tools");

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
    box(s, x, 3.62, pw, 0.58, { title: t, sub: "\n" + l, line: C.tool, fill: C.toolTint,
      fs: 10.5, sfs: 8.5, subMono: true });
    if (i < 3) line(s, x + pw + 0.01, 3.91, x + pw + 0.14, 3.91, { w: 1.25 });
  });
  text(s, [
    { text: "post_process ENFORCES the spec's qc_gates", options: { bold: true, color: C.ink } },
    { text: " — never skippable, and execute() is not overridable by an adapter. Loading is " +
      "validating too: a default outside its own range, an unknown gate id or a SKILL.md " +
      "missing a section is a load-time error, and a toolkit that fails anywhere registers " +
      "NOTHING rather than a partial set." },
  ], M, 4.3, 6.3, 0.62, { fontSize: 10.5 });

  // The comparison that is actually defensible: not strictness, but where the verdict lives
  // and whether it can be left out. Both columns are mined - ours from the spec files, theirs
  // from their runner - because this is the table where we are the weaker side.
  tbl(s, ["", "here", "the reference pipeline"], [
    ["the verdict",
     "declared in the spec, resolved by id, mandatory — and a FAIL node never reaches the front",
     "computed in the coroutine that parses the output, as 'pass' in pipeline.state"],
    ["the thresholds", "in the spec, beside the tool",
     `in a PROD dataclass in the runner (${BC ? Object.keys(BC.prod).length : 15} fields)`],
    ["who is stricter, on the two stages we share",
     `total_score ≤ ${OURG.fastrelax.total_score.max}, fa_rep ≤ ${OURG.fastrelax.fa_rep.max}, ` +
       "no interaction_energy",
     BC ? `< ${BC.prod.fastrelax_max_score}, < ${BC.prod.fastrelax_max_fa_rep}, < ` +
       `${BC.prod.fastrelax_max_interact} — THEY ARE` : "(reference checkout absent)"],
  ], M, 5.02, [1.85, 2.3, 2.15], { fs: 9, hfs: 9.5, hfill: C.tool,
      rowH: [0.26, 0.5, 0.3, 0.46], margin: 0.06,
      cell: (i, j) => (i === 2 && j === 2 ? { color: C.fail, bold: true } : {}) });

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

  card(s, rx, 5.02, rwd, 1.92, "Where this defence is still thin", [
    "mock_noodle exists so the QC layer is tested at campaign scale against a tool that lies. " +
      "The real toolkits have no equivalent.",
    "Their gates are almost entirely metric_in_range against a number the tool chose to report " +
      "about itself — which is exactly what a confidently-wrong tool passes.",
    "No structural gates: nothing checks the ligand is in the output complex, that there are no " +
      "chain breaks, or that sequence length matches the contig. The reference pipeline gates on " +
      "RFD3's clash counts; we open that sidecar JSON and do not read it (backlog B1/G2).",
  ], { fill: C.failTint, hc: C.fail, fs: 10 });
  footer(s, "Our thresholds are mined from the spec files, theirs from their runner's PROD " +
    "dataclass — the one comparison in this deck where we are behind.");
  s.addNotes(
`[1:25] Adding a tool is a YAML file plus a subclass, never a change to the composer, validator or manager. If you have to touch those, the layering is wrong.

The spec declares typed ports, a compute pattern, resources, the metrics it reports, mandatory gates resolved by id from a shared library, and a cost model that feeds gate five. Loading is validating: an unknown gate id or a missing skill section is a load-time error, and a toolkit that fails anywhere registers nothing rather than a partial set.

The table at the bottom left is the comparison I think is defensible, and it is not about strictness. Here the verdict is declared in the tool's spec, resolved out of a shared gate library, mandatory for every scheduled tool, and a failed node can never reach the front whatever it scored. There it is computed inside the same coroutine that parses the output and read back out of pipeline state as a boolean called pass. Neither is unsafe — one can be left out by whoever writes the next stage, the other cannot.

Then the third row, which I want to say before anyone looks it up. On the two Rosetta stages we share, their thresholds are stricter than ours: total score under minus two-fifty, repulsion under a hundred, and an interaction energy we do not compute at all. So the claim is about where the verdict lives and whether it is optional — not about us being more careful. We are not, yet.

On the right, the tool that lies: it succeeds, reports designability of nought point nine one, and emits a structure with two percent secondary structure. One test asserts all three at once. The real toolkits have no equivalent, and that is ask six.`);
}

// ================================================================ 11. ACT 2 - Performance

{
  const s = pres.addSlide();
  divider(s, {
    n: 2, of: 3, name: "Performance",
    definition: "What does composing, validating and scoring a graph cost - in wall clock, " +
      "in hardware, and in scientific yield?",
    claims: [
      ["The loop is not the cost",
       `Over ${A.scrutiny.n_untrusted + A.scrutiny.n_trusted} six-stage runs, everything ` +
       `outside a task - dispatch, absorb, QC, provenance - is a median ${A.scrutiny.overhead_s[1]}s ` +
       `of a ${Math.round(A.scrutiny.run_s[1])}s run, and running untrusted costs ` +
       `${A.scrutiny.overhead_s[2].toFixed(1)}s [${A.scrutiny.overhead_s[3].join(", ")}]. ` +
       `The reference manager's adaptive callback is the same order: ` +
       `${pct(BL.manager.occupancy[0])}-${pct(BL.manager.occupancy[1])} of wall.`],
      ["The failures that eat allocations are bounded, in code",
       `Backend startup and teardown both, measured against two lost allocations and the ` +
       `${BL.teardown.gpu_h} GPU-h a teardown that never returned cost the reference ` +
       `pipeline - ${pct(BL.teardown.share_of_billed)} of that job's billed total, spent ` +
       `after the science was done.`],
      ["The headroom is not orchestration",
       `Tasks fill ${pct(A.allocation.task_share_trust[1])} of elapsed, so the idle hardware ` +
       `is the three GPUs we never give work to - and packing is the lever the reference ` +
       `pipeline already pulled, from ${pct(BL.packing.k1.gpu[1])} to ${pct(BL.packing.k8.gpu)}.`],
    ],
    caveat: "there is no serial baseline and no head-to-head. One lineage, one GPU, three idle, " +
      "on a different partition from every reference figure - so nothing here divides into a speedup.",
  });
  s.addNotes(
`[0:20] Act two: performance — both kinds, because hardware cost and scientific yield are not linear in each other.

The loop is not the cost. The failures that eat allocations are bounded in code, both ends of the backend lifecycle. And the headroom is not orchestration: tasks fill ninety-five percent of elapsed, so what is idle is three of four GPUs.

In red: no serial baseline and no head-to-head. Nothing in this act divides into a speedup.`);
}

// ================================================================ 12. The seam: dispatch
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "★ One generic factory, and a submit that does not await",
    "Performance · the seam, 1 of 2");

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
`[1:15] The slide I would defend hardest, and it is four lines of real code.

A task graph is plain data. To run it, one generic factory builds a closure per node, sets its dunder-name to the node id, and hands it to asyncflow's function_task decorator. That is the whole adapter — no codegen, no templating. And setting dunder-name first is not a trick: the decorators take no name keyword, so this is exactly what lets one factory serve every node of every graph. The closure binds workdir to a local rather than reaching through self, because it gets pickled to a process pool and self would drag the dispatcher along with it.

Second block, submission. Walk the graph topologically, pass each dependency's unawaited future as an argument — that is how you express an edge — build a gather with return_exceptions, and return without awaiting. That one change is what let the reasoner stop being the loop body. Two idioms, not interchangeable: unawaited futures are edges, gather is independent work.

Right-hand side, measured rather than assumed. Cancellation is advisory: cancel returns False once a callable has started, asyncflow throws that answer away, so queued work is reclaimed, running work is not, and nobody tells you which happened. A run's terminal state always comes from collecting it.`);
}

// ================================================================ 13. The seam: the engine
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "★ Building the engine on the loop that will use it",
    "Performance · the seam, 2 of 2");

  code(s, [
    'async def make_engine_bounded(kind, config, timeout_s, heartbeat_s, work_dir):',
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
    '        return await WorkflowEngine.create(backend=backend, work_dir=work_dir), backend',
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
`[1:20] The second half of the seam is construction, and this is where the expensive lessons are.

Three things in make_engine_bounded are load-bearing. Only the synchronous construction goes to a dedicated daemon thread, not the default executor, because a stuck call on a pooled thread would hang interpreter shutdown too. The backend's async init and the engine are built back on the caller's own loop. And that await is not politeness: rhapsody's backends are awaitable, and awaiting is what registers the task states. Construct one synchronously and it appears to work, then fails much later with "backend not registered, available backends: empty list".

The right column is what each lesson cost. Two full allocations went to an engine built on a throwaway loop — asyncflow captures the running loop in its constructor and puts its dispatch task on it, so an engine built on a closed loop looks fine and dispatches nothing. One two-hour allocation went entirely to Dragon's Batch constructor, which blocks the loop, so our own heartbeat never fired once.

And the most expensive item is teardown, not startup: on the reference pipeline, shutdown never returned after the science had finished, and the job sat an hour before someone cancelled it — sixty-four GPU-hours, thirty-seven percent of that job's bill. Both ends are bounded now, and a stuck teardown is abandoned with a warning rather than raised: results are already durable, and raising would report a campaign that succeeded as failed.`);
}

// ================================================================ 14. What the loop costs

{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "What the loop costs, and what is not measured", "Performance · measured");

  // ---- left: the one real figure. One variable: trusted versus untrusted.
  text(s, "A six-stage run, by where its seconds go", M, 1.42, 6.0, 0.28,
    { fontSize: 12.5, bold: true, color: C.ink });
  const [uRun, tRun] = [A.scrutiny.run_s[0], A.scrutiny.run_s[1]];
  const [uOv, tOv] = [A.scrutiny.overhead_s[0], A.scrutiny.overhead_s[1]];
  const bars = [
    { label: `untrusted\n(n = ${A.scrutiny.n_untrusted})`, run: uRun, ov: uOv },
    { label: `trusted\n(n = ${A.scrutiny.n_trusted})`, run: tRun, ov: tOv },
  ];
  const bx = M + 1.25, bw = 4.3, bmax = 180;
  bars.forEach((b, i) => {
    const y = 1.82 + i * 0.78;
    text(s, b.label, M, y - 0.04, 1.13, 0.42,
      { fontSize: 10, color: C.text, align: "right", valign: "middle" });
    const taskW = ((b.run - b.ov) / bmax) * bw, ovW = Math.max((b.ov / bmax) * bw, 0.07);
    s.addShape(pres.shapes.RECTANGLE, { x: bx, y, w: taskW, h: 0.34,
      fill: { color: C.exec }, line: { color: C.exec } });
    s.addShape(pres.shapes.RECTANGLE, { x: bx + taskW, y, w: ovW, h: 0.34,
      fill: { color: C.radical }, line: { color: C.radical } });
    text(s, `${f1(b.run)}s`, bx + taskW + ovW + 0.08, y - 0.02, 0.9, 0.38,
      { fontSize: 10.5, bold: true, color: C.text, valign: "middle" });
  });
  const ay = 1.82 + 2 * 0.78 - 0.06;
  line(s, bx, ay, bx + bw + 0.3, ay, { color: C.rule, w: 1, noArrow: true });
  [0, 60, 120, 180].forEach(t => {
    const tx = bx + (t / bmax) * bw;
    line(s, tx, ay, tx, ay + 0.07, { color: C.rule, w: 1, noArrow: true });
    label(s, String(t), tx - 0.3, ay + 0.08, 0.6, { fontSize: 9 });
  });
  label(s, "seconds of run wall clock, median", bx, ay + 0.3, bw, { align: "left", fontSize: 9.5 });
  pill(s, "inside a task", bx, ay + 0.56, 1.35, C.exec, { fs: 9, h: 0.26 });
  pill(s, "everything else", bx + 1.45, ay + 0.56, 1.6, C.radical, { fs: 9, h: 0.26 });
  text(s, [
    { text: "Everything else", options: { bold: true, color: C.radical } },
    { text: " is dispatch, absorb, QC, Pareto, provenance and the ledger: " +
      `a median ${tOv}s. Running UNTRUSTED — forced dry-run, cost cap, suspect verdict — ` +
      `costs ${A.scrutiny.overhead_s[2].toFixed(1)}s ` +
      `[${A.scrutiny.overhead_s[3].join(", ")}] on top of that. The gates are not the cost.` },
  ], M, ay + 0.92, 6.0, 0.72, { fontSize: 10.5 });
  text(s, `Declared vs measured, per six-stage chain: ${A.cost.declared_per_chain} GPU-h ` +
    `declared, ${A.cost.measured_median} measured (max ${A.cost.measured_max}). Every declared ` +
    `figure is ≥${A.cost.min_declared_over_max}× the worst task observed, deliberately — gate 5 ` +
    `and the untrusted cap REFUSE graphs against them, so they err high.`,
    M, ay + 1.68, 6.0, 0.6, { fontSize: 10, color: C.muted });

  // ---- right: measured, and not measured
  card(s, M + 6.33, 1.42, 6.0, 2.26, "Measured, and in this deck", [
    `${A.n_timed_tasks} timed tasks over 5 jobs, from asyncflow's own RUNNING → DONE lines in ` +
      "campaign.log — the only per-task wall time a run records.",
    `Per-stage spread: rfd3 ${A.stage_s.rfd3_design[1]}s median, ` +
      `${A.rfd3_tight.n} of ${A.rfd3_tight.of} tasks in ${A.rfd3_tight.band.join("–")}s, ` +
      `one outlier at ${A.stage_s.rfd3_design[5]}s.`,
    `Where the allocation goes: tasks ${pct(A.allocation.task_share_trust[1])} of elapsed, ` +
      `CPU efficiency ${pct(A.allocation.cpu_eff[1])}, peak memory ${A.allocation.maxrss_gb} of ` +
      `${A.allocation.mem_gb} GB.`,
    `Queue wait, unbilled but real: ${Math.min(...A.allocation.queue_s)}–` +
      `${Math.max(...A.allocation.queue_s).toLocaleString()}s against campaign elapsed of ` +
      `${Math.min(...A.allocation.elapsed_s)}–${Math.max(...A.allocation.elapsed_s)}s. It is ` +
      "the real latency of a test cycle, and it is nobody's code.",
  ], { fill: C.panel, fs: 9.5 });
  card(s, M + 6.33, 3.78, 6.0, 2.26, "Not measured — so not claimed", [
    "No serial baseline exists, so nothing on this slide divides into a speedup.",
    `GPU utilisation is recorded nowhere in a run. ≤${pct(A.allocation.gpu_share_max[1])} of ` +
      "billed GPU time is an UPPER BOUND with model load counted inside it.",
    "Concurrency has never happened: every run is one serial chain, so this is not a scheduling " +
      "result. Packing more than one lineage onto a GPU has never been attempted.",
    "The ledger's cost field is the admission estimate echoed back. It is not evidence and no " +
      "figure here uses it.",
  ], { fill: C.failTint, hc: C.fail, fs: 9.5 });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 6.2, w: 12.33, h: 0.62,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, [
    { text: "Where this stops being a systems question:  ", options: { bold: true, color: "F0C898" } },
    { text: `the loop is ~2% of a run and the hardware is ${pct(1 - A.allocation.gpu_share_max[1])} ` +
      "idle. The next real gain is not in this orchestrator — it is giving the other three GPUs " +
      "work, which is a lineage-count question, not a scheduling one.", options: { color: "DCE5EC" } },
  ], M + 0.2, 6.28, 11.95, 0.46, { fontSize: 12 });
  footer(s, A_SRC);
  s.addNotes(
`[1:30] The measured half of the act, and the figure is deliberately about one variable.

Two bars: the median untrusted run and the median trusted run, split into time inside a task and time anywhere else. Everything else means dispatch, absorb, QC, the Pareto update, provenance and the durable ledger — all of it a median of two point eight seconds out of a hundred and sixty. And the comparison is the point: running untrusted, which means a forced dry-run, a cost cap and a suspect verdict whatever it scores, costs zero point zero seconds, interval minus nought point nine to plus one point two. The scrutiny is free, and that is measured rather than argued.

Underneath, the cost models: nought point one seven GPU-hours declared per chain against nought point oh two nine measured. Every declared figure is at least two and a quarter times the worst task observed, because gate five and the untrusted cap refuse graphs against those numbers. Headroom is not inefficiency.

The red card is written as refusals, not apologies. No serial baseline, so nothing here is a speedup. GPU utilisation is recorded nowhere, so seventeen percent is an upper bound with model load inside it.

And the band is the conclusion: the loop costs about two percent and the hardware is eighty-three percent idle. The next real gain is not in this orchestrator — it is giving the other three GPUs work, which is ask seven.`);
}

// ================================================================ 15. Seven jobs (F3)
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, `Seven jobs: what storage bought, and what trust cost`, "Measured · F3");

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
    `import pyrosetta off HDD-backed Lustre: ${D.import_cost_s.pyrosetta_hdd} s for a 598 MB ` +
      "rosetta.so, demand-paged. torch: ~" + D.import_cost_s.torch_hdd + " s.",
    "On NVMe both are seconds — the single variable behind rows one and two.",
    "And we did not find it: the $WORK_DIR move is ported from their own PR #67.",
  ], { fill: C.failTint, hc: C.fail, fs: 9.5 });
  card(s, rx, 3.8, rwd, 1.75, "Wall time is not stable", [
    `rfd3_design took ${D.jobs[2].stages.rfd3_design} s in 22684607 and ` +
      `${D.jobs[3].stages.rfd3_design} s in 22692304 — same campaign, same allocation shape, ` +
      "same parameters, 3.2× apart.",
  ], { fill: C.panel, fs: 10 });
  card(s, rx, 5.7, rwd, 1.25, "So do not tune cost models to it", [
    "They feed gate 5 and the untrusted cap, which REFUSE graphs. They sit a few multiples above " +
      "measurement on purpose.",
  ], { fill: C.composeTint, hc: C.compose, fs: 10, hfs: 11.5 });

  // --- the three trust runs. No per-stage durations were recorded for these, only per-run
  // wall times, so they get a run-level table rather than a bar they cannot honestly fill.
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 4.28, w: 9.0, h: 0.32,
    fill: { color: C.compose }, line: { color: C.compose } });
  text(s, "Then three jobs about the SHAPE, not the science — 15 runs, 6/6 tasks every time",
    M + 0.12, 4.28, 8.8, 0.32,
    { fontSize: 11, bold: true, color: C.white, valign: "middle" });

  // One short cell per run, derived from the transcribed row rather than retyped.
  const outcome = r => {
    const [, adm, , , gates, led] = r;
    if (led.includes("PROMOTED")) return `${adm} · clean → PROMOTED`;
    if (led.includes("DEMOTED")) return `${adm} · INTEGRITY fail → demoted`;
    if (gates === "none") return `${adm} · clean`;
    return `${adm} · fail (acceptance)`;
  };
  const RA = TRUST["22726105"].rows, RB = TRUST["22728140"].rows;
  tbl(s, ["run", `22726105 · ${TRUST["22726105"].wall}`, `22728140 · ${TRUST["22728140"].wall}`],
    RA.map((r, i) => [r[0], outcome(r), outcome(RB[i])]),
    M, 4.64, [0.8, 4.1, 4.1],
    { fs: 10, hfs: 10, rowH: 0.26, hfill: C.compose,
      cell: (i, j, c) => String(c).includes("demoted") ? { color: C.fail, bold: true }
        : String(c).startsWith("trusted") ? { color: C.good, bold: true } : {} });

  text(s, [
    { text: "22702568 ran 30/30 tasks clean and promoted nothing", options: { bold: true } },
    { text: " — the all-gates rule made promotion a function of target difficulty " +
      "(decision 0013). Two defects, both fixed: packmin's " +
      `total_score <= 1000 bound was ONE observation wide and demoted r0004 over a +` +
      `${TRUST.packmin_bound.tripped_on} pose fastrelax took to ` +
      `${TRUST.packmin_bound.relaxed_to}, and the driver counted a Backtrack as a cycle, so ` +
      `every job asked for ${TRUST.cycle_off_by_one.asked} runs and ran ` +
      `${TRUST.cycle_off_by_one.ran}.` },
  ], M, 6.48, 9.0, 0.56, { fontSize: 9.5, color: C.text });

  footer(s, "Durations transcribed from plans/first-real-run.md; the trust runs from " +
    "plans/next-run-promotion.md and plans/next-run-sustained-trust.md — the raw logs live " +
    "under $WORK_DIR/impress_a_runs on Delta. Bars are tool time.");
  s.addNotes(
`[1:25] Seven jobs, and the figure at the top is really about one variable.

Top row, the HDD baseline: diffusion 137 seconds, sequence design 293, and then packmin could not finish importing PyRosetta inside its three-hundred-second budget, so nothing downstream ran. Middle row, the same campaign with one thing changed — the virtual environment moved to NVMe. Sequence design went from 293 seconds to 18, packmin from not finishing to sixteen.

The reason is on the right. Importing PyRosetta off that filesystem costs 471 seconds, a 598-megabyte shared object demand-paged; torch is another 280. On NVMe both are seconds. That was the single largest cost this project was paying, it was invisible because it looked like a tool timing out — and we did not find it. The fix is ported from their PR sixty-seven.

Bottom right, the caveat for anyone reading our cost models: diffusion took 146 seconds in one job and 45 in the next, same campaign, same parameters. Those numbers feed gates that refuse graphs, so they sit deliberately above measurement.

The table underneath is three later jobs that changed nothing about the science and asked one question — does the shape earn trust. The first ran thirty tasks out of thirty cleanly and promoted nothing, because we were counting design quality as evidence about the workflow. With only integrity gates counting, the same chain promoted after its second run in both later jobs.`);
}

// ================================================================ 16. Scale and yield

{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Where scale stops buying yield", "Performance · the scientific half");

  // ---- left, both figures from the reference pipeline's own report and ours
  text(s, "Its search improves, then plateaus — by the middle third", M, 1.42, 6.0, 0.28,
    { fontSize: 12.5, bold: true, color: C.ink });
  const terc = BL.depth.plddt_terciles;
  terc.forEach((v, i) => {
    const x = M + i * 2.05;
    box(s, x, 1.78, 1.6, 0.62, { title: f1(v), sub: ["first third", "middle", "last third"][i],
      fill: C.baseTint, line: C.base, fs: 17, sfs: 9, tc: C.base });
    if (i < 2) {
      const d = terc[i + 1] - v;
      line(s, x + 1.64, 2.09, x + 2.01, 2.09, { color: d > 1 ? C.good : C.muted, w: 1.5 });
      text(s, `${d > 0 ? "+" : ""}${f1(d)}`, x + 1.5, 2.12, 0.7, 0.26,
        { fontSize: 10, bold: true, color: d > 1 ? C.good : C.muted, align: "center" });
    }
  });
  label(s, "median complex pLDDT by episode tercile, pooled over its clean runs — and median " +
    "ligand_iptm does the same: " + BL.depth.iptm_terciles.join(" → "),
    M, 2.46, 6.0, { align: "left", fontSize: 9.5, h: 0.4 });

  text(s, "And the headline count is not the yield", M, 2.96, 6.0, 0.28,
    { fontSize: 12.5, bold: true, color: C.ink });
  const ind = [
    { label: `IMPRESS, ${BL.novelty.folds} passing folds`, v: BL.novelty.clusters_90pct / BL.novelty.folds,
      note: `${BL.novelty.clusters_90pct} clusters at ≥90% identity`, color: C.base },
    { label: `IMPRESS-A, ${A.diversity.designs} designs`, v: A.diversity.seeds / A.diversity.designs,
      note: `${A.diversity.seeds} structural groups (median TM ${A.diversity.tm_same_seed} ` +
        `within, ${A.diversity.tm_other} across)`, color: C.exec },
  ];
  const ix = M + 2.5, iw = 3.1;
  ind.forEach((r, i) => {
    const y = 3.34 + i * 0.74;
    text(s, r.label, M, y - 0.02, 2.38, 0.3,
      { fontSize: 10, color: C.text, align: "right", valign: "middle" });
    s.addShape(pres.shapes.RECTANGLE, { x: ix, y, w: iw, h: 0.26,
      fill: { color: C.rule }, line: { color: C.rule } });
    s.addShape(pres.shapes.RECTANGLE, { x: ix, y, w: Math.max(r.v * iw, 0.04), h: 0.26,
      fill: { color: r.color }, line: { color: r.color } });
    text(s, pct(r.v), ix + iw + 0.08, y - 0.04, 0.6, 0.34,
      { fontSize: 10.5, bold: true, color: r.color, valign: "middle" });
    text(s, r.note, ix, y + 0.28, iw + 0.7, 0.26, { fontSize: 9, color: C.muted });
  });
  label(s, "independent samples as a share of the headline count, 0–100%. Both analyses " +
    "overcount their own yield, and both say the same thing: width, not depth.",
    M, 4.86, 6.0, { align: "left", fontSize: 9.5, h: 0.42 });

  // ---- right, what this system does about it, and whether it has run
  card(s, M + 6.33, 1.42, 6.0, 1.3, "What this project does about it", [
    "replicas: N means N INDEPENDENT lineages, one DesignNode each — the composer fans out and " +
      "the executor's _absorb never funnels them back into one candidate.",
  ], { fill: C.execTint, hc: C.exec, fs: 10 });
  const rows = [
    ["N lineages, N nodes", "compose/composer.py · executor._absorb", "tested"],
    ["A front that is not monotonic: a measurement supersedes but never deletes a prediction, " +
      "so a node promoted on an optimistic guess can be demoted by its own assay",
     "core/tree.ingest_measurement · core/pareto.py", "tested"],
    ["Trust scored on graph SHAPE, so breadth has an identity of its own and cannot inherit " +
      "credit earned at width 1", "compose/graph.py:51", "built"],
  ];
  let ry = 2.86;
  rows.forEach(([t, where, st], i) => {
    const h = i === 1 ? 0.86 : 0.62;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: M + 6.33, y: ry, w: 6.0, h, rectRadius: 0.06,
      fill: { color: i % 2 ? C.white : C.panel },
      line: { color: C.exec, width: 1.25, dashType: DASH[st] } });
    text(s, t, M + 6.45, ry + 0.05, 5.76, h - 0.3, { fontSize: 10, color: C.text });
    text(s, where, M + 6.45, ry + h - 0.26, 5.76, 0.22,
      { fontSize: 8.5, color: C.muted, fontFace: MF });
    ry += h + 0.1;
  });
  legend(s, M + 6.4, 5.5, { items: [["built, runs for real", "built"],
                                    ["built and tested, never run for real", "tested"]],
                            tw: 3.4 });
  text(s, `Our own ${A.diversity.designs} designs: ${A.diversity.identical_backbones} ` +
    `byte-identical backbones, median Cα RMSD ${A.diversity.ca_rmsd} Å. The seed plumbing does ` +
    "something — but at one lineage per run, the seeds come from the run label, so breadth " +
    "and reproducibility are the same unexercised question.",
    M + 6.33, 6.08, 6.0, 0.6, { fontSize: 9.5, color: C.muted });

  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 5.44, w: 6.0, h: 1.3,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, [
    { text: "The honest state of this slide:  ", options: { bold: true, color: "F09A8C" } },
    { text: "the machinery for width is written, typed and unit-tested, and " +
      "replicas > 1 has never executed. Worse, the cheap route to it is closed: the pattern " +
      "signature includes replica multiplicity, so the trust earned at one lineage does not " +
      "transfer to four — a four-lineage graph starts untrusted, under a cap it already " +
      "exceeds. That is backlog A10 and it is ask 5.", options: { color: "DCE5EC" } },
  ], M + 0.18, 5.52, 5.66, 1.16, { fontSize: 10.5 });
  footer(s, `${BL_SRC}  ·  ${A_SRC}`);
  s.addNotes(
`[1:30] The slide worth the most in this act, and almost none of it is our data.

Top left: their search improves and then stops. Median pLDDT by episode tercile goes ninety point seven, ninety-five point two, ninety-five point oh — plus four and a half, then minus nought point two. Depth buys you something and then it buys you nothing, and they have the sample size to say so where we do not.

Bottom left is the pair worth staring at. Their eight hundred and four passing folds are five hundred and ninety-six clusters — seventy-four percent independent. Our seventeen designs cluster into five structural groups: twenty-nine percent. We are the worse number. Both analyses overcount their own yield, and both point at the same lever: width, not depth.

Right side is what this project does about it, and the dotted borders are doing the work. Replicas-N means N independent lineages, one node each, and the executor never funnels them back into one candidate. The front is deliberately not monotonic, so a node promoted on an optimistic prediction gets demoted by its own assay. Trust is scored on shape, so breadth has an identity of its own.

All of it dotted — written, typed, unit-tested, never executed. And the cheap route is closed: the signature includes replica multiplicity, so trust earned at one lineage does not transfer to four. A four-lineage graph arrives untrusted, under a cap it already exceeds. That is ask five.`);
}

// ================================================================ 17. Four defects
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

  // Three lines at 12pt need more than 0.5" of box: the last line was clipped by the strip.
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 6.34, w: 12.33, h: 0.76,
    fill: { color: C.ink }, line: { color: C.ink } });
  text(s, [
    { text: "Two things to carry away.  ", options: { bold: true, color: "F0C898" } },
    { text: "\"Checked against the binary\" is not \"executed\" — numbers 1 and 2 were both " +
      "invisible to every contract check we had. And a plausible explanation is not a diagnosis: " +
      "the trajectory bug was a convincing cause for a LigandMPNN failure it had nothing to do with.",
      options: { color: "DCE5EC" } },
  ], M + 0.2, 6.42, 11.95, 0.62, { fontSize: 12 });
  s.addNotes(
`[1:15] Four defects reached real hardware, each invisible to a dry run. The pattern across them is more useful than any one.

The first two as a pair: one picked the wrong file of the right extension, the other died in its module-level imports before parsing a single argument we passed it. No contract check we had could see either. Then the storage story from the last slide — where the queued fix was to raise three walltimes six-fold, which would have hidden a 471-second import behind a timeout.

And the subtle one: an estimate that refuses work. Our cost models were literature guesses six to sixty-nine times over reality, and gate five and the interlock cap refuse graphs against those numbers. The inflated GPU side summed past the cap, so the policy truncated the last stage off the chain — which happened to be the only producer of two of the four campaign objectives. The run was unwinnable from the moment it was admitted, and nothing said so.

Two things to carry away. Checked against the binary is not executed. And a plausible explanation is not a diagnosis — the trajectory bug was a convincing cause for a failure it had nothing to do with.`);
}

// ================================================================ 18. The trust ledger
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

  card(s, M + 6.6, 1.95, 6.23, 1.1, "…and then it remembered", [
    "trust_root is absolute now, so evidence accumulates ACROSS jobs: 22702568's last event " +
      "was clean, so 22726105 promoted a run early.",
    `22728140 then ran ${TRUST["22728140"].trusted_cycles} consecutive trusted cycles — ` +
      `${TRUST["22728140"].demotions} demotions, ` +
      `${TRUST["22728140"].integrity_failures} integrity failures.`,
  ], { fill: C.composeTint, hc: C.compose, fs: 9.5 });

  text(s, [
    { text: "How it hid: ", options: { bold: true, color: C.ink } },
    { text: "nothing ever logged where the ledger was, so a file that silently reset looked " +
      "identical to one that had not earned promotion yet — and it was reported that way. " +
      "Campaign start now prints the absolute path with a pattern and trusted count. It had " +
      "been true since the first Delta job, so " },
    { text: "the trusted path did not execute until job 22726105",
      options: { bold: true, color: C.compose } },
    { text: ": every graph composed on real hardware before it ran under the forced dry-run " +
      "and the 10% cap — and that cap is what truncated boltz_predict off the chain twice." },
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
    "on backup B1 shows the same shape, the shrink from 3 lineages to 2 producing a new pattern.");
  s.addNotes(
`[1:25] Two findings about the trust ledger, and the second is open.

The first: the ledger path was relative to the campaign root, and the Delta launcher changes into a per-job directory, so it resolved inside each job and started empty every time — while promotion counts three consecutive clean runs within one file.

What is worth your time is how it hid. Nothing logged where the ledger was, so a file that silently reset looked exactly like one that had not earned promotion yet, and I reported it that way. It had been true since the first Delta job, which is why the trusted path did not execute until 22726105. The fix did more than stop the reset: the ledger is site-wide now, so evidence accumulates across jobs — which is why promotion came a run early and the job after it ran three trusted cycles clean.

The second I hit while generating these numbers, and I have not changed the code. The signature emits one string per node, so N lineages give N duplicate parts and the hash moves with the replica count — though it deliberately does not move when you tune a parameter. The cost is concrete: the cheap route to four lineages was to promote at one and then widen. It does not work. Four is a different, untrusted pattern, still capped, still refused, and the policy would quietly shrink it to three.`);
}

// ================================================================ 19. ACT 3 - Usability

{
  const s = pres.addSlide();
  divider(s, {
    n: 3, of: 3, name: "Usability",
    definition: "Not the interface - the use cases. Is it an application, a platform, or a " +
      "component in something larger?",
    claims: [
      ["As an application: yes, and without an allocation",
       `A campaign is one YAML and one command. The whole local tier - ` +
       `${CODE.tests_collected} tests over ${CODE.test_lines.toLocaleString()} lines - runs on ` +
       "a laptop with no scheduler, no GPU and no cluster."],
      ["As a platform: yes, with a seam that is not the CLI",
       `Toolkits are discovered at runtime, not packaged: ${CODE.n_tools} tools declared in ` +
       "spec.yaml with a SKILL.md beside them. The control plane ships in two transports, and " +
       "a reasoner in another process has driven a campaign over HTTP + SSE."],
      ["As a component: no evidence, and that is the honest answer",
       "Nothing else has ever driven it. There is no resume, no serve, no reason command, and " +
       "sites/*.yaml is read by no code at all."],
    ],
    caveat: "the component claim is empty - and because serve and reason do not exist, " +
      "--model C fails open and reports a model-D campaign as model C.",
  });
  s.addNotes(
`[0:20] Act three: usability — the short act, which is information rather than a problem.

As an application, yes. As a platform, yes, and the seam is not the command line. As a component in someone else's workflow: no evidence, because nothing else has ever driven it.

And in red — because serve and reason do not exist, asking for the headless control model silently gives you the explicit one and reports it as headless.`);
}

// ================================================================ 20. Running it
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "As an application: one YAML, one command",
    "Usability · as an application");

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
    "The corollary: everything only verifiable on HPC is unverified. That is the honest price " +
      "of a tier that needs no scheduler.",
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
`[0:45] Act three, and the easy claim first: as an application this is one YAML and one command.

The command worth pointing at is preflight — it checks the container path, the checkpoints, the Boltz cache, whether PyRosetta imports, and whether the virtual environment is still on slow storage, all on a login node before you spend a queue slot.

The split that matters is that the entire local tier runs on a laptop in about fifteen seconds with no allocation: a complete campaign with a real manager, real policies, a real composer and validator, stubbed science. The corollary is the uncomfortable half — everything only verifiable on HPC is unverified.

One convention worth stealing: a magic number in a test is often a bug report. A stagnation limit of ten thousand appeared in three tests before anyone noticed the defect was in the engine.`);
}

// ================================================================ 21. The control plane
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "As a platform: the seam is the control plane, not the CLI",
    "Usability · as a platform");

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
`[1:15] And as a platform — the more interesting claim, because the seam someone else plugs into is not the command line.

One protocol, nineteen operations, adapters that translate transport only. The decision worth stating is that observe returns the same observation object a policy's decide receives: informed monitoring means parity of evidence, not a progress bar.

Admission is synchronous even over HTTP — a 202 with a run id, or a 409 with the gate and the reason. That is not a style choice. Accepting and rejecting later would sever a rejection from the request that caused it, and it cannot work anyway, because the dry-run instantiates task agents and has to run where the toolkit is installed.

The gap is honest and annoying: all of this is reachable from the test suite and not from a shell. There is no serve command and no reason command, so model C fails open — it builds a policy whose inbox nothing can fill, times out every five seconds, and runs the model-D cascade while reporting itself as model C.

Which is also the answer to the third use case. As a component in someone else's workflow there is no evidence at all: nothing external has ever driven a campaign outside tests, there is no resume, and the site files are read by no code. One of your pipelines running as a tool of ours would be the obvious proof, and that is the P7 row with no member.`);
}

// ================================================================ 22. Status
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "What is real, and what is not — by dimension", "Status");

  // Three rows green and three red PER dimension, on purpose: it forces a decision about
  // which three things actually run, and it shows at a glance whether the candour is evenly
  // spread or concentrated in whichever dimension I was least invested in.
  const cols = [
    { name: "Functionality", col: C.compose,
      real: ["A six-stage real-toolkit campaign, end to end on Delta: 6/6 tasks, four " +
               "objectives, a front.",
             "The engine: compose, five gates, interlock, dry-run, Pareto tree, provenance, " +
               "durable ledger.",
             `Four control models plus conduct() reasoners over one executor — ` +
               `${CODE.n_tools} tools, and adding one has never touched the composer.`],
      not: ["replicas > 1 has NEVER executed. N independent lineages is the invariant most " +
              "likely to be silently wrong.",
            "No measurement has superseded a prediction, so calibration is untested — and " +
              "that is the capability a composed graph has and a fixed one does not.",
            `${R.patterns.unused.length} of the 8 compute patterns have no member, P7 ` +
              "(an IMPRESS pipeline as one tool) among them."] },
    { name: "Performance", col: C.exec,
      real: [`The TRUSTED path: promoted after r0002, then ` +
               `${TRUST["22728140"].trusted_cycles} consecutive trusted cycles — no forced ` +
               "dry-run, no cost cap, no demotion.",
             `Scrutiny measured and free: ${A.scrutiny.overhead_s[1]}s of overhead per run, ` +
               `untrusted costs ${A.scrutiny.overhead_s[2].toFixed(1)}s ` +
               `[${A.scrutiny.overhead_s[3].join(", ")}].`,
             "Dragon startup AND teardown bounded; per-tool cost measured for all six real " +
               "tools and the specs corrected from it."],
      not: ["No serial baseline and no head-to-head, so nothing in act 2 is a speedup.",
            `One GPU of four ever works: GPU-busy ≤${pct(A.allocation.gpu_share_max[1])} as an ` +
              "upper bound, and packing has never been attempted.",
            `No node has reached plain pass — all ${TRUSTED_NODES} trusted nodes missed an ` +
              `acceptance threshold, ${TRUST.acceptance_rate.pct}% over ` +
              `${TRUST.acceptance_rate.of} runs. More draws, not code.`] },
    { name: "Usability", col: C.tool,
      real: ["A campaign is one YAML and one command; the whole local tier runs with no " +
               "allocation.",
             `Toolkits discovered at runtime: ${CODE.n_toolkits} of them, declarative specs ` +
               "plus a SKILL.md, validated at load.",
             "Control plane in two transports, including a reasoner in another process driving " +
               "a campaign over HTTP + SSE."],
      not: ["No resume: the ledger and reattach() exist, nothing resumes from them.",
            "impress-a serve / reason do not exist, so --model C fails open and reports a " +
              "model-D campaign as model C.",
            "sites/*.yaml is read by no code. MCP is designed, not built. Nothing external has " +
              "ever driven a campaign outside tests/."] },
  ];

  cols.forEach((c, i) => {
    const x = M + i * 4.28;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.42, w: 4.0, h: 0.36,
      fill: { color: c.col }, line: { color: c.col } });
    text(s, c.name.toUpperCase(), x + 0.12, 1.42, 3.76, 0.36,
      { fontSize: 11.5, bold: true, color: C.white, valign: "middle", charSpacing: 1 });
    [[c.real, C.good, "Runs, for real", "F0F6F2"],
     [c.not, C.fail, "Has never run", C.failTint]].forEach(([rows, col, head, tint], k) => {
      const y0 = 1.86 + k * 2.56;
      s.addShape(pres.shapes.RECTANGLE, { x, y: y0, w: 4.0, h: 0.3,
        fill: { color: col }, line: { color: col } });
      text(s, head, x + 0.12, y0, 3.76, 0.3,
        { fontSize: 10, bold: true, color: C.white, valign: "middle" });
      rows.forEach((t, j) => {
        const y = y0 + 0.34 + j * 0.72;
        s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.0, h: 0.68,
          fill: { color: j % 2 ? C.white : tint }, line: { color: C.rule } });
        text(s, t, x + 0.1, y + 0.03, 3.8, 0.62, { fontSize: 8.5, color: C.text });
      });
    });
  });

  text(s, [
    { text: "Count the red column: it is the same length as the green one in all three. ",
      options: { bold: true, color: C.ink } },
    { text: `${TRUST.acceptance_rate.of} complete six-stage runs and the trusted path held — ` +
      "every one of them a single lineage, on a system built for width." },
  ], M, 6.98, 12.33, 0.34, { fontSize: 11.5 });
  s.addNotes(
`[1:30] I will not compress this slide, because an audience that catches you overclaiming stops believing everything else. Three columns, three green rows and three red rows each, and the equal lengths are the argument.

Functionality: a real six-stage campaign end to end, the whole engine, four control models over one executor, and adding a tool has never touched the composer. Against that — replicas greater than one has never run; no measurement has superseded a prediction, which is exactly the capability a composed graph has and a written-down one does not; and six of the eight compute patterns have no member, including the one reserved for running their pipeline as one of ours.

Performance: the trusted path promoted after the second run and held three cycles with no safety net; the scrutiny is measured and free; both ends of the Dragon lifecycle bounded against real lost allocations. Against that — no serial baseline; one GPU of four ever works; and no node has reached a plain pass, which wants more draws rather than more code.

Usability: one YAML and one command, the local tier with no allocation, runtime-discovered toolkits, a reasoner in another process. Against that — no resume, no serve or reason command so the headless model lies about which model it is, and the site files are read by nothing.

Sixteen complete runs, the trusted path held, and every one of them one lineage on a system built for width.`);
}

// ================================================================ 23. Asks
{
  const s = pres.addSlide(); s.background = { color: C.ink };
  text(s, "DISCUSSION", M, 0.45, 6, 0.32,
    { fontSize: 13, bold: true, color: "8FB8C9", charSpacing: 3 });
  text(s, "Seven things I would like this room's opinion on", M, 0.78, 12.33, 0.62,
    { fontFace: HF, fontSize: 27, bold: true, color: C.white });
  text(s, "Grouped by what each one costs, not by who owns it — the numbering is the one the " +
    "companion files use.", M, 1.42, 12.33, 0.28, { fontSize: 11, color: "7E8F9C", italic: true });

  // Two groups: things that produce a wrong answer or burn an allocation, and things that are
  // paid by whoever picks the stack up next. Each tagged with the dimension it damages.
  const groups = [
    ["Costs a wrong answer, or real allocation time", [
      ["1", "rhapsody's monitor loop drops a whole sweep", "performance", C.radical,
       "A worker exception that cannot be unpickled takes out every completion in that sweep, " +
         "so a failing run reaches no terminal state. batch_task.get() is guarded; the " +
         "follow-up get_stdout(block=False) re-reads the same entry and catches only OSError. " +
         "Should it catch Exception and fail the ONE task?"],
      ["2", "Why does Dragon's Batch() stall?", "performance", C.radical,
       "Bounded now, not diagnosed. Job 22318678 produced only infra-connect lines for two " +
         "hours. Best guess: GPU-affinity worker rendezvous, or OFI negotiation under " +
         "single-node mode. We fail fast enough to iterate — what should we instrument?"],
      ["3", "Can a running task's GPU ever be reclaimed?", "performance", C.radical,
       "Future.cancel() returns False once started and asyncflow discards the answer, so we " +
         "cannot even learn which happened. Is cooperative cancellation inside the task the " +
         "only route, or is there a backend-level kill we should be using?"],
      ["7", "Is per-GPU packing reachable for us?", "performance", C.radical,
       `Your own runs take GPU utilisation from ${pct(BL.packing.k1.gpu[1])} to ` +
         `${pct(BL.packing.k8.gpu)} by putting 8 pipelines on a GPU. We are at ` +
         `≤${pct(A.allocation.gpu_share_max[1])} with three idle. Is that expressible in a ` +
         "rhapsody resource shape, or does it need Dragon placement we do not control?"],
    ]],
    ["Costs whoever picks this stack up next", [
      ["4", "Nothing looks tasks up by workflow_id", "usability", C.radical,
       "So \"which tasks belong to run R\" is answered by our own handle, which cancellation " +
         "and draining both need. Is a lookup API wanted upstream, or is the tag meant to " +
         "stay a label?"],
      ["5", "Does breadth belong in a pattern's identity?", "functionality", C.compose,
       "Slide 18. Parameters are deliberately excluded from the signature; replica count is " +
         "not. Is trust earned at one lineage evidence about four, when the cap it would lift " +
         "exists to bound blast radius?"],
      ["6", "What is the cheapest real structural gate?", "functionality", C.tool,
       "Every real gate we have is a threshold on a number the tool reports about itself. " +
         "RFD3 gives us ligand_clashes in a sidecar we already open; you gate on it and we do " +
         "not. For Rosetta you gate interaction_energy, which we never compute. Where would " +
         "you start?"],
    ]],
  ];

  groups.forEach(([head, items], g) => {
    const x = M + g * 6.33;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.78, w: 6.0, h: 0.3,
      fill: { color: "243240" }, line: { color: "3B5062" } });
    text(s, head.toUpperCase(), x + 0.14, 1.78, 5.72, 0.3,
      { fontSize: 9.5, bold: true, color: "B8C6D1", valign: "middle", charSpacing: 1 });
    items.forEach(([n, h, dim, col, b], i) => {
      const y = 2.2 + i * 1.19;
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: 6.0, h: 1.09,
        fill: { color: "1E2C36" }, line: { color: "2E414F" } });
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h: 1.09,
        fill: { color: col }, line: { color: col } });
      text(s, n, x + 0.16, y + 0.05, 0.3, 0.3,
        { fontFace: HF, fontSize: 14, bold: true, color: col });
      text(s, h, x + 0.5, y + 0.06, 4.4, 0.28,
        { fontSize: 11.5, bold: true, color: C.white });
      text(s, dim, x + 4.95, y + 0.07, 0.95, 0.24,
        { fontSize: 8, color: col, align: "right", italic: true });
      text(s, b, x + 0.5, y + 0.36, 5.38, 0.68, { fontSize: 8.5, color: "B8C6D1" });
    });
  });

  text(s, "Every claim behind these is reproducible from this checkout, and every file:line on " +
    "these slides is greppable from your laptop while I talk — including the five that point " +
    "into your code rather than mine.",
    M, 6.9, 12.33, 0.4, { fontSize: 10.5, color: "7E8F9C", italic: true });
  s.addNotes(
`[1:35] I would rather end on questions than a summary, and they are grouped by what each one costs rather than by who owns it.

Left column, things that produce a wrong answer or burn an allocation. One: a worker exception that cannot be unpickled takes out a whole monitor sweep rather than one task, so a failing run reaches no terminal state and sits in flight until the wall clock. Our half is fixed; the handler around get_stdout catches only OSError, and I think it wants to catch Exception and fail the single task.

Two and three are shorter. Batch stalled for two hours and we still do not know why; it is bounded now, so we fail in minutes instead of losing an allocation — what should we instrument? And can a running task's GPU ever be reclaimed at all?

Seven is the new one, and it comes out of your numbers. You take GPU utilisation from twelve percent to seventy by packing eight pipelines onto a GPU; we are at seventeen with three idle. Is that expressible in a rhapsody resource shape, or does it need Dragon placement we do not control? It is the largest performance number on our table and I do not know whether it is reachable from where we sit.

Right column, things paid by whoever picks this stack up next. Workflow_id tags every task but nothing looks tasks up by it. Does breadth belong in a pattern's identity? And for the domain people: every real gate we have is a threshold on a number the tool reports about itself, while you gate on clash counts and an interaction energy we never compute. If you were adding one structural gate, where would you start?`);
}

// ================================================================ B1. Backup: one experiment, typed
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Backup — one experiment, and the type at every hop", "Backup · data flow");

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
  // The mock run is mined live, so its story is too: whether the pattern promoted depends on
  // how many clean runs it took to hit the front target, which a reseeded mock can change.
  const clean = adm.length - rej.length;
  const W = n => ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten"][n] ?? String(n);
  const trustLine = MOCK.promoted.length
    ? `the pattern was provisional until the third clean run promoted it ` +
      `(${MOCK.promoted.length} promotion, in trust_events)`
    : `the pattern stayed provisional: the front target was met after ${W(clean)} clean ` +
      `run${clean === 1 ? "" : "s"}, before the third that would promote it`;
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
      `${MOCK.nodes[0].qc} — ${trustLine}.`,
    `Front of ${MOCK.front.length}; the campaign stopped on "${MOCK.stop}" rather than on budget.`,
  ], { fill: C.panel, fs: 10.5 });

  footer(s, "The whole slide is one laptop run against the mock toolkit: real manager, real " +
    "policies, real composer and validator, stubbed science.");
  s.addNotes(
`[1:00] One experiment, left to right, naming the type at each hop — the types are the contract between layers.

The executor builds an observation. The policy returns a decision carrying an experiment intent: tool ids, parameters, a replica count. It is abstract, there is no DAG in it. The composer turns it into a typed graph, which is plain data. Dispatch registers that graph and hands back a handle without awaiting. What comes back is a run outcome, serializable and core-typed, so a reasoner in another process can hold it.

Underneath is an actual run on this laptop. The first row was refused by the interlock — a provisional pattern is capped at ten percent of available budget and three lineages did not fit. The policy shrank to two and resubmitted. That is the retry doing its job: a refusal costs an attempt, not the experiment.

Every design node is marked suspect, because the shape is provisional while it runs. Promotion takes three clean runs, and the card on the right says whether this one got there before the front target stopped it.`);
}

// ================================================================ B2. Backup: compute patterns
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Backup — eight compute patterns, and what each one forbids", "Backup · tools");

  const PAT = R.patterns, PC = PAT.counts;
  const n = p => (PC[p] ? String(PC[p]) : "—");
  const UNUSED = `${PAT.unused[0]}–${PAT.unused[PAT.unused.length - 1]}`;

  label(s, "core/types.py:12 — organised by scheduling implication, never by science",
    M, 1.46, 8.33, { mono: true, align: "left", fontSize: 9.5 });
  tbl(s, ["", "What it is", "What it forces on the orchestrator", "Tools here"], [
    ["P1", "GPU-node-local, in-job", "must declare a GPU — a load-time error if not", n("P1")],
    ["P2", "CPU-parallel fan-out, in-job", "cores, not ranks; no topology to reserve", n("P2")],
    ["P3", "MPI multi-node, in-job", "a reserved rank layout; no resize mid-run", n("P3")],
    ["P4", "external HPC job", "durable job state — it outlives the agent", n("P4")],
    ["P5", "network service over HTTPS", "no local cost; quota, latency and outage", n("P5")],
    ["P6", "in-process library call", "never a scheduled node — inlined, or refused", n("P6")],
    ["P7", "composite pipeline — an IMPRESS run", "parameterize and observe; stages not steered",
     n("P7")],
    ["P8", "external experiment (lab)", "completes out of band, days later", n("P8")],
  ], M, 1.74, [0.75, 2.4, 3.5, 1.68],
    { mono: [0, 3], center: [0, 3], fs: 10, mfs: 10, rowH: 0.31, hfs: 10,
      cell: (i, j) => (j !== 3 ? {}
        : PC[PAT.declared[i]] ? { color: C.good, bold: true } : { color: C.fail }) });

  code(s, [
    'class Pattern(str, Enum):      # 8 members, and only 2 rules derived from them',
    '    def is_inline(self):   return self is Pattern.P6',
    '    def is_external(self): return self in (Pattern.P4, Pattern.P8)',
    '',
    'stages = [t for t in intent.stages            # composer.py - P6 never a node',
    '          if self.reg.get(t).pattern is not Pattern.P6]',
    'if spec.pattern is Pattern.P6:                # validate.py - gate 4 refuses one',
    '    return ValidationFailure(gate="resource", node=tid, reason=...)',
    'if self.pattern is Pattern.P1 and self.resources.gpus == 0:  # spec.py - at LOAD',
    '    raise ValueError(f"{self.id}: P1 declared but resources.gpus == 0")',
  ], M, 4.78, 8.33, 2.05,
    { anchor: "composer.py:45 · validate.py:106 · spec.py:107  ·  EDITED — @property elided",
      fs: 10 });

  const rx = M + 8.63, rwd = W - M - rx;
  const SITES = PAT.consulted_in.reduce((a, c) => a + c.lines.length, 0);
  card(s, rx, 1.46, rwd, 1.72, "Organised by what it forces", [
    "Not by what the tool computes. A tool is P4 for where it must be submitted, not " +
      "because it runs MD.",
    "Which is why one generic factory serves every node: the differences that would have " +
      "needed branching were settled before dispatch.",
  ], { fill: C.panel, fs: 9.5, hfs: 12 });
  card(s, rx, 3.28, rwd, 1.80, "Two of the eight are in use", [
    `All ${CODE.n_tools} registered tools are P1 (${PC.P1}) or P2 (${PC.P2}). ` +
      `${UNUSED} have no member.`,
    "So the P6-inline path, the P4 ledger and the P5 service path are contracts the " +
      "suite asserts and no tool has taken.",
    `P7 is the one reserved for a reference IMPRESS pipeline run as a single tool of ours. It ` +
      "has no member either — so \"IMPRESS becomes one of our tools\" is a contract, not a result.",
  ], { fill: C.failTint, hc: C.fail, fs: 9.5, hfs: 12 });
  card(s, rx, 5.20, rwd, 1.80, "Dispatch does not branch on it", [
    'The docstring says "dispatch depends on these." It does not, yet: ' +
      "exec/dispatch.py builds one closure per node, and exec/resources.py translates " +
      "ResourceShape.",
    `So every consequence is enforced at load time or by a gate — ${SITES} sites in ` +
      `${PAT.consulted_in.length} files, none under exec/ or runtime/.`,
  ], { fill: C.failTint, hc: C.fail, fs: 9.5, hfs: 12 });

  footer(s, "Two senses of one word: a compute pattern is per tool, and is this slide; a " +
    "composition pattern is a graph's shape (compose/graph.py:51) — that is what the trust " +
    "ledger scores.");
  s.addNotes(
`[1:15] One field in that spec decides how the work reaches the middleware, and it is the compute pattern.

Eight of them, and what matters is what they are organised by: not what the tool computes, but what the orchestrator has to do differently. A tool is P4 because of where it must be submitted, not because it runs MD. P6 is the sharpest — an in-process call of thirty milliseconds. Schedule that and you pay serialization and filesystem cost orders of magnitude above the work. So the composer drops P6 stages before they ever become nodes, and gate four refuses one that got through anyway. A scheduled P6 is a composer bug, and it is caught as one.

Two honest things. The last column is the census: all eleven tools are P1 or P2. P3 through P8 have no member, so the inline path, the P4 ledger and the P5 service path are contracts the suite asserts and nothing has ever taken.

P7 deserves singling out in this room, because it is the pattern reserved for running one of their pipelines as a single tool of ours — parameterize it, observe it, never steer inside it. It has no member. So if you have heard me say IMPRESS becomes one of our tools, that is a contract and a taxonomy entry, not something that has happened.

And the enum's own docstring says dispatch depends on these. It does not, yet — every consequence is enforced at load time or at a gate, which is composition time, not dispatch. That is the cheaper place for it, but the docstring is ahead of the code.`);
}

// ================================================================ B3. Backup: control models
{
  const s = pres.addSlide(); s.background = { color: C.white };
  title(s, "Backup — four control models over one executor", "Backup · control models");

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

DECK.save(path.join(__dirname, "impress-a-codewalk.pptx"));
