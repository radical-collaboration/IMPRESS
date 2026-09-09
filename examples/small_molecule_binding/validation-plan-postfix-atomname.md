# Validation plan: RFD3 guided-input atom-name fix

Reference this after the next full HPC production run, once the atom-name mapping fix
(graph isomorphism + Kabsch tie-break in `_infer_ligand_atom_mapping` /
`_normalize_ligand_atom_names`, `small_molecule_binding.py`) has been deployed. Goal: confirm
the fix actually resolved job 21916521's crash pattern, and specifically probe the residual
risks flagged in planning that couldn't be closed by code review alone.

## 1. Did the crash pattern actually go away?

- `grep -c "ComponentValidationError" impress_<jobid>.out` — expect **0** occurrences (job
  21916521 had one per pipeline, 4/4, each fatal).
- `grep -c "Pipeline FAILED" impress_<jobid>.out` — any hits need individual triage; none
  should trace back to a guided-RFD3 atom-name mismatch anymore. If any pipeline still dies
  on its first guided-feedback attempt, the fix did not work and needs re-examination before
  trusting anything else in this file.
- Compare `rfd3` attempt counts and final `ensemble=N` sizes per pipeline against job
  21916521's baseline (p1: 17 rfd3 / 69 ensemble; p2: 14 / 61; p3: 9 / 42; p4: 20 / 96, all
  crashed short of `max_tasks=300`). Pipelines should now run substantially longer and/or
  reach `max_tasks` — if they still terminate early, check whether it's a *new* failure mode
  (see §4) rather than the same one recurring.

## 2. Did the guided inputs actually validate correctly this time?

- Run `python scripts/validate_run.py logs p1` (and p2–p4) against the new run's output —
  the new check 8 (`check_guided_ligand_atom_names`) should pass for every
  `*_rfd3/in/guided_scaffold.pdb` found. If the new run reused this same validate_run.py
  against the *old* job 21916521 logs first, confirm it correctly flagged those as broken
  (proves the check itself discriminates, not just rubber-stamps).
- Spot-check at least one fresh guided pair directly: confirm every name in
  `guided_binder_design.json`'s `select_exposed`/`select_buried` is present among the ligand
  HETATM atom names in the sibling `guided_scaffold.pdb`.

## 3. Residual risk: `DetermineConnectivity`'s distance tolerance on real Boltz geometry

This was flagged as unvalidated against actual Boltz-predicted (not crystallographic) ligand
geometry at plan time.

- For each fresh `guided_scaffold.pdb` produced this run, check the perceived bond/degree
  distribution against `ALR.params`'s (or whichever ligand's) known valences (e.g. each S
  should have exactly 4 heavy neighbors). A mismatch here — even if the run didn't crash —
  signals `covFactor=1.3` may be silently producing a technically-valid-but-wrong isomorphism
  that happened not to trip the coverage check.
- If any pipeline used a different ligand than `ALR` this run (`IND`, `RED`, or `IAI` via
  `sm_binder_design.json`), re-run this check per ligand — the tolerance was only validated
  against `ALR`'s real crash artifacts during implementation.

## 4. Residual risk: near-tie isomorphism candidates (symmetry ambiguity)

Recommended addition during implementation: log the RMSD gap between the winning isomorphism
candidate and the next-best one every time `_infer_ligand_atom_mapping` succeeds. If that
logging was added:

- `grep` the new run's logs for these RMSD-gap lines. A small gap (near-tie) on any accepted
  mapping is a signal the tie-break may have picked arbitrarily between two graph-valid but
  possibly semantically different atom assignments — flag any such case for manual review
  even if the run didn't crash, since a wrong-but-plausible mapping degrades guidance quality
  silently rather than failing loudly.
- If this logging was *not* added during implementation, add it now before trusting any
  further runs that touch a ligand other than `ALR` — `ALR` was proven benign (its two ring
  systems aren't isomorphic to each other, and its only symmetric atoms — each sulfonate's 3
  terminal oxygens — always land in the same exposed/buried bucket), but that guarantee does
  **not** extend to `IND`/`RED`/`IAI` or any future ligand without checking their own
  topology.

## 5. Residual risk: `rdkit` dependency / env pin compatibility

- Confirm `pip check` is clean in the run's actual venv (no regressions from adding `rdkit`
  alongside the existing `boltz`/`gemmi==0.6.5`/`numpy` pins).
- Confirm `boltz` and `gemmi`-dependent steps (co-folding, `mpnn()`'s CIF.GZ→PDB conversion)
  still function normally elsewhere in the same run — a silent pin downgrade caused by
  `rdkit`'s install could show up as an unrelated failure downstream, not necessarily at the
  `rdkit` import site itself.

## 6. Residual risk: `gemmi` atom-name rewrite correctness

`_normalize_ligand_id`'s residue-name rewrite via `gemmi` was already proven correct in
production; atom-name rewriting via the same API was new and only spot-checked (write,
re-read, confirm column alignment) during implementation, not exercised against a real HPC
run until now.

- Re-read a fresh `guided_scaffold.pdb`'s ligand HETATM block and confirm fixed-column PDB
  parsing (as `_load_reference_coords`/`_iter_hetatm_resnames`-style code depends on) still
  finds the residue and every atom name correctly — no column misalignment, no truncated
  names, especially for the 1-character element names (`S1`, `S2`, `O3`, etc.) that weren't
  present in Boltz's own longer names (`S43`, `O24`).

## 7. New-ligand onboarding checklist (for whenever this comes up next)

Not specific to this run, but worth attaching here since it's the same unresolved gap: before
trusting guided feedback for a ligand other than `ALR`, manually verify its two "sides"
(whatever `select_exposed`/`select_buried` partition into) aren't graph-isomorphic to each
other — if they are, the isomorphism step could in principle map the wrong side onto the
wrong bucket without tripping any automated check. `scripts/check_ligand_atom_mapping.py`
(added with this fix) is the tool to run manually against the new ligand's `.params` +
reference PDB before it's ever used in a live guided run.
