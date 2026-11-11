"""The simulated science behind the Colab quickstart. Standard library only.

This module is deliberately free of every IMPRESS and asyncflow import, for two
reasons. `score_stage.py` runs as a subprocess once per task, so anything it
imports is paid for on every task; and the arithmetic below is the part worth
unit-testing, which it can be here without an engine, a backend or an event
loop.

Nothing here models any chemistry. Scores are seeded pseudo-random draws shaped
to look like pLDDT so the adaptive rule has something plausible to react to.
What the notebook measures is the *framework's* behaviour -- when it spawns a
child pipeline and what that does to the run -- not a property of a protein.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

# Drift applied per pass, in score points. Negative means the target is getting
# worse, which is what the adaptive rule hunts for.
FRAGILE_DRIFT = -6.0
STURDY_DRIFT = 1.5
# A migrated target is being worked on in a child pipeline, so it declines more
# slowly -- but it does not recover. That is the point: a child buys time, it
# does not fix the target, and a reader who lowers the threshold sees the run
# spawn again rather than converge.
MIGRATED_DRIFT = -1.0

SCORE_FLOOR = 0.0
SCORE_CEILING = 100.0


@dataclass(frozen=True)
class ToyConfig:
    """Everything the notebook's form cells can set.

    Every field has a default, so `ToyConfig()` is a valid run. `__post_init__`
    rejects the combinations that would hang or produce nothing to look at.
    """

    n_targets: int = 6
    n_passes: int = 3
    degradation_threshold: float = 4.0
    min_degraded_to_spawn: int = 2
    # The ONLY thing that stops child pipelines recursing forever. The framework
    # has no generation concept and enforces no cap: `ImpressManager.start()`
    # returns when no pipeline is left, so a rule that always spawns never
    # returns. See `adaptive_decision` in impress_toy.py.
    max_generations: int = 2
    fragile_fraction: float = 0.5
    noise_sd: float = 1.5
    seed: int = 7
    # Bounds the thread pool, which runs function tasks and the adaptive
    # callback. It does NOT bound the executable tasks: those are subprocesses
    # started on the event loop, not in the pool.
    max_workers: int = 4
    task_duration_s: float = 0.2
    time_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.n_targets < 1:
            raise ValueError(f"n_targets must be >= 1, got {self.n_targets}")
        if self.n_passes < 1:
            raise ValueError(f"n_passes must be >= 1, got {self.n_passes}")
        if self.max_generations < 0:
            raise ValueError(
                f"max_generations must be >= 0, got {self.max_generations}"
            )
        if self.min_degraded_to_spawn < 1:
            raise ValueError(
                "min_degraded_to_spawn must be >= 1, got "
                f"{self.min_degraded_to_spawn}"
            )
        if not 0.0 <= self.fragile_fraction <= 1.0:
            raise ValueError(
                f"fragile_fraction must be in [0, 1], got {self.fragile_fraction}"
            )
        if self.noise_sd < 0.0:
            raise ValueError(f"noise_sd must be >= 0, got {self.noise_sd}")
        if self.degradation_threshold < 0.0:
            raise ValueError(
                "degradation_threshold must be >= 0, got "
                f"{self.degradation_threshold}"
            )
        if self.max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {self.max_workers}")
        if self.task_duration_s < 0.0:
            raise ValueError(
                f"task_duration_s must be >= 0, got {self.task_duration_s}"
            )
        if self.time_scale <= 0.0:
            raise ValueError(f"time_scale must be > 0, got {self.time_scale}")

    @property
    def sleep_s(self) -> float:
        """What one simulated task should actually sleep for."""
        return self.task_duration_s * self.time_scale


@dataclass(frozen=True)
class Verdict:
    """One target's reading at the end of a pass, and what it implies."""

    target: str
    current: float
    previous: float
    degraded: bool

    @property
    def drop(self) -> float:
        return self.previous - self.current


def _digest(*parts: object) -> int:
    """A stable integer from the parts, via sha256.

    `hash()` is salted per interpreter, so a run seeded from it would not
    reproduce across processes -- and the tasks here ARE separate processes.
    """
    joined = ":".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(joined.encode()).digest()[:8], "big")


def _unit(*parts: object) -> float:
    """A deterministic float in [0, 1) from the parts."""
    return _digest(*parts) / float(1 << 64)


def target_names(n_targets: int) -> tuple[str, ...]:
    """The targets a generation-0 pipeline starts with."""
    return tuple(f"T{i}" for i in range(1, n_targets + 1))


def fragile_targets(cfg: ToyConfig) -> frozenset[str]:
    """Exactly `round(n * fragile_fraction)` targets, chosen deterministically.

    Picked by sorting on a hash rather than by sampling each target
    independently, so the count is exact. A run whose fragile count came out
    one short of `min_degraded_to_spawn` would never spawn, and the notebook's
    whole point would silently not happen.
    """
    names = target_names(cfg.n_targets)
    k = round(cfg.n_targets * cfg.fragile_fraction)
    ranked = sorted(names, key=lambda t: _digest(cfg.seed, "fragile", t))
    return frozenset(ranked[:k])


def simulate_score(
    target: str,
    pass_index: int,
    generation: int,
    migrated: bool,
    seed: int,
    noise_sd: float,
    fragile: bool,
) -> float:
    """One target's score at one pass. Deterministic in its arguments.

    Deliberately takes plain scalars rather than a `ToyConfig`, because
    `score_stage.py` reconstructs the call from `sys.argv` and a dataclass
    would have to be serialised to get there.
    """
    base = 70.0 + 20.0 * _unit(seed, "base", target)
    if migrated:
        drift = MIGRATED_DRIFT
    elif fragile:
        drift = FRAGILE_DRIFT
    else:
        drift = STURDY_DRIFT
    noise = random.Random(_digest(seed, "noise", target, pass_index, generation))
    value = base + drift * pass_index + noise.gauss(0.0, noise_sd)
    return round(min(SCORE_CEILING, max(SCORE_FLOOR, value)), 3)


def is_degraded(current: float, previous: float, threshold: float) -> bool:
    """True when the score fell by more than `threshold` since the last pass.

    Strictly greater, so a threshold of 0 does not mark a target that held its
    score exactly. Mirrors `adaptive_criteria` in
    examples/protein_binding/run_protein_binding.py, which compares a target's
    current reading against its previous one and acts on the ones that moved
    the wrong way.
    """
    return (previous - current) > threshold


def verdicts(
    current: dict,
    previous: dict,
    threshold: float,
) -> list:
    """Per-target verdicts for the targets present in both readings."""
    out = []
    for target in sorted(current):
        if target not in previous:
            continue
        curr = current[target]
        prev = previous[target]
        out.append(
            Verdict(
                target=target,
                current=curr,
                previous=prev,
                degraded=is_degraded(curr, prev, threshold),
            )
        )
    return out


@dataclass(frozen=True)
class SpawnDecision:
    """What the adaptive function decided, and why.

    The reason is carried so the notebook can print it. A run that declines to
    spawn is as interesting as one that does, and "no spawn" with no reason
    attached is the thing that makes adaptive behaviour feel arbitrary.
    """

    spawn: bool
    reason: str
    degraded: tuple = field(default_factory=tuple)


def decide(
    current: dict,
    previous: dict,
    generation: int,
    cfg: ToyConfig,
) -> SpawnDecision:
    """The adaptive rule itself, as a pure function.

    Kept separate from the callback that runs on the engine so it can be tested
    without a `WorkflowEngine`, and so the notebook can show the rule without
    showing the plumbing around it.
    """
    degraded = tuple(
        v.target for v in verdicts(current, previous, cfg.degradation_threshold)
        if v.degraded
    )
    if generation >= cfg.max_generations:
        return SpawnDecision(
            False,
            f"no spawn: generation cap reached ({generation}/{cfg.max_generations})",
            degraded,
        )
    if len(degraded) < cfg.min_degraded_to_spawn:
        return SpawnDecision(
            False,
            f"no spawn: {len(degraded)} degraded, "
            f"{cfg.min_degraded_to_spawn} needed",
            degraded,
        )
    return SpawnDecision(
        True,
        f"spawn: {len(degraded)} degraded "
        f"({', '.join(degraded)}) exceeded threshold "
        f"{cfg.degradation_threshold}",
        degraded,
    )
