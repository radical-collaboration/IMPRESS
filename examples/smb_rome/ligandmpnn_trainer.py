"""LigandMPNN trainer task — the small_molecule_binding half of ROME-A.

IMPRESS runs RFD3 → LigandMPNN → PackMin → FastRelax → filter_shape → AF2, and
it is open loop: every campaign improves the designs, never the model.  This
trainer closes that loop by fine-tuning the backbone design model on the
campaign's own high-confidence designs.

**Which LigandMPNN.**  IMPRESS runs ``dauparas/LigandMPNN`` — its
``scripts/mpnn_run.py`` wraps ``run.py`` with the original CLI.  So this
trainer targets the same checkpoint: it fine-tunes ``ligandmpnn_v_32_010_25.pt``
and writes the new weights back to ``{mpnn_dir}/model_params/ligandmpnn_v_32_010_25.pt``
so the campaign's next MPNN pass picks them up with no wrapper change.

**Protein-only fine-tuning.**  Unlike the protein-binding case there is no
context chain — the ligand is non-protein HETATM atoms, which LigandMPNN reads
automatically from the PDB.  Only the designed chain(s) are scored in the loss;
the ligand context enters through the model's featurizer.

**Side-chain packer.**  The side-chain packing model (``ligandmpnn_sc_*``) uses
a different architecture (``Packer``) and a different loss (torsion angles vs
sequence NLL).  It is not fine-tuned here — the backbone design model is the
critical one for ROME's learning signal.

**Reward weighting.**  The ROME manager passes ``reward_fn`` via
``TrainerConfig.train_kwargs``.  It is pickled into the job spec and applied per
sample as a loss weight, normalized within each epoch, so high-reward designs
get more gradient.  Set ``train_kwargs={"reward_fn": my_fn}`` on the
TrainerConfig to use it; omit it to train with uniform weights.
"""

from __future__ import annotations

import base64
import json
import os
import pickle
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


from rome.train.base import TrainTask


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Required corpus fields — the PDB structure file that was produced by the
#: campaign.  ``plddt``, ``interaction_energy`` and ``max_sc`` are optional but
#: used by the reward function and corpus filter.
REQUIRED_FIELDS = ("path",)

#: Default design chains for small-molecule binding: chain A = designed protein.
#: The ligand is HETATM in the same PDB — LigandMPNN reads it automatically.
DEFAULT_DESIGN_CHAINS: Tuple[str, ...] = ("A",)


# ---------------------------------------------------------------------------
# Pure helpers (no torch)
# ---------------------------------------------------------------------------

def pdb_chain_ids(path: str) -> List[str]:
    """Chain IDs present in a PDB, in first-seen order (ATOM/HETATM column 22)."""
    seen: List[str] = []
    try:
        with open(path) as fd:
            for line in fd:
                if line.startswith(("ATOM", "HETATM")) and len(line) >= 22:
                    chain = line[21]
                    if chain not in seen:
                        seen.append(chain)
    except OSError:
        return []
    return seen


def _design_name(record: Dict[str, Any], index: int) -> str:
    raw = str(record.get("uid") or record.get("design_id")
              or os.path.splitext(os.path.basename(record.get("path", "")))[0]
              or f"design_{index}")
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in raw)


def stage_structures(records: List[Dict[str, Any]], staging_dir: str) -> Dict[str, str]:
    """Copy each design's structure into one directory under a unique name."""
    os.makedirs(staging_dir, exist_ok=True)
    staged: Dict[str, str] = {}
    for index, record in enumerate(records):
        name = _design_name(record, index)
        dst = os.path.join(staging_dir, f"{name}.pdb")
        shutil.copyfile(record["path"], dst)
        staged[name] = dst
    return staged


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class LigandMPNNConfig:
    """Configuration for fine-tuning LigandMPNN on campaign designs.

    Parameters
    ----------
    mpnn_dir : str
        Path to the ``dauparas/LigandMPNN`` checkout — the same directory
        ``scripts/mpnn_run.py`` uses.  The trainer imports ``data_utils`` and
        ``model_utils`` from here and writes new weights back into its
        ``model_params/``.
    checkpoint : str, optional
        Path to the backbone design checkpoint to fine-tune.
        Defaults to ``{mpnn_dir}/model_params/ligandmpnn_v_32_010_25.pt``.
    design_chains : sequence of str
        Chains to design; loss is computed on these only.  Ligand context
        (HETATM) is always included by LigandMPNN regardless of this setting.
    batch_tokens : int
        NOT a GPU batch size (LigandMPNN processes one structure at a time).
        Kept for API parity; currently unused — each epoch iterates all designs.
    max_epochs : int
        Training epochs per ROME round.
    learning_rate_factor, warmup_steps : ...
        Noam schedule, as in the original ProteinMPNN trainer.
    label_smoothing : float
        CCE label smoothing weight (0 = hard NLL).
    gradient_norm : float, optional
        Gradient clipping; ``None`` disables it.
    train_script : str, optional
        Path to ``ligandmpnn_train_wrapper.py``; defaults to the sibling file.
    train_func : callable, optional
        ``(job, output_dir) -> checkpoint_path`` escape hatch for testing.
    """

    mpnn_dir: Optional[str] = None
    checkpoint: Optional[str] = None
    design_chains: Sequence[str] = field(default_factory=lambda: list(DEFAULT_DESIGN_CHAINS))

    batch_tokens: int = 4096
    max_protein_length: int = 2000
    max_epochs: int = 3
    learning_rate_factor: float = 2.0
    warmup_steps: int = 4000
    label_smoothing: float = 0.1
    gradient_norm: Optional[float] = 1.0
    backbone_noise: float = 0.1
    dropout: float = 0.1

    seed: int = 0
    device: str = "cuda"

    train_script: Optional[str] = None
    train_func: Optional[Callable[..., str]] = None

    def resolved_checkpoint(self) -> str:
        if self.checkpoint:
            return self.checkpoint
        if self.mpnn_dir:
            return os.path.join(self.mpnn_dir, "model_params", "ligandmpnn_v_32_010_25.pt")
        raise ValueError("LigandMPNNConfig: set mpnn_dir or checkpoint")

    def validate(self) -> None:
        if self.train_func is None and not self.mpnn_dir:
            raise ValueError(
                "LigandMPNNConfig.mpnn_dir must point at the LigandMPNN checkout "
                "(or set train_func to use your own loop)"
            )
        if self.design_chains is None or len(self.design_chains) == 0:
            raise ValueError("LigandMPNNConfig.design_chains must not be empty")


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------

def _load_run_round():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from ligandmpnn_train_wrapper import run_round  # type: ignore
    return run_round


class LigandMPNNTrainer(TrainTask):
    """Fine-tunes LigandMPNN on the campaign's confident designs.

    Writes the updated checkpoint back into
    ``{mpnn_dir}/model_params/ligandmpnn_v_32_010_25.pt`` so the campaign's
    next MPNN pass uses it without any wrapper change.
    """

    wants_hf_dataset = False

    def __init__(
        self,
        config: Optional[LigandMPNNConfig] = None,
        *,
        gpus: Optional[int] = None,
        nodes: Optional[int] = None,
        name: Optional[str] = None,
    ):
        config = config or LigandMPNNConfig()
        config.validate()
        super().__init__(
            gpus=gpus if gpus is not None else 1,
            nodes=nodes if nodes is not None else 1,
            name=name or "ligandmpnn",
        )
        self.config = config

    def validate(self, dataset: Any) -> None:
        super().validate(dataset)
        for index, record in enumerate(dataset):
            record = record or {}
            missing = [f for f in REQUIRED_FIELDS if f not in record]
            if missing:
                raise ValueError(
                    f"LigandMPNN training needs {', '.join(REQUIRED_FIELDS)} on "
                    f"every record; corpus record {index} is missing "
                    f"{', '.join(missing)}.  'path' must point at the relaxed "
                    "design structure (protein + ligand HETATM atoms in one PDB)."
                )
            present = pdb_chain_ids(record["path"]) if os.path.exists(record["path"]) else None
            if present is not None:
                designed = list(record.get("design_chains", self.config.design_chains))
                if present and not any(c in present for c in designed):
                    raise ValueError(
                        f"corpus record {index} ({record['path']}): none of the "
                        f"design chains {designed} are in the structure (chains: {present})."
                    )

    def write_manifest(self, records: List[Dict[str, Any]], output_dir: str) -> str:
        import pandas as pd
        cfg = self.config
        manifest_dir = os.path.join(output_dir, "manifest")
        os.makedirs(manifest_dir, exist_ok=True)
        rows = []
        for index, record in enumerate(records):
            name = _design_name(record, index)
            rows.append({
                "design_id":  name,
                "path":       os.path.abspath(record["path"]),
                "plddt":      record.get("plddt"),
                "interaction_energy": record.get("interaction_energy"),
                "max_sc":     record.get("max_sc"),
                "design_chains": ",".join(list(record.get("design_chains", cfg.design_chains))),
            })
        path = os.path.join(manifest_dir, "train_manifest.parquet")
        pd.DataFrame(rows).to_parquet(path)
        return path

    def as_command(
        self, dataset: Any, output_dir: str, **kwargs: Any
    ) -> Optional[Tuple[str, str]]:
        if self.config.train_func is not None:
            return None
        records = list(dataset)
        self.write_manifest(records, output_dir)
        job, target = self._build_job(records, output_dir, **kwargs)
        job_path = os.path.join(output_dir, "train_job.json")
        with open(job_path, "w") as fd:
            json.dump(job, fd, indent=2)

        script = self.config.train_script or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "ligandmpnn_train_wrapper.py"
        )
        command = f"{sys.executable} {script} --job {job_path}"
        return command, target

    def train(self, dataset: Any, output_dir: str, **kwargs: Any) -> str:
        records = list(dataset)
        self.write_manifest(records, output_dir)

        if self.config.train_func is not None:
            return self.config.train_func(records, output_dir, self.config) or output_dir

        run_round = _load_run_round()
        job, _target = self._build_job(records, output_dir, **kwargs)
        return run_round(job)

    def _build_job(
        self, records: List[Dict[str, Any]], output_dir: str, **kwargs: Any
    ) -> Tuple[Dict[str, Any], str]:
        cfg = self.config
        staged = stage_structures(records, os.path.join(output_dir, "structures"))
        designs = []
        for index, record in enumerate(records):
            name = _design_name(record, index)
            designed = list(record.get("design_chains", cfg.design_chains))
            designs.append({
                "name":           name,
                "path":           os.path.abspath(staged[name]),
                "designed_chains": designed,
                # corpus record fields for reward_fn
                "record": {
                    "plddt":              record.get("plddt"),
                    "interaction_energy": record.get("interaction_energy"),
                    "max_sc":             record.get("max_sc"),
                },
            })

        target = os.path.abspath(cfg.resolved_checkpoint())
        job: Dict[str, Any] = {
            "mpnn_dir":      cfg.mpnn_dir,
            "resume_from":   kwargs.get("model_path") or cfg.resolved_checkpoint(),
            "target_weights": target,
            "output_dir":    os.path.abspath(output_dir),
            "designs":       designs,
            "hyperparams": {
                "max_epochs":          cfg.max_epochs,
                "max_protein_length":  cfg.max_protein_length,
                "backbone_noise":      cfg.backbone_noise,
                "dropout":             cfg.dropout,
                "learning_rate_factor": cfg.learning_rate_factor,
                "warmup_steps":        cfg.warmup_steps,
                "label_smoothing":     cfg.label_smoothing,
                "gradient_norm":       cfg.gradient_norm,
                "seed":                cfg.seed,
                "device":              cfg.device,
            },
        }

        reward_fn = kwargs.get("reward_fn")
        if reward_fn is not None:
            job["reward_fn_pickle"] = base64.b64encode(pickle.dumps(reward_fn)).decode()

        return job, target


# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------

def smb_corpus_filter(
    min_plddt: float = 70.0,
    min_max_sc: float = 0.5,
) -> Callable[[Dict[str, Any]], bool]:
    """Admission gate for the small-molecule binding corpus.

    Accepts designs whose pLDDT and shape complementarity clear the given
    thresholds.  Use :func:`percentile_sampler` to calibrate thresholds from
    the campaign's own distribution instead of setting them by hand.
    """
    def _passes(record: Dict[str, Any]) -> bool:
        plddt = record.get("plddt", 0.0) or 0.0
        max_sc = record.get("max_sc", 0.0) or 0.0
        return float(plddt) >= min_plddt and float(max_sc) >= min_max_sc
    return _passes


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def percentile_sampler(
    fraction: float = 0.33,
    *,
    rank_by: Optional[Dict[str, str]] = None,
    min_shard: int = 8,
    on_summary: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Select the best ``fraction`` of the corpus by average rank.

    Ranking is non-parametric: ``rank_by`` maps field names to ``'high'`` or
    ``'low'`` and ranks are averaged across fields so each contributes equally
    regardless of scale.  A round is never triggered until ``min_shard``
    records are available.

    Default ``rank_by`` for small-molecule binding::

        {"plddt": "high", "interaction_energy": "low", "max_sc": "high"}

    Use this instead of tuning :func:`smb_corpus_filter` thresholds — the
    fraction is a relative claim ("best third of what this campaign produced")
    that calibrates itself automatically, and doesn't require knowing the
    predictor's confidence scale.
    """
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    _DEFAULT_RANK_BY = {"plddt": "high", "interaction_energy": "low", "max_sc": "high"}
    directions = dict(rank_by if rank_by is not None else _DEFAULT_RANK_BY)
    for key, direction in directions.items():
        if direction not in ("high", "low"):
            raise ValueError(f"rank_by[{key!r}] must be 'high' or 'low', got {direction!r}")

    def _sample(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        records = list(records)
        if not records:
            return records
        usable = {
            key: direction for key, direction in directions.items()
            if any(_is_number(r.get(key)) for r in records)
        }
        if not usable:
            return records
        total = {id(r): 0.0 for r in records}
        for key, direction in usable.items():
            ordered = sorted(
                records,
                key=lambda r: (
                    not _is_number(r.get(key)),
                    -float(r[key]) if _is_number(r.get(key)) and direction == "high"
                    else (float(r[key]) if _is_number(r.get(key)) else 0.0),
                ),
            )
            for position, record in enumerate(ordered):
                total[id(record)] += position
        ranked = sorted(records, key=lambda r: (total[id(r)], str(r.get("uid", ""))))
        keep = max(min(min_shard, len(records)), int(round(len(records) * fraction)))
        selected = ranked[:keep]
        if on_summary is not None:
            cutoffs = {}
            for key, direction in usable.items():
                values = [float(r[key]) for r in selected if _is_number(r.get(key))]
                if values:
                    cutoffs[key] = min(values) if direction == "high" else max(values)
            on_summary({
                "corpus": len(records), "selected": len(selected),
                "ranked_by": usable, "cutoffs": cutoffs,
            })
        return selected

    return _sample


__all__ = [
    "LigandMPNNConfig",
    "LigandMPNNTrainer",
    "stage_structures",
    "pdb_chain_ids",
    "smb_corpus_filter",
    "percentile_sampler",
    "DEFAULT_DESIGN_CHAINS",
    "REQUIRED_FIELDS",
]
