#!/usr/bin/env python3
"""The validation project: simulator constants and behaviors vs the public record.

Three kinds of points, honestly separated:

  calibrated  tuned to (or sharing an input with) a published figure.
              Passing proves internal consistency — the constant has not
              drifted — not predictive power.
  emergent    behaviors the model was NOT tuned to produce. They fall out
              of the mechanism, and the public record supports the
              direction (magnitudes are this model's, not the source's).
  sanity      true by construction or deterministic arithmetic. These
              points pin the model's own behavior so it cannot drift
              silently; they cite no external evidence and claim none.

All bracketed references are to REFERENCES.md. Synthetic data is the
seeded workload generator in simulator.py; stochastic points are
asserted across SEEDS so the mechanism, not the seed, carries them.

A registry that lists only the anchors it passes is a highlight reel, so
DECLINED below names the checks this registry does NOT make, and main()
prints them on every run. test_validation.py mutates the model on purpose
and requires the registry to go red, which is the only evidence that a
green run means anything.

Run: python3 validation.py   (exit 1 if any point fails)
"""

from __future__ import annotations

import dataclasses
import functools
import statistics
import sys

from simulator import (
    DT_H,
    MEAN_DURATION_H,
    SIZE_PROBS,
    Config,
    Simulation,
    expected_gpu_hours_per_job,
)

HORIZON_DAYS = 14
SEEDS = (0, 1, 2, 3)

# Hoisted so a mutation test can swap one and watch the registry go red.
# Nothing here is fitted: the policy names are the simulator's own, and the
# comparison constants are round numbers chosen before the runs.
RIGID = "rigid-fifo"
TIERED = "tiered-preemption"
INTENT = "intent-closed-loop"
SMALL_RANGE = (1, 8)            # "small job" band for the queueing comparison
LARGE_RANGE = (64, 512)         # "large job" band
WAIT_RATIO = 2.0                # large jobs must wait more than this x small
LOAD_LO, LOAD_HI = 0.85, 0.95   # offered loads for the queueing smoke test
RESV_RATIO, RESV_TOL = 3.44, 0.10
SLO_FLOOR = 0.99                # the reservation ratio only counts at equal SLO

# What this registry does NOT check. Printed on every run: a validation
# section that lists only its passes invites the reader to assume the rest.
DECLINED: tuple[tuple[str, str], ...] = (
    ("absolute capacity realization",
     "no public source reports capacity realization under a named allocation "
     "policy on a named fleet, so the levels (0.778, 0.858) are the model's "
     "and only their ORDERING is claimed"),
    ("the failure model, at any point in this registry",
     "meta-ettr-band cannot tell failures-off from 10x Meta's rate: "
     "checkpoint arithmetic alone puts the model at ~0.92 and the band is "
     "+/-0.03, so 0x (0.9212) and 10x (0.8763) both sit inside it; it only "
     "exits near 20x. rsc1-failure-rate-constant reads the constant back "
     "and compares it to itself. Between them they pin an input and a "
     "checkpoint constant — the rate at which this model loses and redoes "
     "work is unconstrained by roughly an order of magnitude"),
    ("the SIZE of the scheduling dividend, and elastic resize",
     "scheduler-work-reclaims-capacity asserts only a SIGN — that intent "
     "beats rigid in every seed. Delete elasticity outright and the "
     "dividend falls from 6.63 to 2.52 points while every point stays "
     "green; delete the restore path and it falls to 5.61, also green. The "
     "'~5-8 points' and the resize counts the paper itemises are reported, "
     "not validated"),
    ("Philly wait-ratio magnitudes",
     "only the direction is anchored; this 95%-load simulation produces "
     "ratios far larger than the trace's minutes-scale tail, and no point "
     "asserts a magnitude against [35]"),
    ("the Alibaba anchor as a like-for-like comparison",
     "[37] measures ALLOCATION ratio on a 155,410-GPU fleet; this model "
     "measures capacity REALIZATION on 1,024 GPUs. Adjacent metric, "
     "different scale — direction only"),
    ("inference latency, placement, and multi-tenancy",
     "inference is an aggregate demand curve, node placement is abstracted, "
     "and the cluster is single-tenant, so nothing here validates tail "
     "latency, topology-aware packing, or inter-tenant fairness"),
    ("real scheduler software",
     "no Slurm, Kubernetes, or Borg binary is exercised; rigid-fifo is a "
     "model of a conservative configuration, not a measurement of one"),
)


@dataclasses.dataclass(frozen=True)
class Point:
    name: str
    kind: str        # 'calibrated' | 'emergent' | 'sanity'
    ref: str         # '-' allowed for sanity points only
    expected: float
    tolerance: float
    actual: float
    note: str

    @property
    def ok(self) -> bool:
        return abs(self.actual - self.expected) <= self.tolerance


def _run(policy: str, seed: int, horizon_days: int = HORIZON_DAYS,
         **kw) -> tuple[Simulation, dict]:
    sim = Simulation(Config(horizon_days=horizon_days, seed=seed, **kw), policy)
    return sim, sim.run()


def _mean_wait_h(sim: Simulation, lo: int, hi: int) -> float:
    # Jobs that never started are censored out; at these loads that is
    # conservative for the big-vs-small comparison (the censored jobs are
    # overwhelmingly big ones that would raise the big-job mean further).
    ws = [
        (j.first_start_step - j.submit_step) * DT_H
        for j in sim.jobs
        if j.first_start_step is not None and lo <= j.size <= hi
    ]
    assert ws, f"no started jobs in size range {lo}-{hi}"
    return statistics.mean(ws)


@functools.lru_cache(maxsize=None)
def points(horizon_days: int = HORIZON_DAYS,
           seeds: tuple[int, ...] = SEEDS) -> tuple[Point, ...]:
    """Build the registry. Parameterized so a mutation test can re-evaluate it
    at a reduced horizon; the published run always uses the defaults."""
    SEEDS = seeds                       # noqa: N806 - shadowed on purpose
    run = functools.partial(_run, horizon_days=horizon_days)
    pts: list[Point] = []

    # ---------------------------------------------------------- calibrated
    small_count = sum(p for s, p in SIZE_PROBS if s < 8)
    big_time = (
        sum(p * s * MEAN_DURATION_H[s] for s, p in SIZE_PROBS if s >= 256)
        / expected_gpu_hours_per_job()
    )
    pts.append(Point(
        "meta-most-jobs-small", "calibrated", "[34]",
        expected=0.68, tolerance=0.005, actual=small_count,
        note="Job-count share below 8 GPUs. Tuned to Meta's shape finding "
             "(most jobs small); pinned so the workload cannot drift.",
    ))
    pts.append(Point(
        "meta-most-gpu-time-large", "calibrated", "[34]",
        expected=0.60, tolerance=0.005, actual=big_time,
        note="Expected GPU-hour share of 256+ GPU jobs. Tuned to Meta's "
             "finding that large jobs dominate GPU-time.",
    ))
    pts.append(Point(
        "rsc1-failure-rate-constant", "calibrated", "[34]",
        expected=6.5, tolerance=0.0,
        actual=Config().failures_per_1000_node_days,
        note="Meta RSC-1: 6.50 failures per 1,000 node-days, used verbatim. "
             "This reads the constant back and compares it to itself; no "
             "simulation runs. It pins the input against silent drift and "
             "is named for what it does. Nothing here checks the failure "
             "MODEL — see DECLINED: the registry stays green at 10x this "
             "rate.",
    ))

    ettr = statistics.mean(
        run(RIGID, s, failures=True)[1]["train_ettr"] for s in SEEDS
    )
    pts.append(Point(
        "meta-ettr-band", "calibrated", "[34]",
        expected=0.90, tolerance=0.03, actual=ettr,
        note="GPU-hour-weighted training ETTR with failures on (mean over "
             "seeds). Meta reports ETTR ~0.9 for multi-day 2-4k-GPU RSC-1 "
             "runs — computed at an ASSUMED 1-hour checkpoint interval, "
             "the same constant this model uses (CKPT_INTERVAL_STEPS=12), "
             "so agreement is a shared input, not evidence: without any "
             "failures the model still sits at ~0.92 from checkpoint "
             "arithmetic alone (12 productive steps in 13). Denominators "
             "differ too (Meta: productive/available wallclock per run; "
             "here: productive/allocated GPU-h). Labeled calibrated for "
             "both reasons.",
    ))

    # ------------------------------------------------------------ emergent
    rigid = {s: run(RIGID, s) for s in SEEDS}
    waits_ordered = sum(
        1 for s in SEEDS
        if _mean_wait_h(rigid[s][0], *LARGE_RANGE)
        > WAIT_RATIO * _mean_wait_h(rigid[s][0], *SMALL_RANGE)
    )
    pts.append(Point(
        "philly-large-jobs-wait-longer", "emergent", "[35]",
        expected=float(len(SEEDS)), tolerance=0.0, actual=float(waits_ordered),
        note="Seeds where 64+ GPU jobs wait more than 2x longer than 1-8 "
             "GPU jobs under rigid gang scheduling. Philly reports a longer "
             "tail of queueing delay for >4-GPU jobs (25% wait >=10 min vs "
             "10% of 1-GPU jobs) with fragmentation behind ~78% of "
             "large-job delay occurrences. Direction-only anchor: this "
             "saturated 95%-load simulation produces much larger ratios "
             "than the production trace's minutes-scale tail. Nothing in "
             "the generator or scheduler encodes the ordering; it falls "
             "out of gang admission of rigid sizes.",
    ))

    intent = {s: run(INTENT, s) for s in SEEDS}
    ordering = sum(
        1 for s in SEEDS
        if intent[s][1]["capacity_realization"]
        > rigid[s][1]["capacity_realization"]
    )
    pts.append(Point(
        "scheduler-work-reclaims-capacity", "emergent", "[37]",
        expected=float(len(SEEDS)), tolerance=0.0, actual=float(ordering),
        note="Seeds where the intent policy realizes more of the envelope "
             "than rigid FIFO (delta ~5-8 points here). Direction anchor "
             "on a different metric: Alibaba (OSDI 2026) raised the "
             "ALLOCATION ratio 68%->93% by scheduler-side work alone; this "
             "model's capacity REALIZATION moves the same way for the same "
             "reason — capacity is reclaimed at the allocation layer, not "
             "by buying GPUs.",
    ))

    # -------------------------------------------------------------- sanity
    power_ok = 0
    losses = []
    for s in SEEDS:
        a = run(RIGID, s, power_envelope=True)[1]
        b = run(TIERED, s, power_envelope=True)[1]
        losses.append(a["work_lost_gpu_h"])
        if a["work_lost_gpu_h"] > 0 and b["work_lost_gpu_h"] == 0.0:
            power_ok += 1
    pts.append(Point(
        "emergency-kills-lose-work", "sanity", "-",
        expected=float(len(SEEDS)), tolerance=0.0, actual=float(power_ok),
        note=f"Model consistency, not external validation: graceful "
             f"checkpoint-preemption preserves progress BY CONSTRUCTION "
             f"here, so the content of this point is the magnitude on the "
             f"other side — emergency kills under a daily power "
             f"contraction lose ~1,350-2,100 GPU-h per 14 days "
             f"(measured {min(losses):,.0f}-{max(losses):,.0f}) given "
             f"hourly checkpoints. Note real systems are harsher than the "
             f"graceful branch: Borg-style preemption [25] warns and "
             f"kills, relying on application checkpoints, so work since "
             f"the last checkpoint is lost even in the 'graceful' case.",
    ))

    grows = sum(
        1 for s in SEEDS
        if run(RIGID, s, offered_load=LOAD_HI)[1]["mean_wait_h"]
        > run(RIGID, s, offered_load=LOAD_LO)[1]["mean_wait_h"]
    )
    pts.append(Point(
        "queueing-grows-with-load", "sanity", "-",
        expected=float(len(SEEDS)), tolerance=0.0, actual=float(grows),
        note="Mean wait rises from 0.85 to 0.95 offered load in every "
             "seed — a smoke test on the queue, claiming no external "
             "evidence. Above saturation the started-jobs-only wait "
             "metric censors never-started jobs and flattens, so no "
             "claim is made past 0.95.",
    ))

    # Mean over seeds, not seed 0: the reservation schedule is deterministic
    # so every seed gives the same ratio, but a single-seed figure would be
    # indistinguishable from a lucky one to anyone reading the code.
    resv_ratio = statistics.mean(
        rigid[s][1]["stranded_reservation_gpu_h"]
        / intent[s][1]["stranded_reservation_gpu_h"]
        for s in SEEDS
    )
    slo_all = min(intent[s][1]["slo_attainment"] for s in SEEDS)
    pts.append(Point(
        "demand-tracking-cuts-reservation-waste", "sanity", "-",
        expected=RESV_RATIO, tolerance=RESV_TOL,
        actual=resv_ratio if slo_all >= SLO_FLOOR else 0.0,
        note="Deterministic constant arithmetic, pinned so it cannot "
             "drift: peak-provisioning at 1.05x peak vs demand-tracking "
             "at 1.10x demand yields a 3.44x reservation-stranding ratio "
             "given this demand curve, at equal (1.0) SLO in the steady "
             "scenario (checked across all seeds). The carrier-network "
             "pattern [41] motivates the mechanism; the magnitude is "
             "this model's, not the patent's.",
    ))

    return tuple(pts)


def validate() -> tuple[tuple[Point, ...], bool]:
    pts = points()
    return pts, all(p.ok for p in pts)


def main() -> int:
    pts, ok = validate()
    w = max(len(p.name) for p in pts)
    print(f"{'point':<{w}}  {'kind':<10}  {'ref':<6}  {'expected':>8}  "
          f"{'actual':>8}  {'err':>6}  verdict")
    for p in pts:
        print(f"{p.name:<{w}}  {p.kind:<10}  {p.ref:<6}  {p.expected:>8.3f}  "
              f"{p.actual:>8.3f}  {abs(p.actual - p.expected):>6.3f}  "
              f"{'PASS' if p.ok else 'FAIL'}")
    print()
    print("NOT CHECKED HERE — a registry that prints only its passes is a "
          "highlight reel:")
    for name, why in DECLINED:
        print(f"  - {name}: {why}")
    print()
    if ok:
        print("all points reproduced — calibrated points prove consistency, "
              "emergent points carry the findings, sanity points pin the "
              "model's own arithmetic (see results/summary.md). "
              "test_validation.py breaks the model on purpose and requires "
              "these points to fail; that, not this table, is why a green "
              "run is worth anything.")
    else:
        print("VALIDATION FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
