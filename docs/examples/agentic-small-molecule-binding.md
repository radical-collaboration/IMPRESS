# Agentic Small Molecule Binding

Location: [`examples/agentic_small_molecule_binding/`](https://github.com/radical-collaboration/IMPRESS/tree/main/examples/agentic_small_molecule_binding)

!!! warning "Experimental"
    This example has no production record. Use
    [Small Molecule Binding](small-molecule-binding.md) for real campaigns.

The same small-molecule binder design toolkit as the reference example, with
the state machine removed: an LLM is given the tools and calls them directly.
The question it exists to answer is whether a model reasoning over the
campaign's own metrics directs the search better than a hand-written router,
at a cost the allocation can bear.

## How it relates to the reference

`AgenticSMBPipeline` subclasses `SmallMoleculeBindingPipeline` and overrides
only `run()`. Every task, the shell script behind it, its thread cap, its GPU
pinning and the local analysis steps are inherited unchanged, so both examples
place identical demands on an allocation. The offline test asserts this
directly, comparing each task's `task_description` between the two classes on
both the Dragon and concurrent backends.

Execution is the reference's too: one `WorkflowEngine` over two named rhapsody
backends, `compute` (Dragon) for every tool and `local` (a thread pool) for the
decision step, with one GPU per pipeline and staggered starts.

## The tool surface

| Tool | Runs | Resource |
|---|---|---|
| `design_backbone` | `rfd3` + `analysis_backbone` | GPU, 8 threads |
| `design_sequence` | `mpnn` + `analysis_sequence` | GPU, 4 threads |
| `pack_minimize` | `packmin` + `analysis_packmin` | CPU, 1 thread |
| `relax` | `fastrelax` + `analysis_fastrelax` | CPU, 1 thread |
| `score_interface` | `filter_shape` + `analysis_interface` | CPU, 1 thread |
| `fold_complex` | `boltz` + `analysis_fold` | GPU, 8 threads |
| `inspect_ensemble` | campaign history, in process | free |
| `finish` | ends the pipeline | free |

Each executable tool is paired with its analysis step because every
`analysis_*` reads `{taskcount}_<stage>/out`, and `taskcount` advances with
every executable task — the two cannot be separated.

## The decision layer

Where the reference calls `adaptive_decision()` to pick the next state-machine
step, this calls one turn of the model to pick the next tool. Both run as
`flow.function_task(backend="local")` on a thread pool, for the same reason:
the body is synchronous, and blocking it on the event loop stalls every
pipeline at once — the defect that capped job 22534628 at 37% of baseline
throughput.

## Models

Every model is reached through an OpenAI-compatible `/chat/completions`
endpoint with tool calling, configured by a profile in `models.yaml`, so
comparing models means changing `--model-profile` and nothing else. A
`scripted` profile replays a fixed route with no model at all, and also serves
as the degraded mode if an endpoint fails mid-run.

The `rules-d` profile is the comparison's control. It runs the loop from the
reference example's own `adaptive_decision()` rather than a model, so the
decision rules are held fixed while the execution path varies — which is what
separates the harness's contribution from the decision-maker's. Every other arm
changes both at once.

Each pipeline writes `llm_transcript.jsonl` — every turn, tool call, result and
token count — which is both the comparison data and what makes a run
replayable.

## Running

```shell
# offline: no GPU, no network, no key
PYTHONPATH=../../src python test_agentic_smb.py

# on Delta
export SBATCH_ACCOUNT=<project>-delta-gpu
export WORK_DIR=/work/nvme/<project>/$USER
export IMPRESS_MODEL_PROFILE=claude-opus
export ANTHROPIC_API_KEY=...
sbatch delta_gpu_run.sh
```

The launcher checks the profile, the key and endpoint reachability on the batch
node before queueing anything.

See the example's
[README](https://github.com/radical-collaboration/IMPRESS/tree/main/examples/agentic_small_molecule_binding)
for the guards against a stalling or looping model, and for which figures to
compare against the reference.
