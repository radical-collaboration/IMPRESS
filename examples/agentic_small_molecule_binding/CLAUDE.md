# CLAUDE.md

Guidance for working in `examples/agentic_small_molecule_binding/`.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-10-21 | — | Example created. An LLM drives the reference small-molecule binding toolkit directly through tool calls, on the same asyncflow/Dragon execution and the same task allocation. Model reached through an OpenAI-compatible endpoint so several can be compared run for run. Offline test passes (54 checks); **never run on Delta** |

## What this is

The reference example (`../small_molecule_binding`) walks a fixed state machine
and asks `adaptive_decision()` which step comes next. This example removes the
state machine: the model is given the toolkit and calls it. Everything else is
the reference's.

It is **experimental and unproven on hardware.** Do not present its numbers
alongside the reference's as if both were validated.

## The one rule that matters

`AgenticSMBPipeline` overrides exactly one method of
`SmallMoleculeBindingPipeline`: `run()`. Keep it that way.

The whole claim of this example — that it is the same workflow with a
different decision-maker — rests on inheriting `_register_real_tasks()`
untouched. That is where every `task_description` lives: `gpu_td` (8 threads
plus `Policy(gpu_affinity=[gpu_index])`) for rfd3 and boltz, `mpnn_td` (4
threads plus the GPU) for LigandMPNN, `rosetta_td` (1 thread, no GPU) for
packmin/fastrelax/filter_shape, and `local_task=True` for the six `analysis_*`
steps. Re-registering a task here, or wrapping one to "add" a resource hint,
silently makes the comparison meaningless.

`test_agentic_smb.py` check [1] asserts this mechanically, comparing every
task's `task_description` default between the two classes on both the Dragon
and the concurrent branch. If that check fails, the fix is in this example, not
in the test.

## Structure

| File | What it holds |
|---|---|
| `agentic_pipeline.py` | `AgenticSMBPipeline`: `run()` as an agent loop, `llm_turn()`, history compaction, transcript |
| `tools.py` | `TOOL_SCHEMAS` (what the model sees) and `HANDLERS` (what they run) |
| `llm.py` | `OpenAICompatClient`, `ScriptedClient`, `ModelProfile`, `load_profiles` |
| `prompts.py` | `SYSTEM_PROMPT` and `opening_message()` |
| `models.yaml` | One profile per model under comparison |
| `run_agentic_smb.py` | Engine, backends, GPU assignment, `PipelineSetup`s |
| `delta_gpu_run.sh` | Derived from the reference launcher; adds the endpoint probe |

## Invariants worth knowing before editing

**A tool handler pairs an executable task with its analysis step, always.**
Every `analysis_*` reads `{taskcount}_<stage>/out`, and `taskcount` advances
with each executable task, so anything run between the two points the analysis
at the wrong directory. `score_interface` is stricter still: `filter_shape`
does not increment `taskcount` and reads the *fastrelax* output dir, which is
why the handler refuses unless `previous_task == "fastrelax"`.

**A handler never raises for anything the model controls.** Unknown tool, bad
enum, missing prerequisite, unparseable arguments: all return an error payload.
A model that cannot read its own mistake will repeat it.

**The LLM call runs on the `local` thread-pool backend, via `adaptive_fn`.**
Same seam and same reason as `adaptive_decision`: the body is synchronous, and
on the event loop it blocks every pipeline at once (job 22534628, 67% of wall
clock, p99 56 s). It must stay a *thread* pool — a process pool would mutate a
pickled copy of the pipeline and the tool calls would never come back.

**Tool results are small on purpose.** Metrics and paths, never file contents.
Each one stays in the context window for the rest of the run.

**The cacheable prefix is `messages[:2]` and must stay byte-stable.**
`_compact_history()` rewrites the middle of the conversation and never those
two, so an endpoint offering prompt caching can hit. Putting anything
per-turn into `SYSTEM_PROMPT` defeats that.

**A degraded run must be labelled.** If the endpoint fails after retries, the
pipeline finishes on the scripted route; the transcript, the log line and the
end record all carry `degraded`. Never let that silently produce a result
attributed to the model.

## Not yet done

- Never run on Delta. The smoke gate is in the plan: 1 node, 4 pipelines,
  `gpuA40x4-interactive`, 1 h, with zero task failures, every tool exercised,
  all four GPUs active in `nvsmi.csv`, `runner_status` = `ok`, and a transcript
  per pipeline.
- Outbound HTTPS from a Delta *compute* node is unverified. The login node
  reaches `api.anthropic.com` (HTTP 401, i.e. routable). The launcher's probe
  runs on the batch node and fails fast if a compute node cannot.
- No cost figure yet. `max_llm_turns` is the only cap until a run produces
  tokens-per-passing-fold from the transcripts.
- Parallel tool calls are executed sequentially. One pipeline owns one GPU, so
  concurrency within a pipeline would contend with itself; revisit only if the
  operating point moves to several pipelines per GPU.
