# 04 — rhapsody, radex, ORBIT

**Method note.** The agent assigned to this component was terminated by a session limit mid-exploration.
This report was written directly by the orchestrator from the same refcodes, at somewhat lower depth than
`01`–`03`. Every claim below is grounded in a quoted path; where depth is shallower than the sibling
reports, it says so.

Refcodes, READ-ONLY: `impress-a-refcodes/middleware/{rhapsody,radex,radical.orbit}/`

---

# Section 1 — rhapsody (v0.5.0)

## What it provides

The execution substrate. `BaseBackend(ABC)` (`src/rhapsody/backends/base.py:20`) is a deliberately tiny
contract — four abstract members:

```python
async def submit_tasks(self, tasks: list[dict]) -> None      # base.py:31-40
async def shutdown(self) -> None                             # base.py:43-49
def state(self) -> str                                       # base.py:52-59
def task_state_cb(self, task: dict, state: str) -> None      # base.py:62-70
```

Tasks are **plain dicts**, not typed objects. This matters: the contract carries no resource schema, so
resource portability is not something rhapsody can enforce (see §3).

## Available backends

`src/rhapsody/backends/execution/` contains `concurrent.py`, `dask_parallel.py`, `dragon.py`, `noop.py`,
`radical_pilot.py`, **`orbit.py`**. Exports are conditional on importability
(`backends/__init__.py:19-56`): `ConcurrentExecutionBackend` is unconditional; `DaskExecutionBackend`,
`RadicalExecutionBackend`, `DragonExecutionBackend` and `DragonVllmInferenceBackend` are appended to
`__all__` only if their optional dependencies resolve.

Both backends named in the project's platform decisions exist: **`DragonExecutionBackend`** (HPC) and
**`ConcurrentExecutionBackend`** (laptop/mock). Note the extras gate: `dragon = ["dragonhpc==0.14.1", ...]`
with a comment requiring **Python ≥ 3.11** — consistent with Part C's ≥3.12 agent environment.

Two findings worth carrying forward:

- **`OrbitExecutionBackend`** (`execution/orbit.py:44`) makes ORBIT a *execution backend*, not only a
  control-plane. It wraps `radical.orbit.EndpointRuntime` plus a `RhapsodyClient`, resolving a broker URL
  and token from `~/.radical/orbit/broker.url` and `~/.radical/orbit/broker.token`. This means work can be
  dispatched to a remote HPC endpoint through the broker.
- **`DragonVllmInferenceBackend`** (`backends/ai/vllm.py`) serves vLLM on Dragon behind an `aiohttp` web
  server, with `BatchingConfig`, `DynamicWorkerConfig`, `GuardrailsConfig` and `HardwareConfig`
  (`backends/ai/config.py`). This is directly relevant to Part A's `llm-oracle.md`: the on-prem serving
  option and control model B's degraded-mode fallback have first-class support in the substrate we are
  already adopting.

## Backend discovery — a usable plugin seam

`backends/discovery.py` provides `BackendRegistry` with `register_backend(name, class_or_path)`,
`get_backend_class(name)`, `list_backends()`, plus module-level `get_backend(name, *args, **kwargs)` and
`discover_backends()` returning a name→importable map.

**This is better than the direct-import pattern asyncflow's examples show.** Part C's `sites/*.yaml`
declares `backend.kind`; that string can go through `get_backend()` rather than through an `import` in our
code, which keeps the site config genuinely declarative. It does not remove rhapsody as a dependency, but
it removes rhapsody *names* from our source.

## M2 — resource shapes are NOT portable

The single most actionable finding in this section. The two HPC backends take **incompatible task
descriptions**, in the same release:

| Backend | Shape | Source |
|---|---|---|
| RADICAL-Pilot | `{"ranks": 1, "gpus_per_rank": 1}`; backend init `{"nodes": 1, "resource": "local.localhost"}` | `radical.asyncflow/examples/07-radical_execution_backend.py:26-31` |
| Dragon | `process_template` / `process_templates` objects | `rhapsody/backends/execution/dragon.py`; `radical.asyncflow/examples/06-dragon_execution_backend.py:44-62` |

Keys the Dragon backend actually reads: `args`, `arguments`, `capture_stdio`, `description`, `function`,
`is_native_function`, `kwargs`, `name`, `process_template(s)`, `task_backend_specific_kwargs`, `task_logs`,
`timeout`, `uid`.

There is no common resource vocabulary. **IMPRESS-A must own a resource-normalization layer** translating
`ToolSpec.resources` into per-backend descriptions. Part C already placed `resource_defaults` in
`sites/*.yaml`; this finding upgrades that from convenience to necessity. Note also the example uses
`DragonExecutionBackendV3` while `__init__.py` exports `DragonExecutionBackend` — version drift to pin
against.

## M7 — no external batch submission

A grep across `src/rhapsody/backends/` for `qsub|sbatch|external_job` returns **nothing**. Scheduler
awareness across all of `src/rhapsody` amounts to two files (`execution/radical_pilot.py`,
`backends/constants.py`) — scheduler handling is delegated to RADICAL-Pilot, not implemented by rhapsody.

**Every rhapsody backend assumes work runs inside the current allocation.** Our P4 pattern has no
expression here. See ORBIT §3 for where it does exist.

## State persistence

`persist`/`checkpoint`-adjacent code appears only in `telemetry/`, `api/session.py`, and
`execution/orbit.py`. There is **no durable task ledger**. This confirms `01`'s finding from the asyncflow
side: campaign durability and P4 job tracking are entirely ours to build.

---

# Section 2 — radex

## What it is

A data-exchange layer for moving **scalars and tensors** between workflow components **without a
filesystem**. C++ core (`src/`, `include/`, `CMakeLists.txt`) with a Cython Python client
(`src/python/setup.py`). Typed put/get via `OutgoingHandle` / `IncomingHandle`; types are `int32`,
`int64`, `float`, `double` scalars plus n-dimensional tensors. Backends: **Dragon DDict** and
**SmartRedis/Redis**.

Python usage, from `example/cpp-exchange/dragon/driver.py:12`:

```python
from radex.clients.core import DragonClient as Client
```

Examples cover `cpp-exchange` (dragon, in-mem), `py-cpp-exchange`, `active-learn/cpp-mpi-with-ddict`, and
**`rhapsody-exchange`** (redis, dragon) — so rhapsody interop is demonstrated even though neither rhapsody
nor asyncflow declares radex as a dependency.

## Fit for IMPRESS-A — mostly not

Our artifacts are PDB, mmCIF, FASTA, score files and trajectories: multi-kilobyte-to-multi-gigabyte
structured files. radex is built for numeric scalars and tensors. **It is not a replacement for our
shared-filesystem artifact plane**, and attempting to make it one would mean serializing structure files
into byte tensors, losing exactly the inspectability Part C's storage layout was designed for.

Two narrower roles are plausible but neither is needed now:

- **Cheap metric streaming.** Returning per-cycle scalar metrics from tasks to the outer loop without a
  file round-trip. Real, but our metric volume is small and the filesystem cost is negligible against
  minutes-to-hours tool runtimes.
- **Tight P1→P1 numeric hand-off**, e.g. embeddings between ML stages. Speculative.

The cost side is concrete: a C++ build with Cython bindings plus a Dragon or Redis backend, on every
target site. For a benefit we have not demonstrated needing.

**Verdict: out of scope for Phase 4.** Revisit only if profiling shows filesystem I/O is a material
fraction of campaign wall-clock — which, given Part A's cost table (tools run for minutes to hours), is
unlikely.

---

# Section 3 — radical.orbit

## What it is

A **star topology**: one broker hub plus many participants. Endpoints run on HPC login or compute nodes and
dial the broker over a single **outbound** WebSocket, which is firewall-friendly. A `gateway` module serves
an HTTP/SSE surface for non-participant callers. Control flows through the star; bulk data moves out of
band (Globus, shared filesystem, SSH tunnels).

## M6 — this is a credible answer to the control-plane placement question

Part B `08` left open where the control-plane adapter runs, given that compute nodes on leadership machines
are generally not externally reachable. ORBIT's topology inverts the problem: the endpoint **dials out**,
so nothing needs to accept inbound connections on a compute node.

The gateway (`src/radical/orbit/gateway.py`) is FastAPI-based with real SSE streaming — `StreamingResponse`,
a per-client `BoundedDropOldestQueue` with configurable depth (`sse_queue: int = 1024`, line 140), auth
middleware (`_auth_dispatch`, line 217), and topology push frames (line 302). That maps closely onto Part B
`06`'s required event stream, including the drop-oldest backpressure behaviour a long-running campaign
needs.

## M7 — external batch submission lives *here*, not in rhapsody

`plugin_psij.py` wraps **PSI/J** with a three-class endpoint/broker pattern exposing `submit_job`,
`get_job_status`, `list_jobs`, `cancel_job`, `submit_tunneled`, `tunnel_status`, with generated submit
scripts retained under `~/.psij/work/<scheduler>/` for inspection.

Independently, ORBIT ships its own batch-system abstraction — `BatchSystem(ABC)`
(`batch_system.py:84`) with `detect()`, `in_allocation()`, `job_id()`, `job_state()`, `job_nodes()`,
`nodelist()`, `cancel()`, `job_allocation()` — and **two concrete implementations**:
`batch_system_pbs.py` (`PBSProBatchSystem`, line 145; its docstring names Aurora's PBSPro explicitly and
parses both `qstat -f` text and `-F json`) and `batch_system_slurm.py`.

This is the direct answer to two Part A findings at once: **PBS Pro support exists**, and it exists in the
component that also provides external job submission. Part A observed that neither prior-art execution
layer spoke PBS Pro; ORBIT does.

## Plugin model

Eighteen plugins under `src/radical/orbit/plugin_*.py`, including `plugin_rhapsody.py` (the reciprocal of
rhapsody's `OrbitExecutionBackend`), `plugin_task_dispatcher.py`, `plugin_staging.py`,
`plugin_globus.py` (bulk data movement), `plugin_replay.py`, `plugin_queue_info.py`, `plugin_sysinfo.py`,
`plugin_sfapi_connect.py` (NERSC Superfacility API), and several `plugin_iri_*` (Integrated Research
Infrastructure). `plugin_base.py` / `plugin_host_base.py` define the extension contract.

Our `CampaignControlPlane` would plausibly be an ORBIT plugin served by an endpoint inside the job, with
the HTTP/SSE gateway and the Python client SDK as two of Part B's adapters.

## P8 — a plausible ingestion path

Part B `09` forward-declared P8 (robotic-lab measurement, days-to-weeks latency, out-of-band arrival) and
added `ingest_measurement` to the control plane. A broker that external systems dial into, with an
authenticated HTTP gateway, is a natural ingestion point — and `plugin_globus.py` covers the bulk-data leg.
Speculative but architecturally aligned; nothing was built or tested for this.

## Costs and unknowns

- **Someone must run the broker**, persistently, somewhere reachable by both the HPC endpoint and external
  callers. That is a real operational commitment, not a library dependency.
- Maturity was **not** assessed in depth here — `ROADMAP.md`, `plans/`, and test coverage went unread when
  the exploring agent was terminated. ORBIT is the component this report is least confident about, and its
  apparent fit is strong enough that the gap matters.
- ORBIT imports rhapsody (10 occurrences) while rhapsody declares an optional `orbit` extra: the coupling
  is bidirectional and optional in both directions, which is flexible but makes version compatibility a
  thing to pin deliberately.

---

# Closing synthesis

| Component | Status for IMPRESS-A | Attaches at which Part B seam |
|---|---|---|
| **rhapsody** | **Required** — the only source of real HPC backends. Reached by name through `get_backend()` from site config, not by direct import | `07` execution layer — backend construction |
| **rhapsody `DragonVllmInferenceBackend`** | **Useful** | `02` control model B degraded-mode / on-prem oracle serving |
| **radex** | **Out of scope** | none; revisit only on profiling evidence |
| **ORBIT** | **Useful, possibly required** — the only PBS Pro support, the only external-batch path (PSI/J), and a credible control-plane transport | `06` control plane (M6), `07` P4 dispatch (M7), `09` P8 ingestion |

The headline is that **ORBIT is more central than the naive pattern implies.** Two capabilities Part B
listed as unresolved or self-build — external batch submission with PBS Pro support, and a firewall-
traversing control plane — already exist there. That does not make adoption automatic: it adds a broker to
operate and a component whose maturity this report did not establish. But it changes ORBIT from "reference
material" to a candidate dependency that Phase 4 must evaluate deliberately.
