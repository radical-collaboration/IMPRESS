# IMPRESS-A: the API and the loop — speaking script

**This file is generated from the `addNotes` blocks in `build_deck.js`.** The deck is the
single source of the spoken prose, so a presenter reading from the notes pane and a presenter
reading from this file never diverge. Regenerate after editing the deck — the command is at the
bottom.

**How to read it.** Plain prose is meant to be *said*. Anything in `[brackets]` is a stage direction
or that slide's budget, and is excluded from the word counts.

**Pacing — measured, not estimated.** Counts are the actual spoken prose at 155 words/minute, a
realistic rate for technical material delivered with pauses.

| Slide | Spoken | | Slide | Spoken |
|---|---|---|---|---|
| 1. title | 1.1 min | | 13. ACT 2 divider | 0.8 |
| 2. what it is / is not | 1.5 | | 14. surface 4, the inversion | 1.4 |
| 3. the framing slide | 1.2 | | 15. the measured run | 1.4 |
| 4. the loop and who drives it | 1.5 | | 16. measured and not measured | 1.5 |
| 5. the six surfaces | 1.3 | | 17. the interlock | 1.6 |
| 6. ACT 1 divider | 0.7 | | 18. ACT 3 divider | 1.1 |
| 7. surfaces 1 and 2 | 1.4 | | 19. as an application | 1.4 |
| 8. surface 3 | 1.5 | | 20. surface 5, the control plane | 1.6 |
| 9. intent, not a DAG | 1.5 | | 21. the layering contract | 1.4 |
| 10. surface 6, the spec | 1.4 | | 22. status by dimension | 1.1 |
| 11. the task agent | 1.5 | | 23. asks | 1.5 |
| 12. gates and refusal | 1.5 | | | |

**Main path: 4794 words = 30.9 minutes of speech.** Backups add 1.3 min if used.

| Act | The question it answers | Slides | What it concedes |
|---|---|---|---|
| **Functionality** | what can you write against this that you cannot write against a pipeline? | 6-12 | every toolkit that exists is one of the four real stages of a single chain, plus mocks, and nobody outside this package has authored either a toolkit or a policy |
| **Performance** | what does the loop cost, and where does it serialise? | 13-17 | no concurrent run and no serial baseline anywhere in the deck, so nothing divides into a speedup - and the stages were mocks, so this times the ENGINE and never the science |
| **Usability** | application, platform, or component? | 18-21 | nothing outside this package has ever driven a campaign, and `--model C` with no caller falls back to model D after 5 s instead of failing |

| Order | What's in | Speech | Fits |
|---|---|---|---|
| **A · full** | every main slide | **30.9** | a 35-minute slot, or a working session where questions land inline |
| **B · default** | drop 4, 9, 11, 21 | **25.1** | a 30-minute slot: drops the loop/driver slide, the intent seam, the task-agent phases and the layering test. Each is recoverable in a sentence, and 5 still carries the map |
| **C · hard twenty** | drop 4, 5, 7, 9, 10, 11, 19, 21 | **19.6** | a hard 20 that leaves room for discussion: the framing, the three dividers, one surface per act, both measured slides, the interlock finding, status and asks |

**Protect 2, 3, 12, 15, 16, 17, 22 and 23.** Two and three are what buy the rest of the deck (the caveats at minute two and the named weak dimension); 12, 15 and 17 are the only slides carrying evidence from a real run; 16 is what keeps the performance act honest; 22 is status and 23 is the asks. Never cut a divider - a cut deck without them is a list of slides. Backups B1 (compute patterns) and B2 (the type lattice) are out of every order; do not put them back to fill time.

**Say these out loud even if nothing prompts them:** that nothing outside this package has ever driven a campaign, so the component claim is empty and the control plane is the most carefully built unused thing in here; that `replicas > 1` DOES run - the mock campaign in this deck ran two lineages - and what has never run is `replicas > 1` on the real six-stage chain (backlog A10); that every stage in the measured run was a mock, so the timings are the engine and never the science; and that the 31% acceptance figure on slide 16 is transcribed from the project's Delta run archive, not mined from this checkout.

---

## 1. title — *1.1 min*

Thanks. This is a code walk through IMPRESS-A's API — and the deliberate claim in the
title is that there isn't one API, there are six. An operator writes a YAML file. A tool
author writes a spec file. Someone writing a reasoner implements one method. Someone
driving a campaign from outside the allocation speaks a protocol over a socket. Those are
genuinely different surfaces with different audiences, and the reason the project is worth
half an hour of your time is what they have in common underneath: one executor that owns
all the state, and one set of gates that refuses all of them the same way.

[Point at the ring on the right.] Six callers, one engine.

Everything on these slides is derived against ${HEAD}, and every number is mined from the
checkout by a script that ships beside the deck — so if you pull this branch and re-run
it, a figure that has moved will disagree with me out loud. There is one run in this deck
and it takes under three seconds on a laptop; I ran it while building these slides.

## 2. what it is / is not — *1.5 min*

Two things before the content, because this room can check me and I would rather hand you
the caveats than have you find them.

The strip across the top is the loop, and I will come back to it. The one mark worth
noticing now is the back edge: this is a loop, not a pipeline, and the reasoner is not the
body of it — several experiments sit at different steps at the same time.

Left card: what actually ran to make this deck. A complete campaign on the bundled mock
toolkit, ${Q.elapsed_s} seconds, ${Q.n_composed} graphs composed, one of them refused, two admitted,
${Q.n_results} design nodes, a Pareto front of ${Q.front_size}. That is a real campaign through the real
manager, the real composer, the real validator and the real provenance writer.

Right card, and this is the one I want you to hold onto: every stage of it was a mock. The
science is stubbed. There is one experiment in flight at a time, so I have no concurrency
measurement and no baseline to divide by. On the real chain, more than one replica has
never run — that is backlog A10 and I will show you exactly why on slide fifteen. And
nothing outside this package has ever driven a campaign: the control plane, which is the
most carefully designed surface in here, is tested and unused.

## 3. the framing slide — *1.2 min*

A technical audience arrives with three questions and they take different evidence, so the
deck is in three acts in this order.

Functionality: what can you write against this that you could not write against a
pipeline. The evidence there is that a tool is ${S.n_tool_spec_fields} declared fields rather than a code
path, a reasoner is ${S.policy_ops.length} methods, and everything either of them produces goes through the
same gates.

Performance: what the loop costs and where it serialises. I have a real end-to-end number
and a provenance record count, and I have no concurrency measurement at all.

Usability: application, platform, or component. One YAML and one command makes it an
application. ${S.n_tools} tools discovered at runtime from a directory makes it arguably a platform.

And the component claim is empty, which is the weak dimension and I would rather say it
now than have it extracted at minute twenty. The control plane and the remote session are
the most carefully built surfaces here — and nothing has ever driven a campaign through
them. If you want to find a real bug in this project today, that is where it is.

## 4. the loop and who drives it — *1.5 min*

One line, and it is the same line it has always been: observe, decide, compose, validate,
execute, analyze, update, terminate.

What changed — and this is the change that produced an API rather than a loop — is who
drives it. The manager used to *be* the loop. It called decide once per cycle and then
blocked on the graph that call asked for, which means a reasoner could never be consulted
while work was running. If you are an LLM deciding what to design next, being unreachable
for the twenty minutes your last idea takes to run is a fairly serious limitation.

Now the reasoner is its own coroutine and it calls the campaign. There are two ways to be
one. You can implement decide, answer one question at a time, and a driver plays the part
the old loop played — that is models A through D, unchanged, and it stays the auditable
default. Or you implement conduct, take the session, and drive yourself: submit five
experiments, then collect them in the order they finish.

Underneath both, the executor owns all the state and is its only writer. Note what that
means for the API: terminating is not the reasoner's decision. Budget, stagnation,
repeated failure — those are facts about state the reasoner cannot see, so the executor
decides when the campaign is over, and the reasoner finds out by being raised into.

## 5. the six surfaces — *1.3 min*

This is the map. Six surfaces, ordered by who writes against them rather than by module,
because a tour by module answers a question nobody asked.

An operator gets three subcommands and ${S.n_cli_models} control models. A scientist gets a YAML file with
${S.n_campaign_spec_fields} fields that describes the scientific question and nothing about search strategy.
A reasoner author implements ${S.policy_ops.length} methods and returns one of ${S.decision_members.length} decisions.
A reasoner — in this process or on a login node — gets ${S.n_session_ops} operations onto a live campaign.
An external caller gets ${S.n_plane_ops} operations behind ${S.n_routes} HTTP routes. And a tool author writes a
spec file with ${S.n_tool_spec_fields} fields plus an adapter with four phases.

Those are small numbers, deliberately. The interesting part is the bottom left: all six
reach exactly one executor, one tree, one provenance log, and all six are refused the same
way. And the bottom right is why I can say that with a straight face — the layering is an
allow-list walked by a test, not a diagram in a doc. Policy may import core and nothing
else. Core imports nothing internal at all.

Act one is surfaces one, two, three and six. Act two is four. Act three is five.

# Act 1 — Functionality

## 6. ACT 1 divider — *0.7 min*

Act one: functionality. Not features — tasks. What can you write against this that you
could not write against a pipeline?

Three claims. A tool is a declaration rather than a code path. A policy emits abstract
intent and never a DAG. And composition is free because refusal is cheap.

The weak one, before the act rather than after it: every toolkit that exists is one of the
${K.n_real_toolkits} real stages of a single chain, plus the mocks. Nobody outside this package has ever
written either a toolkit or a policy, so "it is easy to add one" is a claim about the shape
of the interface and not about anyone's experience.

## 7. surfaces 1 and 2 — *1.4 min*

Surfaces one and two are the ones a human touches, and the interesting thing about them is
what they refuse to contain.

On the left is a real campaign file, trimmed. Six stages named by tool id. Per-tool
parameters: the ligand SMILES, the contig spec, the diffusion step count. Four replicas —
and that means four independent lineages, four design nodes, not four samples inside one
tool. And the objectives, with directions and floors.

What is deliberately not in this file is how to explore. There is no threshold schedule, no
retry policy, no fan-out rule. Those belong to whichever reasoner you launched. The file
says what the campaign is about; the policy says what to try next. That split is the
reason you can run the same scientific question under four different control models and
compare them, which is the whole experiment this project exists to run.

Small detail that cost a real debugging session: a relative path in here resolves against
the YAML's own directory, not the working directory, because the launcher cds into a
per-job directory before loading the spec.

On the right: three subcommands. And the one worth noticing is preflight, which I will
come back to in act three, because it is the surface that respects that an allocation costs
money.

## 8. surface 3 — *1.5 min*

Surface three. If you want to write a reasoner, this is the whole contract: three methods
and four possible answers.

decide takes an observation and returns a decision. interpret is the hook for when reading
a result is itself a judgement call — it defaults to None, because deterministic metric
extraction by the task agents is the normal case. And on_rejected is mandatory: if your
graph is refused, you get the structured reason and another attempt.

Four decisions. Run this experiment. Branch from an earlier node. Stop and ask a human.
Done.

Two absences are deliberate and both are API design rather than implementation. conduct is
not a member of this Protocol even though it is the other way to be a reasoner — adding it
would break every existing policy, and because the Protocol is runtime_checkable its
membership list is load-bearing for anyone doing an isinstance check. And there is no
"await" decision: waiting is something the reasoner does by calling result, not something
it asks the loop to do on its behalf. One control-flow vocabulary, not two.

On the right, the four shipped models, and the reason a fifth is cheap: subclass BasePolicy
and implement one method. They also compose — the CLI wraps whatever you chose in a
corrections guard by default, which is why the run in this deck reported its policy as
"rulecorrectionspolicy of threshold".

## 9. intent, not a DAG — *1.5 min*

This is the seam I would defend hardest, so it gets its own slide.

A policy returns an ExperimentIntent. Look at what is in it: a goal in words, an optional
toolkit hint, an ordered list of tool ids, a parameter bag, a parent node, and a replica
count. That is abstract. It is not a DAG. Turning it into a typed graph with N lineages,
resolving the ports, type-checking the hops — that is the engine's job.

And the parameter bag is merged, not authoritative: the campaign's own params go underneath
whatever the policy asked for, so the policy always wins on a key it actually set, and gets
the ligand and the contig for free on every key it did not. The consequence is that no
policy in this package names a single tool parameter. None of them knows that boltz_predict
takes a ligand_smiles.

That is what makes the control models swappable rather than nominally pluggable, and it is
backed by the import rule: policy may import core and nothing else, enforced by a test.

The cost, on the right in red: a policy can only ask for things the composer can build out
of an ordered stage list. So "free graph composition" is free within one topology family,
and every graph in this deck's run was the same four-tool chain at two different widths.

## 10. surface 6, the spec — *1.4 min*

Surface six, and this is the one I would most like someone in this room to use in anger.

A tool is a YAML file. This is RFD3, trimmed. It declares an id, a toolkit, a compute
pattern — P1 means GPU-node-local and in-job — a dotted path to the adapter class, a
resource shape, typed output ports, parameters with ranges and a note on what each one
trades, the metrics it promises to report, its QC gates, and a cost model.

Four consumers read this one file — composer, validator, budget guard, task agent — which
is why it is declarative: a scientist can review a tool in a pull request without reading
Python.

Bottom left is what earns the design. Loading a toolkit validates it: a default outside its
own range, a gate nobody implemented, a missing SKILL.md section — all load-time errors. And
a toolkit that fails anywhere registers nothing, so an RFD3 container problem cannot take
PyRosetta down with it.

Bottom right, and this is the sharpest rule in the project: an acceptance threshold must
never be the only thing that notices a value is missing. That is how a fabricated zero
passes for a measurement. So the spec will refuse to load if you put a threshold on a
metric that no integrity gate promises to report.

## 11. the task agent — *1.5 min*

The other half of surface six is the adapter, and it has four phases.

pre_process can rewrite the request. parameterize resolves the declared defaults, refuses
anything frozen or out of range, and — this one matters — draws this lineage's seed if the
tool declares one, which is what makes four replicas four independent samples rather than
four copies of one design. run is the phase an adapter author actually writes.

And post_process extracts the metrics and enforces the gates. That docstring says "never
skippable" and it means it: there is no path from a tool's output into campaign state that
does not go through the spec's gates.

The box on the right in red is execute, and it is deliberately not overridable. Pattern
dispatch belongs to the execution layer. An adapter that scheduled its own work would
bypass the rule that P6 is inlined and P4 gets a durable ledger entry, which is exactly
the kind of thing that works fine until it doesn't.

Bottom right is the reason any of this exists. Scientific tools fail silently far more often
than they crash. An empty output directory, a FASTA header the parser didn't recognise, a
relax that diverged — all of those exit zero. ${K.gate_fixtures} fixtures ship with the toolkits and
${K.gate_fixtures_bad} of them are recorded failures kept as tests. A node that fails a gate is never
rankable, whatever its scores say.

## 12. gates and refusal — *1.5 min*

Composition is free; this is what makes it affordable.

Five gates, in order, before anything executes. Types — and the type lattice is scientific,
not file-format based, so handing a monomer to an interface scorer is a type error at
composition time. Structure: cycles, orphans, an in-process tool that should have been
inlined. Parameters. Resources against what the site actually has. Budget against the
ledger. Then a dry run in which every task agent parameterizes and nothing executes.

The field I want to point at is top right: transient. It is true when the graph is fine and
only the moment is wrong. Gates one through five are deterministic properties of the graph
and are never transient — the interlock's cost cap is. Without that distinction a policy
answers resource contention by dropping replicas and truncating stages, which reads from
the outside as the policy quietly degrading itself.

And here is that happening for real, in the run that built this deck. The policy asked for
${ref.lineages} lineages, ${Q.composed[0].tasks} tasks. The interlock refused it as transient:
"${ref.reason}". The policy came back with ${Q.composed[1].lineages} lineages and ${Q.composed[1].tasks}
tasks, and that was admitted — twice.

Bottom right, honestly: that is not the interlock being clever, and it is the exact
mechanism that backlog A10 says will bite on the real chain. More on that in act two.

# Act 2 — Performance

## 13. ACT 2 divider — *0.8 min*

Act two: performance. And I want to be careful here, because systems vocabulary makes
everything sound measured.

Three claims. The reasoner is no longer the loop body, which is an architectural claim with
an API consequence. Refusal is measurably cheap — the refused graph and its replacement were
composed inside the same millisecond. And the steady-state cost of a cycle is small: 71
milliseconds for the second cycle against 1.09 seconds for the first, and the whole
difference is engine construction happening once.

The caveat, up front: there is no concurrent run in this deck and no serial baseline, so
none of those numbers divides into a speedup. And every stage was a mock, so what I have
timed is the engine — compose, validate, dispatch, absorb — and never the science.

## 14. surface 4, the inversion — *1.4 min*

Surface four, and this is the one the architecture turns on.

Left lane is yours: a coroutine. You submit as many experiments as you like and then
collect them with as_completed, which yields them in the order they finish rather than the
order you asked. Right lane is ours: admit through the gates, dispatch, reap, absorb into
the tree, and decide when the campaign is over.

Look at what crosses in the middle, because those labels are the API. An observation goes
both ways — and it is the same object a policy's decide receives, which is ADR 0007: parity
of evidence, not a progress bar. An intent goes forward and a run id comes back, or an
exception does, synchronously, in the same breath as the request. A run outcome comes back
when the run finishes. And a node id goes forward for a backtrack, which is non-destructive
because the tree is append-only.

Two properties are deliberate. Everything on this interface is serializable — nothing live
crosses it — which is what makes a reasoner on a login node talking to an executor inside a
batch allocation possible at all. And the whole thing is typed in core, because a policy may
import core and nothing else, so if the session had been typed anywhere else the seam would
have rotted on the first commit.

## 15. the measured run — *1.4 min*

This is the one real measurement in the deck, and it is small on purpose: one variable,
which cycle.

The campaign times itself — every provenance record carries a timestamp, so these offsets
are measured rather than instrumented in by me. Cycle one, from composed to dispatched,
${d1.toFixed(2)} seconds. Cycle two, ${((d2 - c2) * 1000).toFixed(0)} milliseconds. The entire difference is
building the execution engine, which happens once.

So the steady-state cost of going round this loop — compose a graph, type-check it, run it
through five gates and a dry run, dispatch four mock tasks across two lineages, absorb the
results, re-rank the Pareto front, write the provenance — is about seventy milliseconds.

Now the units, because this is where overclaiming is easy. The campaign's own span is
${span} seconds. The process took ${Q.elapsed_s}. So about a second and a half is Python interpreter
startup and imports, outside the loop entirely — which, if you care about cycle latency on
a cluster, is the number that will annoy you first.

And the denominators, on the right: one host, one experiment in flight, two lineages, four
mock tasks each. I varied nothing. This is a latency figure for the engine. It is not a
throughput result and it is not a scaling result, and I have neither.

## 16. measured and not measured — *1.5 min*

This is the slide that makes the act honest, and it is two lists.

On the left, everything I measured, with where each number came from — and the one worth
naming is that two lineages absorb as two distinct nodes with distinct metrics, which is the
cheap half of the independence invariant.

On the right in red, written as refusals rather than apologies. I have no concurrent run,
so the single thing the session API exists for is unmeasured. I have no serial baseline, so
nothing on the left divides into a speedup. Every stage was a mock, so there is no
science-per-GPU-hour number here of any kind. One backend. And on the real chain, more than
one replica has never run.

The dark box is the part I would actually argue about over coffee. Four lineages do not buy
four times the chance of a good design. The acceptance rate across this project's real runs
is about thirty-one percent and nothing in this engine improves it. What the engine controls
is how many draws you can afford, and whether you can tell a bad draw from a broken tool.

Which means the interesting figure is not tasks per hour. It is how few GPU-hours it takes
to learn that a workflow shape is not worth running again. That is what the interlock is
for, and it is the next slide.

## 17. the interlock — *1.6 min*

This is my favourite mechanism in the project and it has a seam in it, so you get both.

The rule: a shape nobody has run before is neither blocked nor trusted. Cost-capped at ten
percent of budget, forced dry run, every node marked suspect however good the scores.
Promotes after three clean runs, demotes on one. And a design that merely scores badly is
not evidence against the workflow — that is decision 0013, and it is the right distinction.

Now the table. In this run there are two pattern signatures, and they are the same four-tool
chain — one composed at three lineages, one at two. Two widths, two patterns.

And that is not what the function says it does. The docstring says shape only: tool ids plus
typed edges, with parameter values excluded deliberately so that changing a parameter cannot
reset accumulated trust. But look at the loop: it emits one entry per node. A three-lineage
graph contributes three copies of every hop, so it hashes differently. Replica width is in
the signature by construction rather than by decision.

Why that bites: to run the four-lineage independence check that this project actually needs,
you must first earn trust at four lineages, because trust at one does not transfer. Backlog
A10 already names this, so it is a known cost rather than something I found this morning —
but it is the clearest example I have of a design rule and its implementation disagreeing
quietly.

# Act 3 — Usability

## 18. ACT 3 divider — *1.1 min*

Act three: usability. Not the user interface — the use cases. Is this an application, a
platform, or a component?

As an application I think it is genuinely strong: one file, one command, and a preflight
step that exists because an allocation costs money.

As a platform it is arguable in the honest sense: tools are discovered at runtime from a
directory, and an environment variable points it at yours without touching the package. The
interface is there. Nobody has used it.

As a component it is empty, and that is the weak claim I promised you in the first three
minutes. Nineteen control-plane operations, a remote session that implements the reasoner's
own protocol over a socket, and no caller.

And the specific thing I would fix first: launching model C with nothing attached to steer
it does not block and does not fail. It falls back to model D after five seconds. So the
headless mode can silently become the explicit-policy mode, and the only sign is a line in
the log.

## 19. as an application — *1.4 min*

As an application, the thing I would point at is not the run command — it is preflight.

Every real adapter in this project raises on a missing environment variable. But it raises
once a task is already running, which on HPC means inside the allocation, after the queue
wait. So preflight runs the same checks on the login node, where repairing them is free and
there is still internet.

The detail worth stealing is the third state. None means undetermined, not failed. Several
probes shell out to import a heavy science stack and can take minutes on a loaded login
node; report that as FAIL and you have trained the reader to ignore the FAIL column.

And the rule that holds it together: None is only ever for a probe that produced no answer.
A missing MPNN_DIR is a FAIL forever. A pyrosetta import error is a FAIL. A pyrosetta
timeout is undetermined. The moment "warn" starts meaning "a failure we would rather not
block on", the column is decoration.

What it has caught: a venv on spinning disk instead of NVMe, which works perfectly, about
eight times slower, and shows up inside an allocation as an unexplained task timeout.

And every job writes one directory you can hand to someone else — including the git sha and
whether the checkout was dirty.

## 20. surface 5, the control plane — *1.6 min*

Surface five is the one an external caller sees, and it is the one I would most like
someone to attack.

One protocol. In-process and HTTP are adapters over it, and the rule — ADR 0007 — is that no
adapter may offer an operation the others do not. ${S.n_plane_ops} operations, ${S.n_routes} route heads, and the
routes are a mechanical rendering of the Protocol, which is why the mining script counts
both and puts them next to each other: if they drift, the slide is wrong out loud.

Four semantics in that table are not the transport's invention. Admission is synchronous:
202 with a run id, or 409 carrying the structured failure that refused it. Waiting is a long
poll with three honest answers: here it is, ask again, or the campaign ended and the answer
is never coming. Observe returns the same object a policy's decide receives. And a
measurement can arrive after the campaign is over, because the campaign record is
append-only and outlives execution.

On the right: RemoteSession implements the reasoner's own protocol over this plane, which
means the sequential driver and an unmodified threshold policy run against a socket exactly
as they run in memory. That is the test that the seam is real.

And the honest box at the bottom right: this is not a public-facing server. No auth, no TLS.
The module's own docstring says bind it to loopback. That is fine today because nothing uses
it, and it is the first thing that has to change when something does.

## 21. the layering contract — *1.4 min*

Last content slide, and it is the one that makes everything I have claimed checkable.

Ten layers. Each row shows what that layer may import, and the red column shows the edges
that are forbidden. This is not a diagram in a document — it is a table in a test that walks
the source with ast and fails the suite on any edge that is not in the list.

Three of these are load-bearing. Policy may not reach tools or exec: if it could, a policy
would stop emitting abstract intent and start invoking tools, and the control models would
stop being swappable. Compose may not reach exec: that single absence is what makes the
entire validation path testable with no backend, which is the whole laptop test tier. And
core imports nothing internal, which is what keeps the serializable seam honest.

Two details I like. It walks the ast rather than scanning module-level imports, because the
adapters defer their heavy science imports into run bodies on purpose — so a deferred import
of exec inside a compose function is caught too. And it is an allow-list, so a new
cross-layer import fails by default: the contract cannot rot by addition.

One honest blind spot, which the test's own docstring names: a dynamic importlib call is
invisible to it.

## 22. status by dimension — *1.1 min*

Status, three columns, and the format is the argument: three things that run and three that
do not, per dimension, deliberately the same length.

Functionality runs: six surfaces exercised, loading validates, and refuse-and-retry was
observed in a real run rather than asserted. Functionality does not: one topology family,
no third-party author, and the calibration machinery — a measurement superseding a
prediction, the one capability a composed graph has that a written-down one does not — has
never been exercised.

Performance runs: engine latency is measured, both ends of the backend lifecycle are
bounded, and the provenance log is complete enough to time the campaign from outside.
Performance does not: no concurrency measurement, no baseline, and the real chain has only
ever run one lineage.

Usability runs: one YAML and one command, runtime toolkit discovery, two transports tested
against each other. Usability does not: nothing external drives it, model C fails open, and
there is no serve command.

The red column is not a to-do list. It is the list of things you should not believe from
this deck.

## 23. asks — *1.5 min*

I would rather end on the questions than on a summary, and they are grouped by what each one
costs. The left column costs a wrong answer or real time. The right column costs whoever
adopts this next.

One. Should the pattern signature normalise replica width? It is documented as shape-only
and deliberately excludes parameter values, but it emits one entry per node, so width is in
the hash. Fixing it makes trust transfer across widths. It also weakens the argument that a
wide run is genuinely a new shape, which may be the right argument. I do not know which.

Two. Should a streak of acceptance failures demote a pattern? Trust counts integrity only,
which is the right rule — but a tool emitting well-formed, uselessly-scored output promotes
after three runs.

Three. Should shrink-on-transient live in the base class? Today the default is Stop and
every policy re-implements shrinking, and that is exactly where a four-lineage independence
check quietly becomes a three-lineage one.

Four. Is loopback-only permanent for the control plane?

Five. Should model C with no caller refuse to start rather than fall back?

Six. Should the CLI's policy imports be lazy? Listing tools currently pays for langgraph,
and about a second and a half of this deck's run was startup outside the loop.

Thank you — and the fastest way to disagree with any of this is to pull the branch and run
the mining script.

## B1. compute patterns — *0.6 min*

Backup slide, if someone asks about the pattern taxonomy. Eight patterns, organised by what
they imply for scheduling rather than by what the tool computes. Two are used: P1 for the
GPU stages and P2 for the Rosetta fan-out. P6 is the interesting one — in-process, and it
must never be scheduled; the composer inlines it, so a scheduled P6 is a bug and not a slow
path. P4 and P8 are the two that outlive the agent and therefore need a durable ledger
entry, and P8 is forward-declared for a wet-lab measurement arriving after the campaign has
ended.

## B2. the type lattice — *0.7 min*

Second backup: the type lattice. Twelve scientific types rather than file formats, and the
reason is gate one. If these were .pdb and .json, the type gate could only check that a file
exists — and the composer could not refuse a graph that is structurally fine and
scientifically meaningless.

Two distinctions do most of the work. Small molecule versus parameterized, so an
unparameterised ligand reaching a force field is a type error at composition time rather
than silent corruption. And backbone versus complex, so an interface scorer cannot be handed
a monomer. Note the asymmetry in unifies_with: a complex satisfies a backbone requirement
because it contains one, and not the reverse.

---

## Regenerating this file

The prose lives in `build_deck.js`. After editing a slide's `addNotes`:

```sh
python3 make_script.py --deck build_deck.js
```
