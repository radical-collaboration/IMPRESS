# rhapsody: DragonVllmInferenceBackend's chat endpoint ignores sampling parameters and fakes token counts

**Component:** rhapsody-py 0.7.0 (`src/rhapsody/backends/ai/vllm.py`, checked at `aca8e3e`) ·
**Severity:** silent wrong behaviour for any OpenAI-compatible client · **Status:** diagnosed
from source, not reported upstream; not yet exercised on hardware
**Evidence:** source reading, 2026-11-11, while planning IMPRESS-A's local-reasoner route
(`agent/plans/backlog.md` I4).

## What we saw

`POST /v1/chat/completions` on the backend's HTTP service accepts the OpenAI request shape and
answers in OpenAI's response shape, but:

- **`max_tokens` and `temperature` are read and discarded** (`vllm.py:531-532`, under
  `# FIXME pass to self.generate()`). A client asking for 4096 tokens at temperature 0 gets the
  server's defaults.
- **Messages are flattened without the model's chat template** (`:537-549`): they become
  `"System: ...\n\nUser: ...\n\nAssistant:"`. An instruction-tuned model sees a format it was
  not trained on.
- **`response_format` is not supported**, so structured (JSON-schema) output is unavailable.
- **`usage` is word counts, not tokens** (`:592-597`: `len(prompt.split())`). A client
  accounting for tokens records numbers that look real and are not.

## Fix

Pass `max_tokens`/`temperature` (and `top_p`, `stop`) through `generate()` into the Inference
request. Apply the tokenizer's chat template (`tokenizer.apply_chat_template`) instead of the
string join. Take `usage` from vLLM's own token counts. Reject `response_format` with a 400 until
it is supported, rather than ignoring it.

## Impact on us

IMPRESS-A plans to run a locally hosted reasoner (a provenance-compliant open model) as engine
`prompt_task`s on this backend. Until these are fixed, the reasoner must use its text-JSON
fallback (`agent/src/impress_a/policy/llm.py: _json_object`), and any token accounting from this
backend must be marked as estimated.
