"""A real IMPRESS run, small enough to watch.

Everything here is the genuine framework: a real `ImpressManager`, a real
`WorkflowEngine` on asyncflow's `LocalExecutionBackend`, real executable tasks
that start real subprocesses, and real adaptive child-pipeline spawning. Only
the science is simulated -- see `toy_science.py`.

The notebook holds the narrative; this module holds the machinery, so the cells
stay short enough to read.

Three things in here exist because of verified framework behaviour rather than
taste:

* **Commands use bare tokens only.** `LocalExecutionBackend` `shlex.split`s a
  command and re-joins the parts with spaces, so `'two words'` arrives as two
  arguments. Backlog F15.
* **The event recorder is thread-safe and only the event loop prints.** An
  `adaptive_fn` is an engine task on a thread pool, so it runs in a worker
  thread (measured: `ThreadPoolExecutor-0_0`). Printing from there interleaves
  badly in a notebook.
* **The adaptive rule caps its own depth.** The framework has no generation
  concept and enforces no cap. `ImpressManager.start()` returns when no
  pipeline is left, so a rule that always spawns never returns.

A note on wall time: each `await self.run_adaptive_step(wait=True)` costs about
a second, because the manager notices the flag on a 0.5s poll and clears the
barrier on a later one. That, not `task_duration_s`, is what a short run's
clock is mostly made of -- and it is honest to show it rather than hide it.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

from radical.asyncflow import LocalExecutionBackend, WorkflowEngine
from toy_science import ToyConfig, decide, fragile_targets, target_names

from impress import ImpressBasePipeline, ImpressManager, PipelineSetup
from impress.utils.logger import ImpressLogger, LogLevel

SCORE_STAGE = Path(__file__).resolve().parent / "score_stage.py"

EVENT_KINDS = (
    "run_start",
    "pipeline_start",
    "task_start",
    "task_end",
    "adaptive_eval",
    "spawn",
    "pipeline_end",
    "run_end",
)

# Declared once per `run_toy` and handed to every child config. The framework
# requires the *declared engine task*, not the coroutine it was declared from:
# `PipelineSetup` raises TypeError on a bare function, and a child config that
# carries the bare function fails the same way mid-run. This mirrors
# examples/dummy_adaptive.py. It is module-level, which is why `run_sweep` runs
# its configurations one at a time. (`pipeline._adaptive_fn`, which the manager
# sets, is the private alternative that avoids the global.)
_ADAPTIVE_TASK: Any = None


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


class EventRecorder:
    """Append-only run log, safe to write from any thread.

    `emit` may be called from the event loop (the pipeline's `run`) or from a
    thread-pool worker (the adaptive callback), so appends are locked. Printing
    is done only by `stream`, which runs as a task on the loop.
    """

    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._lock = threading.Lock()
        self._events: list = []
        self._pending: deque = deque()
        self._t0 = time.monotonic()

    def emit(
        self,
        kind: str,
        *,
        pipeline: str = "",
        generation: int = -1,
        task: str = "",
        targets: Optional[list] = None,
        detail: Optional[dict] = None,
    ) -> dict:
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {kind!r}; known: {EVENT_KINDS}")
        event = {
            "t": round(time.monotonic() - self._t0, 4),
            "kind": kind,
            "pipeline": pipeline,
            "generation": generation,
            "task": task,
            "targets": list(targets or ()),
            "detail": dict(detail or {}),
        }
        with self._lock:
            self._events.append(event)
            self._pending.append(event)
        return event

    @property
    def events(self) -> list:
        with self._lock:
            return [dict(e) for e in self._events]

    def drain(self) -> list:
        with self._lock:
            out = list(self._pending)
            self._pending.clear()
        return out

    def flush(self) -> None:
        """Print whatever is left. Called once after the manager returns."""
        if self.quiet:
            self.drain()
            return
        for event in self.drain():
            print(format_event(event))

    async def stream(self, interval: float = 0.05) -> None:
        """Print events as they arrive. The only thing in here that prints."""
        while True:
            self.flush()
            await asyncio.sleep(interval)


def format_event(event: dict) -> str:
    """One human-readable line per event."""
    # Name and generation are separate columns. A child's name already carries
    # its lineage, so folding the generation into it prints `p1.g1.g1`.
    gen = f"g{event['generation']}" if event["generation"] >= 0 else "  "
    bits = [
        f"[{event['t']:6.2f}s]",
        f"{event['pipeline'] or '-':<10s}",
        f"{gen:<3s}",
        f"{event['kind']:<14s}",
    ]
    if event["task"]:
        bits.append(f"{event['task']:<20s}")
    detail = event["detail"]
    if "pass" in detail:
        bits.append(f"pass {detail['pass']}")
    if "score" in detail:
        bits.append(f"score {detail['score']:.1f}")
    if "mean" in detail:
        bits.append(f"mean {detail['mean']:.1f}")
    if event["targets"]:
        bits.append(" ".join(event["targets"]))
    if "reason" in detail:
        bits.append(f"-- {detail['reason']}")
    return "  ".join(bits)


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------


class ToyPipeline(ImpressBasePipeline):
    """One pipeline over a set of targets, for a fixed number of passes.

    `ImpressManager` spreads a setup's `config` dict into keyword arguments, so
    every field below arrives as a keyword rather than as one dict.

    Every attribute a task body reads is assigned *before* `super().__init__()`,
    because the base class calls `register_pipeline_tasks()` from its
    constructor -- and does so before `self.logger` exists.
    """

    def __init__(
        self,
        name: str,
        flow: Any = None,
        cfg: Optional[ToyConfig] = None,
        targets: tuple = (),
        generation: int = 0,
        migrated: tuple = (),
        previous_scores: Optional[dict] = None,
        pass_offset: int = 0,
        recorder: Optional[EventRecorder] = None,
        parent_name: str = "",
        **kwargs: Any,
    ) -> None:
        self.cfg = cfg or ToyConfig()
        self.targets = list(targets) or list(target_names(self.cfg.n_targets))
        self.generation = generation
        self.migrated = frozenset(migrated)
        self.fragile = fragile_targets(self.cfg)
        self.previous_scores = dict(previous_scores or {})
        self.current_scores: dict = {}
        self.pass_offset = pass_offset
        self.pass_index = pass_offset
        self.parent_name = parent_name
        self.recorder = recorder or EventRecorder()
        self.script = str(SCORE_STAGE)

        super().__init__(name, flow, **kwargs)

    # -- tasks -------------------------------------------------------------

    def register_pipeline_tasks(self) -> None:
        @self.auto_register_task()
        async def structure_prediction(target: str, pass_index: int) -> str:
            """A real subprocess. Returns the command; stdout is the score.

            Bare tokens only -- see F15 in this module's docstring.
            """
            return (
                f"python3 {self.script} {target} {pass_index} {self.generation} "
                f"{int(target in self.migrated)} {self.cfg.seed} "
                f"{self.cfg.noise_sd} {int(target in self.fragile)} "
                f"{self.cfg.sleep_s}"
            )

        @self.auto_register_task(local_task=True)
        async def score_extraction(scores: dict) -> float:
            """A cheap CPU-only stage, so it runs in-process.

            `local_task=True` registers the coroutine itself rather than
            submitting it to the engine, and `wrap_local_task` times each call
            and emits one `impress.LocalStage` telemetry event when telemetry
            is on. The real flows use this for analysis steps that are not
            worth a task launch.
            """
            return sum(scores.values()) / len(scores) if scores else 0.0

    # -- control flow ------------------------------------------------------

    async def run(self) -> None:
        rec = self.recorder
        rec.emit(
            "pipeline_start",
            pipeline=self.name,
            generation=self.generation,
            targets=self.targets,
            detail={"parent": self.parent_name} if self.parent_name else {},
        )

        last = self.pass_offset + self.cfg.n_passes
        for pass_index in range(self.pass_offset, last):
            self.pass_index = pass_index
            if not self.targets:
                # Every target migrated into a child. The real examples set
                # `kill_parent = True` here and let the manager cancel this
                # task; stopping cleanly keeps a quickstart's log readable.
                rec.emit(
                    "pipeline_end",
                    pipeline=self.name,
                    generation=self.generation,
                    detail={"reason": "all targets migrated to a child"},
                )
                return

            await self._run_one_pass(pass_index)
            await self.run_adaptive_step(wait=True)
            self.previous_scores = dict(self.current_scores)

        rec.emit(
            "pipeline_end",
            pipeline=self.name,
            generation=self.generation,
            targets=self.targets,
            detail={"reason": f"completed {self.cfg.n_passes} passes"},
        )

    async def _run_one_pass(self, pass_index: int) -> None:
        """All targets' predictions at once, then one extraction over them."""
        rec = self.recorder
        futures = {}
        for target in self.targets:
            rec.emit(
                "task_start",
                pipeline=self.name,
                generation=self.generation,
                task="structure_prediction",
                targets=[target],
                detail={"pass": pass_index},
            )
            # No await: collect the futures first so the subprocesses overlap.
            futures[target] = self.structure_prediction(target, pass_index)

        scores = {}
        for target, future in futures.items():
            stdout = await future
            scores[target] = float(stdout.strip())
            rec.emit(
                "task_end",
                pipeline=self.name,
                generation=self.generation,
                task="structure_prediction",
                targets=[target],
                detail={"pass": pass_index, "score": scores[target]},
            )

        rec.emit(
            "task_start",
            pipeline=self.name,
            generation=self.generation,
            task="score_extraction",
            detail={"pass": pass_index},
        )
        mean = await self.score_extraction(scores)
        rec.emit(
            "task_end",
            pipeline=self.name,
            generation=self.generation,
            task="score_extraction",
            detail={"pass": pass_index, "mean": mean},
        )

        self.current_scores = scores

    def drop_targets(self, targets) -> None:
        """Hand these targets off to a child and stop working on them.

        Mirrors the real protein-binding example, which pops a migrated target
        out of the parent's own working set so the two pipelines do not both
        keep pushing on it.
        """
        gone = set(targets)
        self.targets = [t for t in self.targets if t not in gone]
        for t in gone:
            self.current_scores.pop(t, None)
            self.previous_scores.pop(t, None)


# --------------------------------------------------------------------------
# The adaptive decision
# --------------------------------------------------------------------------


async def adaptive_decision(pipeline: ToyPipeline) -> None:
    """Compare this pass against the last one and maybe spawn a child.

    The manager awaits this as an engine task and chooses nothing itself. It
    runs on a thread pool, so it may mutate the live pipeline object -- which
    is the whole reason the backend must be a thread pool and not a process
    pool, where it would mutate a pickled copy.

    Its return value is discarded, and an exception raised here is logged and
    swallowed. State is communicated by mutating `pipeline`.
    """
    rec = pipeline.recorder
    decision = decide(
        pipeline.current_scores,
        pipeline.previous_scores,
        pipeline.generation,
        pipeline.cfg,
    )
    rec.emit(
        "adaptive_eval",
        pipeline=pipeline.name,
        generation=pipeline.generation,
        targets=list(decision.degraded),
        detail={"reason": decision.reason, "spawn": decision.spawn},
    )
    if not decision.spawn:
        return

    migrated = list(decision.degraded)
    child = f"{pipeline.name}.g{pipeline.generation + 1}"
    pipeline.submit_child_pipeline_request(
        {
            # Required. The manager indexes config["name"] directly, so a
            # missing name is a KeyError inside its poll loop.
            "name": child,
            "type": type(pipeline),
            "config": {
                "cfg": pipeline.cfg,
                "targets": migrated,
                "generation": pipeline.generation + 1,
                "migrated": migrated,
                "previous_scores": {
                    t: pipeline.current_scores[t] for t in migrated
                },
                "pass_offset": pipeline.pass_index + 1,
                "recorder": rec,
                "parent_name": pipeline.name,
            },
            # The declared task, never the bare coroutine.
            "adaptive_fn": _ADAPTIVE_TASK,
        }
    )
    pipeline.drop_targets(migrated)
    rec.emit(
        "spawn",
        pipeline=pipeline.name,
        generation=pipeline.generation,
        targets=migrated,
        detail={"child": child, "reason": decision.reason},
    )


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def _manager_logger(quiet: bool) -> ImpressLogger:
    """The manager's own logger, turned down or turned off.

    `ImpressLogger` writes every level to stdout and offers no hook, so
    swapping the instance is the only way to control it -- which is what the
    framework's own tests do. The manager builds one in its constructor; this
    replaces it before `start()`.

    Quiet means a run during a sweep, where the framework's lifecycle lines
    would bury the result table under a hundred lines per configuration.
    Otherwise the lines are kept, because watching the manager submit a child
    pipeline is half the point of the notebook -- but at INFO, which drops the
    twice-a-second DEBUG poll summaries.
    """
    if quiet:
        return ImpressLogger(use_colors=False, output_stream=io.StringIO())
    return ImpressLogger(use_colors=False, min_level=LogLevel.INFO)


@dataclass
class RunResult:
    """One run's configuration and everything it recorded."""

    cfg: ToyConfig
    events: list
    work_dir: Path
    scores: list = field(default_factory=list)
    genealogy: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.scores:
            self.scores = scores_from_events(self.events)
        if not self.genealogy:
            self.genealogy = genealogy_from_events(self.events)

    @property
    def makespan(self) -> float:
        return max((e["t"] for e in self.events), default=0.0)

    @property
    def pipelines(self) -> list:
        seen = []
        for e in self.events:
            if e["kind"] == "pipeline_start" and e["pipeline"] not in seen:
                seen.append(e["pipeline"])
        return seen

    @property
    def spawns(self) -> int:
        return sum(1 for e in self.events if e["kind"] == "spawn")

    @property
    def max_generation(self) -> int:
        return max((e["generation"] for e in self.events), default=0)

    @property
    def decisions(self) -> list:
        """Every adaptive verdict, in order, as `(pipeline, reason)`.

        This is what a determinism check should compare: wall-clock times
        jitter between runs, the decisions do not.
        """
        return [
            (e["pipeline"], e["detail"]["reason"])
            for e in self.events
            if e["kind"] == "adaptive_eval"
        ]


def scores_from_events(events: list) -> list:
    """Flatten the per-target readings out of the event log."""
    rows = []
    for e in events:
        if e["kind"] != "task_end" or "score" not in e["detail"]:
            continue
        rows.append(
            {
                "pipeline": e["pipeline"],
                "generation": e["generation"],
                "target": e["targets"][0],
                "pass": e["detail"]["pass"],
                "score": e["detail"]["score"],
                "t": e["t"],
            }
        )
    return rows


def genealogy_from_events(events: list) -> list:
    """One row per spawn: who spawned whom, and which targets moved."""
    return [
        {
            "parent": e["pipeline"],
            "child": e["detail"]["child"],
            "generation": e["generation"] + 1,
            "migrated": list(e["targets"]),
            "t": e["t"],
        }
        for e in events
        if e["kind"] == "spawn"
    ]


async def run_toy(
    cfg: Optional[ToyConfig] = None,
    *,
    quiet: bool = False,
    work_dir: Optional[str] = None,
) -> RunResult:
    """One complete run. Returns everything the figures need.

    Call it with top-level `await` in a notebook cell. `asyncio.run` fails
    here: `WorkflowEngine` requires a running loop, and a notebook already has
    one.
    """
    global _ADAPTIVE_TASK

    cfg = cfg or ToyConfig()
    root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="impress-toy-"))
    root.mkdir(parents=True, exist_ok=True)
    rec = EventRecorder(quiet=quiet)
    rec.emit("run_start", detail={"seed": cfg.seed, "work_dir": str(root)})

    # An explicit work_dir keeps asyncflow's per-session directories out of the
    # notebook's working directory; without it they are created in the cwd.
    pool = ThreadPoolExecutor(max_workers=cfg.max_workers)
    backend = await LocalExecutionBackend(pool)
    flow = await WorkflowEngine.create(backend=backend, work_dir=str(root))
    manager = ImpressManager(flow, use_colors=False)
    manager.logger = _manager_logger(quiet)

    # telemetry_config stays None: `flow.start_telemetry` imports rhapsody
    # unguarded, and rhapsody is not one of this package's dependencies.
    _ADAPTIVE_TASK = flow.function_task(adaptive_decision)

    printer = None if quiet else asyncio.create_task(rec.stream())
    try:
        await manager.start(
            pipeline_setups=[
                PipelineSetup(
                    name="p1",
                    type=ToyPipeline,
                    config={
                        "cfg": cfg,
                        "targets": list(target_names(cfg.n_targets)),
                        "generation": 0,
                        "recorder": rec,
                    },
                    adaptive_fn=_ADAPTIVE_TASK,
                )
            ]
        )
    finally:
        if printer is not None:
            printer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await printer
        # The caller owns the engine: the manager never shuts it down.
        await flow.shutdown()

    rec.emit("run_end", detail={})
    rec.flush()
    return RunResult(cfg=cfg, events=rec.events, work_dir=root)


async def run_sweep(
    cfg: Optional[ToyConfig] = None,
    param: str = "degradation_threshold",
    values: tuple = (1.0, 2.0, 4.0, 6.0, 8.0),
    repeats: int = 1,
) -> list:
    """Vary one knob and report what it did to the run.

    Sequential by construction: each configuration gets its own engine, and the
    declared adaptive task is module-level.
    """
    cfg = cfg or ToyConfig()
    rows = []
    for value in values:
        for rep in range(repeats):
            one = replace(cfg, **{param: value, "seed": cfg.seed + rep})
            result = await run_toy(one, quiet=True)
            finals = {}
            for row in result.scores:
                key = row["target"]
                if key not in finals or row["pass"] > finals[key]["pass"]:
                    finals[key] = row
            mean_final = (
                sum(r["score"] for r in finals.values()) / len(finals)
                if finals
                else 0.0
            )
            rows.append(
                {
                    param: value,
                    "repeat": rep,
                    "seed": one.seed,
                    "pipelines": len(result.pipelines),
                    "spawns": result.spawns,
                    "max_generation": result.max_generation,
                    "makespan_s": round(result.makespan, 2),
                    "mean_final_score": round(mean_final, 2),
                }
            )
    return rows


def summary_table(result: RunResult) -> list:
    """A few rows a notebook can print next to the figures."""
    tasks = [e for e in result.events if e["kind"] == "task_end"]
    return [
        {"metric": "pipelines", "value": len(result.pipelines)},
        {"metric": "generations reached", "value": result.max_generation},
        {"metric": "children spawned", "value": result.spawns},
        {"metric": "tasks completed", "value": len(tasks)},
        {"metric": "adaptive evaluations", "value": len(result.decisions)},
        {"metric": "makespan (s)", "value": round(result.makespan, 2)},
    ]
