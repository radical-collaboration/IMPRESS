#!/usr/bin/env python3
"""Standalone LigandMPNN fine-tuning wrapper — ROME-A's training executable.

The training manager submits this script as a shell command, the same way
IMPRESS submits its inference wrappers.  The manager stages the round's
structures, writes a self-contained job spec (JSON), and runs::

    python ligandmpnn_train_wrapper.py --job <job.json>

The round runs in its own process on its own GPU; VRAM is released when the
process exits.

Job spec keys (all written by ``LigandMPNNTrainer``)::

    {
      "mpnn_dir":       "/path/to/LigandMPNN",
      "resume_from":    "/path/to/ligandmpnn_v_32_010_25.pt",
      "target_weights": "/path/to/ligandmpnn_v_32_010_25.pt",  # in-place update
      "output_dir":     "/path/to/round_output_dir",
      "designs": [
        {"name": "d0", "path": "/stage/d0.pdb",
         "designed_chains": ["A"],
         "record": {"plddt": 85.0, "interaction_energy": -12.0, "max_sc": 0.65}}
      ],
      "hyperparams": { ... },
      "reward_fn_pickle": "<base64-pickled callable>"  # optional
    }

Fine-tuning notes:

- LigandMPNN has no bundled training script (``training/`` holds only JSON data
  files), so this wrapper imports ``model_utils.ProteinMPNN`` and
  ``data_utils.{parse_PDB, featurize, get_score}`` directly.
- One structure per GPU forward pass (LigandMPNN's batch dimension is 1).
  Gradient accumulation across the epoch aggregates the signal.
- Only the backbone design model (``ligandmpnn_v_32_010_25.pt``) is fine-tuned.
  The side-chain packing model has a different architecture (``Packer``) and a
  different loss; it stays at pretrained weights.
- ``reward_fn`` (from ``train_kwargs``) is pickled into the job spec and applied
  as per-sample loss weights normalized within each epoch.  Omit it for uniform
  weighting.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pickle
import random
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Inline utilities (no torch at import time — trainer is dragon-free)
# ---------------------------------------------------------------------------

class _NoamOpt:
    """Noam learning-rate schedule, as used by the original ProteinMPNN trainer."""

    def __init__(self, d_model: int, factor: float, warmup: int,
                 optimizer: Any, step: int = 0):
        self.optimizer = optimizer
        self._step = step
        self.warmup = warmup
        self.factor = factor
        self.d_model = d_model

    @property
    def rate(self) -> float:
        s = max(1, self._step)
        return self.factor * (
            self.d_model ** -0.5 * min(s ** -0.5, s * self.warmup ** -1.5)
        )

    def step(self) -> None:
        self._step += 1
        lr = self.rate
        for pg in self.optimizer.param_groups:
            pg["lr"] = lr
        self.optimizer.step()

    def zero_grad(self) -> None:
        self.optimizer.zero_grad()


def _label_smoothed_nll(
    S: Any, log_probs: Any, mask: Any, smoothing: float = 0.1
) -> Tuple[Any, Any]:
    """Label-smoothed CCE, returning (average_loss[B], loss_per_residue[B, L])."""
    import torch
    import torch.nn.functional as F
    S_one_hot = F.one_hot(S.long(), 21).float()
    S_smooth = (1.0 - smoothing) * S_one_hot + smoothing / 21.0
    loss_per_residue = -(S_smooth * log_probs).sum(-1)           # [B, L]
    denom = mask.float().sum(-1) + 1e-8
    average_loss = (loss_per_residue * mask.float()).sum(-1) / denom  # [B]
    return average_loss, loss_per_residue


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_ligandmpnn(mpnn_dir: str):
    """Import ``data_utils`` and ``model_utils`` from the LigandMPNN checkout."""
    if not os.path.isdir(mpnn_dir):
        raise FileNotFoundError(
            f"{mpnn_dir!r} does not exist — set MPNN_DIR to the LigandMPNN checkout"
        )
    if mpnn_dir not in sys.path:
        sys.path.insert(0, mpnn_dir)

    from data_utils import parse_PDB, featurize, get_score  # type: ignore
    from model_utils import ProteinMPNN                      # type: ignore
    return parse_PDB, featurize, get_score, ProteinMPNN


def _load_reward_fn(job: Dict[str, Any]) -> Optional[Callable[[Dict], float]]:
    raw = job.get("reward_fn_pickle")
    if not raw:
        return None
    return pickle.loads(base64.b64decode(raw.encode()))


# ---------------------------------------------------------------------------
# Per-structure forward pass
# ---------------------------------------------------------------------------

def _make_feature_dict(
    protein_dict: Dict[str, Any],
    designed_chains: List[str],
    device: Any,
    atom_context_num: int,
    featurize: Callable,
) -> Dict[str, Any]:
    """Featurize one PDB dict with chain mask for the designed chain(s)."""
    import torch
    import numpy as np
    chain_letters = protein_dict["chain_letters"]
    chain_mask = torch.tensor(
        np.array([c in designed_chains for c in chain_letters], dtype=np.int32),
        device=device,
        dtype=torch.int32,
    )
    protein_dict["chain_mask"] = chain_mask

    fd = featurize(
        protein_dict,
        model_type="ligand_mpnn",
        number_of_ligand_atoms=atom_context_num,
    )
    L = fd["mask"].shape[1]
    fd["batch_size"] = 1
    fd["randn"] = torch.randn([1, L], device=device)
    fd["symmetry_residues"] = [[]]
    fd["symmetry_weights"] = [[]]
    return fd


# ---------------------------------------------------------------------------
# Main training loop
# ---------------------------------------------------------------------------

def run_round(job: Dict[str, Any]) -> str:
    """Run one fine-tuning round from a job spec; return the checkpoint path.

    Teacher-forced scoring: ``model.score(feature_dict, use_sequence=True)``
    decodes with the true sequence at all previous positions.  The loss is
    label-smoothed CCE over the designed chain only.

    Reward weighting: if ``reward_fn_pickle`` is present in the job, each
    sample's loss is multiplied by ``reward_i / sum(rewards)`` (normalized
    within the epoch), so high-reward designs dominate the gradient signal.
    """
    import gc
    import torch

    hp = job["hyperparams"]
    parse_PDB, featurize, get_score, ProteinMPNN = _import_ligandmpnn(job["mpnn_dir"])
    reward_fn = _load_reward_fn(job)

    torch.manual_seed(int(hp["seed"]))
    device = torch.device(hp["device"] if torch.cuda.is_available() else "cpu")
    model = None
    optimizer = None
    try:
        # -- load checkpoint + derive architecture params from it ---------------
        resume = job.get("resume_from")
        if not resume or not os.path.exists(resume):
            raise FileNotFoundError(
                f"checkpoint not found: {resume!r}"
            )
        ckpt = torch.load(resume, map_location=device)
        atom_context_num = ckpt.get("atom_context_num", 16)
        k_neighbors = ckpt.get("num_edges", 32)

        model = ProteinMPNN(
            node_features=128, edge_features=128, hidden_dim=128,
            num_encoder_layers=3, num_decoder_layers=3,
            k_neighbors=k_neighbors, device=device,
            atom_context_num=atom_context_num,
            model_type="ligand_mpnn",
            ligand_mpnn_use_side_chain_context=False,
            augment_eps=float(hp["backbone_noise"]),
            dropout=float(hp["dropout"]),
        ).to(device)
        model.load_state_dict(ckpt["model_state_dict"])
        step = int(ckpt.get("step", 0))

        optimizer = _NoamOpt(
            128, float(hp["learning_rate_factor"]), int(hp["warmup_steps"]),
            torch.optim.Adam(model.parameters(), lr=0.0, betas=(0.9, 0.98), eps=1e-9),
            step,
        )

        designs = job["designs"]
        max_length = int(hp["max_protein_length"])
        smoothing = float(hp["label_smoothing"])
        gradient_norm = hp.get("gradient_norm")

        # -- pre-parse all structures (avoid repeated ProDy parsing per epoch) --
        parsed: List[Tuple[Dict, List[str]]] = []
        for design in designs:
            try:
                protein_dict, *_ = parse_PDB(design["path"], device=device)
                L = protein_dict["S"].shape[0]
                if max_length and L > max_length:
                    print(
                        f"[WARN] {design['name']}: length {L} > max_protein_length "
                        f"{max_length}, skipping", flush=True
                    )
                    continue
                parsed.append((protein_dict, design["designed_chains"], design.get("record", {})))
            except Exception as exc:
                print(f"[WARN] {design['name']}: parse_PDB failed: {exc}", flush=True)

        if not parsed:
            raise RuntimeError("No structures survived parsing; nothing to train on.")

        model.train()

        for _epoch in range(int(hp["max_epochs"])):
            random.shuffle(parsed)

            # Compute reward weights for this epoch
            if reward_fn is not None:
                raw_rewards = [max(0.0, float(reward_fn(rec))) for _, _, rec in parsed]
                total = sum(raw_rewards) + 1e-8
                weights = [r / total for r in raw_rewards]
            else:
                n = len(parsed)
                weights = [1.0 / n] * n

            optimizer.zero_grad()
            for (protein_dict, designed_chains, _record), w in zip(parsed, weights):
                if w <= 0.0:
                    continue
                try:
                    fd = _make_feature_dict(
                        protein_dict, designed_chains, device, atom_context_num, featurize
                    )
                except Exception as exc:
                    print(f"[WARN] featurize failed: {exc}", flush=True)
                    continue

                output = model.score(fd, use_sequence=True)
                loss_mask = fd["mask"] * fd["chain_mask"]
                avg_loss, _ = _label_smoothed_nll(
                    output["S"], output["log_probs"], loss_mask, smoothing
                )
                # avg_loss shape [1]; weight by reward and scale by batch count
                weighted = avg_loss[0] * w * len(parsed)
                weighted.backward()

            if gradient_norm and float(gradient_norm) > 0.0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), float(gradient_norm))
            optimizer.step()
            step += 1

        # -- write checkpoint atomically ----------------------------------------
        cpu_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
        ckpt_out = {
            "model_state_dict": cpu_state,
            "num_edges": k_neighbors,
            "atom_context_num": atom_context_num,
            "step": step,
            "optimizer_state_dict": optimizer.optimizer.state_dict(),
        }
        target = job["target_weights"]
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        tmp = target + ".tmp"
        torch.save(ckpt_out, tmp)
        os.replace(tmp, target)

        # Completion marker — ROME polls for this (see rome.trainer.TRAIN_COMPLETE_MARKER).
        output_dir = job.get("output_dir")
        if output_dir:
            with open(os.path.join(output_dir, "train_complete"), "w") as fd_marker:
                fd_marker.write(target)

        return target

    finally:
        del model, optimizer
        gc.collect()
        try:
            import torch as _t
            if _t.cuda.is_available():
                _t.cuda.empty_cache()
        except Exception:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True,
                        help="path to the job spec JSON written by LigandMPNNTrainer")
    args = parser.parse_args(argv)

    with open(args.job) as fd:
        job = json.load(fd)
    checkpoint = run_round(job)
    print(checkpoint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
