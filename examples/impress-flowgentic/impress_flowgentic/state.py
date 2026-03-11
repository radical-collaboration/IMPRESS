from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SequenceScore(BaseModel):
    sequence: str
    score: float


class EnsembleRecord(BaseModel):
    target: str      # protein target identifier
    step_index: int
    type: Literal["backbone", "sequence", "decoy"]
    score: float
    input_ref: str   # "START" or output_ref of the preceding step
    output_ref: str  # identifier/path for this output


class PassState(BaseModel):
    pipeline_name: str
    pass_index: int
    skip_design: bool
    seq_rank: int
    num_seqs: int

    active_targets: list[str] = Field(default_factory=list)
    fasta_targets: list[str] = Field(default_factory=list)

    base_path: str
    output_path: str
    output_path_mpnn: str
    output_path_af: str

    iter_seqs: dict[str, list[SequenceScore]] = Field(default_factory=dict)
    selected_sequences: dict[str, str] = Field(default_factory=dict)

    current_scores: dict[str, float] = Field(default_factory=dict)
    score_history: dict[str, list[float]] = Field(default_factory=dict)

    events: list[str] = Field(default_factory=list)

    # Routing: set by analysis tasks, read by conditional edge router functions
    current_route: str = ""

    # Per-pass trajectory (accumulated in-memory; flushed to ensemble store by analyze_fold)
    trajectory: list[dict] = Field(default_factory=list)

    # Output references updated by each data-transformation task
    backbone_refs: dict[str, str] = Field(default_factory=dict)   # target → backbone id
    backbone_scores: dict[str, float] = Field(default_factory=dict)

    # Path to the pipeline's JSONL ensemble store (set at pipeline init, constant per pipeline)
    ensemble_store_path: str = ""
