# F20 — Retire the manager's adaptive wrappers; move the contract into `PipelineSetup`

**Status:** **closed** — merged with PR 1 (#72, `9a413cd`); all 6 criteria pass. Criterion 5
(the smb mock comparison) was run on 2026-10-21, after the merge, on a machine with rhapsody (see
[Criterion 5](#criterion-5)). See [Result](#result) · **Items:** F20 · **Evidence:** commit `22a1f82` (F19, **passed**
on `23062773` + `23065238`), radical.asyncflow **0.6.0** checkout (`175cf76`,
`v0.5.1-14-g175cf76`), engine probe of 2026-10-21, test baseline 120 passed / 5 skipped
· **Branch:** `framework-defaults-pr1` (verified not an ancestor of `origin/main`)
· **Extends:** [F19](2026-10-15-asyncflow-pattern-rollback.md#f19),
[f19-delta-acceptance](2026-10-20-f19-delta-acceptance.md)

<a id="f20"></a>

## Why

F19 (`22a1f82`) made `adaptive_fn` an engine task the caller declares and stopped the manager
choosing where it runs. It is now confirmed on Dragon (`23062773`, `23065238`), so the design
is settled and what remains is where the contract lives. Two adaptive-specific helpers
survived that cut:

- `_invoke_adaptive_fn` (`src/impress/impress_manager.py:143-152`) — one `await`, whose only
  added behaviour is `workflow_id=f"{pipeline.name}:adaptive"`.
- `_check_adaptive_fns` (`:154-174`) — the gate rejecting an `adaptive_fn` that is not a
  declared task, called from `submit_new_pipelines()` (`:102`).

Three findings say the contract belongs in the model, not in the manager. All are validated
against the **0.6.0** checkout, not the 0.5.1 revision F19 was written against.

**1. The gate has a hole exactly where the contract is tightest.** asyncflow sets its marker
on the *original* function, not on the wrapper — `setattr(func, "__task_description__", ...)`
at `workflow_manager.py:559`, before `@wraps` at `:561`. So once
`adaptive_task = flow.function_task(adaptive_decision)` has run, the **bare**
`adaptive_decision` carries the mark too and `_is_flow_task` (`impress_manager.py:315-321`)
returns True for it. Probed against a real 0.6.0 `WorkflowEngine` on a
`NoopExecutionBackend`:

```
 declared task: marked=True  coroutinefn=False
 bare original: marked=True  coroutinefn=True
```

Passing the bare function into a child config — the exact mistake
`docs/concepts/architecture.md:171-172` warns about — therefore passes the gate and fails at
run time instead: `TypeError: ... unexpected keyword argument 'workflow_id'`, caught at
`impress_manager.py:137`, logged by `logger.adaptive_failed` (`src/impress/utils/logger.py:284-294`),
barrier released at `:141`, pipeline walks on with no decision taken and no child spawned.
`incoming_child_pipeline_request` stays `None`, so `get_child_pipeline_request()`
(`impress_pipeline.py:75-89`) reports nothing. The run completes, looks complete, and is
silently narrower.

This failure mode is invisible to F19's acceptance criteria: `23062773` scored "0 adaptive
failures" on a runner that spawns no children at all
([f19-delta-acceptance](2026-10-20-f19-delta-acceptance.md#result)). The two runners that do
spawn children — `examples/dummy_adaptive.py` and
`examples/discontinuous_scaffolds/run_discontinuous_scaffolds.py` — keep the bare name and the
declared task side by side in module scope, and neither has run on Delta.

**2. The marker is vestigial upstream.** `__task_description__` is written once at
`workflow_manager.py:559` and read **nowhere** in asyncflow's `src/`, `tests/`, `examples/` or
`docs/` (grep, 0.6.0). IMPRESS's only check that a callback is a task keys on an attribute
upstream does not itself depend on, and which could be dropped in any release without
upstream noticing.

**3. Correction to F19: `workflow_id` does not prevent a task-name collision.**
`impress_manager.py:148-150` says `workflow_id` exists because "asyncflow names a function
task after its own `__name__` otherwise, which collides across pipelines sharing one
callback", and the BACKLOG's F19 row repeats it. The first half is right, the consequence is
not. `comp_desc["name"]` is `function.__name__` **unconditionally** (`workflow_manager.py:749`),
whether or not `workflow_id` is passed; `workflow_id` is resolved separately at `:753` and is
only ever a telemetry label. Identity is `comp_desc["uid"]` from a global monotonic counter
(`:750`, `utils.py:3-10`), and the component registry is uid-keyed (`:794`). Concurrent
invocations of one shared callback get distinct uids and distinct futures: **they never
collide functionally, only in the trace.**

The label is still worth keeping, and the acceptance runs are the argument for it rather than
against: 1604 of 1604 (`23062773`) and 2070 of 2070 (`23065238`) adaptive tasks arrived
labelled `p<N>:adaptive`, which is how adaptive share was attributed per pipeline at all
(0.28 % and 0.35 % of wall clock, p50 0.003 s). It is worth *more* than it looks, because the
backend field cannot substitute for it: those same adaptive tasks' TaskCreated/TaskStarted/
TaskCompleted events name `compute` while only TaskQueued/TaskSubmitted name `local` —
asyncflow's lifecycle-event mislabel, F13's first ask, identical on `22927576`
([f19-delta-acceptance](2026-10-20-f19-delta-acceptance.md#result)). The label is the only
reliable way to find an adaptive call in a trace. But it is an observability device, not a
safety one, and should not be documented as the latter.

It is also weaker than it looks in one example: `discontinuous_scaffolds` names its backbone
and sequence children identically to their parent (`run_discontinuous_scaffolds.py:272`,
`:332`), so `{pipeline.name}:adaptive` already collides there. Uniqueness is carried by a
separate `branch_id` (`:138-145`).

### asyncflow 0.6.0 survey (incidental, but it is why this was re-validated)

The checkout is now `0.6.0` (`175cf76`), 14 commits past the `038d52a` F19 cites, including
"Refactor asyncflow task handling into component handling". Every upstream fact F19 and this
plan rest on survives it, with line numbers shifted ~23:

| Fact | 0.5.1 | 0.6.0 | Holds |
|---|---|---|---|
| Marker set on the original function | `:536` | `workflow_manager.py:559` | yes |
| Decorator returns a **sync** `wrapped` | `:539` | `:562` | yes |
| Task name is `function.__name__`, always | `:726` | `:749` | yes |
| `workflow_id` is a label, resolved separately | `:728-731` | `:753` | yes |
| Sync body rejected at **call** time | `:675-680` | `:700-703` | yes |
| Registry keyed on `uid`, not name | `:771` | `:794` | yes |
| `fut.task` set by the engine (used by `utils/stdio.py`) | `:756` | `:791` | yes |
| No `has_backend`/task predicate; `backend` returns only the default | `:141` | `:149` | yes |

Also confirmed, because they gate other items: **none of F13's asks 3, 4 or 5 are fixed in
0.6.0.** `_tel_executable` still prefers `executable` over `name` (`:774-776`, ask 3);
`LocalExecutionBackend` still joins with `" ".join([executable] + arguments)`
(`backends.py:329`, ask 4) and still passes no `env=` to the subprocess (ask 5). So
[F15 part 1](2026-10-15-asyncflow-pattern-rollback.md#f15) and F16 stay blocked. Ask 1, the
lifecycle-event backend mislabel, is likewise unfixed and was observed again on both F19
acceptance runs. `backends.py` gained only `supports_implicit_data_linking` /
`supports_explicit_data_linking` flags.

**Version gap to be aware of:** the checkout is 0.6.0 but the venv still has the
`radical_asyncflow-0.5.0` dist (`.venv/lib/python3.14/site-packages/`). Tests and the F19
acceptance runs exercised 0.5.0. Upgrading is a separate decision and **not** part of this
item; every claim above was checked against both.

## Change

### 1. Move the contract into `PipelineSetup` — `src/impress/pipelines/setup.py`

Add a `field_validator("adaptive_fn")` accepting `None` or a declared task and rejecting
everything else. Move `_is_flow_task` out of `impress_manager.py:315-321` to sit beside it,
and close finding 1 with a second condition:

- a declared task is the engine's **sync** wrapper (`def wrapped`, `workflow_manager.py:562`,
  returning an `asyncio.Future`);
- a bare `async def` is a coroutine function, and `inspect.iscoroutinefunction` does **not**
  follow `__wrapped__`, so it still reports True through `functools.wraps`.

So `marked and not inspect.iscoroutinefunction(fn)` separates the two where `hasattr` alone
cannot. Verified on Python 3.10 and the project's 3.14, and against the real 0.6.0 engine
(probe above). Keep the existing error text (`impress_manager.py:169-174`) — it names the
pipeline and the fix — and add a third case for the bare-but-marked function, which needs its
own wording: declared elsewhere, pass the task object rather than the function.

Fix the two stale descriptions that the validator would then contradict:
`setup.py:25-27` ("sync or async. ImpressManager runs it off the event loop by default") and
`docs/concepts/architecture.md:198-199` ("a plain function or a coroutine function"). Both
predate F19 and already describe something `_check_adaptive_fns` rejects today.

**Behaviour change for the PR body** (BACKLOG Conventions require stating it): validation
moves from submit time to construction time. A bad top-level setup now fails in the runner
before `manager.start()`. A bad child config fails at `PipelineSetup.from_dict()`
(`impress_manager.py:225`) rather than at `submit_new_pipelines()` (`:287`) — same manager-loop
iteration, so the run ends the same way, a few lines earlier.

**No opt-out, as with F19,** and for the same reason: this narrows a gate that exists because
there is no fallback path left. Noted here because the Conventions rule asks for one.

### 2. Delete both helpers — `src/impress/impress_manager.py`

- Drop `_check_adaptive_fns` and its call at `:102`. `submit_new_pipelines` keeps the
  whole-batch guarantee for free: `_normalize_pipeline_setup` already builds every
  `PipelineSetup` in the list comprehension at `:101`, before the construction loop starts, so
  the first bad setup still raises before any pipeline runs.
- Inline `_invoke_adaptive_fn` into `_run_adaptive_fn` as
  `await adaptive_fn(pipeline, workflow_id=f"{pipeline.name}:adaptive")`, moving the
  `workflow_id` note from `:146-150` into `_run_adaptive_fn`'s docstring **and correcting it**
  per finding 3: a grouping label for the trace — the only reliable way to find an adaptive
  call while F13's ask 1 stands — not collision avoidance.
- Drop the `inspect` import if nothing else in the module uses it.

Deliberate asymmetry, for the reviewer: `_invoke_adaptive_fn` is the adaptive twin of
`ImpressBasePipeline._wrap_executable_task` (`src/impress/pipelines/impress_pipeline.py:148-163`),
which does the same labelling job for the 32 tool-stage registrations. That one stays — it
also attaches the failure-reporting callback and uses `setdefault` so a caller can override
the label, whereas the adaptive one hardcodes it and does nothing else.

### 3. Tests

- `tests/conftest.py:32-46` — `MockWorkflowEngine.function_task` returns an **`async def`**
  wrapper, so the stricter validator would reject its own mock tasks. Return a sync wrapper
  that swallows `workflow_id` and returns an awaitable, matching upstream's shape.
  `LocalBackendFlow` (`tests/unit/test_manager_adaptive_logic.py:86-98`) already returns a
  sync `def flow_task` and needs nothing.
- `tests/unit/test_manager_adaptive_logic.py:208-212` — `test_no_adaptive_fn_is_allowed` calls
  `_check_adaptive_fns` directly; move it to a `PipelineSetup` construction test. The two
  rejection tests (`:184-206`) keep their assertions but target construction; keep
  `assert manager.pipeline_tasks == {}` by driving them through `submit_new_pipelines`.
- **Add the regression this item exists for:** a callback decorated into `adaptive_task`, with
  the **bare** original passed as `adaptive_fn`, must raise at construction. This fails on
  `22a1f82`.
- `tests/integration/test_task_defaults_local.py:123` —
  `test_undeclared_adaptive_fn_fails_before_any_work` asserts the submit-time boundary; re-aim
  it at the new one.

### Constraints this leaves on future examples

Unchanged by this item, but now enforced by the model rather than the manager, so
`docs/concepts/architecture.md:164-172` should state them as the standing rule:

- The body is `async def`. Upstream rejects a sync function at **call** time, not decoration
  time (`workflow_manager.py:700-703`), so this is still only caught by a run.
- It is declared on a **thread** pool — it mutates the live pipeline object. Nothing checks
  this; a process pool mutates a pickled copy and the decision silently vanishes.
- An unknown `backend=` name is unvalidated and surfaces as a bare `KeyError` inside the
  engine's run loop at submit.
- Every child config carries the **task object**. With §1 this is finally caught.
- A callback shared by concurrently-adaptive pipelines keeps its module-level caches
  thread-safe and memoised (`architecture.md:174-180`). Five of the six runners share one
  callback object this way.

## Test

Pass criteria, written before the work:

| # | Criterion | Pass |
|---|---|---|
| 1 | Unit + integration suite | ≥ 120 passed, 5 skipped, 0 failed (baseline 2026-10-21) |
| 2 | New regression: bare-but-marked function as `adaptive_fn` | raises `TypeError` naming the pipeline at construction; fails on `22a1f82` |
| 3 | `ruff check src tests` and `ruff format --check src tests` | clean |
| 4 | `examples/dummy_adaptive.py` | runs to a third generation, exercising `submit_child_pipeline_request` → `from_dict` → the new validator |
| 5 | smb mock run (`run_test_small_molecule_binding.py`) vs a worktree at the branch head | byte-identical event sequence (F19 recorded 496 events, 124 adaptive calls, 0 failures) |
| 6 | No example source changes | `git diff --stat examples/` touches no `.py` |

**No Delta run of its own, and none to fold into.** F19's acceptance is complete
(`23062773` + `23065238`), so unlike the earlier draft of this plan there is no pending run to
attach to. The justification for skipping one: F20 deletes a wrapper and relocates a check,
changing no code path a Delta run exercises — criterion 5 is the evidence for that, and
criterion 2 covers the one behaviour that does change. The failure it prevents is in the
child-spawning runners, which have never been part of a Delta acceptance anyway.

If a Delta run happens for another reason before PR 1 merges, check that adaptive tasks are
still 100 % labelled `p<N>:adaptive` and that adaptive share stays within the restated
**≤ 0.5 %** bar (`23062773` 0.28 %, `23065238` 0.35 %;
[decision](2026-10-20-f19-delta-acceptance.md#rerun)).

<a id="result"></a>

## Result (2026-10-21, implementation)

| # | Criterion | Measured | Verdict |
|---|---|---|---|
| 1 | Suite ≥ 120 passed / 5 skipped / 0 failed | **123 passed, 5 skipped, 0 failed** (+3: two new regressions, one split) | pass |
| 2 | Bare-but-marked rejected at construction; fails before the change | raises `TypeError` naming the pipeline. Both new tests run against a worktree at `6aadc2e` give **`Failed: DID NOT RAISE TypeError`** | pass |
| 3 | `ruff check` / `ruff format --check` clean | clean (ruff auto-fixed 3 × F541, redundant `f` prefixes, in the new validator) | pass |
| 4 | `dummy_adaptive.py` reaches a third generation | ran to **`p2_g2_g2`**, child configs through `from_dict` → the new validator, clean exit | pass |
| 5 | smb mock event sequence byte-identical | **not run at implementation; run 2026-10-21, pass** ([below](#criterion-5)) — `run_test_small_molecule_binding.py` imports `run_small_molecule_binding`, which imports `rhapsody`; `ModuleNotFoundError` in both trees. Same absence skips the 5 tests above | **blocked** |
| 6 | No example source changes | `git diff --stat examples/` empty | pass |

**Criterion 5 is the one gap, and it is an environment limit, not a result.** The mock run is
what F19 used to show the refactor changed no observable behaviour, so it should be run on a
machine with rhapsody before this merges. What covers the same ground meanwhile: criterion 4
exercises the full adaptive protocol including child spawning, and
`tests/integration/test_task_defaults_local.py` exercises the real engine on a declared
backend — including the new real-engine regression, which asserts upstream's marking
behaviour directly so it fails loudly if a future asyncflow stops marking the original.

**Scope note.** Three tests in `tests/unit/test_pipeline_setup.py` (`test_all_fields`,
`test_known_fields_separated`, `test_adaptive_fn_included_when_set`) used a bare
`async def fn(p)` as a stand-in `adaptive_fn` while testing dict round-tripping. They are not
about the adaptive contract, so they now take a declared task from a `_declared_task(mock_flow)`
helper rather than being exempted from it. This was not in the plan; it is the blast radius of
moving validation into the model, and the right correction — a stand-in that the model rejects
is not a valid stand-in.

<a id="criterion-5"></a>
**Criterion 5, run 2026-10-21.** The smb mock was run with `ve/small_mol`, which has rhapsody, on
merge `0cefeb2` (`main` with F20, merged into `smb-benchmark-f19`), and compared with the
pre-merge head `fd01231`. The comparison covered all three runner modes: adaptive,
`--nonadaptive`, and `--nonadaptive --selection first`.

| Mode | Stages | Decisions | Selection lines | Errors |
|---|---|---|---|---|
| adaptive | 124, identical | 136, identical | identical | 0 |
| `--nonadaptive` | 180, identical | 180, identical | identical | 0 |
| `--nonadaptive --selection first` | 180, identical | 180, identical | identical (60 `mode=first`) | 0 |

- **"Identical" excludes one thing.** The guided-backbone path printed in two adaptive `fold`
  lines contains the scratch run directory, so it differs between any two runs; that path is
  normalised before comparing.
- **Adaptive also matches PR 1's head.** The adaptive run is identical to a mock of PR 1's head
  `4011f0d` as well.
- **No `TypeError` from the new validator.** Both runners pass the declared wrapper,
  `flow.function_task(...)(policy)`.
- **The suite has no skips here.** With rhapsody present it is 128 passed / 0 skipped: the
  123 + 5 above, with the 5 now running.

**Not done, deliberately:** the sixth F13 ask (a public "is this a task of mine?" predicate).
It is listed below and belongs with the other upstream asks, not in this change.

## What this gives up

- **The label convention loses its single home** — one line plus a docstring in
  `_run_adaptive_fn`. Acceptable given finding 3, and given the labels already collide in
  `discontinuous_scaffolds`.
- **It still rests on a vestigial upstream attribute** (finding 2). The coroutine-function
  condition is independent of the marker, but the marker check is not. **Add a sixth ask to
  [F13](2026-10-08-framework-deferred.md):** a public predicate for "is this a task of mine?",
  alongside the existing `has_backend` ask.
- **Two of the five constraints above stay unenforceable** (thread pool, `async def` body)
  with or without this change.
