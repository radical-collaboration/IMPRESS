# ALR's MD parameters, typed once (K1)

`ligand_parameters.json` is the artifact; everything else here is what produced it or what it
describes. **Do not edit any of these files in place.** The artifact carries a SHA-256 of
`ligand.mol2` and `ligand.frcmod`, and `LigandParameters.verify` refuses a directory whose
bytes have moved — because after an in-place edit every label in the corpus was measured with
something other than what the artifact says, and nothing else would disagree.

## Why these files exist at all

There is **exactly one ligand** across this project's entire campaign history: identical SMILES
in 267/267, 112/112, 182/182 and 423/423 `boltz_input.yaml`, and the same
`input_pdbs/scaffold-with-ALR.pdb` behind every rfd3 input (audit finding 4, 2026-11-23). The
single-ligand degeneracy that makes Model A's training data unusable makes this cheap: the
ligand is typed once, committed, and read by every MD run, rather than re-typed per design at
the cost of an AM1-BCC calculation each time and a different charge set whenever a tool version
moves.

## The force field, and why it is not CGenFF

**GAFF2 with AM1-BCC charges, mixed with a CHARMM36m protein and TIP3P water.** The stated
pairing is CGenFF for the ligand, and `par_all36_cgenff.prm` and `top_all36_cgenff.rtf` are on
disk — but there is no CGenFF binary on this machine, and typing needs ParamChem, a web service
wanting network access and an account. That is the same operational shape as PLINDER and not
something a protocol body can assume, so the offline route is taken and **named in the
artifact**: a force field is part of what a measured number means, and a `preorg_rmsd` measured
under GAFF2 and one measured under CGenFF are two measurements.

`force_field` travels into every label's provenance. The artifact is built to take CGenFF
parameters whenever somebody has an account; nothing else has to change.

## What the run found, 2026-11-23

| | |
|---|---|
| Atoms | 44, of which **30 heavy** — which matches the 30 HETATM in the complex |
| Formal charge | **−2** (two sulfonates), so **two Na⁺** neutralise the ligand |
| Charge sum | **−2.004003** from AM1-BCC, corrected to −2.000000 and the residual **recorded** |
| GAFF2 types | `c3 ca h1 ha hc ho ne nf o oh os s6` — the azo nitrogens typed `ne`/`nf` rather than guessed |
| parmchk2 penalties | **seven, all impropers**, max score **6.0** |
| Template match | **ambiguous** — see below |

**The charge residual is the one worth knowing about.** AM1-BCC computes charges per atom and
they do not sum to the formal charge exactly. Left alone, the system's net charge is not an
integer, and PME neutralises that with a uniform plasma — so energies come out shifted by an
amount that depends on the box volume and nothing reports it. Every MD setup distributes the
residual; almost none records it. It is recorded here, so a reader who finds a 1e-4 charge
offset in a topology can find out it was put there on purpose.

**The penalties are all impropers, which is the good case.** The `BOND`, `ANGLE` and `DIHE`
sections of `ligand.frcmod` are empty: GAFF2 had every one of those parameters exactly. The
seven it guessed are aromatic-ring impropers taking either the default value or the general
`X-X-ca-ha` analogy at penalty 6.0, which is routine for a substituted aromatic. **The azo
group — the coverage the plan flagged as the weak point — was typed, not guessed.**

**The template match is ambiguous and that is recorded rather than silenced.** ALR is nearly
symmetric, so its pose matches its SMILES template more than one way and RDKit picks one.
Which mapping was picked decides every atom *name*. A later run that picked the other one
produces the same energies under different names, so a corpus whose rows came from two runs
would have atom names that do not line up — which is why `template_match_ambiguous` is a field
and not a log line.
