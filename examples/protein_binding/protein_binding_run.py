import copy
import json
import logging
import os
import shutil
import asyncio
from typing import Dict, Any, List, Optional
from concurrent.futures import ProcessPoolExecutor

import anthropic
import numpy as np
import pandas as pd

# from rhapsody.backends import DragonExecutionBackendV3
from radical.asyncflow import LocalExecutionBackend
import rhapsody
rhapsody.enable_logging(level=logging.DEBUG)

from impress import PipelineSetup
from impress import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline


LLM_MODEL = "claude-opus-4-6"

METRIC_COLS = [
    "mpnn_score",
    "mpnn_global_score",
    "seq_recovery",
    "confidence_score",
    "ptm",
    "iptm",
    "complex_plddt",
    "complex_ipde",
]

_STATIC_PROMPT = """\
# Protein Design Workflow Advisor

## Background: Computational Protein Design
Computational protein design uses machine learning models to engineer novel amino acid \
sequences that fold into target structures with desired functional properties. A common \
workflow couples a sequence design model (e.g., ProteinMPNN) with a structure prediction \
model (e.g., Boltz, AlphaFold2). The sequence model proposes residues compatible with a \
given backbone; the structure model folds that sequence into a three-dimensional conformation. \
Each candidate is evaluated on confidence metrics: pLDDT (per-residue confidence), pTM \
(predicted template modeling score), ipTM (interface pTM), and iPDE (interface predicted \
distance error). Sequence quality is captured by MPNN score and sequence recovery relative \
to the native. Iterative refinement reruns this loop on the same sequence lineage, while \
sampling draws a new sequence from the design model. An ensemble of predictions accumulates \
across passes and provides the reference distribution against which individual candidate \
quality is judged.

## Task
This system is a workflow router tasked with making a decision about the next stage of the \
current workflow. To make this decision, compare the given protein design candidate with the \
ensemble of prior candidates and decide whether to continue to refine the current candidate \
or to sample a new one. The candidate design is the result of a sequence-structure tool chain: \
a model is used to compute a candidate sequence from a given backbone, then another model is \
used to predict a conformed structure from the candidate sequence. Each predicted sequence and \
structure is analyzed on a number of metrics. The results of all analyses are compiled and \
used to produce the ensemble distributions below.

The quality of a given design is determined by comparing the current design metrics with the \
prior ensemble. The next stage of the workflow will either be to refine the current candidate \
sequence or to sample a new sequence. It would be good to refine the current sequence if \
doing so is likely to result in a high-quality structure, i.e., a structure with analytics \
that would place it above average in the prior ensemble. Otherwise, it would be better to \
sample a new sequence for refinement.

Determine whether the current candidate should be refined or if a new candidate should be \
sampled. Assert your decision as EXACTLY one of the following two sentences:
- "The current sequence should be refined."
- "A new sequence should be sampled."

## Ensemble Data
"""


def _parse_mpnn_fasta(fasta_path: str, seq_rank: int) -> Dict[str, Any]:
    """Parse an MPNN FASTA file and return sequence data at the given rank.

    Skips the first two lines (original-structure header and sequence), then
    parses each sampled block into a record, sorts by mpnn_score ascending
    (matching s2 logic), and returns the record at seq_rank.

    Header format: ">T=0.1, sample=N, score=X, global_score=Y, seq_recovery=Z"
    """
    records = []
    current_meta: Dict[str, Any] = {}

    with open(fasta_path) as fh:
        lines = fh.readlines()[2:]  # skip original-sequence header + sequence

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            parts = line.split(",")
            current_meta = {
                "mpnn_score": float(parts[2].replace(" score=", "")),
                "mpnn_global_score": float(parts[3].replace(" global_score=", "")),
                "seq_recovery": float(parts[4].replace(" seq_recovery=", "")),
            }
        else:
            records.append({**current_meta, "sequence": line})

    records.sort(key=lambda r: r["mpnn_score"])
    idx = min(seq_rank, len(records) - 1)
    return records[idx]


def _format_distributions_text(
    prior_df: pd.DataFrame,
    current_row: Dict[str, Any],
    metric_cols: List[str],
) -> str:
    """Format ensemble distributions and current candidate metrics as prompt text."""
    lines: List[str] = []

    lines.append("=== Current Candidate Metrics ===")
    for col in metric_cols:
        lines.append(f"  {col}: {current_row[col]:.4f}")

    if prior_df.empty:
        lines.append("\n=== No prior ensemble data available. ===")
        return "\n".join(lines)

    lines.append(f"\n=== Prior Ensemble Distributions (N={len(prior_df)} predictions) ===")

    for col in metric_cols:
        values = prior_df[col].dropna().values
        if len(values) == 0:
            lines.append(f"\n{col}: (no data)")
            continue

        mean = float(np.mean(values))
        std = float(np.std(values))
        n_bins = max(1, min(10, len(values)))
        counts, bin_edges = np.histogram(values, bins=n_bins)

        percentile = float(np.sum(values < current_row[col]) / len(values) * 100)

        bin_str = ", ".join(f"{e:.3f}" for e in bin_edges)
        count_str = ", ".join(str(c) for c in counts)

        lines.append(f"\n{col}:")
        lines.append(f"  N={len(values)}, mean={mean:.4f}, std={std:.4f}")
        lines.append(f"  bins: [{bin_str}]")
        lines.append(f"  counts: [{count_str}]")
        lines.append(f"  current candidate percentile: {percentile:.0f}th")

    return "\n".join(lines)


async def _query_llm(distributions_text: str) -> bool:
    """Send ensemble distributions to Claude and parse a refine/new-sample decision.

    Returns True if a new sequence should be sampled, False if the current
    sequence should be refined.
    """
    prompt = _STATIC_PROMPT + distributions_text

    client = anthropic.AsyncAnthropic()
    message = await client.messages.create(
        model=LLM_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text
    return "A new sequence should be sampled." in response_text


async def adaptive_criteria(pipeline: ProteinBindingPipeline, protein: str) -> bool:
    """Collect per-protein design metrics, update ensemble.csv and
    ensemble_distributions.npz, then query the LLM for a routing decision.

    Returns True if a new sequence should be sampled (move protein to child
    pipeline), False if the current sequence should be refined (keep in
    current pipeline).  Returns False without calling the LLM when no prior
    ensemble data exists.
    """
    # --- Locate analytics files ---
    fasta_path = os.path.join(
        pipeline.output_path_mpnn, f"job_{pipeline.passes}", "seqs", f"{protein}.fa"
    )
    conf_json_path = os.path.join(
        pipeline.output_path,
        "af", "prediction", "dimer_models", protein,
        f"boltz_results_{protein}", "predictions", protein,
        f"confidence_{protein}_model_0.json",
    )

    # --- Read sequence metrics ---
    seq_data = _parse_mpnn_fasta(fasta_path, pipeline.seq_rank)

    # --- Read structure metrics ---
    with open(conf_json_path) as fh:
        conf = json.load(fh)

    current_row: Dict[str, Any] = {
        "name": protein,
        "pass": pipeline.passes,
        "sequence": seq_data["sequence"],
        "mpnn_score": seq_data["mpnn_score"],
        "mpnn_global_score": seq_data["mpnn_global_score"],
        "seq_recovery": seq_data["seq_recovery"],
        "confidence_score": conf["confidence_score"],
        "ptm": conf["ptm"],
        "iptm": conf["iptm"],
        "complex_plddt": conf["complex_plddt"],
        "complex_ipde": conf["complex_ipde"],
    }

    # --- Update ensemble.csv ---
    ensemble_path = os.path.join(pipeline.base_path, "ensemble.csv")
    if os.path.exists(ensemble_path):
        ensemble_df = pd.read_csv(ensemble_path)
    else:
        ensemble_df = pd.DataFrame(columns=["name", "pass", "sequence"] + METRIC_COLS)

    prior_df = ensemble_df.copy()

    new_row_df = pd.DataFrame([current_row])
    ensemble_df = pd.concat([ensemble_df, new_row_df], ignore_index=True)
    ensemble_df.to_csv(ensemble_path, index=False)

    # --- Compute distributions → ensemble_distributions.npz ---
    dist_arrays: Dict[str, np.ndarray] = {}
    for col in METRIC_COLS:
        values = ensemble_df[col].dropna().values
        n_bins = max(1, min(10, len(values)))
        counts, bin_edges = np.histogram(values, bins=n_bins)
        dist_arrays[f"{col}_counts"] = counts
        dist_arrays[f"{col}_bin_edges"] = bin_edges

    npz_path = os.path.join(pipeline.base_path, "ensemble_distributions.npz")
    np.savez(npz_path, **dist_arrays)

    # --- Query LLM (skip when no prior data) ---
    if prior_df.empty:
        return False

    dist_text = _format_distributions_text(prior_df, current_row, METRIC_COLS)
    return await _query_llm(dist_text)


async def adaptive_decision(pipeline: ProteinBindingPipeline) -> None:
    """Adaptive function for protein structure optimization.

    For each protein in the current pass: collects analytics, updates the
    ensemble, and queries the LLM for a routing decision.  Proteins the LLM
    judges as needing a new sample are moved to a child pipeline; all others
    continue refinement in the current pipeline.
    """
    MAX_SUB_PIPELINES: int = 3

    # Read current scores from the per-pass stats CSV
    file_name = f"af_stats_{pipeline.name}_pass_{pipeline.passes}.csv"
    with open(file_name) as fd:
        for line in fd.readlines()[1:]:
            line = line.strip()
            if not line:
                continue
            name, *_, score_str = line.split(",")
            protein = name.split(".")[0]
            pipeline.current_scores[protein] = float(score_str)

    # Always update ensemble for all proteins (including first pass)
    decisions: Dict[str, bool] = {}
    for protein in list(pipeline.current_scores.keys()):
        if protein not in pipeline.iter_seqs:
            continue
        decisions[protein] = await adaptive_criteria(pipeline, protein)
        label = "new sample" if decisions[protein] else "refine"
        pipeline.logger.pipeline_log(f"Adaptive decision for {protein}: {label}")

    # First pass — save scores and return (LLM decisions not used for routing)
    if not pipeline.previous_scores:
        pipeline.logger.pipeline_log("Saving current scores as previous and returning")
        pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)
        return

    # Route proteins based on LLM decisions
    sub_iter_seqs: Dict[str, Any] = {}
    for protein, decision in decisions.items():
        if decision:
            sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)

    # Spawn a child pipeline for proteins that need a new sample
    if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
        new_name: str = f"{pipeline.name}_sub{pipeline.sub_order + 1}"

        pipeline.set_up_new_pipeline_dirs(new_name)

        for protein in sub_iter_seqs:
            src = f"{pipeline.output_path_af}/{protein}.pdb"
            dst = f"{pipeline.base_path}/{new_name}_in/{protein}.pdb"
            shutil.copyfile(src, dst)

        new_config = {
            "name": new_name,
            "type": type(pipeline),
            "adaptive_fn": adaptive_decision,
            "config": {
                "is_child": True,
                "start_pass": pipeline.passes,
                "passes": pipeline.passes,
                "iter_seqs": sub_iter_seqs,
                "seq_rank": pipeline.seq_rank + 1,
                "sub_order": pipeline.sub_order + 1,
                "previous_scores": copy.deepcopy(pipeline.previous_scores),
            },
        }

        pipeline.submit_child_pipeline_request(new_config)
        pipeline.finalize(sub_iter_seqs)

        if not pipeline.fasta_list_2:
            pipeline.kill_parent = True
    else:
        pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)


async def impress_protein_bind() -> None:
    """Execute protein binding analysis with LLM-driven adaptive optimization."""
#    backend = await DragonExecutionBackendV3()
    backend = await LocalExecutionBackend(ProcessPoolExecutor())

    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name="p1",
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision,
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)
    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
