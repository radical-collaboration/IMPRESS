"""Offline test for the agentic example: no GPU, no network, no API key.

Covers the four things that can be checked without an allocation:

  1. Task descriptors are byte-identical to the reference pipeline's. This is
     what "equivalent task allocation" actually means, so it is asserted rather
     than described.
  2. The scripted client drives the same stage sequence as the reference
     non-adaptive runner, over mock tools on a local backend.
  3. A bad tool call returns an error payload instead of raising.
  4. Both budgets -- turns and ensemble entries -- terminate the loop.

Run it with the reference example's venv:

    PYTHONPATH=../../src python test_agentic_smb.py
"""

import asyncio
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
_REF_DIR = os.path.abspath(os.path.join(_HERE, os.pardir, "small_molecule_binding"))
for _p in (_HERE, _REF_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The reference pipeline requires these even in mock mode (it validates them in
# __init__, before it ever looks at self.mock).
os.environ.setdefault("MPNN_DIR", "/nonexistent/mpnn")
os.environ.setdefault("FOUNDRY_SIF_PATH", "/nonexistent/foundry.sif")
os.environ.setdefault("BOLTZ_CACHE", "/nonexistent/boltz")

from agentic_pipeline import AgenticSMBPipeline  # noqa: E402
from llm import Completion, ScriptedClient, ToolCall  # noqa: E402
from radical.asyncflow import LocalExecutionBackend, WorkflowEngine  # noqa: E402
from small_molecule_binding import SmallMoleculeBindingPipeline  # noqa: E402
from tools import TOOL_NAMES  # noqa: E402

from impress import ImpressManager, PipelineSetup  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail=None) -> None:
    # Detail only on failure, and truncated: the concurrent-backend task
    # descriptors carry a merged copy of os.environ.
    suffix = ""
    if not ok and detail is not None:
        suffix = f" -- {str(detail)[:200]}"
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{suffix}")
    if not ok:
        FAILURES.append(name)


# ── 1. Task descriptors ────────────────────────────────────────────────────

class _DragonishBackend:
    """Anything that is not a ConcurrentExecutionBackend takes the Dragon path."""


class _RecordingFlow:
    """Captures each task's task_description default, and runs nothing."""

    def __init__(self, backend):
        self.backend = backend
        self.descriptors: dict[str, dict] = {}

    def executable_task(self, **kwargs):
        import inspect

        def decorator(func):
            param = inspect.signature(func).parameters.get("task_description")
            self.descriptors[func.__name__] = (
                param.default if param and param.default is not param.empty else {}
            )

            async def noop(*a, **kw):
                return None
            noop.__name__ = func.__name__
            return noop
        return decorator

    def function_task(self, **kwargs):
        def decorator(func):
            return func
        return decorator


_STAGES = ("rfd3", "mpnn", "packmin", "fastrelax", "filter_shape", "boltz")


def _descriptors(cls, backend, **extra) -> dict[str, dict]:
    flow = _RecordingFlow(backend)
    cls(name="d1", flow=flow, base_path="/tmp/none",
        scripts_path="/tmp/none", input_dir="/tmp/none", gpu_index=2, **extra)
    return {s: d for s, d in flow.descriptors.items() if s in _STAGES}


def _concurrent_backend():
    """A ConcurrentExecutionBackend instance without running its async setup."""
    from rhapsody.backends import ConcurrentExecutionBackend
    return object.__new__(ConcurrentExecutionBackend)


def test_descriptors() -> None:
    print("\n[1] task descriptors match the reference")
    for label, backend in (("concurrent", _concurrent_backend()),
                           ("dragon", _DragonishBackend())):
        ref = _descriptors(SmallMoleculeBindingPipeline, backend)
        agentic = _descriptors(AgenticSMBPipeline, backend)
        check(f"[{label}] same stages registered",
              sorted(ref) == sorted(agentic), f"{sorted(ref)} vs {sorted(agentic)}")
        for stage in sorted(ref):
            check(f"[{label}] {stage} descriptor identical",
                  ref[stage] == agentic[stage],
                  f"{ref.get(stage)} vs {agentic.get(stage)}")

    # And that the descriptors still have the reference's documented shape, so a
    # refactor that quietly drops the thread caps or the GPU pin is caught here
    # rather than on the allocation. Read off the concurrent branch, where the
    # values are plain env vars.
    ref = _descriptors(SmallMoleculeBindingPipeline, _concurrent_backend())
    for stage, threads in (("rfd3", "8"), ("boltz", "8"), ("mpnn", "4"),
                           ("packmin", "1"), ("fastrelax", "1"),
                           ("filter_shape", "1")):
        env = (ref.get(stage) or {}).get("env", {})
        check(f"{stage} capped at {threads} thread(s)",
              env.get("OMP_NUM_THREADS") == threads, env.get("OMP_NUM_THREADS"))
    for stage in ("rfd3", "mpnn", "boltz"):
        env = (ref.get(stage) or {}).get("env", {})
        check(f"{stage} pinned to its GPU",
              env.get("CUDA_VISIBLE_DEVICES") == "2",
              env.get("CUDA_VISIBLE_DEVICES"))
    for stage in ("packmin", "fastrelax", "filter_shape"):
        env = (ref.get(stage) or {}).get("env", {})
        check(f"{stage} takes no GPU", "CUDA_VISIBLE_DEVICES" not in env)


def test_pin_host() -> None:
    print("\n[8] pin_host adds host placement and changes nothing else")
    # Unset: the agentic descriptors must stay byte-identical to the
    # reference's. This is the invariant every comparison rests on, so it is
    # checked again here with the option present but off.
    ref = _descriptors(SmallMoleculeBindingPipeline, _DragonishBackend())
    off = _descriptors(AgenticSMBPipeline, _DragonishBackend(), pin_host=None)
    for stage in sorted(ref):
        check(f"pin_host unset: {stage} unchanged", ref[stage] == off[stage],
              f"{ref.get(stage)} vs {off.get(stage)}")

    try:
        from dragon.infrastructure.policy import Policy  # noqa: F401
    except Exception as exc:
        check("dragon policy importable", False, repr(exc))
        return
    on = _descriptors(AgenticSMBPipeline, _DragonishBackend(),
                      pin_host="gpub999")
    for stage in sorted(ref):
        rt = (ref[stage] or {}).get("process_template", {})
        ot = (on[stage] or {}).get("process_template", {})
        check(f"pin_host set: {stage} env unchanged",
              rt.get("env") == ot.get("env"),
              f"{rt.get('env')} vs {ot.get('env')}")
        pol = ot.get("policy")
        check(f"pin_host set: {stage} placed on the named host",
              getattr(pol, "host_name", None) == "gpub999",
              getattr(pol, "host_name", None))
        # The GPU pin is the reference's, carried over untouched -- losing it
        # would silently hand every tool every GPU on the node.
        ref_gpu = list(getattr(rt.get("policy"), "gpu_affinity", []) or [])
        own_gpu = list(getattr(pol, "gpu_affinity", []) or [])
        check(f"pin_host set: {stage} keeps the reference GPU affinity",
              ref_gpu == own_gpu, f"{ref_gpu} vs {own_gpu}")


# ── 2-4. The loop, over mock tools ─────────────────────────────────────────

def _setup_mock_inputs(base: str, name: str) -> str:
    in_dir = os.path.join(base, f"{name}_in")
    os.makedirs(in_dir, exist_ok=True)
    for fname, body in (("ALR_binder_design.json", "{}"),
                        ("ALR.params", "NAME A:R\n"),
                        ("ALR.smiles", "CC\n")):
        with open(os.path.join(in_dir, fname), "w") as fh:
            fh.write(body)
    return in_dir


async def _run_pipeline(client, *, max_llm_turns=60, max_tasks=12, name="p1"):
    base = tempfile.mkdtemp(prefix="agentic-smb-")
    in_dir = _setup_mock_inputs(base, name)

    backend = await LocalExecutionBackend(ThreadPoolExecutor())
    flow = await WorkflowEngine.create(backend=backend)
    manager = ImpressManager(flow)

    # The manager drops finished pipelines from pipeline_tasks, so hold on to
    # the object here instead of looking it up afterwards.
    holder: list = []

    async def adaptive_fn(pipeline):
        if not holder:
            holder.append(pipeline)
        pipeline.state['_llm_tool_calls'] = pipeline.llm_turn()

    # The manager rejects a plain coroutine: the callback has to arrive as an
    # engine task so it runs on a thread pool rather than the event loop. The
    # engine's only backend here is already a thread pool, so no name is
    # needed; the runner names `local` because its default backend is `compute`.
    adaptive_task = flow.function_task(adaptive_fn)

    setup = PipelineSetup(
        name=name,
        type=AgenticSMBPipeline,
        adaptive_fn=adaptive_task,
        kwargs={
            "base_path": base,
            "scripts_path": os.path.join(_REF_DIR, "scripts"),
            "input_dir": in_dir,
            "mock": True,
            "max_tasks": max_tasks,
            "max_llm_turns": max_llm_turns,
            "llm_client": client,
            "num_refine_cycles": 2,
            "mpnn_ensemble_size": 2,
        },
    )
    try:
        await manager.start(pipeline_setups=[setup])
    finally:
        await flow.shutdown()

    return holder[0], base


def _stages(pipeline) -> list[str]:
    out = []
    for msg in pipeline.messages:
        if msg.get("role") != "tool":
            continue
        try:
            out.append(json.loads(msg["content"]).get("stage"))
        except json.JSONDecodeError:
            pass
    return out


def test_scripted_route() -> None:
    print("\n[2] scripted client reproduces the reference route")
    pipeline, base = asyncio.run(_run_pipeline(ScriptedClient(), max_tasks=9))
    stages = _stages(pipeline)
    expected_cycle = ["backbone", "sequence", "packmin", "fastrelax",
                      "interface", "fold"]
    check("first cycle matches run_nonadaptive's route",
          stages[:6] == expected_cycle, f"{stages[:6]}")
    check("every result is well-formed JSON", len(stages) == len(
        [s for s in stages if s]), str(stages))
    check("ensemble budget terminated the run",
          len(pipeline.state["ensemble"]) >= 9,
          f"{len(pipeline.state['ensemble'])} entries")
    transcript = os.path.join(base, pipeline.name, "llm_transcript.jsonl")
    check("transcript written", os.path.isfile(transcript))
    if os.path.isfile(transcript):
        with open(transcript) as fh:
            events = [json.loads(line)["event"] for line in fh]
        check("transcript has start and end",
              events[0] == "start" and events[-1] == "end", str(events[:2]))


class _BadCallClient:
    """Asks for things the model might plausibly get wrong, then finishes."""

    name = "bad-calls"

    def __init__(self):
        self._script = [
            ("no_such_tool", {}),                      # unknown tool
            ("relax", {}),                             # out of order
            ("design_sequence", {"source": "sideways"}),  # bad enum
            ("inspect_ensemble", {"kind": "nonsense"}),   # bad argument
            ("design_backbone", {"guide_model": "/no/such/file.pdb"}),
            ("finish", {"reason": "done probing"}),
        ]
        self._i = 0

    def complete(self, messages, tools):
        name, args = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        call = ToolCall(id=f"bad-{self._i}", name=name, arguments=args)
        return Completion(
            text="", tool_calls=[call],
            raw_message={"role": "assistant", "content": "",
                         "tool_calls": [{"id": call.id, "type": "function",
                                         "function": {"name": name,
                                                      "arguments": json.dumps(args)}}]},
        )


def test_bad_calls() -> None:
    print("\n[3] bad tool calls return errors, not exceptions")
    pipeline, _ = asyncio.run(_run_pipeline(_BadCallClient(), max_tasks=50))
    results = []
    for msg in pipeline.messages:
        if msg.get("role") == "tool":
            results.append(json.loads(msg["content"]))
    check("ran to completion without raising", len(results) >= 6, str(len(results)))
    check("unknown tool reported", results[0].get("ok") is False
          and "no such tool" in results[0].get("error", ""), str(results[0]))
    check("out-of-order relax refused", results[1].get("ok") is False, str(results[1]))
    check("bad enum refused", results[2].get("ok") is False, str(results[2]))
    check("bad inspect kind refused", results[3].get("ok") is False, str(results[3]))
    check("missing guide file refused", results[4].get("ok") is False, str(results[4]))
    check("finish accepted", results[5].get("ok") is True, str(results[5]))
    check("nothing ran after finish", len(results) == 6, str(len(results)))


class _NeverFinishesClient(ScriptedClient):
    name = "never-finishes"


def test_turn_budget() -> None:
    print("\n[4] the turn budget stops a model that never finishes")
    pipeline, _ = asyncio.run(_run_pipeline(
        _NeverFinishesClient(), max_llm_turns=4, max_tasks=10_000))
    check("stopped at the turn budget", pipeline.llm_turns == 4,
          f"{pipeline.llm_turns} turns")
    check("ensemble below its own budget",
          len(pipeline.state["ensemble"]) < 10_000)


class _SilentClient:
    name = "silent"

    def complete(self, messages, tools):
        return Completion(text="I am thinking.", tool_calls=[],
                          raw_message={"role": "assistant",
                                       "content": "I am thinking."})


def test_no_tool_calls() -> None:
    print("\n[5] a model that calls nothing is nudged once, then stopped")
    pipeline, _ = asyncio.run(_run_pipeline(_SilentClient(), max_llm_turns=20))
    check("stopped after the nudge", pipeline.llm_turns == 2,
          f"{pipeline.llm_turns} turns")


def test_compaction() -> None:
    print("\n[7] history compaction keeps the transcript valid")
    import agentic_pipeline as ap

    # Built directly rather than run: compaction is pure message surgery, and a
    # real run long enough to cross the thresholds costs a minute of polling.
    pipeline = AgenticSMBPipeline(
        name="c1", flow=_RecordingFlow(_concurrent_backend()),
        base_path="/tmp/none", scripts_path="/tmp/none", input_dir="/tmp/none")
    pipeline.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "open"},
    ]
    for i in range(60):
        call_id = f"c{i}"
        pipeline.messages.append({
            "role": "assistant", "content": "",
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": "relax", "arguments": "{}"}}],
        })
        pipeline.messages.append({
            "role": "tool", "tool_call_id": call_id,
            "content": json.dumps({"stage": "fastrelax", "ok": True,
                                   "pass": i % 2 == 0}),
        })
    pipeline.llm_turns = 60
    before = len(pipeline.messages)
    pipeline._compact_history()

    check("compaction ran", pipeline._summarised_through == 1,
          pipeline._summarised_through)
    check("conversation got shorter", len(pipeline.messages) < before,
          f"{before} -> {len(pipeline.messages)}")
    check("kept the most recent results",
          len([m for m in pipeline.messages if m.get("role") == "tool"])
          == ap._HISTORY_KEEP_RESULTS,
          len([m for m in pipeline.messages if m.get("role") == "tool"]))

    msgs = pipeline.messages
    check("system prompt untouched", msgs[0]["role"] == "system")
    check("opening message untouched", msgs[1]["role"] == "user")
    check("summary inserted as a user turn", msgs[2]["role"] == "user"
          and json.loads(msgs[2]["content"])["stage"] == "history",
          msgs[2])
    check("summary counts the dropped results",
          json.loads(msgs[2]["content"])["by_stage"]["fastrelax"]["runs"]
          == 60 - ap._HISTORY_KEEP_RESULTS,
          json.loads(msgs[2]["content"])["by_stage"])
    check("tail resumes at an assistant turn", msgs[3]["role"] == "assistant",
          msgs[3].get("role"))

    # Every tool result must answer a tool_call from the assistant message
    # before it; an orphan is a 400 on an OpenAI-compatible endpoint, and
    # naive slicing produces one.
    orphans, unanswered = [], []
    open_ids: set = set()
    for msg in msgs:
        if msg.get("role") == "assistant":
            unanswered.extend(open_ids)
            open_ids = {tc["id"] for tc in (msg.get("tool_calls") or [])}
        elif msg.get("role") == "tool":
            if msg.get("tool_call_id") in open_ids:
                open_ids.discard(msg["tool_call_id"])
            else:
                orphans.append(msg.get("tool_call_id"))
    unanswered.extend(open_ids)
    check("no orphaned tool results", not orphans, orphans[:5])
    check("no unanswered tool calls", not unanswered, unanswered[:5])

    # Idempotent below the threshold: a second pass must not keep trimming.
    pipeline._compact_history()
    check("no further compaction while under the threshold",
          pipeline._summarised_through == 1, pipeline._summarised_through)


def test_schemas() -> None:
    print("\n[6] schemas and handlers agree")
    from tools import HANDLERS
    check("every schema has a handler", sorted(TOOL_NAMES) == sorted(HANDLERS),
          f"{sorted(TOOL_NAMES)} vs {sorted(HANDLERS)}")


if __name__ == "__main__":
    test_schemas()
    test_descriptors()
    test_scripted_route()
    test_bad_calls()
    test_turn_budget()
    test_no_tool_calls()
    test_compaction()
    test_pin_host()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        sys.exit(1)
    print("all checks passed")
