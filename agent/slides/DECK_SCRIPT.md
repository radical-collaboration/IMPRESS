# IMPRESS-A code walk — speaking script

Companion to [`DECK_OUTLINE.md`](DECK_OUTLINE.md) (slide structure) and
[`CODE_FOR_DECK.md`](CODE_FOR_DECK.md) (the staged code blocks). Slide numbers and snippet IDs match
across all three.

**This file is generated from the `addNotes` blocks in `build_deck.js`.** The deck is the single
source of the spoken prose, so a presenter reading from the notes pane and a presenter reading from
this file never diverge. Regenerate after editing the deck — the command is at the bottom.

**How to read it.** Plain prose is meant to be *said*. Anything in `[brackets]` is a stage direction
or that slide's budget, and is excluded from the word counts.

**Pacing — measured, not estimated.** Counts are the actual spoken prose at 155 words/minute, a
realistic rate for technical material delivered with pauses.

| Slide | Spoken | | Slide | Spoken |
|---|---|---|---|---|
| 1. Title | 0.9 min | | 9. The seam: the engine | 1.6 |
| 2. What it does | 1.1 | | 10. Tools are data | 1.3 |
| 3. The constraint | 1.1 | | 11. Four jobs (F3) | 1.3 |
| 4. The loop (F1) | 1.3 | | 12. Four defects | 1.5 |
| 5. Architecture (F2) | 1.1 | | 13. The trust ledger | 2.1 |
| 6. One experiment, typed | 1.1 | | 14. Running it | 0.9 |
| 7. Admission | 1.4 | | 15. Status | 1.1 |
| 8. The seam: dispatch | 1.4 | | 16. Asks | 1.5 |

**Main path: 3210 words = 20.7 minutes of speech.** Backups add 2.6 min if used.

| Order | What's in | Speech | Fits |
|---|---|---|---|
| **A · full** | every main slide | **20.7** | a 25-minute slot, or 20 with questions strictly held to the end |
| **B · default** | drop 6 (typed dataflow) and 10 (tools) | **18.3** | a 20-minute slot with a few questions taken inline |
| **C · hard twenty** | B, and drop 14 (how to run it — it is in the README) | **17.4** | a hard 20 that leaves real room for discussion |

**Protect 8, 9, 13 and 16.** Those are the two seam slides, the trust findings and the asks, and
they are what this room came for. Slides 6 and 10 are the designated cuts: the typed-dataflow strip
is recoverable in one sentence on slide 4, and the tool-spec slide is recoverable on slide 7.
Order C drops 14 as well — how to run it is in the README, and this audience will read that rather
than watch it.

Do **not** compress 15 (status). An audience that catches you overclaiming stops believing the rest,
and this deck's credibility rests on the caveats being volunteered rather than extracted.

**Three things to say out loud even if nothing prompts them:** `replicas > 1` has never executed
(slide 15), nothing has ever been promoted by the trust ledger so the trusted path has never run
(slide 13), and the Delta durations on slide 11 are transcribed from `plans/first-real-run.md`
rather than read from a log on this machine.

---

## 1. Title — *0.9 min*

[0:45] A code walk, not a results talk. IMPRESS-A runs protein design campaigns on HPC: you give it a goal and a budget, and it decides what experiment to run next, composes a workflow out of a tool registry, runs it through asyncflow and rhapsody, and updates a population of candidates.

The word doing the work is composes. There is no fixed pipeline anywhere in this repository. Every experiment is a new graph no human has reviewed, and most of the code I will show you exists because of that one fact.

When some of you last saw this, nothing real had ever run. Since then a six-stage campaign completed on Delta. I will walk the seam, show what four jobs cost us, and be precise about how little one completed campaign proves.

## 2. What it does — *1.1 min*

[1:05] The shape of a campaign, and then what one actually produced.

Across the top: a goal, a reasoner that decides, a composer that turns that into a typed DAG, admission, execution, absorption. Two edges make it a loop rather than a pipeline — a rejected graph comes back with a structured reason and another attempt, and every decision after the first sees every result so far.

Left card, all measured. Six stages end to end in under three minutes: diffusion, sequence design, two Rosetta stages, a shape filter, a Boltz prediction. All four objectives came back with real values, admitted on the first attempt, cost measured per stage.

Right card, because you would ask and I would rather say it first. One lineage, one cycle, one draw. Replicas greater than one has never run. The node is marked suspect rather than pass, because the pattern is still provisional — the interlock working, not a failure. And no measurement has ever superseded a prediction.

Treat it as a floor. What it proves is that the plumbing survives contact with real tools.

## 3. The constraint — *1.1 min*

[1:00] If you keep one slide, keep this one. Everything after it is a consequence rather than a preference.

Two facts. A machine composes workflows no human has reviewed. And the tools those workflows call fail silently far more often than they crash — a generator hands back a structure with no secondary structure, a confident designability number, and exit code zero.

Five things fall out. A policy emits abstract intent, not a DAG, so control models stay swappable. Everything is validated before it executes: five gates, then a dry-run where every agent parameterizes without running. Trust is scored on shape and has to be earned. Exit code is never evidence, so a QC-failed node can never reach the front whatever it scored. And exactly one component writes state and decides when to stop.

The honest flip side is at the bottom. If a person reviewed every graph before it ran, you would write the DAG down once and schedule it, and most of this would stop paying for itself.

## 4. The loop (F1) — *1.3 min*

[1:15] Two coroutines meeting at a session, and the asymmetry between them is the point.

Left, a reasoner: observe, decide, submit, wait. Two ways to be one — implement decide and let a driver play the loop, which is what models A through D do; or implement conduct and drive yourself, submitting as many experiments as you like and collecting them in the order they finish. The second is what makes a federation of agents generating an ensemble in parallel expressible at all.

Right, the executor: admit, dispatch, reap, absorb. It is the only writer of campaign state. Note what it is not — it is not the loop body with a policy called inside it. The reasoner is a peer.

The red arrow is the one people miss. A rejected submission does not burn the experiment: the policy gets a structured reason and another attempt, bounded by max_attempts and independently capped in the executor, because a conduct reasoner is under no obligation to honour anything the driver promises.

Two rules hold it together. One writer, and every mutating block is await-free, so an observation is never taken halfway through absorbing a run. And the executor decides termination, because budget and stagnation are facts a reasoner cannot see.

## 5. Architecture (F2) — *1.1 min*

[1:00] Eight layers, and the thing worth looking at is in red.

Control plane at the top, one protocol with two transports shipped. Then the policy layer, the swappable one. A thin manager facade, the runtime that owns state, composition and validation, tools, exec, and at the bottom core, which imports nothing internal.

The red marks are four arrows that do not exist. A policy may not import tools, exec or runtime; compose may not import exec. I draw them because an edge that is merely absent reads as an oversight, and this room will ask whether the rule is enforced or merely intended.

It is enforced. A test walks the package with ast and checks every internal import against one table — ast.walk rather than module-level imports, because the real adapters defer their science imports into run bodies on purpose, and a deferred cross-layer import is exactly as fatal as one at the top.

Writing that test found two edges nobody had documented. Both are in the table now.

## 6. One experiment, typed — *1.1 min*

[1:00] One experiment, left to right, naming the type at each hop — the types are the contract between layers.

The executor builds an observation. The policy returns a decision carrying an experiment intent: tool ids, parameters, a replica count. It is abstract, there is no DAG in it. The composer turns it into a typed graph, which is plain data. Dispatch registers that graph and hands back a handle without awaiting. What comes back is a run outcome, serializable and core-typed, so a reasoner in another process can hold it.

Underneath is an actual run on this laptop. Four admissions over three cycles. The first row was refused by the interlock — a provisional pattern is capped at ten percent of available budget and three lineages did not fit. The policy shrank to two and resubmitted. That is the retry doing its job: a refusal costs an attempt, not the experiment.

Six design nodes, every one marked suspect, because the shape stayed provisional until the third clean run promoted it.

## 7. Admission — *1.4 min*

[1:15] This is the answer to "you let a machine invent workflows?"

Five gates, in order, first refusal wins. Gate two rejects a tool composed without its QC gates, so you cannot compose your way out of quality control. Gate four rejects a P6 tool somebody tried to schedule — those are meant to be inlined, and a scheduled one is a composer bug.

Then three things that are not gates. The interlock. A dry-run, where every agent parameterizes without executing — that catches a graph that type-checks but cannot be turned into a command line. And a reservation.

Reserve is last for a reason: the dry-run awaits, and by the time it returns another submission may have claimed the budget gate five saw. Reserve re-checks against available budget and is the authoritative decision.

On the right, the trust half. A pattern is the graph's shape — tool ids and typed edges, hashed, parameter values deliberately excluded so tuning a parameter does not reset trust. A provisional shape is capped, forced through a dry-run, marked suspect whatever it scores, and may have only one instance in flight, because promotion counts consecutive clean runs and N concurrent copies are one draw sampled N times.

The limit, from our own limitations doc: this buys examination and delay, not soundness. A consistent novel silent failure promotes.

## 8. The seam: dispatch — *1.4 min*

[1:20] The slide I would defend hardest, and it is four lines of real code.

A task graph is plain data. To run it, one generic factory builds a closure per node, sets its dunder-name to the node id, and hands it to asyncflow's function_task decorator. That is the whole adapter — no codegen, no AST rewriting, no templating. And setting dunder-name first is not a trick: the decorators take no name keyword, so this is precisely what lets one factory serve every node of every graph.

The closure binds workdir to a local rather than reaching through self, because it gets pickled to a process pool and self would drag the dispatcher, and the engine's futures, along with it.

Second block, submission. Walk the graph in topological order, pass each dependency's unawaited future as an argument — that is how you express an edge. Build a gather with return_exceptions, and return without awaiting. That one change is what let the reasoner stop being the loop body.

Two idioms, not interchangeable: unawaited futures as arguments are edges, gather is independent work.

Right-hand side, measured rather than assumed. Cancellation is advisory. Cancel returns False once a callable has started, asyncflow throws that answer away, so queued work is reclaimed, running work is not, and nobody tells you which happened. A run's terminal state always comes from collecting it.

## 9. The seam: the engine — *1.6 min*

[1:25] The second half of the seam is construction, and this is where the expensive lessons are.

Three things in make_engine_bounded are load-bearing. Only the synchronous construction goes to a helper thread — a dedicated daemon thread, not the default executor, because a stuck call on a pooled thread would hang interpreter shutdown too. The backend's async init and the engine are built back on the caller's own loop. And that await is not politeness: rhapsody's backends are awaitable, and awaiting registers the task states. Construct one synchronously and it appears to work, then fails much later with "backend not registered, available backends: empty list".

The right column is what each cost. Two full allocations went to an engine built on a throwaway loop — asyncflow's engine captures the running loop in its constructor and puts its dispatch task on it, so an engine built on a closed loop looks fine and dispatches nothing. Every submitted task just hangs.

One two-hour allocation went entirely to Dragon's Batch constructor, which blocks the event loop, so our own heartbeat never fired once in two hours.

And the most expensive item is teardown, not startup: on the reference pipeline, shutdown never returned after the science finished and the job sat an hour before someone cancelled it — sixty-four GPU-hours, thirty-seven percent of that job's bill.

Both ends are bounded now, and a stuck teardown is abandoned with a warning rather than raised: results are already durable, and raising would report a campaign that succeeded as failed.

## 10. Tools are data — *1.3 min*

[1:10] Adding a tool is a YAML file plus a subclass, never a change to the composer, validator or manager. If you have to touch those, the layering is wrong.

The spec declares typed ports, which is what gate one checks edges against; a compute pattern; resources; the metrics it reports; mandatory QC gates resolved by id from a shared library; and a cost model that feeds gate five.

Loading is validating. A default outside its own range, an unknown gate id, a skill document missing a section — all load-time errors. And a toolkit that fails anywhere registers nothing, never a partial set, because a half-registered toolkit is how you get a campaign that silently composes around the missing piece.

Four phases, and post_process is where QC is enforced — not skippable, not overridable by an adapter.

On the right, the tool that lies: it succeeds, reports designability of 0.91, and emits a structure with two percent secondary structure. One test asserts all three at once — the tool succeeded, the numbers look great, QC caught it anyway.

And the honest gap. The real toolkits have no equivalent. Their gates are thresholds on each tool's own opinion of itself, which is precisely what a confidently-wrong tool passes.

## 11. Four jobs (F3) — *1.3 min*

[1:15] Four jobs to a completed campaign, and the figure is really about one variable.

Top row, the HDD baseline. Diffusion 137 seconds, sequence design 293, and then packmin could not finish importing PyRosetta inside its three-hundred-second budget, so nothing downstream ran at all.

Middle row, the same campaign with one thing changed: the virtual environment moved from HDD-backed Lustre to NVMe. Sequence design went from 293 seconds to 18, packmin from not finishing to sixteen.

The reason is on the right. Importing PyRosetta off that filesystem costs 471 seconds — a 598-megabyte shared object, demand-paged. Torch is another 280. On NVMe both are seconds. That was the single largest cost this project was paying, and it was invisible because it looked like a tool timing out.

It nearly caused a second bug, which is the more useful half. The queued fix was to raise three walltimes six-fold, which would have hidden the real cost behind timeouts far too large.

Bottom right, the caveat for anyone reading our cost models. Diffusion took 146 seconds in one job and 45 in the next — same campaign, same parameters. These numbers feed gates that refuse graphs, so they sit deliberately above measurement and must not be tightened toward equality.

## 12. Four defects — *1.5 min*

[1:20] Four defects reached real hardware, each invisible to a dry run. The pattern across them is more useful than any one.

What a tool writes. Our glob for the diffusion output picked a trajectory rather than the design — same extension, and "denoised" sorts before the design's own name. A five-megabyte multi-frame stack went downstream as the backbone instead of a nineteen-kilobyte design.

Whether a tool can import. LigandMPNN died in its module-level imports, before parsing a single argument we passed it. No flag or path we sent could ever have been read.

Where the bytes live — the storage story from the last slide.

And the subtle one: an estimate that refuses work. Our cost models were literature guesses six to sixty-nine times over reality, and gate five and the interlock cap refuse graphs against those numbers. The inflated GPU side summed past the cap, the chain was refused, and the policy truncated the last stage off — which happened to be the only producer of two of the four campaign objectives. The run was unwinnable from the moment it was admitted, and nothing said so.

Two things to carry away. Checked against the binary is not executed. And a plausible explanation is not a diagnosis — the trajectory bug was a convincing cause for a failure it had nothing to do with, and only recovering the real stderr separated them.

## 13. The trust ledger — *2.1 min*

[1:35] Two findings about the trust ledger, and the second is new as of building this deck.

The first. The executor loaded the ledger from a path relative to the campaign root, and the Delta launcher changes directory into a per-job working directory before starting. So the ledger resolved inside each job and started empty every time. Two real runs left two files — one with zero clean runs, one with one — and promotion counts three consecutive clean runs within one file.

What is worth your time is how it hid. Nothing ever logged where the ledger was, so a file that silently reset looks exactly like one that has not earned promotion yet — and I reported it that way. It had been true since the first Delta job, which means the trusted code path has never executed, and the ten percent cap has applied to every graph ever composed on real hardware. That cap is exactly what truncated the last stage off the chain twice.

The second I hit while generating the numbers for this deck, and I have not changed the code. The signature emits one string per node and hashes the sorted join, so N lineages give N duplicate parts and the hash changes with the replica count — even though it deliberately does not change when you tune a parameter. The table shows the same chain hashing three ways at one, two and four replicas.

The cost is concrete. The cheapest route to exercising four independent lineages was to promote the pattern with a one-replica campaign, then run four. It does not work: four replicas is a different, untrusted pattern, still capped, still refused, and the policy would quietly shrink it to three and run a weaker check than the one we asked for.

So, genuinely open: is trust earned at one lineage evidence about four, when the cap it would lift exists to bound blast radius?

## 14. Running it — *0.9 min*

[0:45] The command worth pointing at is preflight: it checks the container path, the checkpoints, the Boltz cache, whether PyRosetta imports, and whether the virtual environment is still on slow storage — all on a login node, before you spend a queue slot.

The split that matters is that the entire local tier runs on a laptop in about fifteen seconds with no allocation: a complete campaign with a real manager, real policies, a real composer and validator, stubbed science. That is deliberate, because HPC iteration is slow and expensive. The corollary is the uncomfortable half, which is the next slide.

One convention I would steal for other projects: a magic number in a test is often a bug report. A stagnation limit of ten thousand appeared in three separate tests before anyone noticed the defect was in the engine, not the test setup.

## 15. Status — *1.1 min*

[1:00] I will not compress this slide, because an audience that catches you overclaiming stops believing everything else you said.

Left, what genuinely runs. A real six-stage campaign on Delta. The engine — composition, gates, interlock, Pareto tree, provenance, a durable ledger. Four control models over one shared executor. The control plane in two transports, including a reasoner driving a campaign from another process. Both ends of the Dragon lifecycle bounded, each against a real lost allocation.

Right, what has never run. Replicas greater than one — the invariant most likely to be silently wrong, because N replicas are supposed to be N independent lineages with different seeds, and the only evidence the seed plumbing does anything is that the nodes carry different metrics. Nothing has ever been promoted by the trust ledger. No measurement has superseded a prediction. No structural QC gate exists for any real tool. There is no resume. The headless control model fails open and reports itself as the wrong model.

One campaign has completed. One lineage, one cycle, one draw.

## 16. Asks — *1.5 min*

[1:20] I would rather end on questions than a summary, and these are the six I actually want answers to.

The first four are for the middleware authors. One: a worker exception that cannot be unpickled takes out a whole monitor sweep rather than one task, so a failing run reaches no terminal state and sits in flight until the wall clock. Our half is fixed, but the handler around get_stdout catches only OSError, and I think it wants to catch Exception and fail the single task.

Two: Batch stalled for two full hours and we still do not know why. It is bounded now, so we fail in minutes rather than losing an allocation — which means we can finally iterate. What should we instrument?

Three: can a running task's GPU ever be reclaimed? Four: workflow_id tags every task but nothing looks tasks up by it, so our own handle stays the only answer to what belongs to a run.

Five is for everyone — the one from slide thirteen. Does breadth belong in a pattern's identity?

Six is for the domain people. Every real gate we have is a threshold on a number the tool reports about itself. RFD3 hands us clash counts in a file we already open; for Rosetta, upstream gates on an interaction energy we do not compute. If you were adding one structural gate, where would you start?

## B1. Backup: control plane — *1.2 min*

[0:45] One protocol, nineteen operations, and adapters that translate transport only.

The design decision worth stating is that observe returns the same observation object a policy's decide receives. Informed monitoring means parity of evidence, not a progress bar — whatever a control model is allowed to reason about, a human watching is allowed to see.

Admission is synchronous even over HTTP: you get a 202 with a run id, or a 409 with the gate and the reason. That is not a style choice. Accepting and rejecting later would sever a rejection from the request that caused it, and it cannot work anyway, because the dry-run instantiates task agents and therefore has to run where the toolkit is installed.

The gap is honest and annoying: all of this is reachable from the test suite and not from a shell. There is no serve command and no reason command. One consequence is that model C — the headless, externally-steered mode — fails open: it builds a policy whose inbox nothing can fill, times out every five seconds, and silently runs the model-D rule cascade while reporting itself as model C.

## B2. Backup: control models — *1.4 min*

[0:40] Four control models, exactly one active per campaign, fixed at launch.

A is a four-node LangGraph loop, auditable node by node. B is a single heavyweight structured call over rich campaign state. C is headless — it blocks on the control plane for a directive from outside. D is explicit: rules, a bandit, Bayesian optimization, or replay, and fully reproducible.

They compose rather than inherit. You can wrap any of them in a rule-corrections policy for an unconditional external guard, or a logging policy for provenance, and those are decorators rather than subclasses. Writing a fifth is one method.

The claim everything rests on is that below the policy layer, all four are byte-identical. A campaign run by a hand-written rule cascade exercises exactly the same machinery as one steered by a frontier model, which is what makes comparing them meaningful at all.

And one editorial point, since Flowgentic's authors are in the room: the outer loop is still ours on purpose. It is just two coroutines now rather than one. We looked at ceding it to a framework and it pushes the gates, the dry-run and the interlock into awkward places — and Flowgentic's own README reaches the same conclusion, recommending the augmented rung over the fully agentic one. Worth saying out loud, with credit.

---

## Regenerating this file

The prose lives in `build_deck.js`. After editing a slide's `addNotes`:

```sh
python3 slides/make_script.py        # rewrites DECK_SCRIPT.md from build_deck.js
```
