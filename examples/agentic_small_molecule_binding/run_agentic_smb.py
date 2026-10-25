"""Entry point for the agentic small-molecule binding example.

The execution setup is the reference runner's, deliberately unchanged: one
WorkflowEngine over two named rhapsody backends (`compute` = Dragon, `local` =
a thread pool), telemetry on, one GPU per pipeline round-robin, staggered
starts, run config over argv, and a runner_status file for the launcher.

The one substantive difference is what `adaptive_fn` does. In the reference it
is `adaptive_decision()`, which picks the next state-machine step. Here it is
one turn of the model, which picks the next tool call. Both run on the `local`
thread-pool backend for the same reason: the body is synchronous and blocking
it on the event loop would stall every pipeline at once (job 22534628).
"""

import argparse
import asyncio
import os
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace

from radical.asyncflow import WorkflowEngine

from impress import ImpressManager, PipelineSetup

_HERE = os.path.dirname(os.path.abspath(__file__))
_REF_DIR = os.path.abspath(os.path.join(_HERE, os.pardir, "small_molecule_binding"))
for _p in (_HERE, _REF_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import logging  # noqa: E402

import rhapsody  # noqa: E402
import vllm_service  # noqa: E402
from agentic_pipeline import AgenticSMBPipeline  # noqa: E402
from llm import build_client, load_profiles  # noqa: E402

# PROD is the reference campaign's thresholds and budgets. Importing it rather
# than restating it is what keeps the two examples comparable: if the reference
# config moves, this moves with it.
from run_small_molecule_binding import PROD, _on_task_event  # noqa: E402

rhapsody.enable_logging(level=logging.INFO)


BACKEND = os.environ.get("IMPRESS_BACKEND", "dragon").lower()
START_STAGGER_S = 60

# argv, not environment: `dragon -w ssh` forwards only BASE_ENV_VARNAMES, so
# anything the launcher exports is silently dropped on a multi-node run. See
# the long note in run_small_molecule_binding.py.
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument("--n-pipelines", type=int, default=None)
_ap.add_argument("--work-dir", default=None)
_ap.add_argument("--model-profile", default=None)
_ap.add_argument("--max-llm-turns", type=int, default=None)
_args, _ = _ap.parse_known_args()

cfg = PROD
_n_pipelines = _args.n_pipelines or os.getenv("IMPRESS_N_PIPELINES")
if _n_pipelines:
    cfg = replace(cfg, n_pipelines=int(_n_pipelines))

MODEL_PROFILE = (_args.model_profile
                 or os.getenv("IMPRESS_MODEL_PROFILE")
                 or "scripted")
MAX_LLM_TURNS = int(_args.max_llm_turns
                    or os.getenv("IMPRESS_MAX_LLM_TURNS")
                    or 200)


def _node_gpus() -> list[int]:
    """GPU device IDs on a compute node (see the reference runner)."""
    if BACKEND == "dragon":
        from dragon.native.machine import Node, System
        return list(Node(System().nodes[0]).gpus or [])
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is not None:
        return [int(d) for d in visible.split(",") if d.strip().isdigit()]
    try:
        import torch
        return list(range(torch.cuda.device_count()))
    except Exception:
        return []


def _n_nodes() -> int:
    if BACKEND == "dragon":
        from dragon.native.machine import System
        return System().nnodes
    return 1


async def llm_turn(pipeline: AgenticSMBPipeline) -> None:
    """One model turn, as the pipeline's adaptive step.

    Registered as flow.function_task(backend="local"), so the blocking HTTP
    call runs on the thread pool rather than the shared event loop. Safe off
    the loop for the same reason adaptive_decision is: ImpressManager awaits
    this pipeline's adaptive task before the pipeline advances, so nothing else
    writes this pipeline's state meanwhile. It must stay a THREAD pool -- a
    process pool would mutate a pickled copy and the tool calls would be lost.
    """
    pipeline.state['_llm_tool_calls'] = pipeline.llm_turn()


async def _vllm_launch(venv: str, model: str, host: str, port: int,
                       log_file: str, tp_size: int, gpu_fraction: float,
                       tool_parser: str, extra_args: str,
                       task_description: dict = {}):  # noqa: B006
    """Executable task: start the server detached, print its address."""
    return vllm_service.serve_command(
        venv=venv, model=model, host=host, port=port, log_file=log_file,
        tp_size=tp_size, gpu_fraction=gpu_fraction, tool_parser=tool_parser,
        extra_args=extra_args)


async def _vllm_stop(port: int, task_description: dict = {}):  # noqa: B006
    """Executable task: stop the server on the node it was placed on."""
    return vllm_service.stop_command(port)


async def impress_agentic_smb() -> None:
    work_dir = _args.work_dir or os.environ.get(
        "IMPRESS_WORK_DIR", os.path.join(_HERE, "logs"))
    os.makedirs(work_dir, exist_ok=True)

    profiles = load_profiles(os.path.join(_HERE, "models.yaml"))
    if MODEL_PROFILE not in profiles:
        raise SystemExit(
            f"unknown --model-profile {MODEL_PROFILE!r}; "
            f"models.yaml defines {sorted(profiles)}")
    profile = profiles[MODEL_PROFILE]
    print(f"[LLM] profile={profile.name} model={profile.model} "
          f"base_url={profile.base_url} max_llm_turns={MAX_LLM_TURNS}", flush=True)

    if BACKEND == "dragon":
        from rhapsody.backends import DragonExecutionBackend
        compute = await DragonExecutionBackend(name="compute")
    else:
        from rhapsody.backends import ConcurrentExecutionBackend
        compute = await ConcurrentExecutionBackend(
            ProcessPoolExecutor(), name="compute")
    from rhapsody.backends import ConcurrentExecutionBackend
    local = await ConcurrentExecutionBackend(
        ThreadPoolExecutor(max_workers=cfg.n_pipelines), name="local")

    flow = await WorkflowEngine.create(backend=[compute, local])
    manager: ImpressManager = ImpressManager(
        flow,
        telemetry_config={
            "checkpoint_path": os.path.join(work_dir, "telemetry"),
            "resource_poll_interval": 15.0,
            "checkpoint_interval": 300.0,
        },
        telemetry_subscribers=[_on_task_event],
    )

    adaptive_fn = flow.function_task(backend="local")(llm_turn)

    # ── Optionally host the model inside this allocation ──────────────────
    # The server is an asyncflow task on the Dragon backend like any other, so
    # Dragon is still reached through rhapsody. It has to detach and exit
    # rather than run as a service task, because asyncflow's service support
    # is inert on this backend -- see vllm_service for the detail.
    pin_host = None
    stop_server = None
    if profile.kind == "dragon_vllm":
        hosts = vllm_service.node_hostnames()
        if len(hosts) < 2:
            raise SystemExit(
                f"profile {profile.name!r} hosts the model in-allocation and "
                f"needs >= 2 nodes so the model and the pipelines do not share "
                f"GPUs; this allocation has {len(hosts)}. "
                f"Submit with --nodes=2.")
        srv = dict(profile.serve or {})
        model_host = hosts[int(srv.get("node_index", -1))]
        pin_host = hosts[0] if model_host != hosts[0] else hosts[-1]
        port = int(srv.get("port", 8000))
        n_gpus = int(srv.get("gpus", 4))
        log_file = os.path.join(work_dir, "vllm_server.log")
        print(f"[LLM] serving {profile.model} on {model_host} "
              f"(gpus 0-{n_gpus - 1}); pipelines pinned to {pin_host}",
              flush=True)

        launch = flow.executable_task(capture_stdio=True)(_vllm_launch)
        out = await launch(
            venv=srv.get("venv", os.environ.get("VLLM_VENV", "")),
            model=profile.model, host=model_host, port=port,
            log_file=log_file, tp_size=int(srv.get("tp_size", 1)),
            gpu_fraction=float(srv.get("gpu_fraction", 0.90)),
            tool_parser=srv.get("tool_parser", "hermes"),
            extra_args=srv.get("extra_args", ""),
            task_description=vllm_service.service_task_description(
                model_host, list(range(n_gpus))),
            workflow_id="vllm:launch")
        addr = (out or "").strip().splitlines()
        endpoint = "http://" + (addr[-1] if addr else f"{model_host}:{port}")
        print(f"[LLM] launch task returned {endpoint}; waiting for it to load",
              flush=True)
        served = vllm_service.wait_healthy(
            endpoint, timeout_s=float(srv.get("ready_timeout_s", 1800)),
            log=lambda m: print(m, flush=True))
        # vLLM names the model by the id it was given; use what the server
        # reports so a mismatch cannot turn every request into a 404.
        profile.base_url = endpoint + "/v1"
        profile.model = served
        stop_server = (flow.executable_task(capture_stdio=True)(_vllm_stop),
                       port, model_host, n_gpus)

    gpus = _node_gpus()

    def _gpu_for(i: int):
        return gpus[(i - 1) % len(gpus)] if gpus else None

    slots = max(1, len(gpus) * _n_nodes())

    def _delay_for(i: int) -> int:
        return ((i - 1) // slots) * START_STAGGER_S

    print(f"[GPU] devices per node: {gpus or 'none'}; pipeline -> GPU: "
          + ", ".join(f"p{i}:{_gpu_for(i)}" for i in range(1, cfg.n_pipelines + 1)),
          flush=True)

    pipeline_setups: list[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=AgenticSMBPipeline,
            adaptive_fn=adaptive_fn,
            kwargs={
                "base_path":                 work_dir,
                "scripts_path":              os.path.join(_REF_DIR, "scripts"),
                "input_dir":                 os.path.join(_REF_DIR, f"p{i}_in"),
                "backbone_max_ca_deviation": cfg.backbone_max_ca_deviation,
                "backbone_min_ss_fraction":  cfg.backbone_min_ss_fraction,
                "fastrelax_max_fa_rep":      cfg.fastrelax_max_fa_rep,
                "fastrelax_max_total_score": cfg.fastrelax_max_score,
                "fastrelax_max_interact":    cfg.fastrelax_max_interact,
                "interface_min_sc":          cfg.interface_min_sc,
                "fold_min_plddt":            cfg.fold_min_plddt,
                "fold_min_ligand_iptm":      cfg.fold_min_ligand_iptm,
                "diffusion_batch_size":      cfg.diffusion_batch_size,
                "num_refine_cycles":         cfg.num_refine_cycles,
                "mpnn_ensemble_size":        cfg.mpnn_ensemble_size,
                "rfd3_partial_t":            cfg.rfd3_partial_t,
                "max_tasks":                 cfg.max_tasks,
                "gpu_index":                 _gpu_for(i),
                "start_delay":               _delay_for(i),
                # Agentic additions. One client per pipeline: each is its own
                # conversation, and they must not share mutable state.
                "max_llm_turns":             MAX_LLM_TURNS,
                "llm_client":                build_client(profile),
                "pin_host":                  pin_host,
            },
        )
        for i in range(1, cfg.n_pipelines + 1)
    ]

    try:
        await manager.start(pipeline_setups=pipeline_setups)
    finally:
        if stop_server is not None:
            stop_fn, port, model_host, n_gpus = stop_server
            try:
                # Before flow.shutdown(): it tears every backend down
                # concurrently and reaps nothing, so a server left running
                # would hold the node until Slurm kills the job.
                await stop_fn(
                    port=port,
                    task_description=vllm_service.service_task_description(
                        model_host, list(range(n_gpus))),
                    workflow_id="vllm:stop")
                print("[LLM] vLLM server stopped", flush=True)
            except Exception as exc:
                print(f"[LLM] could not stop the vLLM server: {exc!r}")
        if manager.telemetry:
            try:
                await manager.telemetry.stop()
            except Exception as exc:
                print(f"[TELEMETRY] stop() failed: {exc!r}")
        await flow.shutdown()


def _write_runner_status(status: str) -> None:
    work_dir = _args.work_dir or os.environ.get("IMPRESS_WORK_DIR")
    if not work_dir:
        return
    try:
        with open(os.path.join(work_dir, "runner_status"), "w") as fh:
            fh.write(status + "\n")
    except OSError as exc:
        print(f"[RUNNER] could not write runner_status: {exc!r}")


if __name__ == "__main__":
    try:
        asyncio.run(impress_agentic_smb())
    except BaseException as exc:
        _write_runner_status(f"failed: {exc!r}"[:500])
        raise
    _write_runner_status("ok")
