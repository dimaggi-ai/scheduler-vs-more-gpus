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


def _run(policy: str, seed: int, **kw) -> tuple[Simulation, dict]:
    sim = Simulation(Config(horizon_days=HORIZON_DAYS, seed=seed, **kw), policy)
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


@functools.lru_cache(maxsize=1)
def points() -> tuple[Point, ...]:
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
        "rsc1-failure-rate", "calibrated", "[34]",
        expected=6.5, tolerance=0.0,
        actual=Config().failures_per_1000_node_days,
        note="Meta RSC-1: 6.50 failures per 1,000 node-days, used verbatim.",
    ))

    ettr = statistics.mean(
        _run("rigid-fifo", s, failures=True)[1]["train_ettr"] for s in SEEDS
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
    rigid = {s: _run("rigid-fifo", s) for s in SEEDS}
    waits_ordered = sum(
        1 for s in SEEDS
        if _mean_wait_h(rigid[s][0], 64, 512)
        > 2.0 * _mean_wait_h(rigid[s][0], 1, 8)
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

    intent = {s: _run("intent-closed-loop", s) for s in SEEDS}
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
        a = _run("rigid-fifo", s, power_envelope=True)[1]
        b = _run("tiered-preemption", s, power_envelope=True)[1]
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
        if _run("rigid-fifo", s, offered_load=0.95)[1]["mean_wait_h"]
        > _run("rigid-fifo", s, offered_load=0.85)[1]["mean_wait_h"]
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

    resv_ratio = (
        rigid[0][1]["stranded_reservation_gpu_h"]
        / intent[0][1]["stranded_reservation_gpu_h"]
    )
    slo_all = min(intent[s][1]["slo_attainment"] for s in SEEDS)
    pts.append(Point(
        "demand-tracking-cuts-reservation-waste", "sanity", "-",
        expected=3.44, tolerance=0.10,
        actual=resv_ratio if slo_all >= 0.99 else 0.0,
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
    if ok:
        print("all points reproduced — calibrated points prove consistency, "
              "emergent points carry the findings, sanity points pin the "
              "model's own arithmetic (see results/summary.md)")
    else:
        print("VALIDATION FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
