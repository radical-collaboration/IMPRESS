"""The live model client for control model B, and the profiles that name a model.

Backlog H2: `OraclePolicy` defaults to `RehearsalOracle` and nothing passes a model, so
`--model B` runs the deterministic stand-in. `LangChainOracle` was built nowhere, brace-sliced
JSON out of the reply despite a docstring claiming structured output, and had none of what Part
B doc 02 sections 3 and 7 require: a pinned dated model id, sampling parameters, `Retry-After`
backoff, 429-vs-529. The `oracle = ["litellm"]` extra was imported by nothing.

This is ported from `examples/agentic_small_molecule_binding/llm.py`, which has four hardware
runs behind it, rather than written fresh - and what that example measured is carried as
comments in `models.yaml` instead of being re-derived. Two deliberate differences:

**Async, not synchronous.** The sibling's `complete()` is sync because it is called from a
pipeline's `adaptive_fn` on a thread-pool backend, where a blocking call cannot stall the loop
every pipeline shares (job 22534628: 67% of wall clock, p99 56 s). Here the halves run in the
control process's own loop, which is what phase 7 bought, so the right answer is an async
client and no thread at all.

**No tool calling.** Model B makes one structured decision per signal and the campaign executes
it; the model never calls a tool. So there are no tool schemas to render, no tool-call parser to
match, and the reply is one JSON object.

**Two retry layers, and they are not the same thing.** Transport failures - a 429, a 503, a
timeout - are retried here with exponential backoff, because the request was never answered.
A reply that arrives and does not satisfy the schema is retried by `policy/reasoning.ask`, with
the rejection appended to the prompt, because the model needs telling what was wrong. Collapsing
them would either retry a bad answer without correcting it or re-send a corrected prompt to an
endpoint that is simply down.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

#: Where `impress-a run --model-profile` looks when given no path. Repository-relative, like
#: `campaigns/` and `sites/`.
DEFAULT_PROFILES = "models.yaml"

#: Status codes worth another attempt. 429 is rate limiting, 5xx is the endpoint's problem;
#: a 400 or a 401 will fail identically however many times it is sent, and retrying one wastes
#: a decision's worth of wall clock while an allocation is held.
RETRYABLE = (408, 409, 425, 429, 500, 502, 503, 504, 529)


class LLMError(RuntimeError):
    """Transport or protocol failure talking to the endpoint."""


@dataclass
class ModelProfile:
    """One model under comparison, named in `models.yaml`."""

    name: str
    kind: str = "openai_compat"       # openai_compat | rehearsal
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    max_tokens: int = 4096
    #: Sampling is pinned, not defaulted: a comparison between two models cannot hold
    #: temperature constant if neither request states it, and an endpoint's default is free to
    #: change between runs. 0.0 because a decision is not a creative writing task - what
    #: variation the campaign wants comes from the draw, not from the decider.
    temperature: float = 0.0
    request_timeout_s: float = 300.0
    max_retries: int = 4
    extra_body: dict[str, Any] = field(default_factory=dict)

    @property
    def is_live(self) -> bool:
        return self.kind == "openai_compat"


def load_profiles(path: str | Path = DEFAULT_PROFILES) -> dict[str, ModelProfile]:
    """Every profile in a `models.yaml`, by name."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return {name: ModelProfile(name=name, **(cfg or {}))
            for name, cfg in (raw.get("profiles") or {}).items()}


def build_oracle(profile: ModelProfile, stages: list[str] | None = None) -> Any:
    """The `NodeReasoner` a profile names.

    `rehearsal` is the network-free stand-in and takes the campaign's chain, because a
    rehearsal that answers with a chain the campaign did not declare is backlog H2's dangerous
    half: a real campaign would validate the real toolkits and then execute mocks, reported as
    a model-B result.
    """
    if profile.kind == "rehearsal":
        from .oracle import RehearsalOracle
        return RehearsalOracle(stages=stages)
    if profile.kind != "openai_compat":
        raise LLMError(f"profile {profile.name!r} has unknown kind {profile.kind!r}; "
                       f"expected 'openai_compat' or 'rehearsal'")
    return OpenAICompatOracle(profile)


class OpenAICompatOracle:
    """One structured decision per call, from any OpenAI-compatible endpoint.

    Implements `policy/reasoning.NodeReasoner`, so the same bounded corrective retry serves
    this and model A's nodes. The pinned dated model id, the prompt and the raw reply all reach
    provenance through `reasoning.ask`'s sink, which is what makes a live arm replayable - and
    what the four-arm experiment reads for decision-layer timing.
    """

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile
        #: The PINNED dated id, not the profile's nickname. `claude-sonnet` names a profile;
        #: `claude-sonnet-5-5` names what answered, and that is what a figure has to carry.
        self.model_id = profile.model or profile.name
        self.prompt_tokens = 0
        self.completion_tokens = 0
        #: Earlier turns of the current node's exchange. A reasoning model may REQUIRE its own
        #: `reasoning_content` back on a follow-up - Beam refuses a request whose earlier
        #: assistant messages lack it - so the corrective retry has to be a real conversation
        #: rather than a fresh single-turn request. That is the one multi-turn path here, and
        #: a single-turn probe of the endpoint cannot show it working.
        self._history: list[dict[str, Any]] = []

        api_key = None
        if profile.api_key_env:
            # Key first, so a missing key is not reported as a missing package.
            api_key = os.environ.get(profile.api_key_env)
            if not api_key:
                raise LLMError(
                    f"profile {profile.name!r} needs {profile.api_key_env} in the "
                    f"environment. On Delta export it from the launcher - it must also "
                    f"survive the `dragon -w ssh` hop, so put it in ~/.bashrc for a "
                    f"multi-node run")
        try:
            from openai import AsyncOpenAI  # lazily: an optional extra
        except ImportError as missing:
            raise LLMError(
                "the openai package is required for a live endpoint: install the 'oracle' "
                "extra (`pip install -e '.[oracle]'`). The 'rehearsal' profile needs nothing"
            ) from missing

        self._client = AsyncOpenAI(
            base_url=profile.base_url, api_key=api_key or "unused",
            timeout=profile.request_timeout_s,
            max_retries=0)      # retried below, with backoff and a log line

    def reset(self) -> None:
        """Forget the current node's exchange. Called between decisions, not between retries."""
        self._history = []

    async def think(self, node: str, prompt: str,
                    schema: dict[str, str]) -> dict[str, Any]:
        """One decision, as a JSON object. Raises `LLMError` when the endpoint will not answer.

        The schema is sent as prose in the request *and* as `response_format` where the
        endpoint supports it. Prose because this is the form every compatible endpoint
        understands; `response_format` because an endpoint that enforces it removes a whole
        class of corrective retry. An endpoint that rejects the parameter is retried once
        without it rather than failing the decision - which is what "OpenAI-compatible" means
        in practice, since the compatibility surface is not uniform.
        """
        messages = self._history + [{"role": "user", "content": self._render(prompt, schema)}]
        # Transport first, then parsing - and they are deliberately not in the same try.
        # A reply that arrives and is unusable must reach `reasoning.ask`, which appends the
        # rejection to the prompt and asks again; retried here it would be re-requested
        # uncorrected. A declined request must not be retried at all: the model will decline
        # four more times, and the four attempts cost a decision's worth of wall clock while
        # an allocation is held.
        resp = await self._request(messages, structured=True)
        reply = self._message_from_response(resp)
        self._history = messages + [reply["message"]]
        log.info("oracle: %s answered node %s (%d prompt, %d completion tokens)",
                 self.model_id, node, reply["prompt_tokens"], reply["completion_tokens"])
        return reply["payload"]

    @staticmethod
    def _render(prompt: str, schema: dict[str, str]) -> str:
        return (f"{prompt}\n\nReply with ONE JSON object and nothing else, matching this "
                f"schema:\n{json.dumps(schema, indent=2)}")

    async def _request(self, messages: list[dict[str, Any]], structured: bool) -> Any:
        """The raw response. Retries transport faults only; parsing is the caller's."""
        last: Exception | None = None
        for attempt in range(max(1, self.profile.max_retries)):
            kwargs: dict[str, Any] = dict(
                model=self.profile.model, messages=messages,
                max_tokens=self.profile.max_tokens,
                temperature=self.profile.temperature,
                **self.profile.extra_body)
            if structured:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                return await self._client.chat.completions.create(**kwargs)
            except Exception as failure:          # noqa: BLE001 - any transport fault
                last = failure
                if structured and _is_bad_request(failure):
                    # The endpoint does not accept `response_format`. Drop it and say so
                    # once, rather than retrying an identical rejected request four times.
                    log.info("oracle: %s rejected response_format; retrying as prose",
                             self.model_id)
                    structured = False
                    continue
                if not _is_retryable(failure):
                    raise LLMError(f"{self.model_id}: {failure!r}") from failure
                delay = _backoff(failure, attempt)
                log.warning("oracle: %s attempt %d failed (%s); retrying in %.1fs",
                            self.model_id, attempt, failure, delay)
                await asyncio.sleep(delay)
        raise LLMError(f"{self.model_id}: {last!r}") from last

    def _message_from_response(self, resp: Any) -> dict[str, Any]:
        """The parsed payload, the assistant message to carry forward, and the token counts."""
        choice = resp.choices[0]
        msg = choice.message
        finish = getattr(choice, "finish_reason", None)
        text = msg.content or ""

        message: dict[str, Any] = {"role": "assistant", "content": text}
        # Carry the model's own reasoning back. A reasoning model may REQUIRE it on the next
        # request: Beam refuses any follow-up whose earlier assistant messages lack
        # `reasoning_content` with `400 missing_required_parameter`. Turn one succeeds and turn
        # two does not, so a single-turn probe passes while every corrective retry fails - once
        # reported as 144 degraded turns that looked like a healthy run. Providers that do not
        # return the field simply do not get it back.
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning is None:
            reasoning = (getattr(msg, "model_extra", None) or {}).get("reasoning_content")
        if reasoning is not None:
            message["reasoning_content"] = reasoning

        usage = getattr(resp, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

        if finish == "content_filter":
            # Measured on `claude-opus-5-5` through this endpoint in the sibling example:
            # every request came back filtered with 0 completion tokens, with the system
            # prompt and without it. Named rather than reported as "no JSON object", because
            # the remedy is a different model and not a reworded prompt.
            raise LLMError(
                f"{self.model_id} declined the request (finish_reason=content_filter, "
                f"{completion_tokens} completion tokens). This is the model refusing the "
                f"workload, not a prompt bug - see models.yaml")
        if finish == "length":
            raise LLMError(
                f"{self.model_id} hit max_tokens ({self.profile.max_tokens}) before "
                f"finishing its answer. For a reasoning model this usually means the "
                f"reasoning spent the budget: raise max_tokens in the profile")

        return {"payload": _json_object(text, self.model_id), "message": message,
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


def _json_object(text: str, model_id: str) -> dict[str, Any]:
    """The reply as a dict. Parsed, never brace-sliced.

    `LangChainOracle` took `text[text.find("{"):text.rfind("}") + 1]`, which silently accepts a
    prose answer that happens to contain two braces and produces a decision from whatever was
    between them. A reply that is not an object is a schema failure, and `reasoning.ask` is
    what tells the model so.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # A fenced block is the one deviation worth absorbing: it is this common, and the
        # content inside it is the model's actual answer rather than a guess at one.
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{model_id} did not return JSON: {bad}") from bad
    if not isinstance(payload, dict):
        raise ValueError(f"{model_id} returned a {type(payload).__name__}, not a JSON object")
    return payload


def _status_of(failure: Exception) -> int | None:
    return getattr(failure, "status_code", None) or getattr(
        getattr(failure, "response", None), "status_code", None)


def _is_retryable(failure: Exception) -> bool:
    """A transport fault worth another attempt, as opposed to a request that is simply wrong."""
    status = _status_of(failure)
    if status is None:
        return True          # a timeout or a connection reset carries no status
    return int(status) in RETRYABLE


def _is_bad_request(failure: Exception) -> bool:
    return _status_of(failure) == 400


def _backoff(failure: Exception, attempt: int) -> float:
    """Exponential, unless the endpoint said when to come back.

    `Retry-After` is honoured because ignoring it is how a rate-limited client stays rate
    limited: four exponential retries into a 60-second window all fail, and the decision is
    lost for no reason.
    """
    headers = getattr(getattr(failure, "response", None), "headers", None) or {}
    after = headers.get("retry-after") or headers.get("Retry-After")
    if after:
        try:
            return min(float(after), 120.0)
        except (TypeError, ValueError):
            pass
    return min(2.0 ** attempt, 30.0)


__all__ = ["DEFAULT_PROFILES", "RETRYABLE", "LLMError", "ModelProfile",
           "OpenAICompatOracle", "build_oracle", "load_profiles"]
