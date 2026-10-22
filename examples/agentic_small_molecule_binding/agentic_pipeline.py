"""An LLM drives the reference small-molecule binding toolkit directly.

`AgenticSMBPipeline` subclasses the reference `SmallMoleculeBindingPipeline`
and overrides exactly one thing: `run()`. Everything else -- which tools exist,
what command each one runs, how many threads it gets, which GPU it is pinned
to, which steps stay local -- is inherited unchanged, so the agentic example
and the reference place identical demands on the allocation.

What changes is who decides. The reference walks a fixed state machine and asks
`adaptive_decision()` for the next step. Here there is no state machine: the
model is given the toolkit and calls it.

The LLM call itself goes through the pipeline's `adaptive_fn`, which the runner
registers on the `local` thread-pool backend. That seam already exists for
exactly this reason -- synchronous work that must see the live pipeline object
and must not block the event loop every pipeline shares.
"""

from __future__ import annotations

import json
import os
import sys
import time

_REF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "small_molecule_binding")
if _REF_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_REF_DIR))

import prompts  # noqa: E402
from llm import ScriptedClient  # noqa: E402
from small_molecule_binding import SmallMoleculeBindingPipeline  # noqa: E402
from tools import HANDLERS, TOOL_SCHEMAS  # noqa: E402

# Older tool results are folded into one summary past this many turns, so the
# transcript cannot grow without bound on a long run. The system prompt and the
# opening message are never touched, which keeps the cacheable prefix stable.
_HISTORY_KEEP_TURNS = 40
_HISTORY_KEEP_RESULTS = 24


class AgenticSMBPipeline(SmallMoleculeBindingPipeline):
    """The reference toolkit, driven by a model instead of a state machine."""

    def __init__(self, **kwargs):
        # Read before super().__init__(), which calls register_pipeline_tasks().
        self.max_llm_turns = kwargs.pop("max_llm_turns", 200)
        self.transcript_dir = kwargs.pop("transcript_dir", None)
        self.llm_client = kwargs.pop("llm_client", None)
        super().__init__(**kwargs)

        self.messages: list[dict] = []
        self.llm_turns = 0
        self.llm_prompt_tokens = 0
        self.llm_completion_tokens = 0
        self.llm_degraded = False
        self._transcript_path = None
        self._summarised_through = 0

    # ── Transcript ─────────────────────────────────────────────────────────

    def _transcript(self, record: dict) -> None:
        """Append one record. Every run is replayable and comparable from this."""
        if self._transcript_path is None:
            base = self.transcript_dir or os.path.join(self.base_path, self.name)
            os.makedirs(base, exist_ok=True)
            self._transcript_path = os.path.join(base, "llm_transcript.jsonl")
        record["t"] = time.time()
        record["pipeline"] = self.name
        try:
            with open(self._transcript_path, "a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            # A full or over-quota filesystem must not take the run down --
            # job 22726386 died that way on the project's inode limit.
            self.logger.pipeline_log(f"[llm] transcript write failed: {exc!r}")

    # ── One model turn, executed on the `local` backend ────────────────────

    def llm_turn(self) -> list:
        """Ask the model what to do next. Called by the runner's adaptive_fn.

        Returns the tool calls it asked for, and leaves the assistant message
        appended to self.messages. Synchronous by design: it runs on a thread,
        not the event loop.
        """
        self._compact_history()
        try:
            completion = self.llm_client.complete(self.messages, TOOL_SCHEMAS)
        except Exception as exc:  # noqa: BLE001 - includes LLMError
            # Degrade rather than abandon the allocation: finish the run on the
            # reference route and say so loudly, so the result is never mistaken
            # for the model's own work.
            self.logger.pipeline_log(
                f"[llm] endpoint failed ({exc!r}); falling back to the scripted "
                "route for the rest of this pipeline")
            self._transcript({"event": "degraded", "error": repr(exc)})
            self.llm_degraded = True
            self.llm_client = ScriptedClient()
            completion = self.llm_client.complete(self.messages, TOOL_SCHEMAS)

        self.llm_turns += 1
        self.llm_prompt_tokens += completion.prompt_tokens
        self.llm_completion_tokens += completion.completion_tokens
        self.messages.append(completion.raw_message)
        self._transcript({
            "event": "assistant",
            "turn": self.llm_turns,
            "text": completion.text,
            "tool_calls": [{"name": c.name, "arguments": c.arguments}
                           for c in completion.tool_calls],
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
            "degraded": self.llm_degraded,
        })
        return completion.tool_calls

    def _compact_history(self) -> None:
        """Fold old tool results into one summary message.

        Keeps the system prompt and the opening message untouched so the
        cacheable prefix stays byte-stable, and keeps the most recent results
        verbatim, since those are what the next decision turns on.
        """
        if self.llm_turns < _HISTORY_KEEP_TURNS:
            return
        tool_idx = [i for i, m in enumerate(self.messages) if m.get("role") == "tool"]
        if len(tool_idx) <= _HISTORY_KEEP_RESULTS:
            return
        # Back the cut up to the assistant message that issued that tool call.
        # A `tool` message with no preceding assistant tool_calls to match is a
        # 400 on an OpenAI-compatible endpoint, so the tail must never begin
        # with one.
        cut = tool_idx[-_HISTORY_KEEP_RESULTS]
        while cut > 2 and self.messages[cut].get("role") != "assistant":
            cut -= 1
        if cut <= 2:
            return

        stages: dict[str, dict[str, int]] = {}
        for msg in self.messages[:cut]:
            if msg.get("role") != "tool":
                continue
            try:
                payload = json.loads(msg.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            tally = stages.setdefault(payload.get("stage", "?"),
                                      {"runs": 0, "passed": 0})
            tally["runs"] += 1
            tally["passed"] += int(bool(payload.get("pass")))

        summary = {
            "stage": "history",
            "note": "Earlier turns, summarised. Full detail is in the transcript.",
            "by_stage": stages,
            "ensemble_used": len(self.state.get("ensemble", [])),
        }
        # Keep messages[0:2] (system + opening), replace the middle, keep the
        # tail. The tail must start at a message the endpoint will accept after
        # a user message, so the summary is sent as a user turn.
        self.messages = (
            self.messages[:2]
            + [{"role": "user", "content": json.dumps(summary)}]
            + self.messages[cut:]
        )
        self._summarised_through += 1

    # ── The loop ───────────────────────────────────────────────────────────

    async def run(self):
        # Same state keys the reference run() seeds, so every inherited task and
        # analysis step finds what it expects.
        self.state.setdefault('ensemble', [])
        self.state.setdefault('rfd3_input_pdb', None)
        self.state.setdefault('seq_retry_count', 0)
        self.state.setdefault('last_seq_fasta', None)
        self.state.setdefault('fastrelax_prev_metrics', None)
        self.state.setdefault('interface_prev_metrics', None)
        self.state.setdefault('backbone_guided_fail_count', 0)

        if self.start_delay:
            import asyncio
            self.logger.pipeline_log(
                f"start delayed {self.start_delay}s (staggered start)")
            await asyncio.sleep(self.start_delay)

        self.messages = [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.opening_message(self)},
        ]
        model_name = getattr(self.llm_client, "name", "?")
        self._transcript({"event": "start", "model": model_name,
                          "max_llm_turns": self.max_llm_turns,
                          "max_tasks": self.max_tasks})
        self.logger.pipeline_log(
            f"AgenticSMBPipeline starting (model={model_name}, "
            f"max_llm_turns={self.max_llm_turns}, max_tasks={self.max_tasks})")

        empty_turns = 0
        done = False

        while not done:
            if self.llm_turns >= self.max_llm_turns:
                self.logger.pipeline_log(
                    f"Turn budget exhausted ({self.max_llm_turns}). Stopping.")
                break
            if len(self.state['ensemble']) >= self.max_tasks:
                self.logger.pipeline_log(
                    f"Task budget exhausted ({self.max_tasks} ensemble entries). "
                    "Stopping.")
                break

            # The manager runs _adaptive_fn, which calls llm_turn() on the
            # `local` backend and leaves the calls here.
            self.state['_llm_tool_calls'] = []
            await self.run_adaptive_step()
            tool_calls = self.state.get('_llm_tool_calls') or []

            if not tool_calls:
                empty_turns += 1
                if empty_turns >= 2:
                    self.logger.pipeline_log(
                        "Model returned no tool call twice in a row. Stopping.")
                    break
                self.messages.append({
                    "role": "user",
                    "content": "No tool was called. Call a tool to continue, "
                               "or call finish if the campaign should stop.",
                })
                continue
            empty_turns = 0

            for call in tool_calls:
                result = await self._dispatch(call)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                })
                self._transcript({"event": "tool_result", "tool": call.name,
                                  "result": result})
                if call.name == "finish" and result.get("ok"):
                    self.logger.pipeline_log(
                        f"Model called finish: {result.get('reason')!r}")
                    done = True
                    break

        self._transcript({
            "event": "end",
            "turns": self.llm_turns,
            "ensemble": len(self.state.get('ensemble', [])),
            "prompt_tokens": self.llm_prompt_tokens,
            "completion_tokens": self.llm_completion_tokens,
            "degraded": self.llm_degraded,
        })
        self.logger.pipeline_log(
            f"Pipeline complete ({self.llm_turns} turns, "
            f"{len(self.state.get('ensemble', []))} ensemble entries, "
            f"{self.llm_prompt_tokens}+{self.llm_completion_tokens} tokens"
            + (", DEGRADED to scripted route" if self.llm_degraded else "") + ")")

    async def _dispatch(self, call) -> dict:
        """Run one tool call. Never raises for anything the model controls."""
        handler = HANDLERS.get(call.name)
        if handler is None:
            return {"stage": "?", "ok": False,
                    "error": f"no such tool: {call.name!r}. "
                             f"Available: {sorted(HANDLERS)}"}
        if "__parse_error__" in call.arguments:
            return {"stage": "?", "ok": False,
                    "error": "arguments were not valid JSON; send them again"}
        try:
            return await handler(self, **call.arguments)
        except TypeError as exc:
            return {"stage": "?", "ok": False,
                    "error": f"bad arguments for {call.name}: {exc}"}
        except Exception as exc:  # noqa: BLE001 - a tool failing is campaign data
            # A failed stage is survivable: the reference kills the pipeline on
            # one (BACKLOG 15), which at this scale wastes a GPU for the rest of
            # the job. Report it and let the model decide what to do.
            self.logger.pipeline_log(f"[tool] {call.name} failed: {exc!r}")
            return {"stage": "?", "ok": False,
                    "error": f"{call.name} failed: {exc}"}
