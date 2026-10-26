# CLAUDE.md

Guidance for working in `examples/agentic_small_molecule_binding/`.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-10-25 | — | **The LLM can be hosted inside the allocation, and the infrastructure is done.** `vllm serve` runs as an asyncflow task on the rhapsody Dragon backend, on a node of its own; the ordinary `OpenAICompatClient` reaches it unchanged. Two 2-node runs: `23180011` (Qwen2.5-0.5B, plumbing) and `23201195` (Qwen2.5-7B, 13:14, `runner_status: ok`). **The node partition holds** — verified on hardware with bracketed `pgrep` patterns: model node had 1 vLLM process, 0 tool processes, 27.6 GB on GPU 0; pipeline node had 0 vLLM, 2 tool processes, 0 GPU contention. `node_hostnames()` must read Dragon's node order, not Slurm's: on `23201195` Slurm listed `gpub[020,035]` but Dragon's last node was **gpub020**, so a `SLURM_NODELIST` parse would have pinned the model onto the pipelines' node. 7B ready in **160 s** (faster than the 0.5B's 190 s — engine start dominates, not the 15 GB of weights), so `ready_timeout_s: 1800` has 11x headroom. **Qwen2.5-7B's tool calls are good and its stamina is not.** 3 error payloads in 41 turns (against the 0.5B's 6 in 19), correct stage ordering including the `score_interface`-after-`fastrelax` rule, and **3 of 3 folds passed**, median pLDDT 88.4. But all four pipelines self-terminated after 6/8/10/17 turns, spending **2-6 of a 300-entry ensemble budget**; three called `finish` with reasons that misstate the state (p4: *'High pLDDT achieved and budget spent'* at 4/300). `SYSTEM_PROMPT` already says to finish only when the budget is spent, so this is agentic stamina rather than prompt wording, and no reword should be attempted before a stronger model is tried. A 4 h run at this configuration would buy ~13 minutes of work and ~3h47m of idle 2-node allocation, so it was **not** submitted; `local-qwen-72b` (tp=4 across the model node's four otherwise-idle A40s) is the next arm |
| 2026-10-22 | — | **Paired 4 h / 1 node / 4 pipeline comparison on `gpuA40x4`: `23114772` (reference, `adaptive_decision`) vs `23114775` (agentic, `claude-sonnet-5-5`), submitted together, same inputs and same `PROD` thresholds.** Both ran the full 4 h to `TIMEOUT`, 0 task failures, **0 degraded**. Every figure below is read off the Boltz/Rosetta outputs on disk by one script over both arms, never off either arm's own bookkeeping. **Toolkit throughput is equal** — 15.5 vs 16.2 rfd3/pipeline-h — so the LLM round trip costs no measurable throughput, the result I least expected. The funnel is not equal: reference **53** distinct passing designs (13.25/node-h, 0.302 GPU-h each) against agentic **176** (44.0/node-h, 0.083 GPU-h each), a **3.3×**. It is not duplicate re-folding (182 distinct sequences, 16 repeats) and not one lucky backbone (**192 of 260 backbones yielded a passing fold, 74 %, against 53 of 248, 21 %**). Median pLDDT 94.2 vs 89.6. The mechanism is upstream of folding: `fastrelax` passed **88 %** (213/242) for the agent against **49 %** (87/176) for the reference, and the reference spent 858 mpnn tasks to the agent's 349 — it resequences and retries where the agent moves on. Agent cost $25.40 (1462 turns, 12.2 M prompt tokens) = **$0.14 per passing design**. **Do not quote the 3.3× yet.** The reference arm underperformed its own record — `22701168` is on file at 0.160 GPU-h per passing fold and ~25 passing folds/node-h, so this baseline came in about 2× worse than the same configuration has historically managed, and until that is explained some unknown part of the gap is a degraded baseline rather than agent skill. The unexplained `fastrelax` gap is the thread to pull first. `_compact_history()` validated under load: per-turn prompt plateaued at ~8.5 k tokens over ~365 turns per pipeline with zero degraded, so the orphaned-tool-result fix holds. Decision-layer share could **not** be measured: no `local`-backend spans are identifiable in telemetry, which is BACKLOG 8 (asyncflow mislabels the backend on task events) |
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

- **The 4 h comparison's baseline is not trusted yet.** The reference arm
  (`23114772`) produced 0.302 GPU-h per passing fold where `22701168` is on
  file at 0.160 under the same one-pipeline-per-GPU configuration. Until that
  2× is explained — post-merge regression, node variance, or a difference in
  how the historical figure was counted — the agent's 3.3× advantage is an
  upper bound, not a result. Re-run the reference arm, and check it against
  `22701168`'s own method before quoting any ratio.
- **The `fastrelax` gap is unexplained.** 88 % for the agent against 49 % for
  the reference, same tool and same thresholds. Either the agent feeds it
  better-packed structures, or something differs in how each arm reaches it.
  This is the most important open question: it is where the funnel difference
  actually originates, and the fold counts are downstream of it.
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
