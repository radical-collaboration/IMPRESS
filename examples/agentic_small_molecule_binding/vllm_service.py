"""Host the LLM inside the allocation: a vLLM server as a Dragon task.

The server is reached through the same OpenAI-compatible client as a hosted
model, so nothing in the agent loop changes -- only where the endpoint points.
That is the whole reason this route serves vLLM's own OpenAI server rather than
rhapsody's `DragonVllmInferenceBackend`: that backend's chat endpoint flattens
the message list into one string and has no tool-calling path at all
(`rhapsody/src/rhapsody/backends/ai/vllm.py:519-549`), and this example is built
entirely on native tool calls.

Dragon is still reached through rhapsody and the server is still an asyncflow
task on the `DragonExecutionBackend`; only the serving layer differs.

**Why the server detaches instead of being a service task.** asyncflow has a
`service=True` flag, but only the RADICAL-Pilot backend reads it, and even there
the "service is ready" callback is dead code (`radical_pilot.py:425-430`).
`DragonExecutionBackend` ignores it, so a task's future resolves only when its
process exits. A server held as a normal task would therefore never resolve and
could not hand back its address. Instead the launch task starts the server in
the background, prints `host:port`, and exits -- so its stdout carries the
endpoint, which is how asyncflow passes values between tasks at all.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def node_hostnames() -> list[str]:
    """Hostnames of the allocation's nodes, in Dragon's own order.

    Dragon's order is what `Policy(host_name=...)` is matched against, so the
    split between the model's node and the pipelines' node has to be made from
    this list rather than from Slurm's.
    """
    from dragon.native.machine import Node, System

    return [Node(h).hostname for h in System().nodes]


def serve_command(venv: str, model: str, host: str, port: int, log_file: str,
                  tp_size: int = 1, gpu_fraction: float = 0.90,
                  tool_parser: str = "hermes", extra_args: str = "") -> str:
    """Shell command that starts the server detached and prints its address.

    `--enable-auto-tool-choice` with a parser matching the model family is what
    makes the server emit real `tool_calls`; without it the model's tool syntax
    comes back as ordinary text and the agent sees no calls at all. `hermes` is
    the parser for the Qwen2.5 instruct family.
    """
    cmd = (
        f"{venv}/bin/vllm serve {model}"
        f" --host {host} --port {port}"
        f" --tensor-parallel-size {tp_size}"
        f" --gpu-memory-utilization {gpu_fraction}"
        " --enable-auto-tool-choice"
        f" --tool-call-parser {tool_parser}"
        f" {extra_args}"
    ).strip()
    # setsid so the server outlives the launching task's process group, and
    # </dev/null so it never blocks on stdin. The echo is the task's result:
    # an executable task's future resolves to its stdout, which is the only
    # channel asyncflow gives us for handing the address to the runner.
    return (
        f"bash -c 'mkdir -p $(dirname {log_file}); "
        f"setsid nohup {cmd} > {log_file} 2>&1 < /dev/null & "
        f"echo {host}:{port}'"
    )


def stop_command(port: int) -> str:
    """Shell command that stops the server. Harmless if it is already gone."""
    return (
        "bash -c 'pkill -f \"vllm serve.*--port "
        f"{port}\" || true; echo stopped'"
    )


def wait_healthy(endpoint: str, timeout_s: float = 1800.0,
                 interval_s: float = 10.0, log=print) -> str:
    """Block until the server answers, and return the model id it serves.

    A 7B model takes minutes to load, and every pipeline's first turn would
    fail against a server that is still loading -- which the client's retry
    path would convert into a degraded, scripted run. So the workflow does not
    start until this returns.
    """
    url = endpoint.rstrip("/") + "/v1/models"
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)
            models = [m.get("id") for m in data.get("data", [])]
            if models:
                waited = int(time.time() - deadline + timeout_s)
                log(f"[vllm] ready after {waited}s: {models}")
                return models[0]
            last = "no models listed"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = repr(exc)
        time.sleep(interval_s)
    raise TimeoutError(
        f"vLLM at {endpoint} not ready after {timeout_s:.0f}s (last: {last})"
    )


def model_node_policy(host: str, gpus: list[int]):
    """Dragon placement for the server: a named node, and that node's GPUs.

    `DragonExecutionBackend` takes `num_nodes` but no node offset
    (`rhapsody/.../execution/dragon.py:68-86`), so the only way to keep the
    model and the pipelines off each other is to name the host explicitly on
    both sides.
    """
    from dragon.infrastructure.policy import Policy

    return Policy(placement=Policy.Placement.HOST_NAME, host_name=host,
                  gpu_affinity=list(gpus))


def service_task_description(host: str, gpus: list[int]) -> dict:
    """`task_description` that pins the launch task to the model's node."""
    return {"process_template": {
        "policy": model_node_policy(host, gpus),
        "env": {k: v for k, v in os.environ.items()
                if k.startswith(("HF_", "HUGGING_FACE_", "VLLM_"))},
    }}
