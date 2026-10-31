# Encode the four reasoner models, and start harmonizing the two implementations

**Status: approved 2026-10-29, step 1 partly executed.** `policy/registry.py`, the CLI rewiring,
`impress-a models`, the `--model replay` fix and `tests/test_reasoner_registry.py` are committed as
`fa0266f` on branch `agent/reasoner-models` (186 tests pass). Everything else below is outstanding;
section 1's reference document is the next piece.

Two amendments found while executing, both of which belong to the separate CI/documentation
consolidation plan rather than to this one:

- The verification command below, `ruff check src tests`, **mutates the working tree**, because
  IMPRESS's root `pyproject.toml` sets `fix = true` and `agent/pyproject.toml` declares no
  `[tool.ruff]` of its own. It applied 36 fixes across 20 files on its first run here, all of which
  had to be reverted.
- The lint ceiling of 41 stated in `backlog.md` does not reproduce: 449 findings under the config
  that actually resolves, 9 under ruff's defaults. Nothing in CI lints `agent/` at all, which is why
  neither was noticed.

Where section 1's `docs/impress-a/reference/control-models.md` is *published* from will change once that
consolidation lands. What it should say does not.

## Branch

**This work takes place on a new branch cut from the current branch.** Branch
`agent/reasoner-models`, based on `examples/agentic-small-molecule-binding` at its current HEAD
(`f323fa2`). That base is required rather than incidental: `f323fa2` is the commit that added the
example's control-model-D route, and PR #73's merge (`6553bf0`/`d51c292`) is what first put `agent/` and
the example in one tree — so this is the only branch where both implementations are present to
harmonize. Nothing here lands on `main` directly, and the follow-on hardware runs below are submitted
from this branch so the git sha in each job's `manifest.json` identifies it.

## Context

`agent/` (IMPRESS-A) rests on one swappable abstraction: **only the reasoner differs between control
models**, everything below it is shared. Four are named consistently across seventeen documents —
A (explicit agentic graph, LLM calls bound to nodes), B (LLM oracle), C (headless, external agent
drives), D (explicit rules). D doubles as the scientific control, because it can be made equivalent to
simple adaptivity and is therefore the internal benchmark against the earlier non-agentic work.

Future development will encode these abstractions more deeply. Three problems block it.

**`agent/`'s documentation describes all four models as complete, and two are not.** Model A's LLM slot
is a dead constructor argument and model B's live client is constructed nowhere, yet `README.md`,
`docs/impress-a/reference/frontends.md` and `docs/impress-a/limitations.md` describe both as working LLM reasoners, and
`docs/impress-a/limitations.md:50` asserts a non-reproducibility that is false today.

**The abstraction has no home in either tier.** There is no `docs/impress-a/reference/control-models.md`; the only
real treatment is `planning/phase1-partB-architecture/02-control-models.md`, which `CLAUDE.md:53`
declares process history and "superseded in places". In code, `policy/__init__.py` is 0 bytes and the
letter→class map is a dict in `cli/__init__.py`.

**`examples/agentic_small_molecule_binding/` reimplements `agent/` rather than demonstrating it.** It
imports no part of `impress_a`. Its model-D arm is a second *execution route* for model D, and the
intent is that this pattern live in shared infrastructure so A/B/C/D all reach one workflow-deployment
machinery through a call-time `--model` switch.

**An LLM controller has been tested in this project — in the other implementation.** This is the
correction that reshapes the plan. Roughly eight Delta jobs across four model families drove the
example's harness, with a full written analysis in `impress-agentic-performance/report.md` and run
data in `impress_exports/` - two working directories kept beside this checkout, not in it. So
porting a live client into `impress_a` is
not a leap into the unknown; it is moving a path that already has hardware evidence. The evidence does
**not** extend to `impress_a` itself, and the section below draws that line precisely.

---

## Two documentation trees, and which one this plan writes to

`agent/` is a standalone app with its own `docs/`, and the repository root has a `docs/` of its own.
They share a name and nothing else. Neither tree says what the other is for, which is why every bare
`docs/…` path below is qualified from here on.

|  | root `docs/` | `agent/docs/` |
|---|---|---|
| Subject | the `impress` framework and its examples | the `impress_a` app |
| Published | **yes** — mkdocs/Material, `site_name: IMPRESS`, `site_url: impress-framework.readthedocs.io`, `edit_uri: edit/main/docs/` | **no** — read in-repo only; `agent/` appears nowhere in `mkdocs.yml` |
| What `reference/` means | **generated API docs** — mkdocstrings over `paths: [src]`: `ImpressManager`, `ImpressBasePipeline`, `PipelineSetup`, `ImpressLogger` | **hand-written prose reference** — architecture, frontends, compute-patterns, authoring-tools, middleware-integration |
| `decisions/` | none | 13 numbered immutable ADRs |
| `limitations.md`, `roadmap/` | none | both |
| Nav | Home · Getting Started · Concepts · Examples · API Reference | no nav; `agent/README.md`'s table is the index |
| Edit boundary | `agent/CLAUDE.md` forbids agent-side work from changing it | IMPRESS-A's own |

So the same word means a different genre in each tree: root `docs/impress-a/reference/` is machine-generated from
docstrings, `docs/impress-a/reference/` is prose. Likewise root `docs/concepts/architecture.md` is the
framework's architecture and `docs/impress-a/reference/architecture.md` is the app's — different subjects,
same filename. **Everything this plan writes goes in `agent/docs/`**, except where it says otherwise.

**G14 — the published site documents the agentic example and not the app whose taxonomy it borrows.**
The root site contains no occurrence of "IMPRESS-A", `impress_a`, `agent/`, "control model",
"reasoner", "oracle" or "headless" — verified by grep over all of root `docs/`. Yet
`docs/examples/agentic-small-molecule-binding.md` is in the published nav (`mkdocs.yml:48`), and at
`:62` it says "The `rules-d` profile is the comparison's control" — publishing the profile name whose
`-d` refers to a four-model taxonomy the site never defines. The letters themselves appear only in the
example's unpublished `README.md`/`CLAUDE.md` and in `rules_client.py:1`, so the site is at least not
self-contradictory; it is just missing the referent for one suffix.

Two consequences, and both respect the boundary rule the user chose (keep it; example-side work only):

- **In scope here, example-side:** one clause in `docs/examples/agentic-small-molecule-binding.md:62`
  or the example's README giving `rules-d`'s `-d` its referent.
- **Deferred to step 5's plan:** whether IMPRESS-A joins the published site. Adding `agent/docs/` to
  the root `mkdocs.yml` nav would change IMPRESS's root packaging, which `agent/CLAUDE.md` forbids from
  agent-side work — so it is a decision for the harmonization record (0016), not something to do in
  passing. It becomes unavoidable at step 5, when the example starts driving `impress_a` and the
  published example page has to explain an engine the site does not document.

---

## What is tested, and in which implementation

### The distinction this section rests on

**LLM control was tested. The reasoner-model abstraction was not.** Both halves matter and they are
easy to collapse into each other.

In the Sonnet, Beam and Qwen arms an LLM genuinely was the controller: it decided what ran next, turn by
turn, on real GPUs, producing real designs. What it decided over was **a flat surface of 8 OpenAI tool
schemas backed by the reference pipeline's registered tasks** — multi-turn, with a message history and
compaction, bounded by `max_llm_turns`/`max_tasks` in the example's own loop, QC as `pass` booleans from
the reference's `analysis_*` steps, provenance as `llm_transcript.jsonl`.

**Not one line of `impress_a` executed in any of those jobs.** So none of what makes a control model a
control model in the specified sense was exercised: the `decide`/`interpret`/`on_rejected` contract, the
`Decision` union, abstract `ExperimentIntent` composed into a typed DAG, the five admission gates and
the dry-run, `on_rejected` and bounded retry (nothing refuses an experiment there, so that path has
never run under LLM control at all), the self-promoting trust interlock, the Pareto tree and
backtracking, typed `ArtifactRef`s, the executor as sole writer and termination authority, the durable
ledger, integrity-vs-acceptance QC.

The arms are therefore evidence about **the decision-maker** (does a model direct the search better than
a hand-written router) and about **the LLM transport and serving layer** (can a model be reached, hosted
in-allocation, kept in context, degraded safely). They are not evidence about **the reasoner contract**.

|  | LLM decision-maker | rules decision-maker |
|---|---|---|
| **reference task machinery** (example) | **tested** — Sonnet 23112484/23114775, Beam 23225651/23231797, Qwen 23201195/23207314/23219406 | **untested** — `rules-d`, written today; "licenses nothing about the harness yet" |
| **`impress_a` engine** (gates, interlock, Pareto, ledger) | **untested** — no run, no client, no artifact in any export | **tested** — 22692304 (6/6 stages), 22726105 + 22728140 (promotion, three trusted cycles) |

The tested cells are the diagonal. Both empty cells are what the harmonization route exists to fill:
`rules-d` on the reference machinery is the example's own open item, and LLM control of the `impress_a`
engine is step 1 of this plan. This is also the precise sense in which step 1 is low-risk in one
dimension and not another — **the transport has hardware evidence; the contract it would drive has
none.**

### Provenance of the finding

Established from `impress_exports/` (five archives, listed not extracted, plus
`agentic_decision_arms_20261026b.tar.gz:_export/README.txt` and `CORRECTIONS_20261026.txt`),
`impress-agentic-performance/report.md`, and `git log` on the example.

**Decisive timeline fact:** every hardware run predates both of 2026-10-29's commits — `d5376d9`
(retire the Qwen arms, make local serving model-agnostic) and `f323fa2` (control model D). The LLM-API
rework the user recalls is actually **two** reworks on two dates touching two layers: `484bd06`
(2026-10-26) changed the *client* (`llm.py`, `_completion_from_response` carrying `reasoning_content`),
and `d5376d9` (2026-10-29) changed the *serving/profile* layer (`models.yaml` 147 lines,
`vllm_service.py`, `run_agentic_smb.py`) alongside the Qwen removal. `llm.py` was untouched by the Qwen
commit.

### Tested, and the code path survives essentially unchanged

| Arm | Jobs | Status of the code |
|---|---|---|
| `claude-sonnet` hosted API | 23112484 (1 h), **23114775 (4 h, 192 designs — the headline)** | profile survives the purge; `llm.py` has changed only additively since (`reasoning_content` carried only when the provider sends one; a `bind_pipeline` hook) |
| `beam` hosted reasoning model | 23225651 (1 h), 23231797 (self-stopped at 37 min of a 4 h allocation) | both ran **at or after** `484bd06`, so they are tests of the current `_completion_from_response`; profile survives; needs `REFLECTION_API_KEY` |
| `scripted` | 23110801 | survives, but its own CLAUDE.md records it is **not** a faithful `run_nonadaptive` replay (6-stage cycle against the reference's 7) — a plumbing fixture, not a baseline |
| reference pipeline | 23114772, and 22701168 rescored from archive | unaffected by any of this |

### Tested on code that only partially survives

- **The in-allocation vLLM serving path.** Proven on hardware four times: 23180011 (node partition
  verified with bracketed `pgrep` — 1 vLLM process and 0 tool processes on the model node), 23201195
  (7B, ready in 160 s), 23207314 (72B tensor-parallel across four A40s; the cleanest gate behaviour
  recorded here — FastRelax 76 %, 33/33 folds), 23219406 (block-FP8 falls back cleanly on SM 8.6).
  The infrastructure survived and was deliberately generalized — but `d5376d9` made `tool_parser` a
  required argument of `serve_command()` with no `hermes` default, the runner now refuses a
  `dragon_vllm` profile that names none, every profile those runs used is deleted, and ~405 GB of
  weights are gone. **So: the path is tested; no profile that currently exists has ever run on it.**
- **`_completion_from_response`.** The pre-fix version is gone. 23219379 survives only as the evidence
  for why — all four pipelines fell back to the scripted route on turn two, 144 degraded turns, and the
  transcripts looked healthy because that is what the scripted route looks like. Its 35 passing folds
  would otherwise read as a Beam result.
- **`tools.py`'s `guide_model` "None"-string guard** (`47c874d`) — added because 23229812 hit it 10
  times; the run that exposed it belongs to a retired arm that cannot be re-measured.

### No evidence of having been tested in any implementation

- **`impress_a` with any LLM.** No archive contains an `impress_a` run artifact at all — zero hits for
  `campaign.log`, `provenance`, `ledger` or `_trust` across all five archives, and
  `impress-agentic-performance/` contains **no reference to `impress_a` or to models A/B/C/D**. Every
  documented `impress_a` Delta job is `--model D`. `FourNodePolicy.reasoner` is never read;
  `LangChainOracle` is constructed nowhere. The original claim therefore stands for `impress_a`, and is
  stronger than "untested": there is no run data of any kind.
- **`impress_a` model C from the CLI** — fails open to `ThresholdPolicy` (backlog C6).
- **The example's `rules_client.py` / `rules-d` profile** — written today (`f323fa2`); its own CLAUDE.md
  says "UNMEASURED on hardware — no job has run this arm, so it licenses nothing about the harness yet".
  This is the control arm the whole comparison depends on.
- **The three replacement open-weight profiles** (`local-smoke`, `local-llama-8b`,
  `local-open-weights`) — chat templates and parser registration verified by *reading*
  `tokenizer_config.json`, never by running.
- **`claude-opus`** — profile present; declines this workload (`finish_reason=content_filter`, 0
  completion tokens), with and without the system prompt.
- **`ToolSpec.agent: "llm"`** — read by no code in either implementation.

### Two figures this plan must not restate carelessly

`CORRECTIONS_20261026.txt` and the decision-arms README settle the baseline: 22701168 rescored to 0.159
GPU-h per passing fold against its recorded 0.160, so the 4-hour reference arm 23114772 (0.302) really
did come in ~2× worse than the same workflow's own record. **Quote the agent's advantage as 1.9×
against the healthy baseline, not the 3.3× measured against 23114772.** Open and untested: 22701168 ran
at commit `e2aa00d` and PRs #71/#72/#76 landed before 23114772 — a candidate regression in the
*reference* pipeline that nobody has rerun to check.

---

## Findings — where each element lives, and whether it is documented

Specification of record: `planning/phase1-partB-architecture/02-control-models.md` (§2 A, §3 B, §4 C,
§5 D, §6 comparison matrix). Shipping reference: `docs/impress-a/reference/frontends.md:21-33`, thirteen lines of
table. Letter→class map: `cli/__init__.py:31-32`.

| Element | Code | Documented | State |
|---|---|---|---|
| Contract `decide`/`interpret`/`on_rejected` | `policy/base.py:18-57` | frontends.md:37-50 | complete |
| `conduct(session)`, the second reasoner shape | `policy/driver.py:35`, `core/session.py:55-93` | README:52-58, architecture.md:20-28 — **absent from frontends.md** | surface complete, **no shipped implementation** |
| `Decision` union, `ExperimentIntent` | `core/decision.py:21-56` | frontends.md:45 | complete |
| **Model A** `FourNodePolicy` | `policy/agentic.py:42-127` | planning 02 §2 only; frontends.md:28 is one row | **partial (G1)** |
| **Model B** `OraclePolicy` | `policy/oracle.py:80-162` | planning 02 §3 only | **partial (G2)** |
| **Model C** `ExternalPolicy` | `policy/external.py:18-82` | best documented: decision 0002, planning 06, frontends.md:89-126 | complete; unreachable from CLI (backlog C6) |
| **Model D** `ThresholdPolicy` | `policy/explicit.py:21-107` | planning 02 §5; **named in no `docs/` file** | complete |
| D-replay `ReplayPolicy` | `policy/explicit.py:110-133` | frontends.md:31 as "replay" | **CLI-broken (G8)** |
| `null`, a fifth shipped decider | `policy/wrappers.py:75-87` | frontends.md:77, CLAUDE.md:25 | complete; never reconciled with "four control models" |
| Wrappers (guard, logging) | `policy/wrappers.py:16-72` | frontends.md:69-81 | complete; `LoggingPolicy` unused and untested |
| Letter→class registry | `cli/__init__.py:31-32, 93-115` | nowhere | CLI-only; `policy/__init__.py` **empty** (G5) |
| LLM task agents (`ToolSpec.agent`) | `tools/spec.py:96` | decision 0006, architecture.md:145, roadmap:90 | **read by no code (G7)** |
| Reasoner contextualization | `tools/registry.py:85` `toolkit_skills()` | specified in planning 04:112-124 and 06:65 | **zero callers (G7)** |

### The gaps, in order of how much they mislead

**G1 — Model A has no LLM, and the slot for one is dead.** Planning 02:59-61 specifies "each node is a
bounded LLM call with a declared input and output schema", ~3 calls/cycle, parse-retry with corrective
feedback, escalation to a degraded policy. In code `_hypothesize` (`agentic.py:57`) and `_parameterize`
(`:75`) are deterministic threshold cascades; `self.reasoner = reasoner  # optional LLM` (`:51`) is
**stored and never read**; node 4 (`interpret`, `:111`) formats a string; there is no schema, no retry,
no `fallback` argument (B and C both have one). `_build()` registers two nodes while the module
docstring describes four. Net: `--model A` is a LangGraph-shaped rule cascade, behaviourally a sibling
of D. Its only test asserts termination (`tests/test_campaign.py:53`), never a node.

**G2 — Model B's live path is never constructed.** `OraclePolicy.__init__` defaults to `RehearsalOracle`
(`oracle.py:85`) and `cli.build_policy` never passes a model (`cli/__init__.py:108`), so `--model B`
runs the deterministic stand-in. `LangChainOracle` (`oracle.py:65-77`) is constructed nowhere,
brace-slices JSON despite a docstring claiming "structured output", and has none of what planning 02
§3/§7 require: pinned dated model id, sampling params, `Retry-After` backoff, 429-vs-529.
`pyproject.toml:27` carries an `oracle = ["litellm"]` extra nothing imports. No `docs/` file names an
LLM provider, client library, prompt-provenance record or retry policy. **The working client exists one
directory over, with hardware evidence** — see the evidence section.

**G3 — `docs/impress-a/limitations.md:50` is false today.** "Model A / B policies — **No** — frontier APIs offer no
usable seed" — both are bit-exact in `impress_a`, because neither reaches an API. That row becomes true
when G2 closes. Separately, `limitations.md`'s "Not yet implemented" section does not mention B's unmet
provenance requirements.

**G4 — No policy can vary a real tool's parameters.** A and D emit
`params={"mock_generate": {...}, "mock_design": {...}}` (`agentic.py:84`, `explicit.py:69`), and B's
rehearsal the same (`oracle.py:60`), even when `stages` is the real six-stage chain. `composer.py:63`
reads `intent.params.get(tool_id, {})` per composed stage, so those keys are silently dropped. On a real
campaign a policy's only levers are `replicas`, `parent_node`, `Backtrack`, `Stop` — and backlog A9
records that even `replicas` is capped downstream where the policy cannot see it. This is the gap that
most undercuts model D as the benchmark against the reference's `adaptive_decision()`, which varies the
route and the retry. Documented nowhere.

**G5 — The abstraction has no home in the package.** `policy/__init__.py` is 0 bytes; the letters live in
a CLI dict and are re-derived by `slides/api/run_model.py:134`; per-model configuration (A's reasoner,
B's model, C's timeout, each fallback) is hardcoded in `build_policy` (`cli/__init__.py:93-115`).

**G6 — No reference-tier document for the taxonomy.** `README.md:200` bills `architecture.md` as the
first doc a reader opens; it mentions control models twice (`:17`, `:22`) without naming one and does not
link `frontends.md`. Model D's representative implementations (bandit, Bayesian optimization,
evolutionary — planning 02:143-148) have no shipping counterpart, so a reader cannot tell they are
aspirational; `ThresholdPolicy` is named in no `docs/` file at all.

**G7 — Declared-but-inert seams.** `ToolSpec.agent: Literal["deterministic","llm"]` (`tools/spec.py:96`)
is read by no code while decision 0006, `architecture.md:145` and `roadmap/academy-for-task-agents.md:90`
present it as working. `Registry.toolkit_skills()` (`tools/registry.py:85`) has **zero callers**,
although planning 04:112-124 specifies skill docs are "supplied to the policy at campaign start … the
mechanism by which the toolkit teaches the agent to behave sensibly before its first decision" and
planning 06:65 gives the observation field. Today `obs.available_tools` is bare ids, so B's prompt
(`oracle.py:102`) lists names with no parameters, costs or pitfalls. The fifth specified skill section,
**Composition guidance** (planning 04:122), was dropped from `authoring-tools.md:180`'s four required
sections, and it is the one a reasoner most needs. `ExperimentIntent.toolkit_hint` is read nowhere.

**G8 — Two defects found while reading.** `--model replay` raises `TypeError` before the campaign starts:
`ReplayPolicy.__init__` requires `records` positionally (`explicit.py:115`) and `build_policy`'s
fall-through calls `cls()` (`cli/__init__.py:110-111`). And `ExternalPolicy.decide_after_rejection`
(`external.py:82`) rebuilds a blank `CampaignObservation(campaign_id="", cycle=0, goal="")`, so a
directive supplied after a rejection composes with `goal=""`.

**G9 — Vocabulary drift on the mode-vs-model axis.** The letters are consistent in all seventeen
enumerations. But `planning/phase1-partA-toolkit/briefs/llm-oracle.md:3,13,120`, `briefs/impress.md:134`
and `summary-report.md:128,346` use the letters as *modes* ("control **mode** B") — the ambiguity
decision 0002 was written to kill; `planning/phase1-partC-structure/01-repository-layout.md:12,47` says
`policy/` holds "models A, B, D", omitting C; and the shipping docs dropped mode numbering entirely
while decision 0002's own title is "Control model C *is* control mode 2".

**G10 — The LLM-integration decisions were never promoted out of planning.**
`planning/phase1-partB-architecture/08-open-questions.md:32-35` lists **I1** LangGraph vs Academy for A's
loop (decided in practice, recorded nowhere), **I2** structured-output mechanism, **I3** LiteLLM vs
per-provider, **I4** which tools get LLM task agents. None appears in `plans/backlog.md` — **and I2/I3
have since been answered empirically by the example**, which is exactly the kind of evidence that should
close a planning question rather than leaving it open.

**G11 — Stale references.** Backlog C6 cites `cli/__init__.py:78-80`; the code is at `:102-104`.

**G12 — Model B's specified shape and the informal shape disagree.** Planning 02 §3/§6 specify B as
**one structured call per cycle** over rich state, which is what `OraclePolicy` implements inside
`SequentialPolicyDriver`'s loop. The informal description — "tool calling directly by an LLM, no
bounding loop" — describes free tool-calling against `CampaignSession`, i.e. the `conduct` shape, and
that is what the example built. **Ruling: planning 02 is authoritative; B is one structured call per
cycle.** Free tool-calling over `CampaignSession` is a real, unimplemented shape, recorded as a backlog
item and a documented distinction, not as B.

**G13 — `examples/agentic_small_molecule_binding/` reimplements `agent/`.** It imports no part of
`impress_a` (verified; the only `impress_a`-shaped string is its own function name). Overlap table:

| Capability | `agent/` | example |
|---|---|---|
| The agentic loop | `manager.run()` + `executor.pump()` + `SequentialPolicyDriver.conduct()` | `AgenticSMBPipeline.run()`, a hand-rolled `while not done` (`agentic_pipeline.py:210-313`) |
| Budget bounds and termination | `max_cycles`/`max_runs`/`stagnation_limit`/`max_attempts`; **the executor decides termination, not the reasoner** | `max_llm_turns`, `max_tasks`, `empty_turns >= 2`, inline in the loop that also decides |
| LLM client abstraction | `oracle.DecisionModel` + `RehearsalOracle` + `LangChainOracle` | `llm.LLMClient` + `OpenAICompatClient` + `ScriptedClient` + `RulesClient` — one-to-one, and the example's is the tested one |
| Model B / Model D | `OraclePolicy` / `ThresholdPolicy` | `OpenAICompatClient` / `rules_client.RulesClient` |
| Replay / scripted control | `ReplayPolicy`, `NullPolicy` | `ScriptedClient`'s fixed route table |
| Degraded mode | `fallback` + logged `oracle_degraded` transition (`oracle.py:140-148`) | `llm_turn()` except → `ScriptedClient` + `llm_degraded` + a `degraded` event — same design, same rationale, written twice |
| Tool declaration | `spec.yaml` + `TaskAgent` + `Registry`; loading is validating, typed ports, ranges, `cost_model`, `qc_gates` | `TOOL_SCHEMAS` + `HANDLERS`; no type unification, no range validation, no cost model |
| The science chain | `rfd3_design → ligandmpnn_design → packmin → fastrelax → filter_shape → boltz_predict` | `design_backbone → design_sequence → pack_minimize → relax → score_interface → fold_complex` — same six stages, declared twice |
| The observation | `CampaignObservation` + `observe()`, handed to the reasoner | `inspect_ensemble`, a tool the model must choose to call — called once in 137 turns |
| Stop | the `Decision` union's `Stop` | a `finish` tool |
| QC | `core/qc.py` integrity vs acceptance (decision 0013), gates shared by id | `pass` booleans in handlers, inheriting the reference's quirks (`analysis_sequence` hardcodes `pass: True`; the `_ca_rmsd` gate is inert) |
| Provenance | `core/provenance.py` + `exec/ledger.py` durable ledger | `_transcript()` → `llm_transcript.jsonl` |
| Population / ranking | `core/tree.py` + `core/pareto.py`, front + backtracking + measurement-supersedes-prediction | `state['ensemble']`, a list, plus per-stage `pass` |
| Resource placement | `exec/resources.py`; no backend class named outside `exec/backend.py` | `_tool_task_description()` imports `dragon.infrastructure.policy.Policy` directly |

`agent/` capabilities the example gets none of: the five gates and the dry-run; the trust interlock; the
Pareto tree and backtracking; typed `ArtifactRef`s; the durable ledger and `reattach`; the control
plane; bounded backend startup/teardown; integrity-vs-acceptance QC.

Example capabilities `agent/` lacks: a **tested** LLM client with per-model profiles;
`_compact_history()` context compaction, validated under load (prompt plateaued at ~8.5 k tokens over
~365 turns per pipeline, zero degraded); the hardware evidence above; and a model-D control that
**imports** the reference's `adaptive_decision()` rather than restating it.

**The duplication runs both ways.** `tools/rfd3_agents.py:3` says it is "Adapted from
`IMPRESS/examples/small_molecule_binding/scripts/rfd3.sh`'s real, working" invocation, and rebuilds the
apptainer command line in Python rather than calling the script. So this is two codebases each
reimplementing the other's layer.

### Already recorded honestly — extend, do not re-file

Backlog **C5/C6/C7** (model C's entry points, fail-open, reachability); **F1/F2/F4** (docs debt — F2
already names ADR 0005's "fixed at launch", so the selection correction belongs there); **A7/A8/A9**
(stage truncation, objectives without a producer, the invisible replica cap). Model D as scientific
control is in `policy/explicit.py:3-6`, planning 02:151-153 and `limitations.md:54`; **the stronger
claim — that D can be made equivalent to simple adaptivity, making it the benchmark against the earlier
non-agentic works — is written nowhere.**

---

## Harmonizing the two implementations

Goal: the example's model-D execution route becomes one instance of a shared pattern, so A/B/C/D all
reach the same workflow-deployment machinery through a call-time `--model` switch.

### What is shared, and what is doubled

| Layer | `agent/` | reference + example | Shared? |
|---|---|---|---|
| **0 Middleware** | `asyncflow.WorkflowEngine` over rhapsody by name (`exec/backend.py`) | one `WorkflowEngine` over `compute` (Dragon) + `local` (threads) | **yes — the only one** |
| **1 Deployment machinery** | `Registry` → `Composer` → 5 gates + dry-run + interlock → `Dispatcher`; resources via `exec/resources.py` | `register_pipeline_tasks()` + `auto_register_task(**task_description)`; stages talk through `{taskcount}_<stage>/out`; `scripts/*.sh` hold the real invocations | **no — doubled both ways** |
| **2 Decision frontend** | `ControlPolicy` A/B/C/D + `conduct`, switched by `--model` | a single `adaptive_fn` slot the manager awaits and "chooses nothing" about (`setup.py:40-50`, `impress_manager.py:119-152`); the example fills it with `llm_turn`, switched by `--model-profile` | **no — but the reference's slot is already a one-model version of the same seam** |

Constraints on every option: **neither package imports the other** (`agent/README.md:7` states it as a
property), and **the reference's stages pass data by filesystem convention, not typed artifacts** — so a
registry unification cannot simply inherit `agent/`'s gates.

### Why the comparability objection is weaker than it looks

The example's "one rule that matters" is byte-identical `task_description`s, asserted by
`test_agentic_smb.py` check [1]. But byte-identity is a *proxy*, and the thing itself is already
measured: 23110801 ran "13.1 rfd3/pipeline/h — **the reference's own figure**", and the paired 4-hour
arms came in 15.5 vs 16.2, from which the example concludes the LLM round trip costs no measurable
throughput. Replacing the proxy with a measured parity check is the unlock for the later steps.

### Options considered

1. **Share only the switch** — one module holds the reasoner registry, `--model` resolution, the client
   protocol and the profile loader; each side keeps its execution machinery. Cheapest; closes G2 and G5;
   nothing re-argued. Layer 1 stays doubled.
2. **Reference is the substrate; reasoners plug into `adaptive_fn`** — small diff, preserves the
   published comparison, gives the example A/B/C. But reasoners still interface with the reference's
   task machinery, not the toolkit registry — strictly less of the goal.
3. **Reference becomes a P7 tool** — `compute-patterns.md:23` reserves P7 "Composite pipeline" for
   exactly this and it has no member. **Declined on the record:** P7's definition is "internal stages
   are not individually steered", the opposite of what model D needs.
4. **Shell scripts become the shared stage contract** — `scripts/*.sh` become the one declaration of how
   a stage runs; `agent/`'s adapters call them instead of rebuilding their apptainer lines. No import
   crosses, so `README.md:7` holds; one place per stage to fix a binary's contract, which is where four
   of the five hardware defects in `agent/CLAUDE.md` originated. Needs a deliberate line between script
   and adapter (`rfd3` output discovery, `MPNN_SHIM`, `_pdbtools` are real adapter work).
5. **The example becomes a thin driver** — a campaign spec plus `--model`; its loop, tool schemas, QC
   flags, transcript and termination logic deleted in favour of what exists. The stated intent exactly.
   Largest change; spends the example's current argument; cannot be done first, because `impress_a` has
   no live LLM client to move an arm onto.

### Chosen route: staged 1 → 4 → 5

**This plan executes step 1.** Steps 4 and 5 each get their own plan and decision record. Step 1 is the
prerequisite for both: it closes G2/G5, gives `impress_a` the arm it has never had, makes `--model` the
one switch, and deletes nothing.

Recorded decisions:
- **Model B is one structured call per cycle** (planning 02 §3/§6). Free tool-calling over
  `CampaignSession` is a distinct, unimplemented `conduct` shape — backlogged, not B.
- **The live client is a port of the example's tested OpenAI-compatible client**, with profiles in YAML.
  Resolves planning **I2** (structured output: one Decision-schema tool call) and **I3** (not litellm;
  drop the unused extra).
- **`agent/CLAUDE.md`'s boundary rule stands.** All `examples/` edits are scoped as example-side work;
  `impress_a` gains only the shared registry and client.

---

## The change

### 1. `docs/impress-a/reference/control-models.md` — a new reference-tier document

Derive it from `planning/.../02-control-models.md`, corrected against the code. House style: `#` title,
a one-line normative gloss, `##` sections, tables as the primary device, every rule carrying its failure
mode and its evidence.

Contents: the shared contract and both reasoner shapes (`decide` and `conduct` — the latter is in
`README.md` and `architecture.md` but in no control-model doc, and has no shipped implementation); one
section per model with its specified character, **implementation status**, and **LLM calls/cycle target →
today** (A `~3 → 0`, B `1 → 0`, C `0`, D `0`); planning 02 §6's comparison matrix; `null` reconciled as a
fifth shipped decider (G9); which model-D policies exist versus which are aspirational (G6); the
selection mechanism as it really is (G11, F2); and the B-shape ruling (G12).

It also carries two things only this document can: a **"what runs today, and what has been tested where"**
section — G1, G2 and C6 with file:line evidence, *and* the evidence table above, so a reader learns that
the LLM arm has hardware results in the sibling implementation and none here; and the
**model-D-as-benchmark** rationale, cross-referenced to `examples/agentic_small_molecule_binding/rules_client.py`
with the letter mapping for that example's profile kinds, noting that arm is itself unmeasured.

Then `frontends.md:21-33` shrinks to a pointer and keeps the frontend *axes*; `architecture.md:17,22`
gains the link it lacks; `README.md:70-78` and `docs/impress-a/decisions/index.md` index it.

### 2. `policy/registry.py` — a home for the abstraction (new file)

```python
@dataclass(frozen=True)
class ReasonerModel:
    letter: str                  # "A".."D", "null", "replay"
    name: str
    mode: str                    # "autonomous" | "headless"
    llm: str                     # "none" | "per-node" | "single-call" | "external"
    status: str                  # "implemented" | "partial" | "stub"
    cls: type
    build: Callable[..., Any]    # plain kwargs, never a CampaignSpec
```

`MODELS: dict[str, ReasonerModel]`, with `cli.POLICIES` a derived re-export so
`slides/api/run_model.py:134` keeps working unchanged. **Layering:** `policy` may import `core` only
(`architecture.md:66`, asserted by `tests/test_layering.py`) and `CampaignSpec` lives in
`runtime/executor.py`, so builders take plain kwargs and `cli.build_policy` keeps the
`CampaignSpec` → kwargs adaptation. Add `impress-a models`, which prints the table and is how the status
column stops going stale.

### 3. Model B's live client — port the tested one, and preserve what made it tested

A new `OpenAICompatOracle` in `policy/oracle.py` implementing the existing `DecisionModel` protocol,
ported from `examples/agentic_small_molecule_binding/llm.py`, plus `ModelProfile`/`load_profiles`
reading a YAML profile file (`base_url`, `model`, `api_key_env`, `max_tokens`, `extra_body`,
`request_timeout_s`, `max_retries`).

Five things the port must get right, each for a stated reason:

- **Keep the transport synchronous and offload it.** The tested client is synchronous; the example only
  got away with that by running it on the `local` thread-pool backend, because a blocking call on the
  shared event loop cost 67 % of wall clock on job 22534628 (p99 56 s). Rewriting it with `AsyncOpenAI`
  would mean the transport that carries the hardware evidence is not the transport that runs. So: port
  it as-is and call it from `impress_a` via `asyncio.to_thread`, which keeps the executor's `pump()`
  unblocked **and** keeps the tested code path intact. Revisit only with a measurement.
- **Structured output is one tool call, not JSON scraped from prose.** `DECISION_SCHEMA`
  (`oracle.py:25-33`) becomes a single tool definition; `tool_calls[0].arguments` *is* the decision.
  This satisfies planning 02 §3, fixes `LangChainOracle`'s docstring claim, and resolves I2. Note
  honestly: **tested transport, untested usage** — the hardware runs used eight tool schemas with
  `tool_choice="auto"` and multi-call replies, not one required call.
- **One call per cycle sidesteps 23219379.** `OraclePolicy` rebuilds its prompt each cycle and keeps no
  message history, so the `reasoning_content` requirement that silently degraded all four pipelines on
  turn two cannot bite. Carry the field anyway for providers that send it, and record *why* the
  single-call shape is immune — this is the kind of reasoning that stops someone "simplifying" it later.
- **Two retries, not one.** Transport retry (backoff, `Retry-After`, 429 vs 529) belongs in the client;
  parse retry with corrective feedback already exists in `OraclePolicy.decide` (`oracle.py:126-139`).
  The example has only the first, `impress_a` only the second; conflating them loses one.
- **Label which oracle ran, in the campaign log and in provenance.** Job 23219379 is the evidence: a
  degraded arm is indistinguishable from a deliberate stand-in without a label, and its 35 passing folds
  would otherwise have read as a frontier-model result. Add the pinned dated model id and sampling
  params that planning 02 §7 requires and the current `sink("decisions", …)` record lacks.

`cli.build_policy` gains the wiring so `--model B` can name a profile, with `RehearsalOracle` the
default when none is named. `pyproject.toml`: drop `oracle = ["litellm"]`, add `openai` as an extra.

Example-side, scoped as example-side work: `llm.py` and `models.yaml` become thin re-exports of the
`impress_a` implementations. Prerequisite to flag in the example's README: `impress-a` installed in the
reference's environment. **Do not touch `vllm_service.py`'s serving path in this pass** — it is tested
infrastructure whose every profile is unmeasured, so changing it would compound two risks at once.

### 4. Stubs for the remaining unimplemented seams

Named, documented seams raising `NotImplementedError` rather than absences or dead arguments. None
changes the behaviour of a campaign that runs today.

- **`policy/agentic.py` — model A's node reasoner.** A `NodeReasoner` Protocol mirroring
  `oracle.DecisionModel`, one method per specified node (`hypothesize`, `parameterize`, `analyze`) with a
  declared output schema each. Make `self.reasoner` actually consulted: rename the node bodies as the
  rehearsal path, wrap them in a `RehearsalNodeReasoner` that becomes the explicit `None` default, add
  an `LLMNodeReasoner` stub whose docstring names what it owes (schema validation, bounded parse-retry
  with corrective feedback, escalation to `fallback`), and add the `fallback` argument A lacks. Fix the
  four-nodes-but-two-registered docstring. **A stays stubbed in this pass**; §3's client is what makes
  implementing it cheap later, and A's multi-turn-per-cycle shape is the one that *would* hit the
  `reasoning_content` trap, which is worth recording in the stub.
- **`tools/agent.py` / `tools/spec.py` — the `llm` task-agent kind.** An `LLMTaskAgent` base whose
  `parameterize` raises `NotImplementedError`, and a load-time check that `agent: llm` resolves to a
  subclass of it.
- **Reasoner contextualization.** Add `CampaignObservation.tool_context: str | None = None`
  (`core/decision.py`) with a comment naming `Registry.toolkit_skills()` as producer, the executor as
  filler, and planning 04:112-124 / 06:65 as specification. Left `None` for now.

### 5. Two defect fixes (G8)

- `cli.build_policy`: `replay` needs records — load them from a `--replay-from` provenance path, or
  refuse with a message naming what is missing. Not a `TypeError`.
- `ExternalPolicy`: keep the last observation and reuse it in `decide_after_rejection`.

### 6. Inline comments and docstrings

House style, inferred rather than documented (no `CONTRIBUTING.md`, no `[tool.ruff]` section): the
comment records **the reason or the measurement, not the mechanism**, with job ids where evidence
exists. `policy/explicit.py:90-98` is the exemplar, and the example's own comments are the other model
to match — they cite jobs by number for exactly this purpose.

- `policy/agentic.py` module docstring: nodes 1 and 2 are deterministic, `reasoner` is the unwired seam,
  A is bit-exact today.
- `policy/oracle.py` module docstring: split the "precedent → here" table into what `OraclePolicy`
  implements, what the ported client now adds, and what remains untested here — citing the sibling
  implementation's jobs rather than claiming them as ours.
- `policy/explicit.py:69`, `agentic.py:84`, `oracle.py:60`: record G4 — the composer drops these keys on
  a real chain, so the policy varies no real parameter.
- `policy/base.py`: name `policy/registry.py` as where the letters live.
- `core/decision.py:26` `toolkit_hint` marked reserved-and-unread (or removed); `:95` `available_tools`
  noted as ids only, pointing at `tool_context`.
- `tools/registry.py:85`: `toolkit_skills()` has no caller yet; name its consumer and its spec.
- `cli/__init__.py:93-115`: `build_policy` becomes the `CampaignSpec` → registry-kwargs adapter, with a
  comment on why the registry cannot see `CampaignSpec`.

### 7. `docs/impress-a/limitations.md`, `agent/plans/backlog.md`, `agent/CLAUDE.md`, `docs/impress-a/reference/architecture.md`

- `limitations.md`: replace the false reproducibility row (G3) with one row per model plus the condition
  under which A/B become non-reproducible. Add a section stating plainly that **no LLM has steered an
  `impress_a` campaign, while one has steered the sibling example's across ~8 Delta jobs and four model
  families** — with the evidence table's three tiers, and pointers to
  `impress-agentic-performance/report.md` and `impress_exports/`. Add G4. Carry the 1.9×-not-3.3×
  correction so nobody quotes the upper bound from here.
- `plans/backlog.md`: a new **D-series, reasoner models**, written to `plans/README.md`'s convention —
  A has no node reasoner (G1); policies cannot vary real tool parameters (G4); `ToolSpec.agent: llm`
  inert and `toolkit_skills()` uncalled, promoting I4 (G7); `--model replay` CLI-broken (G8); no
  `conduct` reasoner ships (G12); **first live `--model B` run** as a hardware item; **harmonization
  steps 4 and 5** with plan stubs. Also the items the evidence review surfaced that nothing tracks on
  this side: the in-allocation serving path has no measured profile, and `rules-d` is unmeasured.
  **Amend F2** with 0005's selection correction. Fix C6's stale refs (G11).
- `CLAUDE.md` "Known open risks": a paragraph on what `--model B` now reaches, what is tested where, and
  the labelling rule from 23219379.
- `architecture.md:143-152`: no toolkit spec sets `agent: llm` and nothing branches on it.

### 8. Decision records — `docs/impress-a/decisions/`

Template: `# NNNN — Title` / `**Date:** · **Status:** · **Phase:**` / `## Context` / `## Decision` /
`## Consequences`, indexed in `docs/impress-a/decisions/index.md`. Next free number 0014. Note the root
tree has no decision records, so these have no counterpart to keep in sync.

- **0014 — Model B is one structured call per cycle, emitted as a tool call.** Rules G12, resolves I2
  and I3, names the `conduct` alternative as a separate shape, and records that the single-call shape is
  immune to the `reasoning_content` failure mode A would face.
- **0015 — Where the control model and its configuration are named.** `decisions/0005:10` says "the
  campaign specification"; it is `--model` plus `IMPRESS_A_MODEL`. Amends 0005; F2 already flags it.
- **0016 — `examples/` demonstrates `agent/`; the harmonization route.** The layer analysis, the staged
  1 → 4 → 5 route, P7 considered and declined, and the measured-parity argument that replaces the
  byte-identity proxy. The record steps 4 and 5 are executed against. It also owns the open question
  G14 raises: whether IMPRESS-A joins the root `mkdocs.yml` nav, since at step 5 the published example
  page starts describing an engine the site does not document.

Worth recording if cheap: **LangGraph owns model A's loop** (planning I1), decided and shipped but
recorded nowhere — `academy-for-task-agents.md:3` explicitly disclaims being a decision.

---

## Verification

```bash
cd agent && source .venv/bin/activate
pytest tests -q                       # whole local tier; test_layering.py guards policy -> core
ruff check src tests                  # must not exceed 41 (plans/backlog.md:662)
impress-a tools                        # registry unaffected
impress-a models                       # new: the table, statuses included
impress-a run campaigns/mock-stabilize.yaml --model D    # terminates, non-empty front
impress-a run campaigns/mock-stabilize.yaml --model A    # unchanged, rehearsal nodes
impress-a run campaigns/mock-stabilize.yaml --model B    # unchanged default: RehearsalOracle, labelled
impress-a run campaigns/mock-stabilize.yaml --model replay   # a clear refusal, not a TypeError
python slides/api/run_model.py        # still reads the registry; cli_models unchanged
```

New tests:
- `policy/registry.py` adds no import edge (`tests/test_layering.py` already walks with `ast`);
- registry statuses asserted against the classes they name — a `status: implemented` model whose
  `decide` is `BasePolicy`'s `NotImplementedError` must fail;
- `OpenAICompatOracle` against a fake client: a tool-call reply becomes the right `Decision`; a
  malformed one triggers the policy's parse retry; a transport fault triggers the client's backoff and
  then the declared `fallback`, with the degraded transition logged;
- **the campaign log and provenance distinguish a live oracle from `RehearsalOracle`** — job 23219379's
  lesson, and the one test that would have caught it;
- `reasoning_content` is carried when the provider sends one and not invented when it does not (port the
  example's own test from `484bd06`);
- every stub is reachable and raises with its message;
- `--model replay` refuses with a message; an `ExternalPolicy` post-rejection directive carries the real
  `goal`.

Example-side: `test_agentic_smb.py` still passes with `llm.py`/`models.yaml` as re-exports, including
check [1]'s `task_description` identity, the provenance guard, and the model-D-routes-as-the-reference
assertion.

**Not verifiable locally, and to be stated as such.** A live endpoint is needed to confirm `--model B`
end to end; that is the follow-on below. Until it runs, "`--model B` can reach a live endpoint" is a
claim about code — and the correct way to say it is that the *transport* has hardware evidence in the
sibling implementation while *this* wiring of it has none. The surviving-profile claims in the evidence
section are checkable from `git log` and `models.yaml` and should be re-derived rather than trusted if
they are quoted later.

---

## Follow-on: paired 1-hour, 1-node runs of models B and D

To be executed **after** the work above, from the same branch. This is what moves the untested cell of
the 2×2 — LLM control of the `impress_a` engine — and the matched D arm is its control.

### Shape

One campaign spec, two arms, differing only in `--model`. Submitted together, as the example's paired
4-hour arms were, because arms submitted apart inherit whatever changed in between.

- `campaigns/delta-small-molecule-arms.yaml`, derived from `delta-small-molecule-trust.yaml` — same
  science, same ALR target, same six stages, `max_cycles: 6`, `replicas: 1`, `concurrency: 1`,
  `site: {gpus_per_node: 4, nodes: 1}`, `budget: {gpu_hours: 6.0, cpu_hours: 10.0}`.
- 1 node on `gpuA40x4`, 1 hour each. Billing: 2 × 4 = **8 GPU-h total**. One pass of the chain measured
  2m53s (job 22692304), so an hour is comfortable headroom for six cycles at `concurrency: 1` — which
  is the point: six cycles means six real `decide` calls, not one.
- Arm B: `IMPRESS_A_MODEL=B` with the `beam` profile (`Beam-501B-A23B`, remote API). Token cost is
  negligible — model B makes one call per cycle, so ~6–10 calls against Beam's 239 turns in 23225651.
- Arm D: `IMPRESS_A_MODEL=D`, `ThresholdPolicy`. Expected to reproduce known behaviour — promotion
  after r0002/r0003, as in 22726105 and 22728140 — which is how the shape is shown sound and the LLM
  isolated as the only difference.

### What these runs test, and what they cannot

**Test:** the `ControlPolicy` contract under a live LLM. `decide` returning a real `Decision`; an
LLM-authored `ExperimentIntent` passing or being refused by the five gates; `on_rejected` under a real
rejection; the interlock's treatment of an LLM-proposed pattern; the degraded-mode transition and its
labelling; prompt/response provenance carrying a pinned dated model id; and `asyncio.to_thread` keeping
the executor's `pump()` unblocked, observable as heartbeat continuity across each LLM call.

**Cannot test: decision quality.** Per G4, on the real chain a policy's levers are stage selection,
`parent_node`, `Backtrack` and `Stop` — and this spec caps `replicas: 1`, so B cannot widen either. Its
action space is close to a single point. **These are contract-and-plumbing runs and must be reported as
such**; a yield or quality comparison drawn from them would be exactly the conclusion they cannot
support. Two consequences, in order:

1. Run them anyway as plumbing tests, because a first live run's likely outcome is a plumbing failure
   and this is the cheap way to find it.
2. **Close G4 before any run that claims anything about decision quality.** That is the prerequisite for
   a real B-vs-D comparison, not an optional improvement.

Deliberately **not** combined with these runs: `replicas > 1`, which has never executed (backlog A10).
Four idle GPUs make it tempting, but it would confound two firsts in one job. It gets its own run.

### Prerequisites, each with its evidence

- **`impress-a preflight` must check `REFLECTION_API_KEY` is present.** The example's job 23231485 is
  the evidence: a 9-second `FAILED` because the key was missing from the submitting environment, caught
  by its launcher's pre-flight rather than by spending a 4-hour allocation.
- **Probe the Beam endpoint from the batch node.** 23112484 proved a Delta compute node can reach a
  hosted API, but Beam is a different host, so it needs its own probe. A single-turn probe is sufficient
  *here specifically* — model B keeps no message history, so the `reasoning_content` requirement that
  made a single-turn probe worthless in the example (23219379) cannot arise. Record that reasoning
  beside the probe, or someone will "fix" it into a multi-turn probe that model B has no use for.
- **Re-verify the live model id.** The decision-arms README records that the published docs'
  `Beam-1.0-501B-A23B` is wrong and the live `GET /models` returns `Beam-501B-A23B`. `models.yaml`
  already carries the right one; confirm rather than assume.
- A local `--model B` run against the live endpoint on a **login node** with
  `campaigns/mock-stabilize.yaml` first. No allocation, pennies, and it proves the client, the
  one-tool-call decision, the provenance record and the fallback before any GPU is billed.

### Scoring

From each campaign's own provenance and `jobs/ledger.jsonl`, plus the Boltz and Rosetta outputs on disk
— **never from the reasoner's bookkeeping**. The decision-arms README is explicit that the comparison is
only meaningful if the agent's own accounting plays no part, and `agent/`'s provenance is written by the
executor rather than the reasoner, which is the structural reason that holds here.

What would be learned, stated as observations rather than hoped-for numbers:

- B completes at least one full cycle with a live LLM decision admitted and executed → the untested cell
  of the 2×2 becomes tested, and the claim "no LLM has steered an `impress_a` campaign" retires.
- The campaign log and provenance name the live model id, so a degraded run can never be mistaken for a
  frontier-model result — the 23219379 lesson, applied before it can bite here.
- Every rejection reaches `on_rejected`, and the retry is visible in provenance.
- D reproduces promotion at the known cycle, confirming the shape.

Failure modes to expect and to have already decided how to read: the degraded transition firing (fine,
if labelled); a gate refusing every LLM-authored graph (a finding about the gates or the prompt, not
about the model); heartbeat gaps across an LLM call (`to_thread` not doing its job); and
`_objectives_without_a_producer` warning because B dropped a stage — which is A7/A8's failure mode
arriving from a new direction and worth catching here.

### Afterwards

Record the outcome in `agent/plans/` as a dated run document per `plans/README.md`'s convention, update
the evidence 2×2 in `docs/impress-a/reference/control-models.md` and the tiering in
`docs/impress-a/limitations.md`, and close the backlog item these runs were filed against. If B's arm
degrades or is refused throughout, that is a result and goes in the same place — the example's own
records keep invalid runs as evidence, and this should too.
