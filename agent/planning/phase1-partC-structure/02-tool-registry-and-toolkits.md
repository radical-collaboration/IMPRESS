# 02 — Tool Registry and Toolkits

Answers Part B's C2 (where `ToolSpec`s live) and C3 (how skill docs stay in step with them).

## 1. Shape: declarative spec, code only where behaviour is needed

Each tool is a directory. The spec is data; the agent is code; they version together because they sit
together.

```
toolkits/generation/
├── toolkit.yaml            # id, members, enabled-by-default, shared resource hints
├── SKILL.md                # agent-facing skill document for the whole toolkit
└── tools/
    ├── rfdiffusion3/
    │   ├── spec.yaml       # the ToolSpec  (declarative)
    │   ├── agent.py        # task agent    (code)
    │   ├── templates/      # optional: config/protocol templates
    │   └── tests/
    │       ├── test_parameterize.py
    │       └── fixtures/   # recorded real outputs, for QC-gate tests
    └── rfdiffusion3na/
```

**Why declarative rather than pure code.** A `ToolSpec` is read by four consumers — composer, validator,
budget guard, task agent — and edited mainly by scientists. As YAML it is reviewable in a pull request by
someone who does not read Python, diffable when a parameter range changes, and machine-readable without
importing a module that might pull in a heavy dependency. Part A's briefs are already effectively the prose
form of these specs; `spec.yaml` is that content made executable.

**Why not pure declarative.** Pre-processing, output parsing, and QC gates are behaviour. Expressing
"parse the score file, extract ipTM, check it against the ensemble" in YAML would reinvent a programming
language badly.

## 2. `spec.yaml` — worked example

Every field traces to a Part A finding. Annotated here; in the repo it is plain YAML.

```yaml
id: rfdiffusion3
version: "2026.09"                  # spec version, distinct from tool version
tool_version: {source: foundry, resolve: runtime}   # recorded at execution, not trusted from config

inputs:
  scaffold:  {type: Backbone, required: false}
  hotspots:  {type: ResidueSet, required: false}
outputs:
  designs:   {type: list[Backbone]}

pattern: P1
resources: {gpus: 1, cores: 8, walltime_estimate: "PT10M"}
gpu_portability:                     # Part A T6 — machine-readable, checked at compose time
  cuda: proven
  sycl_xpu: proven
  hip: unproven                      # blocks composition on Frontier unless overridden
state_model: stateless

parameters:
  num_designs:      {type: int,   range: [1, 1000], default: 100, trades: "coverage vs. GPU-hours"}
  diffusion_steps:  {type: int,   range: [20, 200], default: 50,  trades: "quality vs. time"}
  noise_scale:      {type: float, range: [0.0, 1.5], default: 1.0, trades: "diversity vs. designability"}
frozen_parameters:
  checkpoint: {reason: "Mixing checkpoints within a campaign makes designs non-comparable."}

preconditions:
  - checkpoint_present_and_hashed    # Part A: REGISTERED_CHECKPOINTS has sha256=None
  - scaffold_parses_if_provided

qc_gates:
  - id: output_count_matches_request
  - id: has_secondary_structure      # catches the classic silent "designed a noodle" failure
    threshold: {min_ss_fraction: 0.3}
  - id: no_chain_breaks
  - id: radius_of_gyration_plausible

known_silent_failures:
  - mode: "Completes but emits fewer designs than requested"
    detect: output_count_matches_request
  - mode: "Produces extended/disordered backbone with no secondary structure"
    detect: has_secondary_structure

cost_model: {unit: design, wall_clock: "PT10S..PT2M", resources: {gpus: 1}}

agent: deterministic
```

The `gpu_portability` block is the mechanism by which Part A's R1 (no HIP path for the ML core) becomes an
enforced compose-time refusal on Frontier rather than a runtime surprise. A site config may set an override
to attempt it anyway, which is exactly how the verification spike Part A recommended would be run.

## 3. Discovery and registration

The registry resolves toolkits from, in precedence order:

1. An explicit path in the campaign spec or CLI flag
2. `$IMPRESS_A_TOOLKITS` (colon-separated)
3. Installed entry points under `impress_a.toolkits` — how a third party ships a toolkit
4. The bundled `toolkits/` directory

Loading is **validating**: a malformed spec, a parameter range that excludes its own default, a QC gate
referencing an unimplemented check, or a skill document missing its required sections is a **load-time
error**, not a runtime surprise. A toolkit that does not load is reported and disabled rather than silently
partially registered.

Registration never requires editing the composer, the validator, or the manager. That is the test of whether
this layer is correctly factored.

## 4. Skill documents (C3)

A `SKILL.md` lives **in its toolkit directory**, beside the tools it describes. Co-location is the whole
answer to "how do they stay in step": a pull request that changes a parameter range touches the spec and the
skill doc in the same diff, and a reviewer sees both.

Two mechanisms keep that from being merely aspirational:

- **Required sections, checked at load.** Part B `04 §3` fixes them: purpose and when *not* to use, canonical
  sequences, cost posture, pitfalls, composition guidance. A skill doc missing one fails to load.
- **Referential integrity.** Every tool a skill doc names must exist in that toolkit, and every tool in the
  toolkit must be mentioned. Drift becomes a CI failure rather than a slow rot.

Skill docs are assembled into the policy's context at campaign start for the enabled toolkits only. A
campaign that does not enable `simulation` does not pay context for MD guidance it cannot act on.

## 5. Task agents

`agent.py` implements the four phases from Part B `04 §2` against a base class that supplies the scaffolding
— artifact staging, checkpoint hashing, QC-gate execution, provenance emission — so a tool adapter contains
only what is specific to that tool.

```python
class RFDiffusion3Agent(DeterministicTaskAgent):
    async def pre_process(self, ctx: TaskContext) -> Staged: ...
    async def parameterize(self, ctx: TaskContext, request: ToolRequest) -> Invocation: ...
    # execute() inherited — dispatches by pattern; adapters do not choose scheduling
    async def post_process(self, ctx: TaskContext, raw: RawResult) -> ToolResult: ...
```

`execute()` is deliberately **not** overridable in the normal case. Part B's dispatch rules (P6 inlined, P4
ledgered, P5 governed) are properties of the execution layer, and a tool adapter that schedules its own work
would bypass them.

LLM-driven agents subclass `LLMTaskAgent` instead, which adds prompt construction and schema-validated output
with bounded retry. **QC gates remain deterministic in both cases** — an LLM may author a Rosetta protocol;
it does not get to judge whether the result passed its clash check.

## 6. Two registry-wide concerns

**Gate implementations are shared, not per-tool.** `has_secondary_structure`, `no_chain_breaks` and
`clashscore_below` are referenced by many specs. They live in `src/impress_a/tools/gates/` as a named,
tested library; specs reference them by id with thresholds. This prevents fifty subtly different
implementations of the same check.

**Composite (P7) tools are specs like any other.** An IMPRESS pipeline declares its inputs, outputs,
parameters and gates exactly as RFD3 does; only its pattern and its invocation differ. Nothing in the
registry knows IMPRESS is special, which is the practical expression of Part B's decision to demote it to a
tool.
