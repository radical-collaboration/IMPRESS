"""LLM clients for the agentic small-molecule binding example.

Every model is reached through an OpenAI-compatible /chat/completions endpoint
so that different providers can be compared run for run without touching the
pipeline. A profile in models.yaml names the base_url, the model id and the
environment variable holding the key; nothing else in the example knows which
model is in play.

Two clients implement the same `complete()` contract:

  OpenAICompatClient -- the real thing.
  ScriptedClient     -- an offline stand-in that replays a fixed route table
                        as tool calls, so the loop can be tested with no
                        network and no key.

complete() is synchronous on purpose. It is called from the pipeline's
adaptive_fn, which runs on the `local` thread-pool backend precisely so that a
blocking call cannot stall the event loop shared by every pipeline (see
examples/small_molecule_binding/plans/2026-09-30-adaptive-callback-serialization.md).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import yaml


class LLMError(RuntimeError):
    """Transport or protocol failure talking to the endpoint."""


@dataclass
class ToolCall:
    """One tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Completion:
    """One assistant turn: free text, tool calls, and what it cost."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_message: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    """What the agent loop needs from a model."""

    name: str

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        ...


# ── Profiles ───────────────────────────────────────────────────────────────

@dataclass
class ModelProfile:
    name: str
    kind: str = "openai_compat"      # or "scripted"
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    max_tokens: int = 4096
    request_timeout_s: float = 300.0
    max_retries: int = 4
    extra_body: dict[str, Any] = field(default_factory=dict)
    # kind == "dragon_vllm": the model is served inside the allocation and
    # base_url is discovered at run time, not configured here. The client is
    # still OpenAICompatClient -- vLLM's own server speaks the same protocol,
    # tool calls included, which is the whole point of serving it this way.
    serve: dict[str, Any] = field(default_factory=dict)


def load_profiles(path: str) -> dict[str, ModelProfile]:
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    profiles = {}
    for name, cfg in (raw.get("profiles") or {}).items():
        profiles[name] = ModelProfile(name=name, **(cfg or {}))
    return profiles


def build_client(profile: ModelProfile) -> LLMClient:
    if profile.kind == "scripted":
        return ScriptedClient()
    if profile.kind == "dragon_vllm" and not profile.base_url:
        raise LLMError(
            f"profile {profile.name!r} is served inside the allocation; its "
            "base_url is set by the runner once the server is healthy. "
            "Building a client before then is a bug."
        )
    return OpenAICompatClient(profile)


# ── Real client ────────────────────────────────────────────────────────────

class OpenAICompatClient:
    """Chat-completions client with tool calling, for any compatible endpoint.

    Note on Claude: Anthropic's OpenAI-compatibility endpoint accepts this
    request shape, but it does not expose Claude-specific controls (adaptive
    thinking, effort, server-side fallbacks). That is the price of one request
    shape across every model under comparison, which is the point of this
    example. Use `extra_body` in the profile for anything an endpoint adds.
    """

    def __init__(self, profile: ModelProfile):
        self.profile = profile
        self.name = profile.name

        # Key first, so a missing key is not reported as a missing package.
        api_key = None
        if profile.api_key_env:
            api_key = os.environ.get(profile.api_key_env)
            if not api_key:
                raise LLMError(
                    f"profile {profile.name!r} needs {profile.api_key_env} in the "
                    "environment. On Delta, export it from the launcher -- it must "
                    "also survive the `dragon -w ssh` hop, so put it in ~/.bashrc "
                    "for multi-node runs."
                )

        try:
            from openai import OpenAI  # imported lazily: optional extra
        except ImportError as exc:
            raise LLMError(
                "the openai package is required for a live endpoint: "
                "pip install 'impress[agentic]' (the 'scripted' profile needs "
                "nothing)"
            ) from exc

        self._client = OpenAI(
            base_url=profile.base_url,
            api_key=api_key or "unused",
            timeout=profile.request_timeout_s,
            max_retries=0,                 # retried here, with logging
        )

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        last_exc: Exception | None = None
        for attempt in range(self.profile.max_retries):
            try:
                resp = self._client.chat.completions.create(
                    model=self.profile.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=self.profile.max_tokens,
                    **self.profile.extra_body,
                )
                return _completion_from_response(resp)
            except Exception as exc:       # noqa: BLE001 - any transport fault
                last_exc = exc
                time.sleep(min(2.0 ** attempt, 30.0))
        raise LLMError(f"{self.profile.model}: {last_exc!r}") from last_exc


def _completion_from_response(resp) -> Completion:
    choice = resp.choices[0]
    msg = choice.message
    calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            # Malformed arguments are the model's problem to fix; surface them
            # as an empty call so the handler returns a usable error instead of
            # taking the pipeline down.
            args = {"__parse_error__": tc.function.arguments}
        calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    raw: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    # Carry the model's own reasoning back into the assistant message.
    #
    # A reasoning model may REQUIRE this on the next request. Reflection's Beam
    # rejects any follow-up whose earlier assistant messages lack it:
    #   400 missing_required_parameter: Missing required parameter:
    #   'messages[2].reasoning_content'. This model needs the reasoning of every
    #   earlier assistant message.
    # Turn one succeeds and turn two does not, so a single-turn check of the
    # endpoint passes and the run still degrades to the scripted route on its
    # second decision (job 23219379, all four pipelines, 144 degraded turns).
    # Providers that do not return the field simply do not get it back.
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning is None:
        extra = getattr(msg, "model_extra", None) or {}
        reasoning = extra.get("reasoning_content")
    if reasoning is not None:
        raw["reasoning_content"] = reasoning
    if msg.tool_calls:
        raw["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]

    usage = getattr(resp, "usage", None)
    return Completion(
        text=msg.content or "",
        tool_calls=calls,
        raw_message=raw,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


# ── Offline stand-in ───────────────────────────────────────────────────────

# The reference non-adaptive route table (run_nonadaptive.py), expressed as the
# tool the agent would call next given the stage that just finished. Starting
# from nothing, the first call is design_backbone.
_SCRIPTED_ROUTE = {
    None:        ("design_backbone", {"guide_model": None}),
    "backbone":  ("design_sequence", {"source": "backbone"}),
    "sequence":  ("pack_minimize",   {}),
    "packmin":   ("relax",           {}),
    "fastrelax": ("score_interface", {}),
    "interface": ("fold_complex",    {}),
    "fold":      ("design_backbone", {"guide_model": None}),
}


class ScriptedClient:
    """Replays the reference non-adaptive route as tool calls.

    Used by the offline test and as the degraded mode when the endpoint is
    unreachable mid-run: a model outage should cost the run its agency, not the
    rest of the allocation.
    """

    name = "scripted"

    def __init__(self, route: dict | None = None):
        self.route = route or _SCRIPTED_ROUTE
        self._n = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        self._n += 1
        stage = _last_stage(messages)
        tool, args = self.route.get(stage, ("finish", {"reason": "unknown stage"}))
        call = ToolCall(id=f"scripted-{self._n}", name=tool, arguments=args)
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


def _last_stage(messages: list[dict]) -> str | None:
    """The `stage` field of the most recent tool result, if any."""
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        try:
            return json.loads(msg.get("content") or "{}").get("stage")
        except json.JSONDecodeError:
            return None
    return None
