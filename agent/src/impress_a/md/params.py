"""K1: parameterise the ligand **once**, into a committed artifact that says what it is.

**The single-ligand degeneracy that ruins Model A's training data is an advantage here.** There
is exactly one ligand across this project's entire campaign history -- audit finding 4: identical
SMILES in 267/267, 112/112, 182/182 and 423/423 `boltz_input.yaml`, and the same
`scaffold-with-ALR.pdb` behind every rfd3 input. So the ligand is typed once, committed, and
read by every MD run, rather than re-typed per design at the cost of an AM1-BCC calculation each
time and a different charge set whenever a tool version moves.

### Why GAFF2 and not CGenFF, and why that is recorded rather than hidden

CHARMM36m for the protein and CGenFF for the ligand is the stated pairing, and
`par_all36_cgenff.prm` and `top_all36_cgenff.rtf` are on disk -- but **there is no CGenFF binary
on this machine**. Typing needs ParamChem, which is a web service wanting network access and an
account: the same operational shape as PLINDER, and not something a protocol body can assume.

So the offline route is taken and **named in the artifact**: GAFF2 via the installed AmberTools,
with AM1-BCC charges from `sqm`, **and an ff14SB protein to match it** -- one family, one set of
combining rules, one nonbonded convention.

**Not "mixed with a CHARMM36m protein through ParmEd", which is what the pre-K1 plan proposed and
is a nonstarter.** Two families have different combining rules, different 1-4 scaling and
different nonbonded conventions; no single set of cutoffs is right for both, so the result is not
a usable measurement however cleanly ParmEd joins the topologies. ParmEd is not in this
protocol's path at all, `system.nonbonded_for` **refuses a mixed pair by name**, and a test reads
every tleap script this project writes and refuses a parameter source naming a CHARMM file.

That compromise is defensible and silence about it would not be -- *a force field is part of what
a measured number means* -- so `force_field` is a required field of the artifact and travels into
every label's provenance. A `preorg_rmsd` measured under GAFF2 and one measured under CGenFF are
two measurements, and a corpus that mixed them without saying so would be one number.

### What the artifact records, and why each line is there

| Field | Why |
|---|---|
| `force_field` | see above; the whole point |
| `penalties` | parmchk2's own words for every parameter it had to guess. **GAFF2's analogue of a CGenFF penalty score**, and the thing the plan asks not be ignored |
| `net_charge`, `charge_sum`, `charge_residual` | AM1-BCC charges do not sum to an integer, and PME with a non-integer net charge applies a uniform neutralising plasma that shifts energies silently |
| `counterions` | ALR is **-2**, so neutralisation is part of the artifact rather than a solvation detail |
| `atom_types` | twelve GAFF2 types, so a reader can see the azo group was typed (`ne`/`nf`) rather than guessed |
| `template_match_ambiguous` | RDKit warns when a pose matches its SMILES template more than one way. Which mapping was chosen decides every atom *name*, so a run that silently picked the other one would produce the same energies under different names |
| `tools`, `digests` | the version that typed it and the bytes that came out |
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

#: The artifact's filename inside its directory. One name, so a consumer needs no convention.
ARTIFACT_NAME = "ligand_parameters.json"

#: What a GAFF2 run produces and a system build consumes.
MOL2_NAME = "ligand.mol2"
FRCMOD_NAME = "ligand.frcmod"

#: The protein and water force fields the ligand parameters are mixed with. Named here because
#: the artifact records the whole combination: the ligand's parameters alone do not say what a
#: number measured with them means.
#:
#: **ff14SB and not CHARMM36m, and that is a determination rather than a default.** The plan
#: named CHARMM36m for the protein, and OpenMM 8.6 does ship `charmm36.xml`, so it was
#: available. It is not used, for one reason: **the ligand is GAFF2** (see this module's
#: docstring -- CGenFF needs ParamChem), and GAFF2 is the Amber family's small-molecule force
#: field, parameterised and validated against Amber protein force fields. Pairing GAFF2 with
#: ff14SB keeps one family and one set of combining rules; pairing it with CHARMM36m mixes two
#: that were never validated against each other, and needs ParmEd to stitch the topologies
#: together.
#:
#: The cost is stated rather than discovered: **this is not the protocol the plan named**, so a
#: CGenFF + CHARMM36m run later is a *different measurement* and not a refinement of this one,
#: and `force_field` plus `protein_force_field` travel into every label's provenance so a
#: corpus cannot mix them silently.
#:
#: **2026-11-24: this is a stopgap against a directive, and the directive is CHARMM.** The
#: reasoning above answers "what pairs with GAFF2" when the decision was "which family types the
#: ligand", and that was settled by what happened to be installed. Measured the same day:
#: CHARMM36m and CHARMM-modified TIP3P build and solvate this protein offline through OpenMM's
#: bundled `charmm36.xml` with `pdbfixer` repairing the termini, and VMD provides `psfgen`. The
#: only blocker is CGenFF typing for ALR -- one ParamChem round-trip, by hand, once, because
#: there is one ligand across every archive. The switch is episode K7.
PROTEIN_FORCE_FIELD = "ff14sb"
WATER_MODEL = "tip3p"

#: AM1-BCC charges are computed per atom and do not sum to the formal charge exactly. Above
#: this, something is wrong with the input rather than with the arithmetic -- a misread formal
#: charge, or a molecule that lost an atom -- and the run refuses instead of distributing it.
#:
#: Below it, the residual is spread evenly over every atom, which is what every MD setup does
#: and almost none records. **It is recorded here**, because a reader who finds a 1e-4 charge
#: offset in a topology should be able to find out that it was put there on purpose.
MAX_CHARGE_RESIDUAL = 0.01

#: What a file name in this artifact may contain. Deliberately narrow: these names are
#: interpolated into a tleap script and executed, so the set is "what a parameter file is
#: actually called" and not "what a filesystem permits".
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: parmchk2 writes its guesses in prose, one per line, in whichever section needed them. These
#: are the three phrasings it uses; a line matching none of them is a parameter it had exactly.
_PENALTY_MARKERS = ("penalty score", "Using the default value", "ATTN, need revision")


class ParameterisationFailed(RuntimeError):
    """A ligand this module will not hand to an MD run, with the reason named.

    A refusal rather than a best effort: a topology with the wrong charge, the wrong atom count
    or a parameter nobody has is one that runs, produces a trajectory, and reports three metrics
    that mean nothing -- which is the one failure mode `md_label`'s integrity gate cannot see,
    because the instrument worked.
    """


@dataclass
class LigandParameters:
    """One ligand, typed once. **Every field is provenance; none is a tuning knob.**"""

    #: The unit name inside the parameter files: at most three characters, no colon, because
    #: mol2 and tleap cannot carry one. This is **not** the name in the structure.
    resname: str
    smiles: str
    force_field: str
    #: The name as it appears in the PDB, **byte for byte**. For this project's ligand that is
    #: `A:R`, and the colon is a workaround rather than a quirk: `foundry.sif` carries an
    #: internal confound on the label `ALR` from an unrelated data source, so RFD3 inside that
    #: container misresolves the bare `"ALR"` literal, and a name no such source can hold
    #: sidesteps it (`toolkits/rfd3/SKILL.md` is the canonical note).
    #:
    #: **The two names being different is the whole reason this field exists, and neither is
    #: wrong.** The design chain's structures say `A:R`; this parameterisation says `ALR`,
    #: because mol2 and tleap cannot carry a colon in a residue name. A build that matched the
    #: parameter unit's name against a structure would find no ligand, and a holo build that
    #: found no ligand would be an apo build wearing a holo label.
    pdb_resname: str = ""
    protein_force_field: str = PROTEIN_FORCE_FIELD
    water_model: str = WATER_MODEL
    charge_method: str = "am1bcc"
    net_charge: int = 0
    n_atoms: int = 0
    n_heavy_atoms: int = 0
    #: Sum of the per-atom charges as the charge method produced them, before correction.
    charge_sum: float = 0.0
    #: `net_charge - charge_sum`, spread evenly over the atoms. See `MAX_CHARGE_RESIDUAL`.
    charge_residual: float = 0.0
    atom_types: List[str] = field(default_factory=list)
    #: parmchk2's own words, one entry per guessed parameter.
    penalties: List[str] = field(default_factory=list)
    #: The highest numeric penalty score parmchk2 reported, or `None` when it reported none.
    max_penalty: Optional[float] = None
    #: Ions added to neutralise the ligand alone. The protein's own charge is neutralised at
    #: solvation time, where the count depends on the design's sequence.
    counterions: Dict[str, int] = field(default_factory=dict)
    template_match_ambiguous: bool = False
    tools: Dict[str, str] = field(default_factory=dict)
    digests: Dict[str, str] = field(default_factory=dict)
    files: Dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def as_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def load(cls, directory: str) -> "LigandParameters":
        path = os.path.join(directory, ARTIFACT_NAME)
        if not os.path.exists(path):
            raise ParameterisationFailed(
                f"no {ARTIFACT_NAME} in {directory}. The ligand is typed once into a committed "
                "artifact (K1) and read by every run; a system build that typed it itself would "
                "produce a different charge set whenever a tool version moved"
            )
        with open(path) as handle:
            artifact = cls(**json.load(handle))
        artifact._check_names(directory)
        return artifact

    def _check_names(self, directory: str) -> None:
        """Every file this artifact names must be a plain basename. **Checked on load.**

        Two reasons, and the second is why this is a refusal rather than a convention.

        The names in `files` are written **into a tleap script that is then executed**
        (`system._tleap_script`, `freeenergy._dry_tleap_script`), so a name carrying a newline
        is a leap command of somebody else's choosing, and one carrying `..` reads a file from
        outside the artifact. `verify` joins the keys of `digests` to the same directory, so
        both sets are checked.

        The digests do not cover this. They are in the same JSON as the names, so they prove a
        file has not changed since the artifact was written -- not that the artifact is one this
        project wrote. The names are the part that reaches a subprocess, so the names are
        checked by shape.
        """
        for where, names in (("files", list(self.files.values())),
                             ("digests", list(self.digests))):
            for name in names:
                if not name or os.path.basename(name) != name or not _SAFE_NAME.match(name):
                    raise ParameterisationFailed(
                        f"{ARTIFACT_NAME} in {directory} names {name!r} under {where}, which is "
                        "not a plain file name. These names are written into a tleap script "
                        "that is then run, so a separator, a newline or a character outside "
                        "[A-Za-z0-9._-] is refused rather than quoted"
                    )

    def verify(self, directory: str) -> None:
        """Refuse an artifact whose files have changed since it was written.

        The digests are not ceremony. These parameters are **committed** and read by every MD
        run, so the failure they guard against is a parameter file edited in place -- after
        which every label in the corpus was measured with something other than what the
        artifact says, and nothing anywhere would disagree.
        """
        for name, digest in sorted(self.digests.items()):
            path = os.path.join(directory, name)
            if not os.path.exists(path):
                raise ParameterisationFailed(
                    f"{self.resname}'s artifact names {name} and {directory} does not hold it"
                )
            if _sha256(path) != digest:
                raise ParameterisationFailed(
                    f"{name} in {directory} does not match the digest in {ARTIFACT_NAME}. "
                    "Every label measured with these parameters was measured with what was on "
                    "disk, not with what this artifact describes. Re-run the parameterisation "
                    "rather than editing either one."
                )

    @property
    def missing_parameters(self) -> List[str]:
        """The guesses, which a reader should look at before trusting a number."""
        return list(self.penalties)


def parameterise(
    *,
    smiles: str,
    pose_pdb: str,
    out_dir: str,
    resname: str,
    net_charge: int,
    pdb_resname: str = "",
    force_field: str = "gaff2",
    amberhome: str = "",
    notes: str = "",
) -> LigandParameters:
    """Type one ligand on its own pose and write the artifact. **Idempotent by content.**

    `pose_pdb` is the complex the ligand's coordinates come from, and `smiles` is what says
    what the molecule *is*. Both are needed and neither is enough: a PDB of 30 heavy atoms with
    no CONECT records carries no bond orders and no protonation, and a SMILES carries no pose.
    So the bond orders come from the SMILES, the coordinates from the PDB, and the hydrogens
    from RDKit with `addCoords` -- which is the only step here with any freedom in it, and the
    one `template_match_ambiguous` records.
    """
    amberhome = amberhome or os.environ.get("AMBERHOME", "")
    os.makedirs(out_dir, exist_ok=True)
    sdf_path = os.path.join(out_dir, "ligand_with_hydrogens.sdf")

    built = _build_with_hydrogens(smiles, pose_pdb, sdf_path, net_charge)
    mol2 = os.path.join(out_dir, MOL2_NAME)
    frcmod = os.path.join(out_dir, FRCMOD_NAME)

    _antechamber(sdf_path, mol2, resname=resname, net_charge=net_charge,
                 force_field=force_field, amberhome=amberhome, cwd=out_dir)
    _parmchk2(mol2, frcmod, force_field=force_field, amberhome=amberhome, cwd=out_dir)

    charges, types = _read_mol2(mol2)
    charge_sum = round(sum(charges), 6)
    residual = round(float(net_charge) - charge_sum, 6)
    if abs(residual) > MAX_CHARGE_RESIDUAL:
        raise ParameterisationFailed(
            f"{resname}: the charges sum to {charge_sum} and the formal charge is "
            f"{net_charge}, a residual of {residual} against a ceiling of "
            f"{MAX_CHARGE_RESIDUAL}. That is not rounding: it is a misread formal charge or a "
            "molecule missing an atom, and distributing it would hide which"
        )
    _redistribute_charge(mol2, residual)

    penalties = _penalties(frcmod)
    artifact = LigandParameters(
        resname=resname,
        pdb_resname=pdb_resname or resname,
        smiles=smiles,
        force_field=force_field,
        net_charge=int(net_charge),
        n_atoms=len(charges),
        n_heavy_atoms=built["n_heavy"],
        charge_sum=charge_sum,
        charge_residual=residual,
        atom_types=sorted(set(types)),
        penalties=penalties,
        max_penalty=_max_penalty(penalties),
        # One monovalent counterion per unit of ligand charge, in the direction that
        # neutralises it: ALR is -2, so two sodiums. Named rather than computed at solvation
        # time, because a reader of a trajectory should be able to find out why there are two
        # sodiums in it without re-deriving the ligand's charge.
        counterions=({"NA": -int(net_charge)} if net_charge < 0
                     else ({"CL": int(net_charge)} if net_charge > 0 else {})),
        template_match_ambiguous=built["ambiguous"],
        tools=_tool_versions(amberhome),
        digests={name: _sha256(os.path.join(out_dir, name))
                 for name in (MOL2_NAME, FRCMOD_NAME)},
        files={"mol2": MOL2_NAME, "frcmod": FRCMOD_NAME},
        notes=notes,
    )
    with open(os.path.join(out_dir, ARTIFACT_NAME), "w") as handle:
        handle.write(artifact.as_json())
    return artifact


# -- the steps ---------------------------------------------------------------------------


def _build_with_hydrogens(smiles: str, pose_pdb: str, out_sdf: str,
                          net_charge: int) -> Dict[str, Any]:
    """Bond orders from the SMILES, coordinates from the PDB, hydrogens from RDKit."""
    from rdkit import Chem, RDLogger  # noqa: PLC0415
    from rdkit.Chem import AllChem  # noqa: PLC0415

    het = [line for line in open(pose_pdb) if line.startswith("HETATM")]
    if not het:
        raise ParameterisationFailed(
            f"{pose_pdb} holds no HETATM record, so there is no ligand pose in it"
        )
    pose_only = out_sdf.replace(".sdf", "_pose.pdb")
    with open(pose_only, "w") as handle:
        handle.writelines(het + ["END\n"])

    # `sanitize=False`: the pose has no bond orders and no hydrogens, so sanitisation would
    # reject the aromatic rings it cannot perceive. The template supplies both.
    pose = Chem.MolFromPDBFile(pose_only, removeHs=False, sanitize=False)
    if pose is None:
        raise ParameterisationFailed(f"{pose_pdb}'s HETATM records did not parse as a molecule")
    template = Chem.MolFromSmiles(smiles)
    if template is None:
        raise ParameterisationFailed(f"{smiles!r} did not parse as a SMILES")
    if Chem.GetFormalCharge(template) != int(net_charge):
        raise ParameterisationFailed(
            f"the SMILES carries a formal charge of {Chem.GetFormalCharge(template)} and the "
            f"run declared {net_charge}. The declared one decides the counterions and the "
            "AM1-BCC calculation, so a disagreement here is two different molecules"
        )
    if pose.GetNumAtoms() != template.GetNumAtoms():
        raise ParameterisationFailed(
            f"the pose holds {pose.GetNumAtoms()} atoms and the SMILES {template.GetNumAtoms()}"
            ". Matching them would mean choosing which atom is missing"
        )

    # RDKit logs "More than one matching pattern found - picking one" to its own logger when
    # the pose matches the template more than one way, which a near-symmetric molecule does.
    # Captured rather than silenced: which mapping was picked decides every atom NAME, so a
    # later run that picked the other one produces the same energies under different names.
    log = _RDKitLog()
    with log:
        matched = AllChem.AssignBondOrdersFromTemplate(template, pose)
    RDLogger.EnableLog("rdApp.*")
    with_h = Chem.AddHs(matched, addCoords=True)
    Chem.SanitizeMol(with_h)
    Chem.MolToMolFile(with_h, out_sdf)
    return {"n_heavy": template.GetNumAtoms(), "n_atoms": with_h.GetNumAtoms(),
            "ambiguous": log.saw_ambiguity}


class _RDKitLog:
    """Catch RDKit's own warnings for the duration of a block, by file."""

    def __init__(self) -> None:
        self.saw_ambiguity = False
        self._path = ""

    def __enter__(self) -> "_RDKitLog":
        from rdkit import rdBase  # noqa: PLC0415

        self._path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".rdkit.log")
        rdBase.LogToPythonStderr()
        self._captured: List[str] = []
        import io
        import contextlib

        self._buffer = io.StringIO()
        self._redirect = contextlib.redirect_stderr(self._buffer)
        self._redirect.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._redirect.__exit__(*exc)
        text = self._buffer.getvalue()
        self.saw_ambiguity = "More than one matching pattern" in text


def _antechamber(sdf: str, out_mol2: str, *, resname: str, net_charge: int,
                 force_field: str, amberhome: str, cwd: str) -> None:
    binary = _amber_binary("antechamber", amberhome)
    # `-pf y` cleans up sqm's scratch; without it a dozen intermediate files land in `cwd` and
    # the digests below would cover a directory nobody meant to commit.
    command = [binary, "-i", sdf, "-fi", "sdf", "-o", out_mol2, "-fo", "mol2",
               "-c", "bcc", "-nc", str(int(net_charge)), "-at", force_field,
               "-rn", resname[:3] or "LIG", "-pf", "y"]
    _run(command, cwd=cwd, amberhome=amberhome, what="antechamber")
    if not os.path.exists(out_mol2):
        raise ParameterisationFailed(
            f"antechamber returned 0 and wrote no {out_mol2}. Its own log is in {cwd}; the "
            "usual cause is sqm failing to converge on a charge state it was not given"
        )


def _parmchk2(mol2: str, out_frcmod: str, *, force_field: str, amberhome: str,
              cwd: str) -> None:
    binary = _amber_binary("parmchk2", amberhome)
    _run([binary, "-i", mol2, "-f", "mol2", "-o", out_frcmod, "-s", force_field],
         cwd=cwd, amberhome=amberhome, what="parmchk2")
    if not os.path.exists(out_frcmod):
        raise ParameterisationFailed(f"parmchk2 wrote no {out_frcmod}")


def _penalties(frcmod: str) -> List[str]:
    """Every line where parmchk2 says it guessed, verbatim.

    **Verbatim and not summarised**, because the summary a reader needs depends on what they
    are checking: `penalty score= 6.0` on an aromatic CH improper is routine and the same
    number on a bond is not, and a count would hide which.
    """
    out: List[str] = []
    with open(frcmod) as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and any(marker in stripped for marker in _PENALTY_MARKERS):
                out.append(" ".join(stripped.split()))
    return out


def _max_penalty(penalties: List[str]) -> Optional[float]:
    scores = [float(m.group(1)) for line in penalties
              for m in [re.search(r"penalty score=\s*([0-9.]+)", line)] if m]
    return max(scores) if scores else None


def _read_mol2(path: str) -> tuple:
    with open(path) as handle:
        text = handle.read()
    if "@<TRIPOS>ATOM" not in text:
        raise ParameterisationFailed(f"{path} holds no ATOM block")
    block = text.split("@<TRIPOS>ATOM", 1)[1].split("@<TRIPOS>", 1)[0].strip()
    charges, types = [], []
    for line in block.splitlines():
        fields = line.split()
        if len(fields) < 9:
            continue
        types.append(fields[5])
        charges.append(float(fields[8]))
    if not charges:
        raise ParameterisationFailed(f"{path}'s ATOM block holds no usable row")
    return charges, types


def _redistribute_charge(path: str, residual: float) -> None:
    """Spread the charge residual evenly, in place, and leave the file otherwise byte-equal.

    Every MD setup does this and almost none records it. The alternative is a system whose net
    charge is not an integer, which PME neutralises with a uniform plasma -- so the energies
    come out shifted by an amount that depends on the box volume, and nothing reports it.
    """
    if residual == 0.0:
        return
    with open(path) as handle:
        text = handle.read()
    head, rest = text.split("@<TRIPOS>ATOM", 1)
    block, tail = rest.split("@<TRIPOS>", 1)
    rows = [line for line in block.strip().splitlines() if len(line.split()) >= 9]
    share = residual / len(rows)
    fixed = []
    for line in block.strip().splitlines():
        fields = line.split()
        if len(fields) < 9:
            fixed.append(line)
            continue
        fields[8] = f"{float(fields[8]) + share:.6f}"
        fixed.append("%7s %-8s %9s %9s %9s %-8s %4s %-8s %10s" % tuple(fields[:9]))
    with open(path, "w") as handle:
        handle.write(head + "@<TRIPOS>ATOM\n" + "\n".join(fixed) + "\n@<TRIPOS>" + tail)


def _amber_binary(name: str, amberhome: str) -> str:
    candidate = os.path.join(amberhome, "bin", name) if amberhome else ""
    if candidate and os.path.exists(candidate):
        return candidate
    found = shutil.which(name)
    if found:
        return found
    raise ParameterisationFailed(
        f"{name} is not on PATH and AMBERHOME={amberhome or 'unset'} does not hold it. "
        "AmberTools supplies the offline parameterisation route (K1); CGenFY typing needs "
        "ParamChem, which is a network service and an account"
    )


def _run(command: List[str], *, cwd: str, amberhome: str, what: str) -> None:
    env = dict(os.environ)
    if amberhome:
        env["AMBERHOME"] = amberhome
    out = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    with open(os.path.join(cwd, f"{what}.log"), "w") as handle:
        handle.write(out.stdout + "\n--- stderr ---\n" + out.stderr)
    if out.returncode != 0:
        raise ParameterisationFailed(
            f"{what} failed ({out.returncode}): {(out.stderr or out.stdout).strip()[-800:]}"
        )


def _tool_versions(amberhome: str) -> Dict[str, str]:
    versions: Dict[str, str] = {}
    try:
        from rdkit import rdBase  # noqa: PLC0415

        versions["rdkit"] = str(rdBase.rdkitVersion)
    except Exception:  # noqa: BLE001 -- a missing version is not a failed parameterisation
        pass
    version_file = os.path.join(amberhome, "AmberTools", "src", "AmberTools.version")
    if amberhome and os.path.exists(version_file):
        with open(version_file) as handle:
            versions["ambertools"] = handle.read().strip()[:64]
    elif amberhome:
        versions["ambertools"] = f"AMBERHOME={amberhome}"
    return versions


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()
