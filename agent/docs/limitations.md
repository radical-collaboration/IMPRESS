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

**The known open risk.** Backtracking currently works by *branching the tree*, which avoids needing to
cancel in-flight work — so the risk is deferred rather than solved. Anything requiring true cancellation
(aborting a running graph on a `Stop`, reclaiming resources from an abandoned lineage) should be spiked
against the installed asyncflow before being designed around.

## Not yet implemented

Real scientific tool adapters (the bundled toolkit is mock), HTTP+SSE and MCP control-plane adapters,
checkpoint/restart **resume** (the provenance log and job ledger exist; the resume path does not), and
the P5 network-service governor (caching, per-service concurrency caps, `Retry-After` backoff).
