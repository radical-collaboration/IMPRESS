# Stub: exploration cannot move the front, so it counts toward stagnation

**Status:** not started. Found on 2026-09-23 while modelling the explore/exploit timeline for the
lab deck (`slides/timeline_model.py`). Backlog item G1.

## Problem

In the small-molecule campaign, **exploration can never count as progress**. The executor will end a
campaign that is only exploring, even when the exploration is going well.

Three things in the code combine to cause this:

1. **Explore nodes are never feasible.** The exploration chain
   (`rfd3_design → ligandmpnn_design → boltz_predict`) skips Rosetta. Its nodes therefore have no
   `total_score` or `shape_complementarity`. `core/pareto.py::feasible` (line 56) calls
   `Objective.satisfied_by`, which returns `False` for a missing value (line 28). Any objective with a
   `min`/`max` therefore excludes such a node. `delta-small-molecule.yaml` constrains
   `shape_complementarity ≥ 0.55`, so no explore node can ever enter the front.
2. **Stagnation counts landings that leave the front unchanged.**
   `runtime/executor.py::_note_progress` (line 254) increments on every *informed* attempt that leaves
   the front id-set unchanged. That includes the case where the front is empty and stays empty. Every
   informed explore landing is exactly this.
3. **Early exploration is serial, so every run counts.** An untrusted shape has one instance in flight
   (`_admit_once`), so the first explore runs happen one at a time. Each is informed by the one before
   it, so each increments the counter. The informed-wave ruling (`plans/done/`) does not soften this,
   because until promotion there is no wave.

**Evidence (modeled, not measured).** With the shipped `stagnation_limit: 4`, the executor stops the
campaign at t≈135 min, before the first exploit run lands at t=144. That exploit run would have
produced the first front.

```
python3 slides/timeline_model.py --limit 4   # stop: t=135, "front unchanged over 4 informed attempts"
python3 slides/timeline_model.py             # limit 6: campaign runs to t=315, front forms at t=144
```

The smoke spec (`delta-small-molecule-smoke.yaml`, `stagnation_limit: 2`) is tighter still.

**Why this hasn't happened yet.** No shipped policy emits the truncated explore chain. `ThresholdPolicy`
explores by changing parameters on the *campaign's* six-tool chain. So this is latent: it will fire
the first time a `conduct()` reasoner explores the way the deck describes.

**Why raising the limit is the wrong fix.** Raising `stagnation_limit` would hide the problem. It is
the `10_000`-in-a-test pattern `CLAUDE.md` warns about: the engine parameter is being pushed to make
a scenario work, so suspect the engine first.

## The question to settle first

Is exploration *progress*? The executor currently has one measure of progress, a change to the front.
That is correct for exploitation and blind to exploration by construction. Termination belongs to the
executor (`CLAUDE.md` invariants; `docs/reference/architecture.md`), so the fix belongs there or in the campaign spec, not
in the reasoner.

## Candidate approaches (not yet chosen)

- **A screening front.** Keep a second, weaker ranking over the objectives a node *does* carry, such
  as `ligand_iptm` and `complex_plddt` for explore nodes. A change to it counts as progress. This keeps
  the main front strict. It needs a rule for which objectives a screening node is ranked on.
- **Stagnation measured per shape.** Count stagnation per pattern signature, and stop only when every
  active shape has stalled. This ties into the interlock's per-signature bookkeeping.
- **Declared in the spec.** Allow `objectives` entries to be marked `screening: true`, so feasibility
  ignores them when they are missing but ranking still uses them when they are present. This is the
  smallest change, but it weakens `feasible` for the main front too, which may be unacceptable.
- **Keep counting, but don't count explore runs while the front is empty.** This is cheap. It is also
  arguably wrong, because a campaign that only ever explores should still end eventually.

## Related, found at the same time

`ExperimentIntent.parent_node` only attributes lineage (`_absorb` sets `DesignNode.parent`). It does
not feed the parent's artifacts into the chain. So "exploit a promising node" today means "re-run its
*recipe* on the full chain", not "refine its structure". This is worth deciding alongside the above,
since both concern what exploitation means in this engine.

## Verification

- A campaign-scale test in `tests/test_campaign.py`:
  - a `conduct()` reasoner submits the truncated chain serially under the shipped
    `stagnation_limit`, then an exploit run;
  - assert the campaign is **not** stopped before the exploit run lands;
  - assert a campaign that *only* explores without improvement still terminates.
- `slides/timeline_model.py --limit 4` should no longer stop before t=144 once its stagnation rule
  mirrors whatever is chosen. Keep the model in step with `_note_progress`.
