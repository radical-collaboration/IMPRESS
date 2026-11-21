# asteer_design Toolkit

This project's own design-chain tools, all four of them: `liganchor_propose` (Model A's
anchor emitter), `rfd3_steered_design` (the steered generator), and `preorg_score` and
`affdelta_score`, the clients onto ROME's resident surrogate streams.

## Purpose

**These two tools hold no weights, and that is structural.** `TaskAgent`s are constructed and
discarded per invocation and `ToolSpec.agent` is inert (backlog H4), so nothing in an
impress-a task can keep a model loaded between calls. A `rome.Stream` is a resident,
hot-reloading inference service, and `rome/manager.py:172` —
`self.trainer.on_checkpoint(self.stream.on_checkpoint)` — makes a finished training round *be*
the event that swaps inference onto new weights without restarting the service. So ROME serves
Models B and C and these are thin clients over that seam (CON-6).

| Tool | Model | Serves |
|---|---|---|
| `liganchor_propose` | **A**, the anchor emitter | the ligand's Rosetta params file becomes the anchoring channel. A placeholder rule today; a trained `LigAnchor` head from round 2 (ROME item 8), resident from M4 |
| `rfd3_steered_design` | — | FK Tier 1: K particles, score the finished designs through B, resample under `G = exp(λ·r)`, re-noise with `partial_t`, re-denoise. The **only** tool here that needs a GPU, and the only one that needs the Foundry container |
| `preorg_score` | **B**, `pocket_preorg` | the FK potential `asteer.fk` consumes, once per particle per resampling event — the one surrogate that must be resident from M2 |
| `affdelta_score` | **C**, `aff_delta` | the corrected ΔG and the bound item 14 ranks on; a GP posterior update, so it may be fitted inside a task until its call rate justifies residency (M4) |

Both pass `structure` through unchanged, exactly as `filter_shape` and `packmin` do. A scoring
stage annotates a design rather than producing a new artifact, and keeping the port is what
lets the chain be reordered or extended without retyping it.

## Canonical sequences

The design chain, with the two stages that exist marked:

    liganchor_propose -> rfd3_steered_design -> preorg_score -> affdelta_score
    [this toolkit]        [this toolkit]          [this toolkit]  [this toolkit]

`preorg_score` before `affdelta_score` because B's risk score is what item 14 gates ABFE
acquisition on, so a design is scored for preorganisation before it is ranked on affinity.
Either runs alone against one structure; neither is a root — `structure` is a declared
required input, so the composer wires it and gate 1 type-checks it.

The laptop counterparts are `mock_preorg_score` and `mock_affdelta_score` in
`toolkits/mock_asd/`, which declare `toolkit: mock` and are therefore refused by a campaign
declaring `tool_delivery: real` (gate 6).

## Cost posture

Cheap, and the figures are CPU-hours because neither tool has a GPU: the GPU belongs to the
stream, which is ROME's resident service and is billed to the stream's own slot, not to the
task that asked it a question.

| Tool | Declared |
|---|---|
| `liganchor_propose` | 0.01 cpu-hours |
| `rfd3_steered_design` | **1.5 gpu-hours** |
| `preorg_score` | 0.01 cpu-hours |
| `affdelta_score` | 0.01 cpu-hours |

`rfd3_steered_design`'s figure is arithmetic over somebody else's measurement: 8 particles
over 4 denoising passes against `rfd3_design`'s measured 0.0405 h per pass is ~1.3 GPU-h, and
item 21 wants 2.25x the worst *observed*, which for this tool is nothing yet. It is declared at
1.5 and flagged, because the batch is one invocation rather than 32 and that is the part the
arithmetic cannot predict. Re-derive it from M2 before any real budget is sized on it.

The three CPU figures are **unverified declarations** rather than measurements — item 21 wants 2.25× the worst
observed and nothing has been observed yet. They are deliberately not padded: a scoring round
trip is milliseconds of local work plus however long the stream takes, and the stream's cost is
not this task's to declare. Re-derive both from M2's `cost_measured`.

## Pitfalls

**An absent stream raises; it never returns a default score.** This is the one behaviour in the
toolkit worth reviewing. A score defaulted on an outage is a well-formed number that enters the
design tree, gets ranked on, and trains the next round of the model that was supposed to produce
it — and no QC gate can catch it, because nothing about the payload is malformed. So an unbound
model, a stream that raises or times out, a stream answering the wrong shape, and a stream
answering for a different model are all `StreamUnavailable`. The campaign body binds a stream
with `impress_a.tools.asteer_design_agents.bind_stream(model_id, stream)` before the first scoring
stage runs.

**`dg_lcb` is omitted when `sigma_dg` is missing, never defaulted — and it is `mean + k·sigma`.**
ΔG is minimised, so the conservative bound is the *upper* one; getting the sign wrong makes an
uncertain design look like the best in the batch. And an LCB computed with a missing or zero
sigma simply *is* the posterior mean wearing the name of a conservative estimate, so the ranking
stops accounting for uncertainty with nothing to show that it did. Omitting it makes
`metrics_reported` fail, which is the integrity failure it actually is;
`rosetta/SKILL.md`'s `interaction_energy` note is the precedent, because 0.0 passes most bounds.

**`sigma_preorg` is declared and deliberately not gated, while `sigma_dg` is gated.** B's sigma
is informational — the FK potential uses the mean — so a model that reports none is usable. C's
is not: item 14 ranks on a bound, so a C with no sigma cannot be ranked at all and the omission
must be an integrity failure. The gate that *should* watch B's sigma is EI.7's
`calibration_in_range`, which is registered from `asteer.impress.gates` and resolvable only
where `IMPRESS_A_GATE_MODULES=asteer.impress.gates` is set (item 39, IMPRESS `6fc103b`). It is
not declared here because the launch path does not set that variable yet, and a spec declaring a
gate the registry cannot resolve makes **this whole toolkit register nothing**.

**`induced_fit_risk` is derived, never measured.** Decision L2: `md_label` measures
`preorg_rmsd`, `rotamer_entropy` and `ligand_rmsf`, and those are what a measurement supersedes.
The risk scalar is a judgement over them that B reports. Never ingest it as a label, and never
ingest `sigma_preorg`, `sigma_dg` or `dg_lcb` — they describe a posterior rather than a molecule
(`asteer.labels_workflow.POSTERIOR_ONLY`).

**Attribution is by construction here, not by checking.** `SurrogateResponse` cannot be built
without `(model_id, version)`, both sides of the seam import `asteer.contracts.surrogate`, and
the twins go through the same payload builder as the real clients — so a score with no model
cannot exist to be reported. `surrogate_version_present` is the second line of defence over the
payload, for a future adapter that builds one by hand.

**`select_hotspots` is never emitted, and the reason is not preference.** M0 measured it (job
`24155612`): the key resolves, all six requested atoms are annotated on `atom_array_input`, and
then `build()` drops the annotation — so `feats.is_atom_level_hotspot` reaches the network as
zeros while the run completes and reports success. `infer_ori_strategy: "hotspots"` cannot build
at all. The hotspot branch was never a branch; it was a silent no-op. Items 26 and 29, and
`tests/test_liganchor.py` asserts no code path produces the key, because RFD3's own
documentation points at it.

**The CFG channel's key spelling is unverified and is therefore a parameter.** The source spec
writes `active donor` with a space in two places and `active_donor` with an underscore in
others, and settling it needs the Foundry container. A wrong key is item 26's failure exactly —
a run conditioned on nothing that reports success — so `cfg_feature_keys` is a campaign
parameter and the agent refuses anything but three of them, because two would drop a channel
silently. Correct it from the container at M2, in YAML, not in a release.

**A donor is read from the params file's bond graph, never from an atom-type table.** A heavy
atom bearing a polar hydrogen is a donor, which is Rosetta's own definition and is what the file
describes. On `ALR.params` this is the difference between a measurement and a guess: two `OH`
oxygens, one `Hpol`, so **one** donor. An atom-type table would have claimed two and the channel
would have asserted an H-bond donor the file does not describe. Acceptor status is the one thing
that needs a lookup, and an atom type with no stated role **refuses the run** rather than
defaulting to apolar — which would shrink the anchor set with nothing to show for it.

**`rfd3_steered_design` is a new tool and not a mode of `rfd3_design`.** That is what keeps the
unsteered control arm intact, so M2 runs both at the same N. A control arm that exists only as a
preserved capability is not a control: without it neither the inertness check nor the outer
loop's success criterion can be read.

**`length` is dropped whenever `partial_t` is set, and the drop is reported.** RFD3's validator
rejects the combination — *"Length argument must not be provided during partial diffusion"* —
and the sibling example paid for it: job `21928556`, three of three pipelines that reached
guided feedback crashed on their first attempt, fixed with `partial.pop('length', None)`. The
project's own `ALR_binder_design.json` carries both, and that file is target identity, so
refusing it would mean hand-editing the thing that identifies the target. The renderer drops it
and reports `length_dropped`, so provenance shows the edit rather than hiding it. Backlog C8.

**Two conditioning checks exist at two layers. Do not read one as the other.**
`conditioning_requested` and `conditioning_applied` on this tool count atoms **into the JSON it
renders** — the half this project controls, checkable with no GPU. Whether the annotation then
survives RFD3's `build()` into `feats` needs the container, is what
`asteer.conditioning.check_from_pipeline` is for, and is an M2 measurement. A green
`conditioning_applied` here does **not** mean the model was conditioned; it means we did not
drop the atoms on the way out.

**The burial channel reaches RFD3 through `select_buried` / `select_exposed`.** Those are in the
documented `DesignInputSpecification` key list and in this project's own committed input. The
CFG trio (`active_donor`, `active_acceptor`, `ref_atomwise_rasa`) is **off by default** behind
`emit_cfg_features`: it appears nowhere in impress-a, nowhere in the documented key list, and
not even consistently spelled in the source specification, and a wrong key is item 26 exactly.
Better evidence is not proof — M0 did not test these two either — so `conditioning_applied` is
declared as an **integrity** gate and M2 is where the question is settled.
