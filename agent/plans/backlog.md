# Backlog

Everything outstanding, as of the stagnation fix. Nothing here is started. Each item says why it
matters so the list can be triaged rather than worked through top to bottom.

State it is measured against: 77 tests passing, lint 41, import contract clean, all control models
run, the real Delta chain composes, dry-runs, and passes `impress-a preflight` for the ALR target
on Delta - but no line of the real toolkits has executed yet (A1).

---

## A. Blocked on a person, not on code

**A1. No real campaign has ever run.** Every claim about the real toolkits is validation, dry-run and
unit-level. `campaigns/_runs/` holds only mock runs.

**A2. `ligand_smiles` was empty** in both Delta campaigns - RESOLVED for the ALR target: both
campaigns now set it to the real value borrowed from the original IMPRESS project's small-molecule
benchmark (`campaigns/data/alr/ALR.smiles`), and `_check_ligand_smiles` (`cli/__init__.py`, wired
into both `run_campaign()` and `preflight()`) fails fast for any *future* target that leaves it
blank, instead of silently modeling no ligand. Verified on Delta: `impress-a preflight` on the
smoke campaign shows no `ligand_smiles` failure row.

**A3. Three unverified arguments — RESOLVED**, checked directly against the installed real
toolkits on Delta this session: LigandMPNN's `--seed`/`--number_of_batches` (confirmed correct as
originally written — `--batch_size` defaults to `1`, so `--number_of_batches <num_seqs>` alone gives
exactly `num_seqs` sequences), and Boltz's `--seed`. RFD3's contract, however, was **wrong**, not
merely unverified: `rfd3_agents.py` invoked `rfd3 design --config <json> --out <dir>`, but the real
CLI (`rfd3.cli:design`, a Typer app forwarding every arg as a Hydra `key=value` override) has no
`--flag` options at all - that invocation would have failed immediately. Rewritten to the real
`out_dir=`/`inputs=`/`diffusion_batch_size=`/`inference_sampler.num_timesteps=`/`seed=` contract; see
`toolkits/rfd3/SKILL.md`. Also found and fixed in the same pass: `boltz_predict` was missing the
required `--no_kernels` flag (a verified CUDA ABI mismatch, not optional); `ligandmpnn_design` had
no way to express a fixed-residue constraint (`--fixed_residues` is a real flag); none of the three
Rosetta toolkits had a way to pass a ligand `.params` file (`-extra_res_fa`), so a real ALR-ligand
PDB would likely raise in `pose_from_pdb()`. All four fixed; see each toolkit's `SKILL.md`.

**A5. The Dragon backend construction hang is bounded, not diagnosed.** Job 22318678 ran the full
2-hour allocation and was killed on the time limit after producing only Dragon's own infra-connect
log lines - no campaign log, no ledger entry, nothing else, for the whole run. Traced to
`rhapsody.DragonExecutionBackend.__init__` building Dragon's `Batch()` (results DDict, GPU-affinity
worker pool, telemetry) synchronously with no `await` points, blocking the event loop entirely -
the codebase's own heartbeat never fired once in 2 hours because of it. Now bounded by
`backend_startup_timeout_s`/`backend_startup_heartbeat_s` on `CampaignSpec` (see
`exec/backend.make_engine_bounded`, `docs/limitations.md`): a future stall fails loudly within
minutes instead of consuming the whole allocation silently. What remains open: *why* `Batch()`/
`Pool()` didn't complete inside 2 hours in the first place (most likely GPU-affinity worker
rendezvous or OFI/libfabric negotiation under single-node `-s` Dragon mode) is still unknown - that
needs a person on a real allocation, with the bounded timeout now giving a fast, clear failure to
iterate against instead of another silent multi-hour loss.

**A4. The rfd3_design rewrite needs a real smoke-run confirmation.** The Hydra contract and
`DesignInputSpecification` JSON shape are verified against the installed `rfd3` CLI's own source,
but the output-parsing half of `RFD3DesignAgent` (glob for `*.cif.gz`, convert via `cif_gz_to_pdb`)
was not re-verified against a real `out_dir` listing - confirm the exact output filenames on the
first real smoke run (`dump_prediction_metadata_json`/`output_full_json` are both `True` by
default, so this should be visible immediately).

## B. Silent-failure defences — unmet for the real toolkits

The project's central claim is that these tools fail *silently*. For the real toolkits that defence
is currently a threshold on each tool's own opinion of itself.

**B1. No structural QC gates.** Nothing checks the ligand is actually present in the output complex,
that there are no chain breaks, or that sequence length matches the contig. `mock_noodle` exists to
prove this failure mode is the dominant one; the real tools have no equivalent.

**B2. No known-bad fixtures.** `docs/reference/authoring-tools.md` requires `tests/` per tool holding
known-BAD outputs. Zero such directories exist, for any toolkit. A gate that has never seen the
output it was written to catch is an assertion, not a test.

**B3. `count_matches_request` is implemented and referenced by nothing** — while `FastRelaxAgent` was,
until recently, fabricating exactly the count such a gate would have caught.

## C. Unbuilt from the roadmap

**C1. MCP adapter.** The protocol and the HTTP adapter exist, so this is a second transport over a
settled interface.

**C2. Checkpoint/restart resume.** The ledger records run state and outcomes and `RunService.reattach()`
reconciles what a previous process left open — but nothing *resumes* a campaign from it.

**C3. P5 network-service governor** — caching, per-service concurrency caps, `Retry-After` backoff.

**C4. Cancellation cannot reclaim a running GPU.** Measured, not unknown: queued work is reclaimed,
running work is not, and the backend does not report which happened. Closing this needs cooperative
cancellation inside task agents, or a backend that can kill a process.

## D. Registry and spec-contract gaps

All undercut the documented "loading is validating" guarantee.

**D1. `ToolSpec` has no `extra="forbid"`** — pydantic ignores unknown keys, so a typo'd field in a
`spec.yaml` is silently dropped instead of failing at load.

**D2. `entry:` importability is never checked at load time** — only when `agent_for` is first called,
i.e. mid-campaign rather than at registration.

**D3. Entry-point discovery is documented but absent.** `authoring-tools.md` promises
`impress_a.toolkits` entry points; `registry.py` has no `importlib.metadata` call.

**D4. The SKILL.md ↔ spec integrity check is half-built and soft.** "Every tool mentioned must exist"
is not implemented; the forward direction is a naive substring test that appends to `errors` **without
disabling the toolkit**, contradicting the all-or-nothing claim in the same docs.

**D5. `filter_shape` declares no parameters**, so gate 3 rejects any composer-proposed tuning of it.

**D6. No `frozen_parameters` in any real toolkit.** The mechanism the authoring guide calls out as
mattering "as much as `parameters`" is exercised only by `mock_generate`.

**D7. `boltz_predict` is P1 while `use_msa_server: true` makes it egress-dependent.**
`compute-patterns.md` rule 4 says such a tool is P5 even with a local fallback; its own SKILL.md
admits the deviation. The validator therefore never applies P5's failure model to a call that can
fail on the network.

## E. Configuration that exists and does nothing

**E1. `sites/*.yaml` is read by no code** — both files say so in their own comments. Its
`tool_delivery: {real|mock}` switch is exactly what would have prevented the mock-chain-on-a-GPU bug.

**E2. Cost models are unmeasured literature guesses**, and gate 5 plus the interlock's 10% cap refuse
graphs against them. Already concrete: the smoke campaign's original budget rejected its own first
run. Early campaigns should record actual-vs-estimated per tool.

## F. Documentation debt

**F1. No ADR records the decoupling** — the largest architectural change in the repo, including the
`on_rejected` scope change (per-cycle → per-experiment, now enforced in two places) and the rebuttal
to `planning/phase3-prior-art/04-patterns-for-phase4.md:41`.

**F2. ADRs 0003, 0005, 0007 unamended** — the interlock's per-signature concurrency rule; ADR 0005's
"fixed at launch" now needing the reattach policy-identity check that `RunService` provides but
nothing enforces; ADR 0007's per-client cursor.

**F3. `planning/phase2-middleware/05-integration-map.md:60`** still claims there is no way to
enumerate the tasks of a run. Softened, not false: `workflow_id` tagging exists in asyncflow 0.5.1,
but no lookup API does.

## G. Engine semantics

**G1. Exploration cannot move the front, so it counts toward stagnation.** Nodes from the explore
chain (`rfd3 → ligandmpnn → boltz`) have no Rosetta metrics, so `pareto.feasible` rejects them against
`shape_complementarity ≥ 0.55`. Every informed explore landing then increments the stagnation
counter. With the shipped `stagnation_limit: 4`, a modeled campaign stops at t≈135 min, before the
first exploit run lands (`slides/timeline_model.py --limit 4`). This is latent, because no shipped
policy emits that chain yet. Raising the limit is the wrong fix. Stub:
[`exploration-vs-stagnation.md`](exploration-vs-stagnation.md).

---

## Recommended order

1. **B1/B2 QC hardening** — the central claim of the project is currently unbacked for real tools.
2. **A1-A3 the first real run** — needs a person, and everything else is speculation until it happens.
3. **D1-D4 registry hardening** — small, self-contained, restores "loading is validating".
4. **F1-F3 docs** — cheap, and the absent ADR is the one a future reader will most want.
5. **C1-C3** on demand; **C4** only if a real campaign shows abandoned runs holding GPUs.
6. **G1** before any `conduct()` reasoner that explores with a truncated chain ships. It is latent until then.

## Verification that applies to any item

`pytest tests -q` — 77 tests green, no allocation. `ruff check src tests` must not exceed 41.
Import contract: `policy` must not reach `tools`/`exec`/`runtime`; `compose` must not reach `exec`;
`core` imports nothing internal. `impress-a run campaigns/mock-stabilize.yaml --model D` and
`--model A` still terminate with a stated reason and a non-empty front, and
`impress-a run campaigns/delta-small-molecule-smoke.yaml --model D` must compose `rfd3_design…`,
never `mock_generate…`.
