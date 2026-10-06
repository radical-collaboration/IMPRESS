# Dragon Batch: process tasks get every GPU, and a per-task `CUDA_VISIBLE_DEVICES` is silently overwritten

**Component:** dragonhpc 0.14.1 (`dragon.workflows.batch`, global/local services), reached through rhapsody 0.5.0 `DragonExecutionBackend`
**Found by:** IMPRESS small-molecule binding on Delta (A40x4 nodes), job `22684833`. See `../2026-10-05-gpu0-only.md`.

## Behaviour

1. **Every GPU by default.** A Batch process task with no `gpu_affinity` in its template policy is given every GPU on its node.
   - `globalservices/policy_eval.py` `_get_gpu_affinity`: an empty `gpu_affinity` returns `node.accelerators.device_list`.
   - `localservices/server.py` `PopenProps` then sets `CUDA_VISIBLE_DEVICES=0,1,2,3`.
   - Most GPU tools (PyTorch, Lightning `--devices 1`) take the first visible device, so N concurrent single-GPU tasks on one node all land on GPU 0. On our runs GPUs 1–3 were 0% busy for a full hour on every node.
2. **The env route is overwritten.** Setting `CUDA_VISIBLE_DEVICES` in `ProcessTemplate(env=...)` has no effect. Local services merges the requested env first, then `PopenProps` writes the accelerator variable from the policy layout over it. The only working control is `Policy(gpu_affinity=[...])`, and nothing in the docs warns about the override.
3. **No GPU accounting in Batch.** Batch never counts GPUs as a resource. Its own pool workers pick one with `random.randint(0, num_gpus - 1)` (`workflows/batch/batch.py`, `Manager.__setstate__`). A caller that wants one GPU per task has to choose the device itself, without knowing which node Batch will place the task on, or which GPUs other tasks already hold there.

## Workaround in use

Each pipeline is given a fixed device, `(N-1) % gpus_per_node`. Its GPU tasks pass that device as `process_template={"policy": Policy(gpu_affinity=[g])}` through rhapsody's `task_backend_specific_kwargs`. Batch still chooses the node, so two pipelines with the same device number can still share a GPU when Batch places them on the same node.

## Ask

- **Dragon:** let a Batch task request a GPU count (e.g. `gpus=1`). Batch would then pick the node and a free device and set `gpu_affinity`, the same way it already tracks cores.
- **Dragon:** when a template env sets the accelerator variable and the policy layout overrides it, document this or warn.
- **rhapsody:** expose that request as a backend-neutral task field (for example `gpus=1`), so callers don't build Dragon `Policy` objects.
