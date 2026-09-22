# Known Limitations

Stated plainly rather than discovered later.

## Scientific scope

**The loop closes *in silico*.** Nothing in the current toolkit consumes experimental data, so the Pareto
front ranks *predicted* quantities. A campaign's output is a prioritized hypothesis set, not validated
designs, and results should be reported that way.

The architecture anticipates this changing: `Property` carries a source and authority so a measurement
supersedes a prediction for the same objective without any change to a campaign specification, and
`ingest_measurement` accepts assay results even after a campaign terminates (`docs/decisions/0012`). What
is *not* built is the other half — nothing selects which designs to send for assay or manages samples.

**Some problem classes need a human-supplied hypothesis.** Where a design protocol depends on expert
mechanistic judgement (catalytic geometry being the clearest case), the agent can vary parameters and run
QC around a supplied hypothesis but cannot author it. Autonomy is narrower there, and a campaign should
say so.

## Residual risk in free composition

The validation regime prevents type-incoherent workflows, missing QC gates, frozen-parameter tampering,
resource-infeasible and platform-impossible graphs, budget overruns, and every *catalogued* silent
failure. It does not prevent a **novel** silent failure — one of a kind no `ToolSpec` anticipated, in a
tool combination no human reviewed. Cross-tool consistency and distributional checks are the general
defences, and they are statistical, not sound.

The self-promoting interlock buys **examination and delay, not soundness**: a *consistent* novel silent
failure — one that passes every gate, agrees with a correlated tool, and looks distributionally ordinary
on all N runs — will promote. Two consequences: raise the promotion threshold for patterns feeding
irreversible or expensive commitments, and weight cross-tool agreement conservatively, since tools
sharing training data or architecture may agree *because* they share a bias.

## Reproducibility, by layer

| Layer | Reproducible? |
|---|---|
| Core, composition, validation | Bit-exact |
| Model D policies | Bit-exact, seeded |
| Tool execution | Approximately — pinned versions and checkpoint hashes; GPU non-determinism remains |
| Model A / B policies | **No** — frontier APIs offer no usable seed, and temperature 0 does not guarantee determinism |
| A campaign as a whole | **Reconstructable, not replayable** |

An LLM-steered campaign can be audited and reconstructed from provenance; it cannot be re-run to the same
answer. Model D exists partly so there is a fully reproducible baseline to compare against.

## Cost estimates are unmeasured

Validation gate 5 refuses graphs against `cost_model` figures drawn from literature and documentation,
not measurements on the target platforms. Early campaigns should record actual-versus-estimated cost per
tool and recalibrate; until then the gate should carry a safety margin rather than be treated as precise.

## Cancellation

**Still the open risk, but now measured.** Backtracking works by *branching the tree*, which avoids
needing to cancel in-flight work. The spike has since been done against the installed asyncflow, and the
answer is: cancellation exists and is **advisory only**.

`ConcurrentExecutionBackend.cancel_task` calls `Future.cancel()`, which returns `False` once a callable
has started — so **queued work is reclaimed and running work is not** — and asyncflow's own cancel hook
discards that boolean, so a caller never learns which happened. `Dispatcher.cancel` and the control
plane's `cancel_run` therefore say so in their return value, and a run's terminal state always comes
from collecting it, never from the fact that cancel was called.

What this leaves unsolved: reclaiming a GPU from a long-running task that should have been abandoned.
That needs cooperative cancellation inside the task agents, or a backend that can kill a process.

## Not yet implemented

The **MCP** control-plane adapter, checkpoint/restart **resume** (the job ledger now records run state
and outcomes, and `RunService.reattach` reconciles what a previous process left open — but nothing
resumes a campaign from it yet), and the P5 network-service governor (caching, per-service concurrency
caps, `Retry-After` backoff).

## Built, but unexercised against real science

Real tool adapters for RFdiffusion3, LigandMPNN, PyRosetta and Boltz exist and are wired to real
binaries, and the Delta HPC launch path is complete. **No campaign has yet run them on real hardware.**
Everything below the adapters is exercised by the laptop tier; the adapters themselves are covered only
for registration, validation and dry-run, because executing them needs the science stack installed.

Two things in particular are unverified and are marked at their call sites: the **seed flag names** for
LigandMPNN and Boltz, and whether LigandMPNN's `--number_of_batches` is the right knob for `num_seqs`.
Run `impress-a preflight` on a login node before committing an allocation.

Related: the QC gates the real toolkits declare lean almost entirely on `metric_in_range` against a
tool's **own** self-reported confidence — which is exactly what a confidently-wrong tool passes. There
are no structural gates yet (is the ligand actually in the output complex, are there chain breaks, does
the sequence length match the contig), and no toolkit carries the known-bad fixtures under `tests/` that
this document's authoring guide asks for.
