# Stub — structural QC gates and known-bad fixtures

**Status:** B2 done, B3 partly. B1 — the structural gates — not started, and still the next
recommended track. See `plans/local-verification.md` for what the fixture harness now covers.

## Problem

Part A's dominant finding, and the reason this project exists, is that scientific tools fail
*silently* far more often than they crash. `mock_noodle` manufactures that failure on purpose: it
completes, reports a confident `designability`, and produces a structure with no secondary structure.
Only a QC gate catches it.

The real toolkits have no equivalent defence. Their gates are almost entirely `metric_in_range`
against a metric the tool **reports about itself** — `complex_plddt`, `ligand_iptm`,
`overall_confidence`, `total_score`. A confidently-wrong tool passes every one of them, which is the
precise failure mode the gates exist to catch. Both `boltz/SKILL.md` and `rosetta/SKILL.md` already
flag their thresholds as uncalibrated guesses.

Every non-mock tool now carries the `tests/` known-bad fixtures `authoring-tools.md` requires, so
each tool's *declared* gates have been seen to fail on output that should fail them. That closes the
"never seen the output it was written to catch" objection for the gates that exist — and leaves the
real gap exactly where this plan says it is: **none of those gates is structural**. A fixture can
only exercise a gate that exists.

## Shape of the work

Gates are shared by id from `tools/gates.py` via the `@gate` decorator, and take
`(raw_output_dict, params) -> GateResult`. Candidates, each checking a *structural fact about the
artifact* rather than a number the tool chose to report:

- **ligand present in the complex** — the campaign is small-molecule binding; a complex with no
  ligand is the highest-value silent failure available.
- **no chain breaks** — consecutive CA-CA distance within range.
- **sequence length matches the contig** — RFD3 is asked for `A1-100`; check it delivered that.
- **ligand not clashing / actually in a pocket** — buried surface area or a contact count.

`_pdbtools.py` currently holds only `secondary_structure_fraction` and `cif_gz_to_pdb`, so most of
these need new helpers. Keep Biopython/gemmi imports inside function bodies — `Registry.load()` and
`dry_run` must keep working with none of the science stack installed, which is what makes the laptop
tier possible.

Fixtures go under `toolkits/<tk>/tools/<id>/tests/` in the format `authoring-tools.md` now
documents, and must include at least one known-BAD output per gate; `test_gate_fixtures.py` picks
them up with no code change. A structural gate needs a structural fixture, which is the first thing
in this plan that will need a real artifact on disk rather than a JSON payload — and Biopython is
importable in the dev venv while gemmi and PyRosetta are not. Write the gate against a failure
actually seen, not an imagined one.

## Watch out for

Gate ids are validated at load: an unknown id means the toolkit registers **nothing**. Add the gate
implementation before referencing it from a spec, or the whole toolkit disappears.

Thresholds are campaign-affecting. A gate that is too strict turns every result into a QC FAIL, and
a FAIL node is never rankable — the campaign would look like it is producing nothing rather than like
the gate is wrong.

## Verification

Each new gate needs a test that feeds it a known-bad fixture and asserts FAIL, plus a good one
asserting PASS. `pytest tests -q` stays green; `impress-a tools` must still list all 11 tools, since
a bad gate id silently removes a whole toolkit.
