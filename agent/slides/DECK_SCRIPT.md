# IMPRESS-A code walk — speaking script

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
| 1. Title | 1.1 min | | 13. The seam: the engine | 1.5 |
| 2. What it does | 1.3 | | 14. What the loop costs | 1.5 |
| 3. The baseline | 1.9 | | 15. Seven jobs (F3) | 1.5 |
| 4. Three dimensions | 0.9 | | 16. Scale and yield | 1.6 |
| 5. The constraint | 1.3 | | 17. Four defects | 1.3 |
| 6. ACT 1 - Functionality | 0.5 | | 18. The trust ledger | 1.5 |
| 7. The loop (F1) | 1.2 | | 19. ACT 3 - Usability | 0.5 |
| 8. Architecture (F2) | 0.7 | | 20. Running it | 0.9 |
| 9. Admission | 1.4 | | 21. The control plane | 1.6 |
| 10. Tools are data | 1.9 | | 22. Status | 1.5 |
| 11. ACT 2 - Performance | 0.5 | | 23. Asks | 1.9 |
| 12. The seam: dispatch | 1.4 | | | |

**Main path: 4531 words = 29.2 minutes of speech.** Backups add 4.3 min if used.

| Act | The question it answers | Slides | What it concedes |
|---|---|---|---|
| **Functionality** | what can you ask for that an adaptive pipeline cannot be asked? | 6-10 | every graph composed so far is the six-stage shape the reference pipeline already had |
| **Performance** | what does composing, validating and scoring a graph cost? | 11-18 | no serial baseline, no head-to-head, one lineage per GPU and three GPUs idle |
| **Usability** | what is it usable as - application, platform, component? | 19-21 | nothing else has ever driven it: no resume, and no serve/reason command |

| Order | What's in | Speech | Fits |
|---|---|---|---|
| **A · full** | every main slide | **29.2** | a 35-minute slot, or a working session where questions land inline |
| **B · default** | drop 17, 18, 20 | **25.5** | a 30-minute slot: drops the defect ledger, the trust-ledger findings and how-to-run-it, each recoverable in a sentence |
| **C · hard twenty** | drop 8, 9, 13, 15, 17, 18, 20 | **20.3** | a hard 20 that leaves real room for discussion - the baseline, the three dividers, the dispatch seam, both measured performance slides, status and asks |

**Protect 3, 4, 14, 16, 22 and 23.** Three and four are what make this a comparison rather than a tour; 14 and 16 are the only measured performance claims in the deck; 22 is status and 23 is the asks. Never cut a divider: a cut deck without them is a list of slides. Backups B1 (typed hops) and B2 (compute patterns) are already out of every order - do not put them back to fill time.

**Say these out loud even if nothing prompts them:** that every run so far is a single lineage and `replicas > 1` has never executed; that on the two Rosetta stages we share, our thresholds are **weaker** than the reference pipeline's PROD gates (backlog G4/G5), so the claim is about where the verdict lives and not about strictness; and that every Delta and baseline figure on these slides is transcribed from run archives outside this checkout, named in each slide's footer.

---

## 1. Title — *1.1 min*

[1:00] A code walk, not a results talk. IMPRESS-A runs protein design campaigns on HPC: you give it a goal and a budget, and it decides what experiment to run next, composes a workflow out of a tool registry, runs it through asyncflow and rhapsody, and updates a population of candidates.

The word doing the work is composes — there is no fixed pipeline anywhere in this repository, and most of the code I will show you exists because of that one fact. But "no fixed pipeline" is only interesting against something, and the something is in this room: the reference IMPRESS pipeline, which is adaptive, which works, and which has run at a scale we have not. The comparison all the way through is against a pipeline that is written down, not against no framework.

Three acts: what you can ask for, what it costs, and what it is usable as. I will name the weakest of the three in the next three minutes.

## 2. What it does — *1.3 min*

[1:10] The shape of a campaign, and then what one actually produced.

A goal, a reasoner that decides, a composer that turns that into a typed DAG, admission, execution, absorption. Two edges make it a loop rather than a pipeline — a rejected graph comes back with a structured reason and another attempt, and every decision after the first sees every result so far.

Left card, all measured: six stages end to end in under three minutes, all four objectives with real values, admitted on the first attempt, cost measured per stage.

Right card, because you would ask and I would rather say it first. Every run we have ever done is a single lineage on one of four GPUs — their comparable runs carry sixteen to two hundred and fifty-six pipelines, so nothing in this deck is a throughput comparison. This node is suspect rather than pass because its pattern was provisional — the interlock working, not a failure. And no measurement has ever superseded a prediction, which is the one capability a composed graph has that a written-down one does not.

Read it as a floor. What it proves is that the plumbing survives contact with real tools.

## 3. The baseline — *1.9 min*

[1:35] What this is compared against. Not a blank page.

The reference IMPRESS pipeline does adaptive protein design at a scale we have not touched — twenty-four thousand task directories, nine hundred passing folds, no task failures on the clean runs. It also solved the thing we have not: eight pipelines per GPU takes utilisation from twelve percent to seventy and cuts cost per fold threefold. And its orchestration is not the overhead, at under two percent of the manager's wall clock.

So the question is not whether an adaptive pipeline works. It does. The question is what it costs to change one — the middle band, mined from their checkout rather than quoted. The shape of the graph is nineteen assignments to next_step inside one decision function; the thresholds are a dataclass in the runner; the QC verdict is computed inside the coroutine that parses the output; the hook is a plain closure with full object access and no schema. One use case is fourteen hundred lines plus a runner — and the non-adaptive version of the same science is a hundred-line routing table, which is what a declarative rewrite actually looks like.

The bottom cards are why I think composition is worth the trouble, and they are their numbers. Their guided feedback, against its own parent fold, is flat — plus nought point nought one one pLDDT, p of nought point eight five. A cheap re-sampler, not a ratchet — and still worth having at four times cheaper per fold. And eight hundred passing folds are five hundred and ninety-six clusters: width buys independent searches, depth refines one.

The last line is owed rather than implied — that pipeline paid for lessons we inherited for free, including the storage fix in act two.

## 4. Three dimensions — *0.9 min*

[0:50] Three dimensions, because this audience arrives with three questions and each takes a different kind of evidence. The deck is three acts in that order: what you can ask for, what it costs in hardware and in yield, and what it is usable as.

I would rather name the weak one now than have it extracted at minute twenty-five. It is the middle column, and specifically performance at scale. Every performance number here comes from one lineage on one GPU — sixteen complete runs, all serial. Replicas greater than one has never executed, so the invariant that N lineages give N independent results is the piece most likely to be silently wrong.

And there is no head-to-head. I have their numbers and ours, on different hardware at different scales, and I will not divide one by the other.

## 5. The constraint — *1.3 min*

[1:05] If you keep one slide, keep this one. Everything after it is a consequence rather than a preference.

Two facts. A machine composes workflows no human has reviewed. And the tools those workflows call fail silently far more often than they crash — a generator hands back a structure with no secondary structure, a confident designability number, and exit code zero.

Five things fall out, each with the file that implements it. A policy emits abstract intent, not a DAG. Everything is validated before it executes. Trust is scored on shape and has to be earned. Exit code is never evidence. And exactly one component writes state and decides when to stop.

The flip side at the bottom is the hinge of the talk. If a person reviewed every graph before it ran, you would write the DAG down once and schedule it, and most of this would stop paying for itself. That is not a strawman — it is the right answer under review, and next door it is fourteen hundred lines of pipeline class per use case that works. Act one is what you get for not writing it down; act two is what that costs.

# Act 1 — Functionality

## 6. ACT 1 - Functionality — *0.5 min*

[0:20] Act one: functionality. Not features — tasks. What can you ask this thing that you cannot ask an adaptive pipeline?

A goal rather than a pipeline. A tool that is a spec file, with its gates part of the spec. A control model you can swap without the layer below knowing.

The weakest claim in red, before the act rather than after it: every graph we have composed is the six-stage chain the reference pipeline already ran.

## 7. The loop (F1) — *1.2 min*

[1:10] Two coroutines meeting at a session, and the asymmetry between them is the point.

Left, a reasoner: observe, decide, submit, wait. Two ways to be one — implement decide and let a driver play the loop, which is what models A through D do, or implement conduct and drive yourself, collecting experiments in the order they finish. The second is what makes a federation of agents generating an ensemble in parallel expressible at all.

Right, the executor: admit, dispatch, reap, absorb, and the only writer of campaign state. Note what it is not: not the loop body with a policy called inside it. The reasoner is a peer.

The red arrow is the one people miss. A rejected submission does not burn the experiment — the policy gets a structured reason and another attempt, bounded twice, because a conduct reasoner is under no obligation to honour anything the driver promises.

Two rules hold it together: one writer, with every mutating block await-free so an observation is never taken mid-absorb; and the executor decides termination, because budget and stagnation are facts a reasoner cannot see.

## 8. Architecture (F2) — *0.7 min*

[0:55] Eight layers, and the thing worth looking at is in red: four arrows that do not exist. A policy may not import tools, exec or runtime; compose may not import exec. I draw them because an edge that is merely absent reads as an oversight, and this room will ask whether the rule is enforced or intended.

It is enforced. A test walks the package with ast and checks every internal import against one table — ast.walk rather than module-level imports, because the real adapters defer their science imports into run bodies on purpose, and a deferred cross-layer import is exactly as fatal as one at the top. Writing that test found two edges nobody had documented.

## 9. Admission — *1.4 min*

[1:15] This is the answer to "you let a machine invent workflows?"

Five gates, first refusal wins. Gate two rejects a tool composed without its QC gates, so you cannot compose your way out of quality control. Gate four rejects a P6 tool somebody tried to schedule.

Then three things that are not gates: the interlock; a dry-run where every agent parameterizes without executing, which catches a graph that type-checks but cannot be turned into a command line; and a reservation. Reserve is last because the dry-run awaits, and by then another submission may have claimed the budget gate five saw.

The trust half on the right is the part a written-down pipeline has no need for. A pattern is the graph's shape, hashed, with parameter values deliberately excluded so tuning a parameter does not reset trust. A provisional shape is capped, forced through a dry-run, marked suspect whatever it scores, and may have only one instance in flight — promotion counts consecutive clean runs, and N concurrent copies are one draw sampled N times. Clean means no integrity gate failed; a design that merely scores badly fails its node but is not evidence against the shape. Counting it was why our five-cycle trust run promoted nothing.

And the limit, from our own limitations doc: this buys examination and delay, not soundness.

## 10. Tools are data — *1.9 min*

[1:25] Adding a tool is a YAML file plus a subclass, never a change to the composer, validator or manager. If you have to touch those, the layering is wrong.

The spec declares typed ports, a compute pattern, resources, the metrics it reports, mandatory gates resolved by id from a shared library, and a cost model that feeds gate five. Loading is validating: an unknown gate id or a missing skill section is a load-time error, and a toolkit that fails anywhere registers nothing rather than a partial set.

The table at the bottom left is the comparison I think is defensible, and it is not about strictness. Here the verdict is declared in the tool's spec, resolved out of a shared gate library, mandatory for every scheduled tool, and a failed node can never reach the front whatever it scored. There it is computed inside the same coroutine that parses the output and read back out of pipeline state as a boolean called pass. Neither is unsafe — one can be left out by whoever writes the next stage, the other cannot.

Then the third row, which I want to say before anyone looks it up. On the two Rosetta stages we share, their thresholds are stricter than ours: total score under minus two-fifty, repulsion under a hundred, and an interaction energy we do not compute at all. So the claim is about where the verdict lives and whether it is optional — not about us being more careful. We are not, yet.

On the right, the tool that lies: it succeeds, reports designability of nought point nine one, and emits a structure with two percent secondary structure. One test asserts all three at once. The real toolkits have no equivalent, and that is ask six.

# Act 2 — Performance

## 11. ACT 2 - Performance — *0.5 min*

[0:20] Act two: performance — both kinds, because hardware cost and scientific yield are not linear in each other.

The loop is not the cost. The failures that eat allocations are bounded in code, both ends of the backend lifecycle. And the headroom is not orchestration: tasks fill ninety-five percent of elapsed, so what is idle is three of four GPUs.

In red: no serial baseline and no head-to-head. Nothing in this act divides into a speedup.

## 12. The seam: dispatch — *1.4 min*

[1:15] The slide I would defend hardest, and it is four lines of real code.

A task graph is plain data. To run it, one generic factory builds a closure per node, sets its dunder-name to the node id, and hands it to asyncflow's function_task decorator. That is the whole adapter — no codegen, no templating. And setting dunder-name first is not a trick: the decorators take no name keyword, so this is exactly what lets one factory serve every node of every graph. The closure binds workdir to a local rather than reaching through self, because it gets pickled to a process pool and self would drag the dispatcher along with it.

Second block, submission. Walk the graph topologically, pass each dependency's unawaited future as an argument — that is how you express an edge — build a gather with return_exceptions, and return without awaiting. That one change is what let the reasoner stop being the loop body. Two idioms, not interchangeable: unawaited futures are edges, gather is independent work.

Right-hand side, measured rather than assumed. Cancellation is advisory: cancel returns False once a callable has started, asyncflow throws that answer away, so queued work is reclaimed, running work is not, and nobody tells you which happened. A run's terminal state always comes from collecting it.

## 13. The seam: the engine — *1.5 min*

[1:20] The second half of the seam is construction, and this is where the expensive lessons are.

Three things in make_engine_bounded are load-bearing. Only the synchronous construction goes to a dedicated daemon thread, not the default executor, because a stuck call on a pooled thread would hang interpreter shutdown too. The backend's async init and the engine are built back on the caller's own loop. And that await is not politeness: rhapsody's backends are awaitable, and awaiting is what registers the task states. Construct one synchronously and it appears to work, then fails much later with "backend not registered, available backends: empty list".

The right column is what each lesson cost. Two full allocations went to an engine built on a throwaway loop — asyncflow captures the running loop in its constructor and puts its dispatch task on it, so an engine built on a closed loop looks fine and dispatches nothing. One two-hour allocation went entirely to Dragon's Batch constructor, which blocks the loop, so our own heartbeat never fired once.

And the most expensive item is teardown, not startup: on the reference pipeline, shutdown never returned after the science had finished, and the job sat an hour before someone cancelled it — sixty-four GPU-hours, thirty-seven percent of that job's bill. Both ends are bounded now, and a stuck teardown is abandoned with a warning rather than raised: results are already durable, and raising would report a campaign that succeeded as failed.

## 14. What the loop costs — *1.5 min*

[1:30] The measured half of the act, and the figure is deliberately about one variable.

Two bars: the median untrusted run and the median trusted run, split into time inside a task and time anywhere else. Everything else means dispatch, absorb, QC, the Pareto update, provenance and the durable ledger — all of it a median of two point eight seconds out of a hundred and sixty. And the comparison is the point: running untrusted, which means a forced dry-run, a cost cap and a suspect verdict whatever it scores, costs zero point zero seconds, interval minus nought point nine to plus one point two. The scrutiny is free, and that is measured rather than argued.

Underneath, the cost models: nought point one seven GPU-hours declared per chain against nought point oh two nine measured. Every declared figure is at least two and a quarter times the worst task observed, because gate five and the untrusted cap refuse graphs against those numbers. Headroom is not inefficiency.

The red card is written as refusals, not apologies. No serial baseline, so nothing here is a speedup. GPU utilisation is recorded nowhere, so seventeen percent is an upper bound with model load inside it.

And the band is the conclusion: the loop costs about two percent and the hardware is eighty-three percent idle. The next real gain is not in this orchestrator — it is giving the other three GPUs work, which is ask seven.

## 15. Seven jobs (F3) — *1.5 min*

[1:25] Seven jobs, and the figure at the top is really about one variable.

Top row, the HDD baseline: diffusion 137 seconds, sequence design 293, and then packmin could not finish importing PyRosetta inside its three-hundred-second budget, so nothing downstream ran. Middle row, the same campaign with one thing changed — the virtual environment moved to NVMe. Sequence design went from 293 seconds to 18, packmin from not finishing to sixteen.

The reason is on the right. Importing PyRosetta off that filesystem costs 471 seconds, a 598-megabyte shared object demand-paged; torch is another 280. On NVMe both are seconds. That was the single largest cost this project was paying, it was invisible because it looked like a tool timing out — and we did not find it. The fix is ported from their PR sixty-seven.

Bottom right, the caveat for anyone reading our cost models: diffusion took 146 seconds in one job and 45 in the next, same campaign, same parameters. Those numbers feed gates that refuse graphs, so they sit deliberately above measurement.

The table underneath is three later jobs that changed nothing about the science and asked one question — does the shape earn trust. The first ran thirty tasks out of thirty cleanly and promoted nothing, because we were counting design quality as evidence about the workflow. With only integrity gates counting, the same chain promoted after its second run in both later jobs.

## 16. Scale and yield — *1.6 min*

[1:30] The slide worth the most in this act, and almost none of it is our data.

Top left: their search improves and then stops. Median pLDDT by episode tercile goes ninety point seven, ninety-five point two, ninety-five point oh — plus four and a half, then minus nought point two. Depth buys you something and then it buys you nothing, and they have the sample size to say so where we do not.

Bottom left is the pair worth staring at. Their eight hundred and four passing folds are five hundred and ninety-six clusters — seventy-four percent independent. Our seventeen designs cluster into five structural groups: twenty-nine percent. We are the worse number. Both analyses overcount their own yield, and both point at the same lever: width, not depth.

Right side is what this project does about it, and the dotted borders are doing the work. Replicas-N means N independent lineages, one node each, and the executor never funnels them back into one candidate. The front is deliberately not monotonic, so a node promoted on an optimistic prediction gets demoted by its own assay. Trust is scored on shape, so breadth has an identity of its own.

All of it dotted — written, typed, unit-tested, never executed. And the cheap route is closed: the signature includes replica multiplicity, so trust earned at one lineage does not transfer to four. A four-lineage graph arrives untrusted, under a cap it already exceeds. That is ask five.

## 17. Four defects — *1.3 min*

[1:15] Four defects reached real hardware, each invisible to a dry run. The pattern across them is more useful than any one.

The first two as a pair: one picked the wrong file of the right extension, the other died in its module-level imports before parsing a single argument we passed it. No contract check we had could see either. Then the storage story from the last slide — where the queued fix was to raise three walltimes six-fold, which would have hidden a 471-second import behind a timeout.

And the subtle one: an estimate that refuses work. Our cost models were literature guesses six to sixty-nine times over reality, and gate five and the interlock cap refuse graphs against those numbers. The inflated GPU side summed past the cap, so the policy truncated the last stage off the chain — which happened to be the only producer of two of the four campaign objectives. The run was unwinnable from the moment it was admitted, and nothing said so.

Two things to carry away. Checked against the binary is not executed. And a plausible explanation is not a diagnosis — the trajectory bug was a convincing cause for a failure it had nothing to do with.

## 18. The trust ledger — *1.5 min*

[1:25] Two findings about the trust ledger, and the second is open.

The first: the ledger path was relative to the campaign root, and the Delta launcher changes into a per-job directory, so it resolved inside each job and started empty every time — while promotion counts three consecutive clean runs within one file.

What is worth your time is how it hid. Nothing logged where the ledger was, so a file that silently reset looked exactly like one that had not earned promotion yet, and I reported it that way. It had been true since the first Delta job, which is why the trusted path did not execute until 22726105. The fix did more than stop the reset: the ledger is site-wide now, so evidence accumulates across jobs — which is why promotion came a run early and the job after it ran three trusted cycles clean.

The second I hit while generating these numbers, and I have not changed the code. The signature emits one string per node, so N lineages give N duplicate parts and the hash moves with the replica count — though it deliberately does not move when you tune a parameter. The cost is concrete: the cheap route to four lineages was to promote at one and then widen. It does not work. Four is a different, untrusted pattern, still capped, still refused, and the policy would quietly shrink it to three.

# Act 3 — Usability

## 19. ACT 3 - Usability — *0.5 min*

[0:20] Act three: usability — the short act, which is information rather than a problem.

As an application, yes. As a platform, yes, and the seam is not the command line. As a component in someone else's workflow: no evidence, because nothing else has ever driven it.

And in red — because serve and reason do not exist, asking for the headless control model silently gives you the explicit one and reports it as headless.

## 20. Running it — *0.9 min*

[0:45] Act three, and the easy claim first: as an application this is one YAML and one command.

The command worth pointing at is preflight — it checks the container path, the checkpoints, the Boltz cache, whether PyRosetta imports, and whether the virtual environment is still on slow storage, all on a login node before you spend a queue slot.

The split that matters is that the entire local tier runs on a laptop in about fifteen seconds with no allocation: a complete campaign with a real manager, real policies, a real composer and validator, stubbed science. The corollary is the uncomfortable half — everything only verifiable on HPC is unverified.

One convention worth stealing: a magic number in a test is often a bug report. A stagnation limit of ten thousand appeared in three tests before anyone noticed the defect was in the engine.

## 21. The control plane — *1.6 min*

[1:15] And as a platform — the more interesting claim, because the seam someone else plugs into is not the command line.

One protocol, nineteen operations, adapters that translate transport only. The decision worth stating is that observe returns the same observation object a policy's decide receives: informed monitoring means parity of evidence, not a progress bar.

Admission is synchronous even over HTTP — a 202 with a run id, or a 409 with the gate and the reason. That is not a style choice. Accepting and rejecting later would sever a rejection from the request that caused it, and it cannot work anyway, because the dry-run instantiates task agents and has to run where the toolkit is installed.

The gap is honest and annoying: all of this is reachable from the test suite and not from a shell. There is no serve command and no reason command, so model C fails open — it builds a policy whose inbox nothing can fill, times out every five seconds, and runs the model-D cascade while reporting itself as model C.

Which is also the answer to the third use case. As a component in someone else's workflow there is no evidence at all: nothing external has ever driven a campaign outside tests, there is no resume, and the site files are read by no code. One of your pipelines running as a tool of ours would be the obvious proof, and that is the P7 row with no member.

## 22. Status — *1.5 min*

[1:30] I will not compress this slide, because an audience that catches you overclaiming stops believing everything else. Three columns, three green rows and three red rows each, and the equal lengths are the argument.

Functionality: a real six-stage campaign end to end, the whole engine, four control models over one executor, and adding a tool has never touched the composer. Against that — replicas greater than one has never run; no measurement has superseded a prediction, which is exactly the capability a composed graph has and a written-down one does not; and six of the eight compute patterns have no member, including the one reserved for running their pipeline as one of ours.

Performance: the trusted path promoted after the second run and held three cycles with no safety net; the scrutiny is measured and free; both ends of the Dragon lifecycle bounded against real lost allocations. Against that — no serial baseline; one GPU of four ever works; and no node has reached a plain pass, which wants more draws rather than more code.

Usability: one YAML and one command, the local tier with no allocation, runtime-discovered toolkits, a reasoner in another process. Against that — no resume, no serve or reason command so the headless model lies about which model it is, and the site files are read by nothing.

Sixteen complete runs, the trusted path held, and every one of them one lineage on a system built for width.

## 23. Asks — *1.9 min*

[1:35] I would rather end on questions than a summary, and they are grouped by what each one costs rather than by who owns it.

Left column, things that produce a wrong answer or burn an allocation. One: a worker exception that cannot be unpickled takes out a whole monitor sweep rather than one task, so a failing run reaches no terminal state and sits in flight until the wall clock. Our half is fixed; the handler around get_stdout catches only OSError, and I think it wants to catch Exception and fail the single task.

Two and three are shorter. Batch stalled for two hours and we still do not know why; it is bounded now, so we fail in minutes instead of losing an allocation — what should we instrument? And can a running task's GPU ever be reclaimed at all?

Seven is the new one, and it comes out of your numbers. You take GPU utilisation from twelve percent to seventy by packing eight pipelines onto a GPU; we are at seventeen with three idle. Is that expressible in a rhapsody resource shape, or does it need Dragon placement we do not control? It is the largest performance number on our table and I do not know whether it is reachable from where we sit.

Right column, things paid by whoever picks this stack up next. Workflow_id tags every task but nothing looks tasks up by it. Does breadth belong in a pattern's identity? And for the domain people: every real gate we have is a threshold on a number the tool reports about itself, while you gate on clash counts and an interaction energy we never compute. If you were adding one structural gate, where would you start?

## B1. Backup: one experiment, typed — *1.2 min*

[1:00] One experiment, left to right, naming the type at each hop — the types are the contract between layers.

The executor builds an observation. The policy returns a decision carrying an experiment intent: tool ids, parameters, a replica count. It is abstract, there is no DAG in it. The composer turns it into a typed graph, which is plain data. Dispatch registers that graph and hands back a handle without awaiting. What comes back is a run outcome, serializable and core-typed, so a reasoner in another process can hold it.

Underneath is an actual run on this laptop. The first row was refused by the interlock — a provisional pattern is capped at ten percent of available budget and three lineages did not fit. The policy shrank to two and resubmitted. That is the retry doing its job: a refusal costs an attempt, not the experiment.

Every design node is marked suspect, because the shape is provisional while it runs. Promotion takes three clean runs, and the card on the right says whether this one got there before the front target stopped it.

## B2. Backup: compute patterns — *1.7 min*

[1:15] One field in that spec decides how the work reaches the middleware, and it is the compute pattern.

Eight of them, and what matters is what they are organised by: not what the tool computes, but what the orchestrator has to do differently. A tool is P4 because of where it must be submitted, not because it runs MD. P6 is the sharpest — an in-process call of thirty milliseconds. Schedule that and you pay serialization and filesystem cost orders of magnitude above the work. So the composer drops P6 stages before they ever become nodes, and gate four refuses one that got through anyway. A scheduled P6 is a composer bug, and it is caught as one.

Two honest things. The last column is the census: all eleven tools are P1 or P2. P3 through P8 have no member, so the inline path, the P4 ledger and the P5 service path are contracts the suite asserts and nothing has ever taken.

P7 deserves singling out in this room, because it is the pattern reserved for running one of their pipelines as a single tool of ours — parameterize it, observe it, never steer inside it. It has no member. So if you have heard me say IMPRESS becomes one of our tools, that is a contract and a taxonomy entry, not something that has happened.

And the enum's own docstring says dispatch depends on these. It does not, yet — every consequence is enforced at load time or at a gate, which is composition time, not dispatch. That is the cheaper place for it, but the docstring is ahead of the code.

## B3. Backup: control models — *1.4 min*

[0:40] Four control models, exactly one active per campaign, fixed at launch.

A is a four-node LangGraph loop, auditable node by node. B is a single heavyweight structured call over rich campaign state. C is headless — it blocks on the control plane for a directive from outside. D is explicit: rules, a bandit, Bayesian optimization, or replay, and fully reproducible.

They compose rather than inherit. You can wrap any of them in a rule-corrections policy for an unconditional external guard, or a logging policy for provenance, and those are decorators rather than subclasses. Writing a fifth is one method.

The claim everything rests on is that below the policy layer, all four are byte-identical. A campaign run by a hand-written rule cascade exercises exactly the same machinery as one steered by a frontier model, which is what makes comparing them meaningful at all.

And one editorial point, since Flowgentic's authors are in the room: the outer loop is still ours on purpose. It is just two coroutines now rather than one. We looked at ceding it to a framework and it pushes the gates, the dry-run and the interlock into awkward places — and Flowgentic's own README reaches the same conclusion, recommending the augmented rung over the fully agentic one. Worth saying out loud, with credit.

---

## Regenerating this file

The prose lives in `build_deck.js`. After editing a slide's `addNotes`:

```sh
python3 make_script.py --deck slides/build_deck.js
```
