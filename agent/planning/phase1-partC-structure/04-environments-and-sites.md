# 04 — Environments, Sites, and Deployment

Answers Part B's C5, given container-first deployment and Part A's Python floor conflict.

## 1. Two tiers, and why the floor conflict dissolves

| Tier | Contents | Python | Delivery |
|---|---|---|---|
| **Agent environment** | `impress_a`, `radical.*`, `rhapsody`, LLM client, and the in-process P6 libraries (RDKit, Biotite, AtomWorks, US-align, `paretoset`) | **≥3.11** (Dragon); 3.10 suffices for the mock/laptop path | conda/uv env, or its own container |
| **Tool environments** | Everything heavy: foundry/RFD3/MPNN/RF3, Boltz, Rosetta, GROMACS, OpenMM, IMPRESS | Each its own | Apptainer `.sif`, site module, or dedicated conda env |

Part A recorded IMPRESS at `requires-python >=3.9` and foundry at `>=3.12` and flagged it as a conflict.
**At this boundary it stops being one.** The agent never imports either; it invokes them across a process or
container boundary, exactly as IMPRESS's own examples invoke foundry via `apptainer exec`. Each tool brings
whatever interpreter it needs inside its own image.

**Corrected in Phase 4 by building it.** Part C originally set this floor at ≥3.12, inherited from
foundry - but foundry runs in a container and does not constrain the agent at all. The real floor is
rhapsody's Dragon extra (`dragonhpc==0.14.1`, documented ≥3.11). The reference implementation runs on
**Python 3.10**, which is sufficient for the entire mock/laptop tier.

The residual constraint is narrow and worth stating: the P6 tools *are* in-process, so they must be
co-installable with `radical.*`. That set is small and light, which is why P6 membership is
a meaningful design property rather than a bookkeeping detail.

## 2. Site configuration

Everything machine-specific lives in `sites/<name>.yaml` and nothing machine-specific lives in code. This is
where Part A's T6 portability matrix becomes operational.

```yaml
# sites/polaris.yaml
name: polaris
scheduler: pbspro                     # NOT slurm — Part A found prior art assumes slurm
backend:
  kind: dragon
  config: {...}
gpu: {vendor: nvidia, api: cuda, per_node: 4}
egress: {mode: direct}                # full HTTPS from compute nodes
filesystems:
  shared: /eagle/<proj>/impress_a
  scratch: /local/scratch
tool_delivery:
  default: apptainer
  image_root: /eagle/<proj>/containers
  overrides:
    rosetta: {kind: module, load: ["rosetta/2026.09"]}
resource_defaults:
  P1: {gpus: 1, cores: 8}
  P3: {nodes: 2, ranks_per_node: 32}
p5_governor: {max_concurrency: {colabfold_msa: 1, rcsb: 4}}
```

Three fields deserve comment.

- **`scheduler`** exists because Part A found *neither* prior-art execution layer speaks PBS Pro —
  `PyRosettaCluster` uses dask-jobqueue and AgentRosetta uses blocking `sbatch --wait`. Polaris and Aurora
  are PBS Pro. The agent emits no scheduler commands; this field configures the backend.
- **`gpu.api`** is what the compose-time portability gate checks each `ToolSpec`'s `gpu_portability` against.
  A campaign on `frontier` (`api: hip`) refuses to compose RF3 unless a site override says otherwise.
- **`p5_governor.max_concurrency`** is fixed configuration the agent cannot raise (Part B `07 §5`). On
  ColabFold it is `1`, honouring the server's documented request for serial single-IP queries.

**Platform priority is a decision, not an ordering of convenience.** Polaris and the NSF ACCESS machines
(Delta, Bridges-2, Expanse) are **primary** — CUDA throughout, where the generative stack runs today.
**Aurora is second**, justified by foundry's real first-party Intel XPU support. **Frontier is
deprioritized**: Part A found no HIP path anywhere in the ML core, making it a from-source porting spike
rather than a rebuild, and no such spike is scheduled.

Sites to start: `polaris`, `delta`, `aurora`, `local`, and `frontier`. `local` selects
`ConcurrentExecutionBackend(ProcessPoolExecutor)` and mock tool delivery — the laptop path. `frontier`
remains in the matrix with `gpu.api: hip`, which means the compose-time portability gate will **refuse** the
ML core there rather than fail at runtime. That refusal is the correct behaviour for a deprioritized
platform: the door stays visible and shut, and reopening it is a site-config override plus a spike, not a
redesign.

## 3. Containers

`containers/` holds definitions and build scripts, not images. Per Part A:

- `foundry.sif` — from `rosettacommons/foundry`, the path IMPRESS already uses.
- Separate images for Boltz, Rosetta, GROMACS/OpenMM.
- **Frontier is deprioritized, so no ROCm image is planned.** Part A found no HIP path anywhere in foundry;
  a ROCm build is a from-source spike, not a rebuild. `containers/frontier/` is *not* created. If the
  decision is ever revisited, ProteinMPNN is the recommended first target (no cuEquivariance dependency),
  then RFD3 (whose cuEquivariance import is already wrapped in a `try/except` with a PyTorch fallback), with
  RF3 last because its CUDA-12 kernel dependency is hard.

Checkpoint staging is separate from images and lives in `$IMPRESS_A_SHARED/checkpoints/` with recorded
hashes — because `foundry install` cannot detect a truncated download, the agent hashes what it actually
loads rather than trusting the download succeeded.

## 4. Secrets and credentials

The LLM oracle needs an API key on a compute node. Keys are read from the environment, injected by the job
submission, and **never** written to campaign storage. Provenance records the pinned model id and sampling
parameters — never the credential. Worth stating explicitly because provenance is otherwise deliberately
exhaustive, and an exhaustive log is exactly where a key ends up by accident.

## 5. Bootstrapping a new site

The porting checklist, in order — this is the practical test of whether the site abstraction holds:

1. Write `sites/<name>.yaml`.
2. Build or locate tool images; record paths.
3. Stage checkpoints and any local databases; record hashes.
4. Run the mock campaign (`05`) against the real backend with stub tools — validates scheduling without
   spending science.
5. Run the smoke campaign — one real tool per pattern.
6. Record measured costs and reconcile against Part A's T5 estimates (Part B `08` flags these as
   unmeasured literature figures).

Step 6 is not optional bookkeeping. Gate 5 refuses graphs on those estimates, so a site where they are badly
wrong will either block legitimate work or fail to prevent overruns.
