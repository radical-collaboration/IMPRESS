# CLAUDE.md

Guidance for working in `examples/agentic_small_molecule_binding/`.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-10-22 | — | **First two runs on Delta, both on one node / 4 pipelines / `gpuA40x4-interactive` / 1 h.** Smoke (`23110801`, scripted profile): 294 tool calls, **0 failures**, all six tools on all four pipelines, GPUs pinned 0-3 and all active (10.0/10.2/11.1/11.2 % mean), 36/47 folds passed, **13.1 rfd3/pipeline/h — the reference's own figure** (`22675825`, `22684833`), so the inherited toolkit performs identically. `TIMEOUT` at 01:00:29 with no `runner_status`, as expected for a job with no natural stop. Live (`23112484`, `claude-sonnet-5-5`, `--max-llm-turns 40`): finished by itself in **37:54**, `runner_status: ok`, Dragon teardown clean in 4 s — the hang of BACKLOG 2 did not occur. **0 invalid tool calls and 0 degraded fallbacks over 137 turns**, so the endpoint held and the guards were never needed. 10/16 folds passed; 1.06 M prompt + 9.8 k completion tokens ≈ **$2.21**, negligible beside the GPU time. **A Delta compute node can reach `api.anthropic.com`** (the launcher's probe, HTTP 400 = routable) — the plan's one open risk, now closed. Behaviour: 3 of 4 pipelines called `finish` deliberately with an accurate summary of their own results, and p2 diagnosed the `fa_rep` relax bottleneck (BACKLOG 3) unprompted. Guided partial diffusion correlates with yield — p3 used it 3× for 4/4 folds, p4 never and got 1/3. Two weaknesses: `score_interface` was called 13× against 27 `relax` (the cheap CPU gate before an expensive fold is being skipped), and `inspect_ensemble` was called **once in 137 turns**. Not a fair throughput comparison: the live run was turn-limited, the smoke run time-limited |
| 2026-10-22 | — | **`claude-opus-5-5` declines this workload through the OpenAI-compatibility endpoint** (`finish_reason=content_filter`, 0 completion tokens), with the system prompt and without it, so it is the design task and not the prompt's wording; `claude-sonnet-5-5` answers the identical request normally and opens with `design_backbone`. Multi-turn tool round-trip verified on Sonnet (4 turns, ~10k prompt / 194 completion tokens). `models.yaml` and `README.md` now say to use the `claude-sonnet` profile. Do **not** try to reword the prompt around this: the bare user message refuses too, and the native API's remedy for a false-positive decline is the server-side `fallbacks` parameter, which this endpoint does not expose |
| 2026-10-21 | — | Example created. An LLM drives the reference small-molecule binding toolkit directly through tool calls, on the same asyncflow/Dragon execution and the same task allocation. Model reached through an OpenAI-compatible endpoint so several can be compared run for run. Offline test passes (54 checks) |

## What this is

The reference example (`../small_molecule_binding`) walks a fixed state machine
and asks `adaptive_decision()` which step comes next. This example removes the
state machine: the model is given the toolkit and calls it. Everything else is
the reference's.

It is **experimental.** Two one-hour runs on Delta (2026-10-22) and nothing
more; the reference has months of multi-node campaigns behind it. Do not
present its numbers alongside the reference's as if both carried the same
weight.

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

- **No time-matched comparison with the reference yet.** The live run was
  limited by `--max-llm-turns 40`, not the clock, so its folds-per-hour cannot
  be set against the reference's. The next run should give the agent the same
  wall clock with a turn cap high enough not to bind.
- **`score_interface` is under-used** (13 calls against 27 `relax`). Its tool
  description leads with the ordering rule, which reads as a restriction rather
  than as the thing to do after a relax. Worth rewording and re-measuring.
- **`inspect_ensemble` was called once in 137 turns.** Either it is not worth
  its place in the tool list, or the prompt does not make a free tool feel
  free. Decide with data before adding more tools.
- The live-endpoint check has been run: Sonnet drives the loop correctly over
  four turns. Opus declines (see the revision row above).
- Outbound HTTPS from a Delta *compute* node is unverified. The login node
  reaches `api.anthropic.com` (HTTP 401, i.e. routable). The launcher's probe
  runs on the batch node and fails fast if a compute node cannot.
- No cost figure yet. `max_llm_turns` is the only cap until a run produces
  tokens-per-passing-fold from the transcripts.
- Parallel tool calls are executed sequentially. One pipeline owns one GPU, so
  concurrency within a pipeline would contend with itself; revisit only if the
  operating point moves to several pipelines per GPU.
