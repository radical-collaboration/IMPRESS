from __future__ import annotations

import asyncio
import copy
import random
from pathlib import Path
from typing import Any

from flowgentic.langGraph.execution_wrappers import AsyncFlowType
from langgraph.graph import END, START, StateGraph

from .base import FlowgenticImpressBasePipeline
from .io import append_ensemble_records, ensure_ensemble_store, ensure_pipeline_layout
from .mocks import (
    PEPTIDE_SEQUENCE,
    compute_mock_metrics,
    generate_mock_backbone,
    generate_mock_sequences,
    parse_mpnn_sequences,
    write_mock_alphafold_for_target,
    write_mpnn_sequences_file,
    write_score_csv,
    stable_hash,
)
from .state import EnsembleRecord, PassState, SequenceScore

# ---------------------------------------------------------------------------
# Hard-coded routing probability tables.
# Keys are node names or "__end__"; values are weights for random.choices().
# Adjust weights here to change default behaviour without touching node code.
# ---------------------------------------------------------------------------

BACKBONE_ROUTING_PROBS: dict[str, float] = {
    "mock_backbone_prediction": 0.0,
    "mock_sequence_prediction": 1.0,  # default: proceed to sequence design
    "mock_fold_prediction":     0.0,
}

SEQUENCE_ROUTING_PROBS: dict[str, float] = {
    "mock_backbone_prediction": 0.0,
    "mock_sequence_prediction": 0.0,
    "mock_fold_prediction":     1.0,  # default: proceed to fold prediction
}

FOLD_ROUTING_PROBS: dict[str, float] = {
    "mock_backbone_prediction": 0.0,
    "mock_sequence_prediction": 0.0,
    "mock_fold_prediction":     0.0,
    "__end__":                  1.0,  # default: terminate the pass
}


def _sample_route(probs: dict[str, float]) -> str:
    """Sample one key from *probs* using the values as weights."""
    keys = list(probs.keys())
    weights = [probs[k] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


class ProteinBindingFlowgenticPipeline(FlowgenticImpressBasePipeline):
    """Flowgentic + LangGraph recreation of the IMPRESS protein-binding pipeline."""

    def __init__(
        self,
        name: str,
        integration: Any,
        configs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        cfg = configs or {}
        cfg.update(kwargs)

        self.is_child = bool(cfg.get("is_child", False))
        self.passes = int(cfg.get("passes", 1))
        self.start_pass = int(cfg.get("start_pass", 1))
        self.seq_rank = int(cfg.get("seq_rank", 0))
        self.num_seqs = int(cfg.get("num_seqs", 6))
        self.sub_order = int(cfg.get("sub_order", 0))
        self.max_passes = int(cfg.get("max_passes", 4))
        self.max_sub_pipelines = int(cfg.get("max_sub_pipelines", 3))
        self.degradation_threshold = float(cfg.get("degradation_threshold", 0.14))

        self.base_path = Path(cfg.get("base_path", Path.cwd() / "workspace")).resolve()

        self.iter_seqs: dict[str, list[SequenceScore]] = self._coerce_iter_seqs(
            cfg.get("iter_seqs", {})
        )
        self.score_history: dict[str, list[float]] = copy.deepcopy(cfg.get("score_history", {}))
        self.current_scores: dict[str, float] = {}
        self.previous_scores: dict[str, float] = {}
        self.last_completed_pass = 0

        self.input_path = self.base_path / f"{name}_in"
        self.output_path = self.base_path / "af_pipeline_outputs_multi" / name
        self.output_path_mpnn = self.output_path / "mpnn"
        self.output_path_af = self.output_path / "af/prediction/best_models"

        ensure_pipeline_layout(self.base_path, name, self.max_passes)
        self.fasta_list_2 = sorted(path.name for path in self.input_path.glob("*.pdb"))

        # Ensemble store: one JSONL file per pipeline, cleared at init and appended per pass.
        store_path = ensure_ensemble_store(self.base_path, name)
        store_path.unlink(missing_ok=True)  # start each pipeline run with a fresh store
        self.ensemble_store_path = str(store_path)

        super().__init__(name=name, integration=integration, **cfg)

        self.pass_app = self._build_pass_graph()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _coerce_iter_seqs(self, raw: dict[str, list[Any]]) -> dict[str, list[SequenceScore]]:
        out: dict[str, list[SequenceScore]] = {}
        for protein, entries in raw.items():
            out[protein] = [
                entry if isinstance(entry, SequenceScore) else SequenceScore(**entry)
                for entry in entries
            ]
        return out

    def set_up_new_pipeline_dirs(self, new_pipeline_name: str) -> None:
        ensure_pipeline_layout(self.base_path, new_pipeline_name, self.max_passes)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_pass_graph(self):  # noqa: C901
        workflow = StateGraph(PassState)

        # ---- router functions ----

        def should_skip_design(state: PassState) -> str:
            """Child pipelines skip backbone+sequence on their first inherited pass."""
            return "skip" if state.skip_design else "run"

        def route_from_analysis(state: PassState) -> str:
            return state.current_route

        # ---- prepare_pass: records pass metadata and dispatches to first node ----

        @self.integration.execution_wrappers.asyncflow(flow_type=AsyncFlowType.EXECUTION_BLOCK)
        async def prepare_pass(state: PassState) -> dict[str, Any]:
            event = f"pass={state.pass_index} skip_design={state.skip_design}"
            return {"events": state.events + [event]}

        # ================================================================
        # Data transformation nodes
        # ================================================================

        @self.integration.execution_wrappers.asyncflow(flow_type=AsyncFlowType.EXECUTION_BLOCK)
        async def mock_backbone_prediction(state: PassState) -> dict[str, Any]:
            backbone_refs: dict[str, str] = {}
            for target in state.active_targets:
                backbone_refs[target] = generate_mock_backbone(
                    target=target, pass_index=state.pass_index
                )
            return {
                "backbone_refs": backbone_refs,
                "events": state.events + [f"backbone_predicted={len(backbone_refs)}"],
            }

        @self.integration.execution_wrappers.asyncflow(flow_type=AsyncFlowType.EXECUTION_BLOCK)
        async def mock_sequence_prediction(state: PassState) -> dict[str, Any]:
            job_seqs_dir = (
                Path(state.output_path_mpnn) / f"job_{state.pass_index}" / "seqs"
            )
            job_seqs_dir.mkdir(parents=True, exist_ok=True)

            produced: dict[str, list[SequenceScore]] = {}
            for target in state.active_targets:
                seqs = generate_mock_sequences(
                    target=target, pass_index=state.pass_index, num_seqs=state.num_seqs
                )
                produced[target] = seqs
                write_mpnn_sequences_file(job_seqs_dir / f"{target}.fa", seqs)

            return {
                "iter_seqs": produced,
                "events": state.events + [f"sequences_predicted={len(produced)}"],
            }

        @self.integration.execution_wrappers.asyncflow(flow_type=AsyncFlowType.EXECUTION_BLOCK)
        async def mock_fold_prediction(state: PassState) -> dict[str, Any]:
            """Build FASTA inputs then run fold prediction (incorporates former build_fasta)."""
            fasta_dir = Path(state.output_path) / "af/fasta"
            fasta_dir.mkdir(parents=True, exist_ok=True)

            targets: list[str] = []
            selected_sequences: dict[str, str] = {}

            for target in state.active_targets:
                candidates = state.iter_seqs.get(target, [])
                if not candidates:
                    continue

                idx = min(state.seq_rank, len(candidates) - 1)
                selected = candidates[idx]
                sequence = (
                    selected.sequence
                    if isinstance(selected, SequenceScore)
                    else selected["sequence"]
                )

                fasta_file = fasta_dir / f"{target}.fa"
                fasta_file.write_text(
                    f">pdz\n{sequence}\n>pep\n{PEPTIDE_SEQUENCE}\n",
                    encoding="utf-8",
                )
                targets.append(target)
                selected_sequences[target] = sequence

            fold_tasks = [
                write_mock_alphafold_for_target(
                    target=target,
                    pass_index=state.pass_index,
                    sequence=selected_sequences[target],
                    output_path=Path(state.output_path),
                    output_path_mpnn=Path(state.output_path_mpnn),
                )
                for target in targets
            ]
            if fold_tasks:
                await asyncio.gather(*fold_tasks)

            return {
                "fasta_targets": targets,
                "selected_sequences": selected_sequences,
                "events": state.events + [f"fold_predicted={len(fold_tasks)}"],
            }

        # ================================================================
        # Analysis nodes
        # ================================================================

        @self.integration.execution_wrappers.asyncflow(flow_type=AsyncFlowType.EXECUTION_BLOCK)
        async def analyze_backbone(state: PassState) -> dict[str, Any]:
            backbone_scores: dict[str, float] = {}
            new_records: list[dict] = []
            step_idx = len(state.trajectory)

            for target in state.active_targets:
                raw = stable_hash(f"{target}-backbone-score-{state.pass_index}")
                score = round(0.6 + (raw % 300) / 1000.0, 3)
                backbone_scores[target] = score

                output_ref = state.backbone_refs.get(
                    target, f"backbone_{target}_pass{state.pass_index}"
                )
                record = EnsembleRecord(
                    target=target,
                    step_index=step_idx,
                    type="backbone",
                    score=score,
                    input_ref="START",
                    output_ref=output_ref,
                )
                new_records.append(record.model_dump())

            route = _sample_route(BACKBONE_ROUTING_PROBS)
            return {
                "backbone_scores": backbone_scores,
                "current_route": route,
                "trajectory": state.trajectory + new_records,
                "events": state.events + [f"analyze_backbone→{route}"],
            }

        @self.integration.execution_wrappers.asyncflow(flow_type=AsyncFlowType.EXECUTION_BLOCK)
        async def analyze_sequence(state: PassState) -> dict[str, Any]:
            job_seqs_dir = (
                Path(state.output_path_mpnn) / f"job_{state.pass_index}" / "seqs"
            )
            ranked = parse_mpnn_sequences(job_seqs_dir)
            new_records: list[dict] = []
            step_idx = len(state.trajectory)

            for target, seqs in ranked.items():
                top_seq = seqs[0] if seqs else None
                score = top_seq.score if top_seq is not None else 0.0
                output_ref = top_seq.sequence[:20] if top_seq is not None else ""
                input_ref = state.backbone_refs.get(target, "START")
                record = EnsembleRecord(
                    target=target,
                    step_index=step_idx,
                    type="sequence",
                    score=score,
                    input_ref=input_ref,
                    output_ref=output_ref,
                )
                new_records.append(record.model_dump())

            route = _sample_route(SEQUENCE_ROUTING_PROBS)
            return {
                "iter_seqs": ranked,
                "current_route": route,
                "trajectory": state.trajectory + new_records,
                "events": state.events + [f"analyze_sequence→{route}"],
            }

        @self.integration.execution_wrappers.asyncflow(flow_type=AsyncFlowType.EXECUTION_BLOCK)
        async def analyze_fold(state: PassState) -> dict[str, Any]:
            metrics = compute_mock_metrics(
                targets=state.fasta_targets,
                pass_index=state.pass_index,
                pipeline_name=state.pipeline_name,
            )

            csv_path = (
                Path(state.base_path)
                / f"af_stats_{state.pipeline_name}_pass_{state.pass_index}.csv"
            )
            write_score_csv(csv_path=csv_path, metrics=metrics)

            current_scores = {target: row["avg_pae"] for target, row in metrics.items()}
            score_history = copy.deepcopy(state.score_history)
            for target, value in current_scores.items():
                score_history.setdefault(target, []).append(value)

            # Build trajectory records for fold outputs
            new_records: list[dict] = []
            step_idx = len(state.trajectory)
            for target in state.fasta_targets:
                score = current_scores.get(target, 0.0)
                input_ref = state.selected_sequences.get(target, "")[:20]
                output_ref = str(
                    Path(state.output_path) / "af/prediction/best_models" / f"{target}.pdb"
                )
                record = EnsembleRecord(
                    target=target,
                    step_index=step_idx,
                    type="decoy",
                    score=score,
                    input_ref=input_ref,
                    output_ref=output_ref,
                )
                new_records.append(record.model_dump())

            completed_trajectory = state.trajectory + new_records

            # Flush the completed trajectory to the ensemble store.
            if completed_trajectory and state.ensemble_store_path:
                pipeline_name = state.pipeline_name
                pass_index = state.pass_index
                for r in completed_trajectory:
                    r["pipeline_name"] = pipeline_name
                    r["pass_index"] = pass_index
                append_ensemble_records(Path(state.ensemble_store_path), completed_trajectory)

            route = _sample_route(FOLD_ROUTING_PROBS)
            return {
                "current_scores": current_scores,
                "score_history": score_history,
                "current_route": route,
                "trajectory": [],  # reset for any subsequent trajectory within this pass
                "events": state.events + [
                    f"analyze_fold→{route}",
                    f"scores_written={csv_path.name}",
                ],
            }

        # ================================================================
        # Wire the graph
        # ================================================================

        workflow.add_node("prepare_pass",              prepare_pass)
        workflow.add_node("mock_backbone_prediction",  mock_backbone_prediction)
        workflow.add_node("analyze_backbone",          analyze_backbone)
        workflow.add_node("mock_sequence_prediction",  mock_sequence_prediction)
        workflow.add_node("analyze_sequence",          analyze_sequence)
        workflow.add_node("mock_fold_prediction",      mock_fold_prediction)
        workflow.add_node("analyze_fold",              analyze_fold)

        # Entry: prepare_pass dispatches to either backbone prediction or fold prediction
        # (skip_design=True is used for child pipelines on their first inherited pass).
        workflow.add_edge(START, "prepare_pass")
        workflow.add_conditional_edges(
            "prepare_pass",
            should_skip_design,
            {"run": "mock_backbone_prediction", "skip": "mock_fold_prediction"},
        )

        # Straight edges: data-transformation → paired analysis
        workflow.add_edge("mock_backbone_prediction", "analyze_backbone")
        workflow.add_edge("mock_sequence_prediction",  "analyze_sequence")
        workflow.add_edge("mock_fold_prediction",      "analyze_fold")

        # Conditional edges from each analysis node to any data-transformation node (or END)
        _data_xform_targets = {
            "mock_backbone_prediction": "mock_backbone_prediction",
            "mock_sequence_prediction": "mock_sequence_prediction",
            "mock_fold_prediction":     "mock_fold_prediction",
        }
        workflow.add_conditional_edges("analyze_backbone", route_from_analysis, _data_xform_targets)
        workflow.add_conditional_edges("analyze_sequence",  route_from_analysis, _data_xform_targets)
        workflow.add_conditional_edges(
            "analyze_fold",
            route_from_analysis,
            {**_data_xform_targets, "__end__": END},
        )

        return workflow.compile()

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        while self.passes <= self.max_passes:
            active_targets = [file_name.split(".")[0] for file_name in self.fasta_list_2]
            if not active_targets:
                self.kill_parent = True
                break

            # Child pipelines skip backbone+sequence on their first inherited pass
            # so that they reuse the parent's best sequences directly for fold prediction.
            skip_design = self.is_child and self.passes == self.start_pass

            state = PassState(
                pipeline_name=self.name,
                pass_index=self.passes,
                skip_design=skip_design,
                seq_rank=self.seq_rank,
                num_seqs=self.num_seqs,
                active_targets=active_targets,
                fasta_targets=[],
                base_path=str(self.base_path),
                output_path=str(self.output_path),
                output_path_mpnn=str(self.output_path_mpnn),
                output_path_af=str(self.output_path_af),
                iter_seqs=self.iter_seqs,
                score_history=self.score_history,
                backbone_refs={},
                backbone_scores={},
                trajectory=[],
                current_route="",
                ensemble_store_path=self.ensemble_store_path,
            )

            final_state = await self.pass_app.ainvoke(state)
            final_state_data = (
                final_state.model_dump()
                if hasattr(final_state, "model_dump")
                else final_state
            )

            self.iter_seqs = self._coerce_iter_seqs(
                final_state_data.get("iter_seqs", self.iter_seqs)
            )
            self.current_scores = final_state_data.get("current_scores", self.current_scores)
            self.score_history = final_state_data.get("score_history", self.score_history)
            self.last_completed_pass = self.passes

            if self.current_scores and not self.previous_scores:
                self.previous_scores = copy.deepcopy(self.current_scores)

            await self.run_adaptive_step(wait=True)

            if self.kill_parent:
                break

            self.passes += 1

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def finalize(self, sub_iter_seqs: dict[str, list[Any]]) -> None:
        for protein in sub_iter_seqs:
            file_name = f"{protein}.pdb"
            if file_name in self.fasta_list_2:
                self.fasta_list_2.remove(file_name)

            model_file = self.output_path_af / f"{protein}.pdb"
            fasta_file = self.output_path / "af/fasta" / f"{protein}.fa"

            if model_file.exists():
                model_file.unlink()
            if fasta_file.exists():
                fasta_file.unlink()

        self.previous_scores = copy.deepcopy(self.current_scores)
