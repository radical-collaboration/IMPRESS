# Plans

Working notes on what is being built and why. Not shipping reference — `docs/` is that. The split:

| | |
|---|---|
| [`backlog.md`](backlog.md) | **The live list.** Everything outstanding, grouped, with a recommended order |
| `*.md` (this directory) | Stubs for the next tracks — enough to start from, not full plans |
| [`done/`](done/) | Completed work, kept for the decisions it records |

## Why `done/` exists

The task lists in there are worthless now; the **rulings** are not. Several decisions made during
that work are load-bearing and are not obvious from reading the code:

- why an untrusted pattern may have only one instance in flight,
- why stagnation counts *informed attempts* rather than runs,
- why the work directory defaults to the process CWD rather than being configured,
- why admission is synchronous even over HTTP,
- why `replicas: N` is a cap in a campaign spec but a request from a policy.

Each is recorded where it was decided, with the evidence that forced it. When one of these looks
arbitrary later, that is the file to read before changing it.

## Convention

A plan states the **problem and the evidence for it** first, then the approach, then how to verify.
A plan that opens with a task list is missing its reason. Where a plan was overruled or its premise
turned out to be wrong, that is recorded in place rather than edited out — being wrong in a
recoverable way is the useful part of the record.
