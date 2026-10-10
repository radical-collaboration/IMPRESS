# Rosetta / RosettaScripts

**One-line identity.** A ~20-year-old, physics/statistics-hybrid macromolecular modeling suite whose XML-scriptable `rosetta_scripts` binary is the primary interface for relax, design, docking, and interface-analysis protocols used across all four in-scope problem classes.

## Identity
- **Version / release examined:** no tagged release in the refcode checkout; `source/version.py` derives the version string from `git describe`/commit id at build time (no static `VERSION` file). Score function identity is pinned by weights files: `database/scoring/weights/ref2015.wts` (comment: "beta_nov15 ... following parameter refitting (Frank DiMaio and Hahnbeom Park), November 2015") and `database/scoring/weights/beta_nov16.wts`.
- **Provenance:** RosettaCommons (100+ academic labs), managed by University of Washington. Refcode path: `tools/rosetta/`.
- **Maturity:** production. Continuously developed since ~2005; used in dozens of published de novo design, enzyme design, and stability campaigns.

## Scientific role
Rosetta is the physics-based scoring/sampling engine underneath three of the four in-scope problem classes:
- **stability/thermostabilization** — `FastRelax` (refinement), `cartesian_ddg`/`ddg_monomer` (see `rosetta-ddg.md`)
- **enzyme/catalytic design** — `enzyme_design`/`match` apps (see `rosetta-enzyme-design.md`)
- **small-molecule binding** — ligand `.params` parameterization, `FastDesign` with ligand-aware constraints
- **de novo binder design** — post-hoc scoring/refinement of ProteinMPNN/RFdiffusion output via `FastRelax`, interface analysis via `InterfaceAnalyzer`

Pipeline stages occupied: **generate** (FastDesign sequence/rotamer sampling), **simulate/relax** (FastRelax), **score** (`ref2015`/`beta_nov16` score functions, `InterfaceAnalyzer`), **analyze** (score-term decomposition, buried-unsat/packstat/shape-complementarity metrics).

### The four protocols that matter to us

**FastRelax** (`source/src/protocols/relax/FastRelax.cc`) — a scripted ramp of `fa_rep` weight interleaved with repack/minimize cycles, driven by a small script language (`repeat`, `scale:<scoretype>`, `repack`, `min <tol>`, `ramp_repack_min`, `accept_to_best`) read from a "relax script" file. Real default script, `database/sampling/relax_scripts/MonomerRelax2019.txt`:
```
repeat %%nrepeats%%
coord_cst_weight 1.0
scale:fa_rep 0.040
repack
scale:fa_rep 0.051
min 0.01
coord_cst_weight 0.5
scale:fa_rep 0.265
repack
...
accept_to_best
endrepeat
```
Supports `cartesian` and `dualspace` modes (`FastRelax::cartesian()`, `FastRelax::dualspace()`, parsed from RosettaScripts tags `cartesian="true"` / `dualspace="true"`), which switch the minimizer between `AtomTreeMinimizer` (torsion space) and `CartesianMinimizer` (xyz space, needs `*_cart.wts` score functions). `database/sampling/relax_scripts/` ships ~20 named scripts (`InterfaceRelax2019`, `PolarDesign2019`, `legacy`, each with `.dualspace` and score-function-specific variants).

**FastDesign** (`source/src/protocols/denovo_design/movers/FastDesign.cc`) — subclasses FastRelax and adds a `TaskFactory`/packer palette so design (sequence change) happens inside the same ramped repack/minimize cycles, rather than as a separate step. XML options include `task_operations`, `cgs` (compositional generalized sequence constraint groups), `clear_designable_residues`, plus all inherited FastRelax options.

**InterfaceAnalyzer** (`source/src/protocols/analysis/InterfaceAnalyzerMover.cc`, app `source/src/apps/public/analysis/InterfaceAnalyzer.cc`) — separates a complex across a jump, repacks each side, and reports `dG_separated`, `dSASA` (total/interface, with per-region and per-residue breakdowns), `packstat` (`compute_packstat_`), `delta_unsat_hbonds`, and shape complementarity (`compute_interface_sc_`, Lawrence-Colman `sc`). This is the standard binder-interface scorecard.

**Scoring function** — `ref2015` (default full-atom score function since ~2017) and `beta_nov16` (successor, used by `MonomerRelax2019.beta_nov16.txt` etc.) are both weighted linear combinations of `fa_atr/fa_rep/fa_sol/fa_elec/hbond_*/rama_prepro/omega/p_aa_pp/fa_dun/...` terms plus a `ref` per-amino-acid reference energy correction and a `METHOD_WEIGHTS` block used only during packing. Cartesian-mode work requires the `_cart` (and `_cart_cst`) weight-set variants (`ref2015_cart.wts`, `beta_nov16_cart.wts`) because `cart_bonded` replaces the internal-coordinate bond terms implicit in torsion-space scoring.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI binary `rosetta_scripts` (built from `source/src/apps/public/rosetta_scripts/rosetta_scripts.cc`, not separately inspected here but standard entrypoint), driven by an XML protocol file and flags:
  ```
  rosetta_scripts.<extras>.<os><compiler>release \
      -parser:protocol my_protocol.xml \
      -in:file:s input.pdb \
      -nstruct 50 \
      -out:path:all outdir/ \
      -score:weights ref2015
  ```
  Also usable as a `Mover` from PyRosetta (`pyrosetta.rosetta.protocols.relax.FastRelax`, `pyrosetta.rosetta.protocols.denovo_design.movers.FastDesign`, `pyrosetta.rosetta.protocols.analysis.InterfaceAnalyzerMover`) — see `pyrosetta.md`.
- **Inputs:** PDB or Rosetta silent-file structures; an XML `<ROSETTASCRIPTS>` document defining `<SCOREFXNS>`, `<RESIDUE_SELECTORS>`, `<TASKOPERATIONS>`, `<MOVERS>`, `<FILTERS>`, `<PROTOCOLS>`; a relax script text file (optional, `relaxscript` tag) for FastRelax/FastDesign.
- **Outputs:** output PDB(s) or silent file(s), a `score.sc` tab-delimited scorefile (one row per `nstruct` decoy, one column per score term plus any Filter-reported values), stdout log with per-cycle tracer output.
- **A concrete example (from the repo's own relax script + weights, assembled per documented convention):**
  ```xml
  <ROSETTASCRIPTS>
    <SCOREFXNS>
      <ScoreFunction name="ref15" weights="ref2015"/>
    </SCOREFXNS>
    <MOVERS>
      <FastRelax name="relax" scorefxn="ref15" relaxscript="MonomerRelax2019"/>
    </MOVERS>
    <PROTOCOLS>
      <Add mover="relax"/>
    </PROTOCOLS>
  </ROSETTASCRIPTS>
  ```
  (`relaxscript` resolves against `database/sampling/relax_scripts/`, confirmed by `FastRelax::get_possible_relax_script_names()` in `FastRelax.cc:1212`.)

## Compute pattern
- **Pattern:** **P2** (CPU-parallel fan-out, in-job) primary — `nstruct` decoys are embarrassingly parallel, independent single-node jobs. **P3** secondary when built/run with `extras=mpi` (`source/tools/build/setup.py` recognizes `mpi` as a build extra) and the MPI job distributor is used to fan a single `rosetta_scripts` invocation across many ranks/nodes for very large `nstruct` — this is a reserved rank topology, not resizable mid-run.
- **GPU vendor portability:** **CPU-only**. `grep -rl "CUDA\|__CUDACC__" source/src/protocols` returns essentially nothing in the core protocol tree (the one hit, `MIFST.cc`, is a deep-learning inverse-folding bridge, not FastRelax/FastDesign/ddg/enzdes). Rosetta's compute-heavy inner loops (packer, minimizer) are pure CPU C++.
- **State model:** restart-required at the decoy level (a killed FastRelax run must restart that decoy from scratch; there is no mid-decoy checkpoint), but **checkpointable at the ensemble level** — since `nstruct` decoys are independent, a killed batch can resume by only re-submitting decoys whose output is missing from the scorefile.
- **Data locality:** shared-FS required for MPI runs (all ranks read the same input PDB/XML/database); self-contained for single-node P2 fan-out (each rank/process needs only its own copy of inputs plus the ~1-2 GB Rosetta `database/` directory).
- **Staging burden:** the Rosetta `database/` directory (rotamer libraries, fragment statistics, score-term lookup tables) — no large model-weight download, but the checked-out `database/` in this refcode is itself hundreds of MB and must be present at runtime via `-database` flag or the `ROSETTA3_DB` environment variable.
- **Container availability:** **official** — `rosettacommons/rosetta` on Docker Hub per `README.md` ("the images have both Rosetta and PyRosetta pre-installed"); the repo's own `docker/` directory (`docker/rosetta-ubuntu-22.04.dockerfile` etc.) only documents *build environments*, not a pre-built binary image — confirmed by `docker/README.md`: "these recipes does not actually clone/build Rosetta ... and only serve as examples."

## Deployment on DOE & ACCESS
No GPU dependency means Rosetta is platform-agnostic across Frontier/Aurora/Polaris/ACCESS in principle, but there is **no prebuilt Rosetta binary for any of these leadership architectures** — it must be compiled from source with `scons.py -j<N> mode=release bin` (optionally `extras=mpi` for the MPI job distributor, `extras=mpi,static` for a portable static binary suited to compute-node execution without shared-library path issues). Build-required on all five target platforms; conda packages exist (`conda.rosettacommons.org` / `conda.graylab.jhu.edu` channels, per `README.md`) but those are built for generic x86_64 Linux and are not guaranteed to match leadership-machine CPU targets (AMD Zen on Frontier vs. Intel Xeon on Aurora/Polaris/ACCESS nodes) — recompiling from source with platform-tuned flags is the safer path. Apptainer is the natural deployment unit: build once per CPU architecture, ship a `.sif`. The **license gate applies uniformly**: Rosetta requires a UW-CoMotion non-commercial (or paid commercial) license acceptance before download/build; this is a one-time human step, not something the agent can self-serve, and must be resolved before Phase 1 compute-node deployment.

## Agentic surface
- **Native MCP:** community / unverified. A third-party server exists (`Arielbs/rosetta-mcp-server`, PyPI package `rosetta-mcp`) offering XML validation, RosettaScripts execution, and documentation lookup tools; it is not affiliated with RosettaCommons and at least one third-party safety scanner flags it as low-trust. No official RosettaCommons MCP server exists.
- **Parameters worth exposing for autonomous variation:**

| parameter | type | sane range | default | trade-off |
|---|---|---|---|---|
| `nstruct` | int | 1–500 (P2 fan-out) | protocol-dependent, often 1–50 | more decoys = better sampling of the funnel, linear CPU cost |
| `scorefxn` (weights file) | enum | `ref2015`, `beta_nov16` (+ `_cart`/`_cst` variants) | `ref2015` | beta_nov16 changes packing/relax behavior non-trivially; do not mix mid-campaign |
| `relaxscript` | enum/file | any file in `database/sampling/relax_scripts/` | `MonomerRelax2019`/legacy default | script choice changes ramp aggressiveness and cycle count, hence cost and how far structures move |
| `cartesian` / `dualspace` | bool | — | `false` | cartesian mode is required for accurate `cart_bonded` energetics (ddG work) but costs more per cycle and needs `_cart` weights |
| `coord_cst_weight` (via `-constrain_relax_to_start_coords`) | real | 0.0–2.0 | 0 unless flag set | prevents FastRelax from drifting far from the input structure; too high defeats the purpose of relaxing |
| `min_tolerance` (script `min <tol>`) | real | 1e-5–1e-2 | 0.01 (typical) then 0.00001 final cycle | tighter tolerance = more minimizer steps = more cost, diminishing returns below ~1e-4 |

- **Parameters that must NOT be agent-varied:** `-database` path (must point at a version-matched `database/` checkout — mismatched database/binary versions produce silent scoring corruption, not a crash); the `ref`/`METHOD_WEIGHTS` line inside a `.wts` file (hand-tuned reference energies; editing them invalidates the score function's calibration against every published benchmark); `fa_rep` final ramp value inside a relax script (should always ramp to 1.0 in the last repack/min cycle — stopping early leaves clashes unresolved, which silently corrupts downstream ddG/interface numbers).

## Failure modes & what the agent must check
- **Loud failure:** missing `-database`, malformed XML (schema-validated at parse time, `-parser:protocol` will exit non-zero with a line number), missing `.params` file for an unrecognized ligand/HETATM (exits with "residue type not found").
- **Silent bad output (the dominant Rosetta hazard):** FastRelax/FastDesign can converge to a structurally plausible but energetically or geometrically pathological pose without any non-zero exit code. The agent must check, per decoy:
  - **Total score outliers** — compare `total_score` across the `nstruct` ensemble; a decoy sitting far above the ensemble median usually did not converge and should be discarded, not trusted as "the answer."
  - **`cart_bonded`** (or `pro_close`/`omega` in torsion mode) — spikes indicate bond-length/angle distortion from over-aggressive minimization; check it did not blow up relative to a native/reference structure.
  - **`rama_prepro`** per-residue — flags backbone dihedrals that fell into disallowed Ramachandran territory during design/relax; a handful of moderate outliers is normal, a systematic shift across many residues is not.
  - **Buried unsatisfied polar groups** (`delta_unsat_hbonds` from InterfaceAnalyzer, or the `BuriedUnsatHbonds` filter) — a common silent failure of interface/ligand design where polar atoms end up buried with no hydrogen-bond partner; this is invisible in `total_score` alone because the packer can hide it behind favorable van der Waals terms.
  - **Clash detection** — residual `fa_rep` after the final full-weight repack/min cycle should be near the ensemble baseline; a residual clash surviving the relax script's final `scale:fa_rep 1 / repack / min 0.00001` sequence means the structure did not actually converge.

## Cost per unit of work
- **1 FastRelax pass, single ~150–300 residue monomer, default `MonomerRelax2019` script (4 repeat cycles):** roughly 3–15 CPU-minutes on a modern server core, scaling worse than linearly with residue count because packer cost grows with rotamer-graph size. A typical `nstruct=50` ensemble for one design target is therefore ~2.5–12 CPU-hours, trivially parallel across 50 cores/ranks (wall-clock ≈ single-decoy cost if resources allow).
- **1 FastDesign pass** — comparable to or somewhat more expensive than FastRelax per cycle (packer must consider all 20 amino acids at designable positions instead of just the native rotamer), typically 1.3–2x FastRelax cost for the same script.
- **1 InterfaceAnalyzer pass** on an already-built complex — seconds to low minutes (two repacks plus SASA/packstat calculation); cheap relative to the relax/design step that produced the structure. Checkpointable: n/a (single-shot, short).
- **Resource shape:** P2 fan-out is single-core-per-decoy by default; each decoy is a single process, no internal threading, so "cores requested" = "nstruct" up to the node's core count, then queue.

## Verdict
**Core.** Rosetta/RosettaScripts is the load-bearing physics engine behind three of four in-scope problem classes (stability, enzyme design, small-molecule work) and provides the standard interface-quality scorecard needed for binder design triage. There is no substitute in this toolkit for FastRelax-quality refinement or InterfaceAnalyzer-quality interface metrics; deep-learning tools in this toolkit generate structure but do not replace Rosetta's physically-grounded scoring and packing. The license gate and build-from-source burden are real but one-time costs, not recurring per-campaign costs, and are not disqualifying.

## Sources
- `tools/rosetta/README.md`, `tools/rosetta/LICENSE.md`, `tools/rosetta/LICENSE.PyRosetta.md`
- `tools/rosetta/source/src/protocols/relax/FastRelax.cc` (script language, cartesian/dualspace options, lines ~1–120, 319–470)
- `tools/rosetta/source/src/protocols/denovo_design/movers/FastDesign.cc` (XML tag options, line ~160-163)
- `tools/rosetta/source/src/protocols/analysis/InterfaceAnalyzerMover.cc` and `source/src/apps/public/analysis/InterfaceAnalyzer.cc`
- `tools/rosetta/database/sampling/relax_scripts/MonomerRelax2019.txt` and directory listing (`database/sampling/relax_scripts/`)
- `tools/rosetta/database/scoring/weights/ref2015.wts`, `beta_nov16.wts`, and `_cart`/`_cst` variants
- `tools/rosetta/source/tools/build/setup.py` (mpi build extra), `tools/rosetta/docker/README.md`
- `tools/rosetta/source/version.py`
- Community MCP (unverified, not RosettaCommons-affiliated): https://github.com/Arielbs/rosetta-mcp-server, https://pypi.org/project/rosetta-mcp — via WebSearch, not in refcode.
