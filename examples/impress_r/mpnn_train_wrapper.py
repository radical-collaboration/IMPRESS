#!/usr/bin/env python3
"""Standalone ProteinMPNN fine-tuning wrapper — ROME-A's training executable.

This is the script the training manager submits **as a shell command**, the same
way IMPRESS submits ``mpnn_wrapper.py`` for inference rather than calling a Python
function inside the campaign process. The manager stages the round's structures,
writes a self-contained job spec (a JSON file), and runs::

    python examples/impress_r/mpnn_train_wrapper.py --job <job.json>

The round therefore executes in its *own* process on its own GPU: nothing about
the fine-tune lives in the manager's address space, and the process exits when
the round finishes, so the CUDA context and the model are released with it.

It sits beside the inference wrapper (``mpnn_wrapper.py``) it complements, in the
IMPRESS-R example rather than in the framework — the trainer is an integration,
and ROME-A itself is workflow-agnostic. The file is deliberately dragon-free — it
imports only the standard library, torch, and the ``dauparas/ProteinMPNN``
checkout named in the job — so it can be run and debugged on its own, exactly
like ``mpnn_wrapper.py``. It is also the single source of truth for the training
loop: ``mpnn.py`` imports :func:`run_round` for the in-process path, so there is
only one copy of the loop.

Job spec (all keys written by ``ProteinMPNNTrainer``)::

    {
      "mpnn_repo": "/path/to/ProteinMPNN",   # the checkout, for its training modules
      "resume_from": "/path/to/v_48_020.pt", # initial weights, or the previous round
      "target_weights": "/path/to/out.pt",   # where to write the new checkpoint
      "designs": [                           # one per staged structure
        {"name": "d0", "path": "/stage/d0.pdb",
         "designed_chains": ["A"], "context_chains": ["B"]}
      ],
      "hyperparams": { ... }                 # architecture + Noam schedule
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple


def _import_proteinmpnn(mpnn_repo: str):
    """Import the checkout's *training* modules and ``parse_PDB``.

    The dauparas repo ships two ``ProteinMPNN`` classes: ``protein_mpnn_utils``
    (inference; ``forward`` takes ``randn``) and ``training/model_utils``
    (training; ``forward`` generates the decoding order itself). The fine-tune
    must use the *training* one, together with the repo's ``featurize``,
    ``loss_smoothed`` and ``NoamOpt``. ``parse_PDB`` comes from the inference
    module.

    Returns ``(parse_PDB, featurize, loss_smoothed, NoamOpt, ProteinMPNN,
    StructureDataset, StructureLoader)`` — the exact objects
    ``training/training.py`` uses.
    """
    training_dir = os.path.join(mpnn_repo, "training")
    if not os.path.isdir(training_dir):
        raise FileNotFoundError(
            f"{mpnn_repo!r} has no training/ directory — is this a "
            "dauparas/ProteinMPNN checkout? The trainer needs its "
            "training/model_utils.py and training/utils.py."
        )
    # training/ first so `model_utils`/`utils` resolve to the training copies,
    # then the repo root for `protein_mpnn_utils`.
    for path in (mpnn_repo, training_dir):
        if path not in sys.path:
            sys.path.insert(0, path)

    from model_utils import (  # type: ignore  # training/model_utils.py
        NoamOpt,
        ProteinMPNN,
        featurize,
        loss_smoothed,
    )
    from protein_mpnn_utils import parse_PDB  # type: ignore  # repo root
    from utils import StructureDataset, StructureLoader  # type: ignore  # training/utils.py

    return (parse_PDB, featurize, loss_smoothed, NoamOpt, ProteinMPNN,
            StructureDataset, StructureLoader)


def _pdb_dicts(job: Dict[str, Any], parse_PDB) -> list:
    """Parse each staged structure and attach its chain mask.

    The designed chain(s) go in ``masked_list`` (predicted and scored); anything
    else present is ``visible_list`` (context — its backbone and true sequence
    condition the prediction but are excluded from the loss). ``featurize`` turns
    that into ``chain_M``. This is the dimer split IMPRESS-R relies on: "design
    chain A given chain B".
    """
    out = []
    for design in job["designs"]:
        designed = list(design.get("designed_chains") or [])
        for entry in parse_PDB(design["path"]):
            present = [k[len("seq_chain_"):] for k in entry
                       if k.startswith("seq_chain_")]
            masked = [c for c in designed if c in present]
            visible = [c for c in present if c not in masked]
            entry["name"] = design["name"]
            entry["masked_list"] = masked
            entry["visible_list"] = visible
            out.append(entry)
    return out


def run_round(job: Dict[str, Any]) -> str:
    """Run one fine-tuning round from a job spec; return the checkpoint path.

    Mirrors ``training/training.py``'s inner loop exactly, using the checkout's
    own ``featurize`` / ``loss_smoothed`` / ``NoamOpt`` and the training
    ``ProteinMPNN``. The loss is over ``mask * chain_M`` — resolved residues of
    the designed chain(s) only. The checkpoint is written in the original
    ``{"model_state_dict", "num_edges", ...}`` format that ``protein_mpnn_run.py``
    loads, from a CPU snapshot so the GPU copy can be freed straight after.
    """
    import gc

    import torch

    hp = job["hyperparams"]
    (parse_PDB, featurize, loss_smoothed, NoamOpt, ProteinMPNN,
     StructureDataset, StructureLoader) = _import_proteinmpnn(job["mpnn_repo"])

    torch.manual_seed(int(hp["seed"]))
    device = torch.device(hp["device"] if torch.cuda.is_available() else "cpu")
    hd = int(hp["hidden_dim"])
    nlayers = int(hp["num_layers"])
    nedges = int(hp["num_neighbors"])
    noise = float(hp["backbone_noise"])
    model = optimizer = None
    try:
        dataset = StructureDataset(
            _pdb_dicts(job, parse_PDB), verbose=False, truncate=None,
            max_length=int(hp["max_protein_length"]),
        )
        if len(dataset) == 0:
            raise RuntimeError(
                "no structures survived parsing/length filtering "
                f"(max_protein_length={hp['max_protein_length']}); nothing to train on."
            )
        loader = StructureLoader(dataset, batch_size=int(hp["batch_tokens"]))

        # -- model at the public v_48 architecture, resume prior weights -----
        model = ProteinMPNN(
            num_letters=21, node_features=hd, edge_features=hd, hidden_dim=hd,
            num_encoder_layers=nlayers, num_decoder_layers=nlayers,
            k_neighbors=nedges, augment_eps=noise, dropout=float(hp["dropout"]),
        ).to(device)

        step = 0
        resume = job.get("resume_from")
        if resume:
            state = torch.load(resume, map_location=device)
            model.load_state_dict(state["model_state_dict"] if "model_state_dict"
                                  in state else state)
            step = int(state.get("step", 0))    # continue the Noam schedule
        model.train()

        optimizer = NoamOpt(
            hd, float(hp["learning_rate_factor"]), int(hp["warmup_steps"]),
            torch.optim.Adam(model.parameters(), lr=0.0, betas=(0.9, 0.98),
                             eps=1e-9),
            step,
        )

        gradient_norm = hp.get("gradient_norm")
        # -- the fine-tuning loop (training/training.py, verbatim) -----------
        for _epoch in range(int(hp["max_epochs"])):
            for batch in loader:
                X, S, mask, lengths, chain_M, residue_idx, mask_self, \
                    chain_encoding_all = featurize(batch, device)
                optimizer.zero_grad()
                mask_for_loss = mask * chain_M
                log_probs = model(X, S, mask, chain_M, residue_idx,
                                  chain_encoding_all)
                _, loss = loss_smoothed(S, log_probs, mask_for_loss,
                                        weight=float(hp["label_smoothing"]))
                loss.backward()
                if gradient_norm and float(gradient_norm) > 0.0:
                    torch.nn.utils.clip_grad_norm_(model.parameters(),
                                                   float(gradient_norm))
                optimizer.step()
                step += 1

        # Snapshot to CPU before the finally frees the GPU copy.
        cpu_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
        ckpt = {
            "model_state_dict": cpu_state,
            "num_edges": nedges,               # protein_mpnn_run.py reads this
            "noise_level": noise,
            "step": int(step),
            "optimizer_state_dict": optimizer.optimizer.state_dict(),
        }
        target = job["target_weights"]
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        # Write beside the target then replace, so a reader (IMPRESS mid-pass)
        # never sees a half-written weights file.
        tmp = target + ".tmp"
        torch.save(ckpt, tmp)
        os.replace(tmp, target)

        # Completion marker, written LAST, into this round's output_dir. The
        # training manager polls for it to detect that the round finished, even
        # when the execution backend never delivers the task's result (a Dragon
        # defect — see docs/dragon.md). It has to be this marker rather than the
        # checkpoint itself: with publish_into_repo the checkpoint is a stable
        # path that already exists from the previous round. Name kept in sync
        # with rome.trainer.TRAIN_COMPLETE_MARKER.
        output_dir = job.get("output_dir")
        if output_dir:
            with open(os.path.join(output_dir, "train_complete"), "w") as fd:
                fd.write(target)
        return target
    finally:
        # Release the GPU as soon as the round ends — see the module docstring.
        del model, optimizer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def main(argv: Tuple[str, ...] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True,
                        help="path to the job spec JSON written by the trainer")
    args = parser.parse_args(argv)

    with open(args.job) as fd:
        job = json.load(fd)
    checkpoint = run_round(job)
    # The last stdout line is the checkpoint path, for a caller reading stdout.
    print(checkpoint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
