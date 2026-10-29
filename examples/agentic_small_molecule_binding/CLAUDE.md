# CLAUDE.md

Guidance for working in `examples/agentic_small_molecule_binding/`.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-10-29 | — | **Control model D is implemented: the reference's own rules now drive the agentic loop, and on mock inputs the two route identically.** This is the comparison's missing control. Every LLM arm changes two things against the reference at once — the rules become a model *and* the state machine becomes a tool-calling harness — so no figure on file says which change is responsible. `rules_client.py` (`kind: rules`, profile `rules-d`) calls the reference's `adaptive_decision()` on the live pipeline and translates the `next_step` it writes into one tool call. It **imports** the rules rather than restating them, for the reason this example imports `PROD`, which means the reference's quirks are reproduced rather than fixed: the backbone similarity gate is inert on a real run (`_ca_rmsd` needs `.pdb`, `analysis_backbone` stores `.cif.gz`) and `analysis_sequence` hardcodes `pass: True`. **Verified against the reference's own loop:** over 18 stages on identical mock inputs both emit the *same sequence*, including the `seq_retry_count >= 3` escalation to an unguided backbone and the cycle-1 resequence from the packed structure. The test asserts it as well as `check()`s it, and was confirmed to bite by breaking the shim. **Two things found building it.** `asyncio.run()` cannot drive `adaptive_decision` here — the adaptive callback is awaited on a running loop rather than threaded, so it raised `RuntimeError` every turn, `llm_turn()` caught it and degraded the pipeline to the scripted route, and the arm produced reference-route-shaped stages with `degraded: true`: **job 23219379's trap, reproduced exactly.** `_apply_rules()` now steps the coroutine (it is `async def` with no `await`), which works whether or not a loop is running, and raises rather than degrade if that ever stops holding. Separately, **the `scripted` profile is not a faithful `run_nonadaptive` replay**: its table sends `packmin -> relax` where the refine cycle runs a second `design_sequence` first, so it emits a 6-stage cycle against the reference's 7. It stays the degraded path and plumbing fixture; `rules-d` is the control. Also fixed: `delta_gpu_run.sh` gated the endpoint probe on the profile *name* (`!= "scripted"`), so a `rules-d` submission would have been probed, built `url = "/models"` and exited 1 before the job was queued; it now keys on `_PROFILE_KIND`. **UNMEASURED on hardware — no job has run this arm, so it licenses nothing about the harness yet** |
| 2026-10-27 | — | **The Qwen arms are retired, their weights are gone, and the in-allocation serving path is model-agnostic — which leaves the comparison with no open-weight arm that has data behind it.** A machine-wide provenance policy (`~/.claude/CLAUDE.md`) bars models developed by Chinese organisations by any route: weights staged on project storage, a server inside an allocation, or a hosted API arm. **About 405 GB of Qwen checkpoints were deleted** — Qwen2.5-0.5B/7B/72B and Qwen3.5-122B-A10B-FP8, the 122B staged twice across two caches — taking the shared bdyk pool from **1.11 T to 742.6 G**. The four `local-qwen*` profiles are replaced by `local-smoke` (Llama-3.2-1B, the plumbing proof), `local-llama-8b` (Llama-3.1-8B, the open-weight arm) and `local-open-weights` (a documented template); 35 GB of Llama weights were already cached, so neither needs a download. `serve_command()` no longer defaults `tool_parser` to `hermes` — it is a required argument, and the runner refuses a `dragon_vllm` profile that names none, because a mismatched parser fails exactly the way a model with no tool training fails. `test_agentic_smb.py` carries a provenance guard that *asserts* as well as `check()`s, so it fails a pytest run and not only the script entry point. **What this does not license:** every Qwen figure below stands as recorded — `23229812` at 0.615 GPU-h per passing fold, `23207314` at 0.242, the 7B's stamina, FP8 falling back cleanly on SM 8.6 — and none of it is re-litigated here. But those numbers are now **frozen**: the arms will not be rerun, so "the worst arm tested" names a model that can no longer be re-measured, and any later claim about it cannot be checked. **The Llama profiles are UNMEASURED.** Both chat templates carry `tools` and `tool_calls` (verified in the cached `tokenizer_config.json`, so vLLM's own jinja — which pip does not install — is not needed) and `llama3_json` is registered in vLLM 0.32.0, but no job has driven the agent loop with either. Until one has, Beam's 0.146/0.174 has nothing open-weight to sit beside |
| 2026-10-26 | — | **Beam promoted to the 4 h allocation stopped itself after 37 minutes, and every claim it made is true.** `23231797` (1 node, 4 pipelines, 4 h limit) returned `runner_status: ok` at **00:37:07** with all four pipelines calling `finish` deliberately and a clean Dragon teardown. **17 folds attempted, 17 passed (100 %)**, best 97.6, median 87.4, 162 turns, **0 degraded, 0 no-tool-call, 2 invalid**, 816 k prompt + 8.6 k completion tokens. Each pipeline's summary was checked against the Boltz confidence files: p1 'five passing' = 5, p2 'eight' = 8, p4 'two, best 97.62' = 2 and 97.62, and p3 quoted **both** of its pLDDT values (93.07, 88.77) correctly. At **0.146 GPU-h per passing fold** it is the cheapest arm measured — **but it spent 2.5 of 16 GPU-h and produced 17 designs where Sonnet's 4 h run produced 192.** Efficiency and productivity diverge here, and the numbers do not say which is wanted; a run that must fill its allocation needs a prompt that says so, not a better model. **Qwen3.5-122B-A10B-FP8 is the worst arm tested.** `23229812` (2 nodes, 1 h, ready in 440 s) ran clean — 255 turns, 0 degraded, 0 no-tool-call — and still returned only **13 of 16 folds** at 0.615 GPU-h each, 3.5x Beam's cost on twice the hardware, median 85.0. The tool histogram says why: **4.75 `design_sequence` per `fold_complex` against Beam's 1.8**, `score_interface` on 48 % of relaxes against 64 %, `inspect_ensemble` 3 times against 11 — i.e. it converges on the reference heuristic's resequence-and-retry pattern. 122B total but **10B active**, which is consistent with Qwen2.5-**72**B (0.242) beating it comfortably. It also sent `guide_model` as the string `"None"` on 10 of 255 turns across all four pipelines; `if guide_model:` accepted it and a GPU task was charged for a typo (fixed, commit `47c874d`) |
| 2026-10-26 | — | **The 0.160 baseline is confirmed correct, so the 4 h reference arm really was degraded and the agent's advantage is 1.9x, not 3.3x.** `22701168` (8 nodes, 32 pipelines, 4 h, 2026-10-06) was extracted from its archive and rescored by the *same* script and method as both 4 h arms. Every historical figure reproduces: **0.159 GPU-h per passing fold** against the recorded 0.160, **25.12 passing folds per node-h** against the recorded ~25, and 15.8 rfd3 per pipeline-h against the 4 h arms' 15.5/16.2. So the discrepancy is **not** in how the old number was counted, which was the benign explanation. Scored side by side: `22701168` 873 folds attempted -> **804 passed (92 %)**, `fastrelax` **64 %**, median pLDDT **94.4**; `23114772` (same workflow, 1 node, 16 days later) 66 attempted -> **53 passed (80 %)**, `fastrelax` **49 %**, median 89.6. **The mechanism is visible in the mpnn column:** `22701168` spent 6.8 mpnn tasks per fold attempted, `23114772` spent **13.0** — it resequenced twice as hard for half the folds, which is what a pipeline does when relax keeps rejecting its structures. So the `fastrelax` gap is not an agent-vs-reference difference at all: it is **49 % vs 64 % within the reference itself**, and the agent's 88 % sits above both. Restate the comparison accordingly — agentic `23114775` at 0.083 against a **healthy** reference at 0.159 is **1.9x**, and the 3.3x quoted against `23114772`'s 0.302 carries a degraded baseline inside it. **Lead, not yet a finding:** `22701168` ran at `e2aa00d`; PRs #71, #72 (`framework-defaults-pr1`) and #76 landed between it and `23114772`. That is a candidate post-merge regression in the *reference* pipeline and it is untested — rerun the reference arm at `e2aa00d` before believing it. Two tooling bugs found while doing this, both of which flattered multi-node arms: `compare_arms.py` divided rfd3 by a hardcoded 4 pipelines (reading 126.2/pipeline-h for a 32-pipeline run) and reported 'folds per node-h' without dividing by nodes (201 instead of 25.1) |
| 2026-10-26 | — | **A frontier reasoning model drives the loop on one node and posts the best billed efficiency so far — and a reasoning model needs its own reasoning handed back.** `23225651` (Reflection Beam, 501B-A23B, `reasoning_effort: medium`, `max_tokens` 32768, 1 node, 1 h) ran to `TIMEOUT` with **239 turns, 0 degraded, 0 no-tool-call turns and 2 invalid calls**: 34 rfd3, 46 mpnn, **25 folds attempted and 23 passed (92 %)**, median pLDDT 93.7, best 97.7, `fastrelax` 62 % (28/45), on 1.29 M prompt + 11.1 k completion tokens. **Three of four pipelines stopped on their own judgment** at 49/53/57 turns with summaries that check out against the Boltz confidence files on disk (p1 claimed *'8 successful folds, best pLDDT 97.71'* — exactly 8 passed, 97.71), so active time was **2.81 pipeline-h of 4.00**, giving 12.1 rfd3 and **8.17 passing folds per active pipeline-h**. p4 stopped with *'budget remains but further attempts are failing relax'*, independently reaching the `fa_rep` diagnosis Sonnet's p2 reached unprompted in `23112484` — two unrelated models naming the same bottleneck from tool results alone, which makes the `fastrelax` spread (49/62/76/88 %) a signal the agents act on rather than a measurement artifact. **Billing correction that changes the ranking:** the comparison script charged every arm for one node, so the 2-node arms were understated 2x. Per *billed* GPU-h per passing fold: Beam **0.174** (4 GPU-h / 23), Qwen2.5-72B **0.242** (8 GPU-h / 33, not the 0.121 first reported), Sonnet 1 h 0.253. Always charge the model's node to the experiment. **A prior Beam run, `23219379`, measured the scripted fallback and not Beam at all:** Beam rejects any request whose earlier assistant messages lack `reasoning_content` (`400 missing_required_parameter`), `_completion_from_response()` dropped the field, and all four pipelines degraded on **turn two** — 144 degraded turns. It looked healthy (33-41 turns, 0 errors, clean cycles) because that is the scripted route's signature; only the `degraded` flag and frozen token counts gave it away. **The pre-flight probe passed because it was single-turn**, so the endpoint check now has to be multi-turn to be worth anything (commit `484bd06`, plus three `_completion_from_response` tests). Also: the live `GET /models` returns **`Beam-501B-A23B`**; the published docs' `Beam-1.0-501B-A23B` is wrong. **FP8 on Ampere works** — `23219406` (Qwen3.5-122B-A10B-FP8, 2 nodes, 30 min smoke) reached `/v1/models` in **620 s** and ran 109 turns, 0 degraded, 8 invalid calls, so the block-FP8 fused-MoE path falls back cleanly on SM 8.6 and the AWQ/INT4 fallback was not needed |
| 2026-10-26 | — | **A 72B model hosted in the allocation sustains the agent loop; the 7B does not.** `23207314` (2 nodes, 1 h, Qwen2.5-7**2**B-Instruct tensor-parallel across the model node's four A40s, `gpu_fraction` 0.93) ran to `TIMEOUT` with **all four pipelines still active at the final second** — 67/62/62/68 turns, against the 7B's 6/8/10/17 the day before. Ready in **360 s** for 145 GB of weights against the 7B's 160 s for 15 GB, so engine start and CUDA-graph capture dominate rather than I/O; `ready_timeout_s: 2400` keeps 6.7x headroom. **2 invalid tool calls in 259 turns, 0 degraded**, peak prompt 8.7–10.5 k (so `_compact_history()` holds at this turn count), **33 folds attempted and 33 passed**, median pLDDT 92.0, best 97.9, `fastrelax` 76 % (34/45). Against the matched 1 h hosted-Sonnet run `23112484` (0.63 h, 16 folds → 10, median 83.6, `fastrelax` 48 %) it is better on every axis — **but it used two nodes to Sonnet's one, so per billed GPU-hour the advantage roughly halves, and the 100 % fold rate is 33 attempts on structures that already cleared `score_interface`, i.e. it measures gating discipline, not structure quality.** API cost $0 against ~$2.21/h. Two behaviours the hosted model lacked: `score_interface` called 11x against 11 relaxes (the cheap CPU gate before every expensive fold, where Sonnet ran 13 against 27) and `inspect_ensemble` 9x in p2 (Sonnet: **once in 137 turns**), so that tool does earn its place. **A prior run, `23206285`, is invalid and kept only as evidence:** its `IMPRESS_WORK_DIR` was moved to a second allocation to dodge a full quota, and `scripts/rfd3.sh` binds only `$WORK_DIR` into apptainer, so every rfd3 write went to the container's `--writable-tmpfs` overlay and vanished. rfd3 logged success, `out/` was empty, analysis returned `pass=false`, and the model correctly concluded its backbones kept failing — a silent environmental failure that reads exactly like a model failure. Guarded in `delta_gpu_run.sh` (commit `2641836`); never point the work dir outside `WORK_DIR` |
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
| `rules_client.py` | `RulesClient`: control model D, the reference's `adaptive_decision()` as the decision-maker |
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

**The in-allocation serving path takes any permitted open-weight model, and every model-specific fact lives in the profile.**
`serve_command()` has no vendor default: `tool_parser` is required, and
`tp_size`, `gpu_fraction`, `--max-model-len` and `--reasoning-parser` are
read off the model card into `models.yaml`. Serving Qwen taught the
infrastructure — node partition (`23201195`), tp=4 across the model node
(`23207314`), block-FP8 on SM 8.6 (`23219406`) — and none of that is
vendor-specific, which is why the path outlived those arms. Which models
may be served at all is settled machine-wide in `~/.claude/CLAUDE.md`;
the enforcement point is the provenance guard in `test_agentic_smb.py`,
and if it fails the fix is the profile, not the test.

**Control model D must route exactly as the reference, and the shim is the only place it can stop doing so.**
`rules_client.py` imports `adaptive_decision` instead of reimplementing
it, so the rules themselves cannot drift. What can drift is the one piece
of local logic: `STEP_MPNN` is not a tool call but a position inside
`_run_refine_cycle()`, and the client mirrors that loop to decide between
`design_sequence(backbone)`, `pack_minimize`, `design_sequence(packed)`
and `relax`. `test_rules_match_the_reference_loop` runs the reference's
own state machine beside the arm on the same mock inputs and asserts the
stage sequences are identical. If it fails, the fix is the shim.

**A rules arm that raises degrades into a fake reference arm.** `complete()`
raising is caught by `llm_turn()`, which finishes the pipeline on the
scripted route — so a broken model D publishes reference-route-shaped
results that differ from a real control only by the `degraded` flag. The
arm asserts `llm_degraded is False`, and the `start` record carries
`control_model` because zero token counts alone cannot tell a deliberate
rules arm from a degraded LLM one.

**A degraded run must be labelled.** If the endpoint fails after retries, the
pipeline finishes on the scripted route; the transcript, the log line and the
end record all carry `degraded`. Never let that silently produce a result
attributed to the model.

## Not yet done

- **The reference pipeline may have regressed between 2026-10-06 and
  2026-10-22, and that is now the most important open question.** Rescoring
  `22701168` reproduced its 0.160 exactly (0.159), so the 2× gap to
  `23114772` is real rather than an artefact of counting. Both ran the same
  reference workflow; `fastrelax` fell from 64 % to 49 % and mpnn per fold
  attempted rose from 6.8 to 13.0. PRs #71, #72 and #76 landed in between.
  **Rerun the reference arm at `e2aa00d` and compare.** Until then, quote the
  agent's advantage as **1.9×** against the healthy baseline, not 3.3×.
- **There is no open-weight arm until `local-llama-8b` runs, and the Qwen
  conclusions are frozen rather than live.** The retired arms' figures are
  on file and reproducible from the transcripts under `logs/23219406/` and
  `logs/23229812/`, but nothing further can be asked of them — "the worst
  arm tested" refers to a model that will not be served here again. Run
  `local-smoke` first to prove the path survived being made
  model-agnostic, then `local-llama-8b` for an arm that can stand against
  Beam. Expect less of an 8B than of the retired 72B, which is the point of
  running it rather than assuming.
- **Control model D is built but has never run on hardware, so the harness
  question is still open.** Submit it at 1 node / 4 pipelines / 4 h, the
  shape `23114772` (reference) and `23114775` (agentic Sonnet) both ran, and
  score all three with one pass of `compare_arms.py`. If model D lands near
  the healthy reference (0.159 GPU-h per passing fold, 92 % fold pass,
  `fastrelax` 64 %, median 94.4) the harness is neutral and the LLM arms'
  advantage is the decision-maker. **If it does not, part of every arm's
  figure is the harness and the 1.9x needs restating** — that is the more
  valuable outcome and the reason to run this before quoting 1.9x again.
  Check `MAX_LLM_TURNS` first: at reference throughput this is ~400+ turns
  per pipeline, so confirm 1000 is not the binding constraint.
- **The `fastrelax` spread is partly explained and still worth pulling.** It is
  not an agent-vs-reference property: the reference posts both 64 % and 49 %
  depending on which commit it ran at. The agent's 88 % is above both, and the
  hosted/local arms land at 50-76 %, so something real varies with the
  decision-maker too — but the reference's own 15-point swing has to be
  resolved first, or any model-to-model comparison inherits it.
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
