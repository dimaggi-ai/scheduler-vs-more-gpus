#!/usr/bin/env python3
"""Discrete-time allocation-policy simulator.

Compares three allocation policies on the same workload, cluster, and events:

  rigid-fifo         FIFO + backfill, rigid job sizes, no preemption, fixed
                     peak-provisioned inference reservation. Power contraction
                     is handled by emergency-killing the newest training jobs
                     (work since last checkpoint is lost). Approximates a
                     conservative Slurm configuration.
  tiered-preemption  Adds Borg-style priority tiers (inference > batch >
                     best-effort) and graceful checkpoint-preemption, still
                     rigid sizes and a fixed inference reservation.
  intent-closed-loop Adds the carrier-network pattern (cf. patents
                     US 2020/0112876, US 11,128,536): declared intents with a
                     controller loop every 15 min that (a) tracks inference
                     demand with 10% headroom instead of peak-provisioning,
                     (b) shrinks elastic training jobs before escalating to
                     graceful preemption, (c) degrades in a strict hierarchy
                     under scarcity (shrink elastic -> preempt best-effort ->
                     preempt newest batch -> never below inference demand).

Workload shape is calibrated to Meta's published job-size findings
(arXiv:2410.21680): most jobs are small, most GPU-time belongs to large jobs.
Failure rates likewise (6.5 failures per 1,000 node-days on RSC-1).

Modeling simplifications (documented; see docs and test suite):
  - 5-minute time step; GPU-hours are the unit of work; linear scaling for
    elastic jobs (progress == allocated GPU-hours) — optimistic for elastic
    resize, which is why resize also pays a checkpoint-overhead step.
  - Inference is an aggregate demand curve, not per-request latency; SLO
    attainment = fraction of steps with allocation >= demand.
  - Node placement is abstracted: a node failure hits a running job with
    probability proportional to its allocation.
  - Single-tenant fair-share (no inter-tenant fairness modeling).
"""

from __future__ import annotations

import dataclasses
import math
from typing import Optional

import numpy as np

# ---------------------------------------------------------------- constants

DT_MIN = 5                      # minutes per step
STEPS_PER_HOUR = 60 // DT_MIN
STEPS_PER_DAY = 24 * STEPS_PER_HOUR
DT_H = DT_MIN / 60.0            # hours per step

CKPT_INTERVAL_STEPS = 12        # checkpoint every 60 min of runtime
OVERHEAD_STEPS = 1              # 5-min non-productive step for ckpt write,
                                # restart, or resize
NODE_GPUS = 8
REPAIR_STEPS = 48               # failed node returns after 4 h

# Job-size distribution calibrated to Meta arXiv:2410.21680 (job-size
# findings, §4): most jobs tiny, GPU-time dominated by 256+ GPU jobs
# (~60% of expected GPU-hours here).
SIZE_PROBS = [
    (1, 0.42), (2, 0.13), (4, 0.13), (8, 0.18), (16, 0.05),
    (32, 0.04), (64, 0.025), (128, 0.015), (256, 0.007), (512, 0.003),
]
MEAN_DURATION_H = {1: 2, 2: 2, 4: 2, 8: 6, 16: 6, 32: 6, 64: 16, 128: 16, 256: 36, 512: 36}
MAX_DURATION_H = 168            # 7-day lifetime cap (Meta policy)
BEST_EFFORT_FRACTION = 0.20
ELASTIC_MIN_SIZE = 16           # jobs >= this size are elastic (intent policy)


@dataclasses.dataclass
class Config:
    gpus: int = 1024
    horizon_days: int = 30
    seed: int = 42
    offered_load: float = 0.95          # of expected training capacity
    # inference demand curve
    inf_base: float = 280.0
    inf_diurnal_amp: float = 80.0
    inf_surges: bool = False            # 2-h surges of +120 GPUs (S4)
    # events
    failures: bool = False              # Meta RSC-1 rate
    failures_per_1000_node_days: float = 6.5
    power_envelope: bool = False        # daily 4-h contraction to 75%
    power_frac: float = 0.75
    power_start_hour: int = 16
    power_hours: int = 4

    @property
    def steps(self) -> int:
        return self.horizon_days * STEPS_PER_DAY

    @property
    def nodes(self) -> int:
        return self.gpus // NODE_GPUS


@dataclasses.dataclass
class Job:
    jid: int
    size: int                   # full requested GPUs
    work: float                 # GPU-hours to complete (at any allocation)
    submit_step: int
    tier: str                   # 'batch' | 'besteffort'
    elastic: bool
    min_size: int
    # mutable state
    status: str = "QUEUED"      # QUEUED | RUNNING | DONE
    alloc: int = 0
    progress: float = 0.0
    progress_since_ckpt: float = 0.0
    steps_since_ckpt: int = 0
    overhead_steps: int = 0     # pending non-productive steps (restart/ckpt/resize)
    first_start_step: Optional[int] = None
    done_step: Optional[int] = None
    preemptions: int = 0
    emergency_kills: int = 0
    resizes: int = 0
    work_lost: float = 0.0
    last_resize_step: int = -(10**9)


@dataclasses.dataclass
class Metrics:
    nominal_gpu_h: float = 0.0
    envelope_gpu_h: float = 0.0         # after power cap and failed nodes
    inf_alloc_gpu_h: float = 0.0
    inf_productive_gpu_h: float = 0.0
    inf_demand_gpu_h: float = 0.0
    train_alloc_gpu_h: float = 0.0
    train_productive_gpu_h: float = 0.0
    slo_ok_steps: int = 0
    total_steps: int = 0
    jobs_submitted: int = 0
    jobs_completed: int = 0
    preemptions: int = 0
    emergency_kills: int = 0
    resizes: int = 0
    work_lost_gpu_h: float = 0.0
    wait_steps_sum: float = 0.0
    waited_jobs: int = 0

    def finalize(self) -> dict:
        idle = self.envelope_gpu_h - self.inf_alloc_gpu_h - self.train_alloc_gpu_h
        reservation_waste = self.inf_alloc_gpu_h - self.inf_productive_gpu_h
        train_unproductive = self.train_alloc_gpu_h - self.train_productive_gpu_h
        productive = self.inf_productive_gpu_h + self.train_productive_gpu_h
        return {
            "nominal_gpu_h": round(self.nominal_gpu_h, 1),
            "envelope_gpu_h": round(self.envelope_gpu_h, 1),
            "productive_gpu_h": round(productive, 1),
            "stranded_gpu_h": round(self.envelope_gpu_h - productive, 1),
            "stranded_idle_gpu_h": round(idle, 1),
            "stranded_reservation_gpu_h": round(reservation_waste, 1),
            "stranded_train_overhead_gpu_h": round(train_unproductive, 1),
            "capacity_realization": round(productive / self.envelope_gpu_h, 4),
            "slo_attainment": round(self.slo_ok_steps / max(1, self.total_steps), 4),
            "train_ettr": round(
                self.train_productive_gpu_h / max(1e-9, self.train_alloc_gpu_h), 4
            ),
            "jobs_submitted": self.jobs_submitted,
            "jobs_completed": self.jobs_completed,
            "preemptions": self.preemptions,
            "emergency_kills": self.emergency_kills,
            "resizes": self.resizes,
            "work_lost_gpu_h": round(self.work_lost_gpu_h, 1),
            "mean_wait_h": round(
                self.wait_steps_sum * DT_H / max(1, self.waited_jobs), 2
            ),
        }


# ---------------------------------------------------------------- workload


def expected_gpu_hours_per_job() -> float:
    return sum(p * s * MEAN_DURATION_H[s] for s, p in SIZE_PROBS)


def make_workload(cfg: Config, rng: np.random.Generator) -> list[Job]:
    """Pre-generate all training-job arrivals for the horizon (seeded)."""
    # Average inference allocation under demand-tracking would be ~inf_base;
    # peak-provisioned policies allocate more, but we calibrate offered load
    # against a common yardstick so all policies see the same queue.
    avg_train_capacity = cfg.gpus - (cfg.inf_base + cfg.inf_diurnal_amp)  # conservative
    target_gpuh_per_step = cfg.offered_load * avg_train_capacity * DT_H
    lam = target_gpuh_per_step / expected_gpu_hours_per_job()  # jobs per step

    sizes = np.array([s for s, _ in SIZE_PROBS])
    probs = np.array([p for _, p in SIZE_PROBS])
    jobs: list[Job] = []
    jid = 0
    for t in range(cfg.steps):
        for _ in range(rng.poisson(lam)):
            size = int(rng.choice(sizes, p=probs))
            mean_h = MEAN_DURATION_H[size]
            # lognormal with median ~ mean_h, sigma 0.8; truncate to 7 days
            dur = float(min(rng.lognormal(math.log(mean_h), 0.8), MAX_DURATION_H))
            elastic = size >= ELASTIC_MIN_SIZE
            jobs.append(
                Job(
                    jid=jid,
                    size=size,
                    work=size * dur,
                    submit_step=t,
                    tier="besteffort" if rng.random() < BEST_EFFORT_FRACTION else "batch",
                    elastic=elastic,
                    min_size=max(size // 4, NODE_GPUS) if elastic else size,
                )
            )
            jid += 1
    return jobs


def inference_demand(cfg: Config, t: int, surge_add: float) -> float:
    hour = (t % STEPS_PER_DAY) / STEPS_PER_HOUR
    diurnal = math.sin((hour - 6.0) / 24.0 * 2.0 * math.pi)
    return max(0.0, cfg.inf_base + cfg.inf_diurnal_amp * diurnal + surge_add)


def power_cap_fraction(cfg: Config, t: int) -> float:
    if not cfg.power_envelope:
        return 1.0
    hour = (t % STEPS_PER_DAY) / STEPS_PER_HOUR
    if cfg.power_start_hour <= hour < cfg.power_start_hour + cfg.power_hours:
        return cfg.power_frac
    return 1.0


# ---------------------------------------------------------------- engine


class Simulation:
    def __init__(self, cfg: Config, policy: str):
        assert policy in ("rigid-fifo", "tiered-preemption", "intent-closed-loop")
        self.cfg = cfg
        self.policy = policy
        self.rng = np.random.default_rng(cfg.seed)
        # Events (failure and surge timing) use a dedicated RNG so that every
        # policy faces an identical event timeline by construction — the main
        # rng also feeds policy-dependent draws (victim selection), which
        # would otherwise desynchronize timelines across policies.
        self.event_rng = np.random.default_rng(cfg.seed + 20_000)
        self.jobs = make_workload(cfg, np.random.default_rng(cfg.seed + 10_000))
        self.metrics = Metrics(jobs_submitted=len(self.jobs))
        self.queue: list[Job] = []
        self.running: list[Job] = []
        self.next_arrival_idx = 0
        self.nodes_down_until: list[int] = []   # step at which each repair ends
        self.surge_until = -1
        self.surge_add = 0.0
        # peak-provisioned reservation for rigid/tiered policies
        self.inf_reservation = math.ceil((cfg.inf_base + cfg.inf_diurnal_amp) * 1.05)
        self.inf_alloc = float(self.inf_reservation)

    # ------------------------------------------------------------ helpers

    def gpus_up(self, t: int) -> int:
        self.nodes_down_until = [e for e in self.nodes_down_until if e > t]
        return self.cfg.gpus - NODE_GPUS * len(self.nodes_down_until)

    def train_alloc(self) -> int:
        return sum(j.alloc for j in self.running)

    def _stop(self, j: Job, graceful: bool, t: int) -> None:
        """Remove a job from the running set, back to the queue."""
        if graceful:
            # checkpoint written at stop: progress preserved
            j.preemptions += 1
            self.metrics.preemptions += 1
        else:
            lost = j.progress_since_ckpt
            j.progress = max(0.0, j.progress - lost)
            j.work_lost += lost
            self.metrics.work_lost_gpu_h += lost
            # that progress was previously counted productive; take it back
            self.metrics.train_productive_gpu_h -= lost
            j.emergency_kills += 1
            self.metrics.emergency_kills += 1
        j.progress_since_ckpt = 0.0
        j.steps_since_ckpt = 0
        j.alloc = 0
        j.status = "QUEUED"
        j.overhead_steps = 0
        self.running.remove(j)
        self.queue.insert(0, j)  # preempted/killed jobs go to the head

    def _start(self, j: Job, alloc: int, t: int) -> None:
        j.status = "RUNNING"
        j.alloc = alloc
        j.overhead_steps = OVERHEAD_STEPS
        if j.first_start_step is None:
            j.first_start_step = t
            self.metrics.wait_steps_sum += t - j.submit_step
            self.metrics.waited_jobs += 1
        self.running.append(j)

    def _resize(self, j: Job, new_alloc: int, t: int) -> None:
        if new_alloc != j.alloc:
            j.alloc = new_alloc
            j.resizes += 1
            j.last_resize_step = t
            j.overhead_steps = max(j.overhead_steps, OVERHEAD_STEPS)
            self.metrics.resizes += 1

    # ------------------------------------------------------------ policies

    def _enforce_cap(self, cap: int, t: int) -> None:
        """Bring inference + training allocation under the cap, policy-style."""
        # inference first: it can never exceed cap
        self.inf_alloc = min(self.inf_alloc, float(cap))
        budget = cap - int(self.inf_alloc)

        if self.policy == "intent-closed-loop":
            # 1) shrink elastic jobs, largest allocation first
            over = self.train_alloc() - budget
            if over > 0:
                for j in sorted(self.running, key=lambda x: -x.alloc):
                    if over <= 0:
                        break
                    if j.elastic and j.alloc > j.min_size:
                        new = max(j.min_size, j.alloc - over)
                        over -= j.alloc - new
                        self._resize(j, new, t)  # cap enforcement ignores cooldown
            # 2) then graceful preemption: best-effort newest, then batch newest
            self._preempt_until_fits(budget, t, graceful=True)
        elif self.policy == "tiered-preemption":
            self._preempt_until_fits(budget, t, graceful=True)
        else:  # rigid-fifo: emergency kills, newest first, work lost
            self._kill_until_fits(budget, t)

    def _preempt_until_fits(self, budget: int, t: int, graceful: bool) -> None:
        def order(js: list[Job]) -> list[Job]:
            return sorted(js, key=lambda x: (x.first_start_step or 0), reverse=True)

        for tier in ("besteffort", "batch"):
            while self.train_alloc() > budget:
                candidates = order([j for j in self.running if j.tier == tier])
                if not candidates:
                    break
                self._stop(candidates[0], graceful=graceful, t=t)
            if self.train_alloc() <= budget:
                return

    def _kill_until_fits(self, budget: int, t: int) -> None:
        while self.train_alloc() > budget:
            newest = max(self.running, key=lambda x: (x.first_start_step or 0))
            self._stop(newest, graceful=False, t=t)

    def _admit(self, cap: int, t: int) -> None:
        """FIFO + backfill admission from the queue."""
        budget = cap - int(self.inf_alloc) - self.train_alloc()
        if budget <= 0:
            return
        admitted: list[Job] = []
        for j in self.queue:
            if budget <= 0:
                break
            want = j.size
            if want <= budget:
                self._start(j, want, t)
                budget -= want
                admitted.append(j)
            elif (
                self.policy == "intent-closed-loop"
                and j.elastic
                and j.min_size <= budget
            ):
                self._start(j, budget, t)  # start shrunk, expand later
                budget = 0
                admitted.append(j)
        for j in admitted:
            self.queue.remove(j)

    def _intent_controller(self, cap: int, t: int, demand: float) -> None:
        """Every 15 min: track inference demand + 10% headroom."""
        self.inf_alloc = min(float(cap), math.ceil(demand * 1.10))

    RESIZE_COOLDOWN_STEPS = 12  # a job is resized at most once per hour

    def _intent_restore(self, cap: int, t: int) -> None:
        """After admission: restore shrunk elastic jobs, all-or-nothing, with
        a per-job cooldown so the controller cannot thrash."""
        budget = cap - int(self.inf_alloc) - self.train_alloc()
        for j in sorted(self.running, key=lambda x: (x.first_start_step or 0)):
            if budget <= 0:
                break
            if (
                j.elastic
                and j.alloc < j.size
                and j.size - j.alloc <= budget
                and t - j.last_resize_step >= self.RESIZE_COOLDOWN_STEPS
            ):
                budget -= j.size - j.alloc
                self._resize(j, j.size, t)

    # ------------------------------------------------------------ main loop

    def run(self) -> dict:
        cfg, m = self.cfg, self.metrics
        for t in range(cfg.steps):
            # --- events -------------------------------------------------
            if cfg.failures:
                up_nodes = self.gpus_up(t) // NODE_GPUS
                p = cfg.failures_per_1000_node_days / 1000.0 / STEPS_PER_DAY
                for _ in range(int(self.event_rng.binomial(up_nodes, p))):
                    self.nodes_down_until.append(t + REPAIR_STEPS)
                    victims = [j for j in self.running]
                    if victims:
                        w = np.array([j.alloc for j in victims], dtype=float)
                        if w.sum() > 0:
                            j = victims[int(self.rng.choice(len(victims), p=w / w.sum()))]
                            self._stop(j, graceful=False, t=t)  # failures are never graceful
            if cfg.inf_surges:
                if t > self.surge_until and self.event_rng.random() < 1.0 / (2 * STEPS_PER_DAY):
                    self.surge_until = t + 2 * STEPS_PER_HOUR
                self.surge_add = 120.0 if t <= self.surge_until else 0.0

            demand = inference_demand(cfg, t, self.surge_add)
            cap = min(self.gpus_up(t), int(self.cfg.gpus * power_cap_fraction(cfg, t)))

            # --- policy control ----------------------------------------
            if self.policy == "intent-closed-loop" and t % 3 == 0:
                self._intent_controller(cap, t, demand)
            if self.policy != "intent-closed-loop":
                self.inf_alloc = float(min(self.inf_reservation, cap))
            self._enforce_cap(cap, t)

            # --- arrivals & admission ----------------------------------
            while (
                self.next_arrival_idx < len(self.jobs)
                and self.jobs[self.next_arrival_idx].submit_step <= t
            ):
                self.queue.append(self.jobs[self.next_arrival_idx])
                self.next_arrival_idx += 1
            self._admit(cap, t)
            if self.policy == "intent-closed-loop" and t % 3 == 0:
                self._intent_restore(cap, t)

            # --- accounting for this step ------------------------------
            m.total_steps += 1
            m.nominal_gpu_h += cfg.gpus * DT_H
            m.envelope_gpu_h += cap * DT_H
            m.inf_alloc_gpu_h += self.inf_alloc * DT_H
            m.inf_demand_gpu_h += demand * DT_H
            m.inf_productive_gpu_h += min(self.inf_alloc, demand) * DT_H
            if self.inf_alloc >= demand:
                m.slo_ok_steps += 1

            done: list[Job] = []
            for j in self.running:
                m.train_alloc_gpu_h += j.alloc * DT_H
                if j.overhead_steps > 0:
                    j.overhead_steps -= 1          # restart/resize/ckpt write
                elif j.steps_since_ckpt >= CKPT_INTERVAL_STEPS:
                    j.steps_since_ckpt = 0          # periodic checkpoint write
                    j.progress_since_ckpt = 0.0
                else:
                    added = j.alloc * DT_H
                    j.progress += added
                    j.progress_since_ckpt += added
                    j.steps_since_ckpt += 1
                    m.train_productive_gpu_h += added
                if j.progress >= j.work:
                    j.status = "DONE"
                    j.done_step = t
                    done.append(j)
            for j in done:
                self.running.remove(j)
                m.jobs_completed += 1

        result = m.finalize()
        result["policy"] = self.policy
        result["seed"] = cfg.seed
        return result


def run_once(policy: str, **cfg_kwargs) -> dict:
    return Simulation(Config(**cfg_kwargs), policy).run()
