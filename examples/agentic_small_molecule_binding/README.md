# Agentic Small Molecule Binding (experimental)

An experiment: take the toolkit of the reference
[`examples/small_molecule_binding`](../small_molecule_binding) pipeline, remove
its state machine, and let an LLM call the tools directly.

Everything below the decision layer is the reference's, unchanged by
construction — this example subclasses `SmallMoleculeBindingPipeline` and
overrides exactly one method, `run()`. The tools, the shell scripts they
invoke, the thread caps, the GPU pinning and the local analysis steps are all
inherited, so the two examples place the same demands on an allocation and
their results are comparable.

**This is experimental.** Two one-hour single-node runs on Delta (2026-10-22)
and nothing else; the reference pipeline has months of multi-node campaigns
behind it, and is what a real campaign should use.

First results, both 1 node / 4 pipelines / 1 h:

| | smoke (`scripted`) | live (`claude-sonnet-5-5`) |
|---|---|---|
| job | `23110801` | `23112484` |
| tool calls | 294 | 154 (turn-limited at 40/pipeline) |
| task failures | 0 | 0 |
| invalid tool calls / degraded | n/a | 0 / 0 |
| folds passed | 36/47 | 10/16 |
| throughput | 13.1 rfd3/pipeline/h (= the reference's) | not time-matched |
| ended | `TIMEOUT` at the wall clock | by itself at 37:54, `runner_status: ok` |
| LLM cost | none | ~$2.21 (1.06 M prompt tokens) |

The live run answered the design's open question — a Delta compute node can
reach the endpoint — and showed the model doing things the state machine
cannot: three of four pipelines chose to stop, with an accurate account of
what they had produced, and one diagnosed the `fa_rep` relax bottleneck
unprompted. It also showed two weaknesses: it skips the cheap
`score_interface` gate before expensive folds, and it almost never calls
`inspect_ensemble`. See `CLAUDE.md` for the full record.

## The 4-hour paired comparison (2026-10-22)

`23114772` (reference) and `23114775` (agentic, `claude-sonnet-5-5`) submitted
together, 1 node / 4 pipelines / 4 h / `gpuA40x4`, same inputs and thresholds.
Both ran to `TIMEOUT` with 0 task failures and 0 degraded turns. Measured off
the tool outputs on disk by one script over both arms:

| | reference | agentic |
|---|---|---|
| rfd3 / pipeline-hour | 15.5 | 16.2 |
| distinct passing designs | 53 | **176** |
| passing designs / node-hour | 13.25 | **44.0** |
| GPU-h per passing design | 0.302 | **0.083** |
| backbones yielding a passing fold | 53/248 (21 %) | **192/260 (74 %)** |
| `fastrelax` pass rate | 87/176 (49 %) | **213/242 (88 %)** |
| mpnn tasks | 858 | 349 |
| median pLDDT | 89.6 | 94.2 |
| LLM cost | — | $25.40 ($0.14/design) |

Throughput is equal, so the model's round trip costs nothing measurable; the
difference is entirely in which work the funnel chooses to do.

**Two caveats, and they matter.** The reference arm came in about 2× worse than
its own record (`22701168`: 0.160 GPU-h per passing fold), so an unknown part
of this gap is a weak baseline rather than agent skill — do not quote the
ratio until that is explained. And the `fastrelax` gap, 88 % against 49 % on
the same tool with the same thresholds, is unexplained and is where the
difference actually originates.

## What is different

| | Reference | Here |
|---|---|---|
| What runs next | A fixed `run()` loop plus `adaptive_decision()` | Whatever the model calls |
| Decision input | `last_analysis_metrics` and the ensemble | The same, as tool results in a conversation |
| Decision cost | ~0.07 s p99 (job 22701168) | One LLM round trip |
| Execution | asyncflow `WorkflowEngine` on Dragon | identical |
| Task placement | GPU tools pinned, Rosetta on 1 CPU thread | identical |

The model sees eight tools: `design_backbone`, `design_sequence`,
`pack_minimize`, `relax`, `score_interface`, `fold_complex`,
`inspect_ensemble` and `finish`. Each of the first six runs the corresponding
inherited task and its paired `analysis_*` step, and returns the parsed metrics
with a pass/fail against the campaign thresholds. `inspect_ensemble` is free
and reads the campaign history. There is no fixed order; three ordering rules
are enforced and return an error payload rather than running anything.

One agent drives one pipeline, and one pipeline owns one GPU — the same
topology the reference uses.

## Running it

Offline, with no GPU, network or API key:

```shell
PYTHONPATH=../../src python test_agentic_smb.py
```

On Delta:

```shell
export SBATCH_ACCOUNT=<project>-delta-gpu
export WORK_DIR=/work/nvme/<project>/$USER
export IMPRESS_MODEL_PROFILE=claude-opus
export ANTHROPIC_API_KEY=...        # also in ~/.bashrc for multi-node runs
sbatch delta_gpu_run.sh
```

The launcher probes the endpoint on the batch node before anything is queued,
so an unreachable endpoint or a missing key costs seconds rather than an hour
of the allocation. `IMPRESS_MODEL_PROFILE=scripted` runs the whole thing with
no model at all, on the reference non-adaptive route — useful for checking the
plumbing on real hardware.

## Comparing models

`models.yaml` holds one profile per model, each an OpenAI-compatible
`/chat/completions` endpoint with tool calling. Comparing two models is a
matter of changing `--model-profile`; nothing else in the example knows which
model is in play.

Anthropic's OpenAI-compatibility endpoint takes this request shape but does not
expose Claude's own controls — adaptive thinking, effort, server-side
fallbacks. That is a deliberate trade: one request shape across every model
under comparison is the point. A single-model study should use the Anthropic
SDK directly instead.

**Measured 2026-10-22: use the `claude-sonnet` profile, not `claude-opus`.**
`claude-opus-5-5` declines this workload through that endpoint — every request
returns `finish_reason=content_filter` with zero completion tokens, with the
system prompt and without it, so it is the design task rather than the prompt's
wording. `claude-sonnet-5-5` answers the identical request normally and opens
with `design_backbone`. An Opus run would hit the endpoint-failure path on turn
one and finish on the scripted route, which is not the experiment. On the
native API the documented remedy for a false-positive decline is the
server-side `fallbacks` parameter; the compatibility endpoint does not offer
it.

Each pipeline writes `{work_dir}/{name}/llm_transcript.jsonl`: every assistant
turn with its tool calls and token counts, every tool result, and the run's
start and end. That file is the comparison data, and it is what makes a run
replayable.

Figures worth comparing against the reference's, which `../small_molecule_binding/CLAUDE.md`
records per job:

- passing folds, and GPU-hours per passing fold (reference best: 0.048 at 8
  pipelines per GPU; 0.160 at one per GPU)
- the decision layer's share of wall clock, read from the `local` backend in
  telemetry — the reference runs at ~1%, and the LLM will not
- tokens per passing fold, from the transcripts

## Guards

A model can stall, loop, or call nonsense, and an allocation is expensive:

- `--max-llm-turns` (default 200) and the inherited `max_tasks` ensemble budget
  both stop the loop.
- A bad tool call — unknown name, bad enum, missing prerequisite, unparseable
  arguments — returns an error payload the model can read and recover from.
- A tool that fails outright is reported as a result rather than killing the
  pipeline. The reference kills the pipeline on a failed stage, which at scale
  idles a GPU for the rest of the job.
- If the endpoint fails after bounded retries, the pipeline finishes on the
  scripted route and the transcript, the log line and the end record all say
  `degraded` — so a degraded run is never mistaken for the model's own work.
- Past 40 turns, older tool results are folded into one summary message. The
  system prompt and the opening message are never touched, so the cacheable
  prefix stays byte-stable.

## Files

| File | What it is |
|---|---|
| `agentic_pipeline.py` | `AgenticSMBPipeline`: the agent loop, in place of `run()` |
| `tools.py` | The tool schemas the model sees, and their handlers |
| `llm.py` | The endpoint client, the profile loader, and the scripted stand-in |
| `prompts.py` | The system prompt and the opening observation |
| `models.yaml` | One profile per model under comparison |
| `run_agentic_smb.py` | Runner: engine, backends, GPU assignment, pipeline setups |
| `delta_gpu_run.sh` | Delta sbatch launcher, derived from the reference's |
| `test_agentic_smb.py` | Offline checks, including that the task descriptors match |

Requires `openai` and `pyyaml` on top of the reference example's environment:

```shell
pip install 'impress[agentic]'
```
