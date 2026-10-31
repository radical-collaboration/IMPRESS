"""Control model D: the reference's own rules driving the agentic loop.

The LLM arms change two things at once against the reference -- the decision
rules become a model, and the fixed state machine becomes a tool-calling
harness -- so no figure on file says which of the two is responsible. This
client changes only the second. It calls the reference's `adaptive_decision()`
on the live pipeline and translates the `next_step` it writes into one tool
call, so the rules are held fixed while the execution path varies.

The rules are *imported*, never restated, for the same reason `run_agentic_smb`
imports `PROD`: a restatement drifts from the reference silently, and an arm
whose whole value is rule-identity cannot afford that. Two consequences of
importing rather than reimplementing, both deliberate:

  * The backbone similarity gate is inert on a real run -- `_ca_rmsd` needs two
    `.pdb` paths but `analysis_backbone` stores `.cif.gz`, so `has_data` is
    False and the branch always takes its STEP_MPNN fallback. Only the fold
    branch (Boltz `.pdb`) and the sequence branch (`.fa`) really evaluate.
  * `analysis_sequence` hardcodes `pass: True`, so the sequence branch routes
    purely on the selective-average comparison.

Reproducing both is correct. "Fixing" either means this is no longer the
reference's rules and the arm stops being a control.

This client reads the pipeline, not `messages`. That is what the reference does,
and `_compact_history()` deletes the older tool results a message-parsing
version would need. It is therefore not "the LLM arm minus the LLM": the LLM
sees a compacted context, model D sees ground truth -- the same ground truth the
reference sees.
"""

from __future__ import annotations

import json
import os
import sys

_REF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "small_molecule_binding")
if _REF_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_REF_DIR))

from llm import Completion, ToolCall  # noqa: E402
from run_small_molecule_binding import adaptive_decision  # noqa: E402
from small_molecule_binding import (  # noqa: E402
    STEP_AF2,
    STEP_DONE,
    STEP_FASTRELAX,
    STEP_INTERFACE,
    STEP_MPNN,
    STEP_RETRY_SEQ,
    STEP_RFD3,
)

# next_step values that map to exactly one tool, with no cycle state involved.
_DIRECT = {
    STEP_RFD3:      "design_backbone",
    STEP_FASTRELAX: "relax",
    STEP_INTERFACE: "score_interface",
    STEP_AF2:       "fold_complex",
}


def _apply_rules(pipeline) -> None:
    """Run `adaptive_decision(pipeline)` to completion, from any context.

    It is `async def` with no `await` -- asyncflow's shape for a task body --
    so driving it one step runs the whole thing. That matters: `asyncio.run()`
    raises `RuntimeError: asyncio.run() cannot be called from a running event
    loop`, and whether a loop is running here depends on how the engine
    dispatches the adaptive callback, which differs between the runner and the
    offline harness. Stepping the coroutine works in both.

    Getting this wrong is not a visible crash. `llm_turn()` catches any
    exception from `complete()` and degrades the pipeline to the scripted
    route, so a model-D arm would quietly produce reference-route-shaped
    results with `degraded: true` -- the exact trap of job 23219379. Hence the
    explicit failure if the no-await assumption ever stops holding.
    """
    coro = adaptive_decision(pipeline)
    try:
        coro.send(None)
    except StopIteration:
        return
    coro.close()
    raise RuntimeError(
        "adaptive_decision() awaited something; control model D assumes its "
        "body is synchronous. Drive it on a real event loop instead.")


class RulesClient:
    """Drives the loop from `adaptive_decision()` instead of a model.

    Satisfies the same `complete()` contract as the LLM clients, so the loop,
    the tools, compaction and the transcript are the LLM arms' unchanged.
    """

    name = "rules-d"
    control_model = "D"

    def __init__(self):
        self.pipeline = None
        self._n = 0
        self._first_turn = True
        # Position inside the reference's refine cycle, or None when not in
        # one. `cycle_i` is the reference's own `_current_cycle_i`.
        self._refine: dict | None = None

    def bind_pipeline(self, pipeline) -> None:
        """Take the live pipeline. Called once by `AgenticSMBPipeline.run()`.

        `build_client()` runs while the pipeline is still a PipelineSetup config
        dict, so the pipeline cannot be supplied at construction.
        """
        self.pipeline = pipeline

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        if self.pipeline is None:
            raise RuntimeError(
                "RulesClient was never bound to a pipeline; "
                "AgenticSMBPipeline.run() must call bind_pipeline(self)")

        tool, args = self._next_call()
        self._n += 1
        call = ToolCall(id=f"rules-{self._n}", name=tool, arguments=args)
        return Completion(
            text="",
            tool_calls=[call],
            raw_message={
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": call.id,
                    "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(args)},
                }],
            },
        )

    # ── the routing itself ─────────────────────────────────────────────────

    def _next_call(self) -> tuple[str, dict]:
        pipeline = self.pipeline

        # The reference's run() sets next_step = STEP_RFD3 *before* its loop,
        # without consulting the rules. Calling adaptive_decision() here instead
        # would hand it last_analysis_step=None, take its unknown-step branch
        # and stop the run on turn one.
        if self._first_turn:
            self._first_turn = False
            self._refine = None
            return self._design_backbone()

        _apply_rules(pipeline)
        step = pipeline.next_step
        last = pipeline.state.get('last_analysis_step')

        if step == STEP_DONE:
            return "finish", {"reason": (
                f"reference rules returned STEP_DONE after {last!r} "
                f"(ensemble {len(pipeline.state.get('ensemble', []))}"
                f"/{pipeline.max_tasks})")}

        if step == STEP_RETRY_SEQ:
            # Re-run mpnn inside the same refine cycle, against the same input.
            return self._design_sequence(self._cycle_i())

        if step == STEP_MPNN:
            return self._refine_step(last)

        tool = _DIRECT.get(step)
        if tool is None:
            return "finish", {"reason": f"unmapped next_step {step!r}"}
        if tool != "score_interface":
            # Anything but the interface gate ends the refine cycle: the
            # reference leaves _run_refine_cycle() to reach them.
            self._refine = None
        if tool == "design_backbone":
            return self._design_backbone()
        return tool, {}

    def _refine_step(self, last: str | None) -> tuple[str, dict]:
        """STEP_MPNN is not one tool call.

        The reference consumes it inside `_run_refine_cycle()`: num_refine_cycles
        passes, each running mpnn and then -- except on the last -- packmin,
        with STEP_RETRY_SEQ re-running mpnn inside the same pass. Which tool
        STEP_MPNN means therefore depends on where in that loop we are, which is
        what `last` disambiguates.
        """
        n_cycles = int(getattr(self.pipeline, "num_refine_cycles", 2))

        if last == 'sequence':
            # mpnn passed, so the inner loop broke. packmin next, unless this
            # was the last cycle -- where run() turns the natural return into
            # STEP_FASTRELAX.
            if self._cycle_i() < n_cycles - 1:
                return "pack_minimize", {}
            self._refine = None
            return "relax", {}

        if last == 'packmin':
            # packmin was good: advance a cycle and resequence from the packed
            # structure, which is what _current_cycle_i >= 1 selects.
            cycle_i = self._cycle_i() + 1
            self._refine = {"cycle_i": cycle_i}
            return self._design_sequence(cycle_i)

        # STEP_MPNN from backbone, fastrelax or interface: the reference calls
        # _run_refine_cycle() afresh, so the loop restarts at cycle 0 and
        # resequences from the backbone.
        self._refine = {"cycle_i": 0}
        return self._design_sequence(0)

    def _cycle_i(self) -> int:
        if self._refine is None:
            self._refine = {"cycle_i": 0}
        return int(self._refine["cycle_i"])

    def _design_backbone(self) -> tuple[str, dict]:
        # state['rfd3_input_pdb'] is the guided seed the fold branch sets, or
        # None for a backbone from scratch. The handler treats None as absent.
        guide = self.pipeline.state.get('rfd3_input_pdb')
        return "design_backbone", {"guide_model": guide}

    def _design_sequence(self, cycle_i: int) -> tuple[str, dict]:
        # The handler sets pipeline._current_cycle_i from `source`, which is the
        # reference's own cycle selector: cycle 0 reads best_backbone_path,
        # later cycles read best_packed_pdb.
        self._refine = {"cycle_i": cycle_i}
        return "design_sequence", {
            "source": "backbone" if cycle_i == 0 else "packed"}
