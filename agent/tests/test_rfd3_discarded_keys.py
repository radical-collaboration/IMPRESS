"""The key rfd3 accepts and throws away, refused by the only layer that can refuse it.

Measured on job `24155612` inside the Foundry container. A **ligand** `select_hotspots`
resolves the residue code and annotates every requested atom `is_atom_level_hotspot` on
`atom_array_input` -- and then `DesignInputSpecification.build()` drops the annotation
entirely, so `constants.py` supplies the zero default and `feats.is_atom_level_hotspot`
reaches the network as all zeros. With `infer_ori_strategy: "hotspots"` the run asserts at
build time; with any other strategy it **runs to completion, writes its outputs and exits 0**,
conditioned on no hotspots at all, and nothing in the run says so.

The first measurement of this said *reaches the model: yes* and was wrong -- the detector had
counted the request string echoed back in `specification.select_hotspots`. The last test here
is that mistake made into an assertion.

RFD3 is a fixed binary in `foundry.sif` and the toolkit `entry` is a wrapper around it, so the
wrapper is the only layer that can act. `toolkits/rfd3/SKILL.md` has carried this as a Pitfall
since `a79be57`: a Pitfall tells a reader, and a refusal tells the run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from impress_a.tools.rfd3_agents import (
    DISCARDED_SPEC_KEYS,
    SUPPORTED_SPEC_KEYS,
    refuse_discarded_spec_keys,
)

#: The shape of this project's own committed input, which is the shape that matters: `ligand`
#: is the literal `A:R` -- ALR's real value, deliberately not the bare `ALR` -- and the
#: atom-level selections are keyed by that same literal.
LIGAND = "A:R"


def _spec(**over) -> dict:
    entry = {"input": "input_pdbs/scaffold-with-ALR.pdb", "ligand": LIGAND,
             "length": "70-170",
             "select_buried": {LIGAND: "C18,C19,N12,O3"},
             "select_exposed": {LIGAND: "C13,C14,O4,O6"}}
    entry.update(over)
    return {"partial": entry}


def test_a_ligand_hotspot_is_refused_and_the_message_names_the_key():
    spec = _spec(select_hotspots={LIGAND: "S1,O5,O7,O8,S2,O6"})

    with pytest.raises(RuntimeError) as caught:
        refuse_discarded_spec_keys(spec, "ALR_binder_design.json")

    why = str(caught.value)
    assert "select_hotspots" in why
    assert LIGAND in why
    assert "accepts and discards" in why
    assert "select_buried" in why, "a refusal should name what to use instead"
    assert "ALR_binder_design.json" in why, "and which file it was reading"


def test_the_message_enumerates_the_keys_that_are_honoured():
    """So the answer is in the refusal rather than in a document the reader has to find."""
    spec = _spec(select_hotspots={LIGAND: "S1"})

    with pytest.raises(RuntimeError) as caught:
        refuse_discarded_spec_keys(spec, "x.json")

    for key in SUPPORTED_SPEC_KEYS:
        assert key in str(caught.value), key


def test_a_protein_hotspot_keyed_by_a_chain_is_untouched():
    """Only ATOM-level hotspots are dropped by `build()`.

    A protein `select_hotspots` reaches the model, so refusing it would break a capability to
    fix a different one. The discriminator is the entry's own declared `ligand`, not the shape
    of the key -- `A:R` versus `A` is one character, and the committed ligand code is the
    stranger of the two.
    """
    refuse_discarded_spec_keys(_spec(select_hotspots={"A": "12,15,30"}), "x.json")


def test_a_hotspot_on_a_ligand_this_entry_does_not_declare_is_untouched():
    """The check is per entry, against that entry's own ligand.

    A multi-entry spec is one file describing several designs, and a key that names a residue
    code this design does not use is not this design's problem.
    """
    refuse_discarded_spec_keys(_spec(select_hotspots={"B:X": "S1,O5"}), "x.json")


def test_the_committed_input_passes_because_it_uses_the_honoured_keys():
    """The regression this must not become: refusing the project's own real input.

    `select_buried`/`select_exposed` are the documented atom-level channel and are what the
    committed spec uses, which is the whole reason the refusal is affordable.
    """
    real = Path(__file__).resolve().parents[1] / "campaigns" / "data" / "alr" \
        / "ALR_binder_design.json"
    if not real.exists():
        pytest.skip("the committed ALR input is not in this checkout")
    spec = json.loads(real.read_text())
    assert any("select_buried" in e for e in spec.values() if isinstance(e, dict)), (
        "this test would prove nothing against an input with no atom-level selection"
    )
    refuse_discarded_spec_keys(spec, str(real))


def test_an_entry_with_no_ligand_at_all_is_not_a_crash():
    """A de novo spec with no ligand is ordinary, and `select_hotspots` on it is a protein
    hotspot by construction."""
    spec = {"denovo": {"input": "x.pdb", "length": "70-170",
                       "select_hotspots": {"A": "12,15"}}}
    refuse_discarded_spec_keys(spec, "x.json")
    refuse_discarded_spec_keys({"denovo": {"input": "x.pdb"}}, "x.json")
    refuse_discarded_spec_keys({}, "x.json")
    refuse_discarded_spec_keys([], "x.json")


def test_the_echo_cannot_satisfy_the_check():
    """The mistake the first measurement made, as an assertion.

    The detector that reported *reaches the model: yes* had counted the request string echoed
    back in `specification.select_hotspots` on the way out. So a spec that carries the key only
    under some other container -- a recorded `specification` block, say -- is NOT a request,
    and a spec that carries it as a real selection IS, whatever else the file holds.
    """
    echoed = {"partial": {"input": "x.pdb", "ligand": LIGAND,
                          "specification": {"select_hotspots": {LIGAND: "S1,O5"}}}}
    refuse_discarded_spec_keys(echoed, "x.json")

    real = dict(echoed)
    real["partial"] = {**echoed["partial"], "select_hotspots": {LIGAND: "S1,O5"}}
    with pytest.raises(RuntimeError):
        refuse_discarded_spec_keys(real, "x.json")


def test_every_discarded_key_carries_the_measurement_behind_it():
    """A refusal with no evidence is a refusal nobody can argue with or overturn."""
    assert DISCARDED_SPEC_KEYS, "the table is empty; nothing is being refused"
    for key, why in DISCARDED_SPEC_KEYS.items():
        assert key not in SUPPORTED_SPEC_KEYS, f"{key} is in both lists"
        assert "measured" in why.lower(), f"{key} names no measurement"
        assert len(why) > 200, f"{key}'s reason is too short to be a reason"
