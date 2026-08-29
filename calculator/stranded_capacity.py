#!/usr/bin/env python3
"""Stranded-capacity calculator.

Accounting model:

    usable = nominal x A x E x P

where, over an analysis window of H hours on N accelerators:

    A  (scheduler availability)  fraction of wallclock the allocation plane
       can admit and place work. Reduced by hard control-plane outages and,
       partially, by degraded-operation windows (weighted).
    E  (allocation efficiency)   fraction of schedulable accelerator-hours
       actually allocated to workloads (losses: fragmentation, queue gaps,
       gang-admission stalls, oversized standing reservations).
    P  (productive ratio)        fraction of allocated accelerator-hours that
       produce forward progress (losses: failure rework, checkpoint overhead,
       restarts). Comparable to Meta's Effective Training Time Ratio (ETTR),
       arXiv:2410.21680.

Losses attribute layer by layer (they sum exactly to nominal - usable):

    L_sched = N*H * (1 - A)
    L_alloc = N*H * A * (1 - E)
    L_prod  = N*H * A * E * (1 - P)

Every preset parameter below is either taken from a primary source cited in
REFERENCES.md or is an explicitly labeled assumption you can override.
"""

from __future__ import annotations

import argparse
import dataclasses
import json


@dataclasses.dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    gpus: int
    window_hours: float
    hard_outage_hours: float = 0.0
    degraded_hours: float = 0.0
    # Fraction of scheduling capability lost during a degraded window.
    # 0.15 means the window costs 15% of its scheduler-availability value.
    degradation_weight: float = 0.15
    allocation_efficiency: float = 1.0
    productive_ratio: float = 1.0
    usd_per_gpu_hour: float = 2.00  # assumption; override with --usd-per-gpu-hour

    def availability(self) -> float:
        lost = self.hard_outage_hours + self.degraded_hours * self.degradation_weight
        if lost > self.window_hours:
            raise ValueError("outage hours exceed analysis window")
        return 1.0 - lost / self.window_hours


@dataclasses.dataclass(frozen=True)
class Result:
    nominal_gpu_hours: float
    availability: float
    usable_gpu_hours: float
    loss_scheduler: float
    loss_allocation: float
    loss_productivity: float
    usd_per_gpu_hour: float

    @property
    def stranded_gpu_hours(self) -> float:
        return self.loss_scheduler + self.loss_allocation + self.loss_productivity

    @property
    def stranded_usd(self) -> float:
        return self.stranded_gpu_hours * self.usd_per_gpu_hour

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["stranded_gpu_hours"] = self.stranded_gpu_hours
        d["stranded_usd"] = self.stranded_usd
        return d


def compute(s: Scenario) -> Result:
    nominal = s.gpus * s.window_hours
    a = s.availability()
    e = s.allocation_efficiency
    p = s.productive_ratio
    if not (0.0 <= e <= 1.0 and 0.0 <= p <= 1.0):
        raise ValueError("allocation_efficiency and productive_ratio must be in [0, 1]")
    return Result(
        nominal_gpu_hours=nominal,
        availability=a,
        usable_gpu_hours=nominal * a * e * p,
        loss_scheduler=nominal * (1.0 - a),
        loss_allocation=nominal * a * (1.0 - e),
        loss_productivity=nominal * a * e * (1.0 - p),
        usd_per_gpu_hour=s.usd_per_gpu_hour,
    )


# Worked examples. Sources in REFERENCES.md; bracketed numbers are reference ids.
PRESETS: dict[str, Scenario] = {
    # [4a] Aug 18, 2026: emergency Slurm patch, whole cluster paused 8:15-11:57
    # (~3.7 h major outage). GPU count: Cannon-proper "1,000+ GPUs" [4].
    # Window: a 30-day operating month around the event.
    "harvard-aug2026": Scenario(
        name="harvard-aug2026",
        description="Emergency scheduler patch pauses the whole fleet for ~3.7 h "
        "(SchedMD bug 25685). Control-plane maintenance as a capacity tax.",
        gpus=1000,
        window_hours=720.0,
        hard_outage_hours=3.7,
    ),
    # [1] May 29 - Jun 1, 2026: sacct query OOMs the Slurm DB host; hard outage
    # ~52 min (8:21->9:13 PM UTC); degraded operation (1-day query cap, triage)
    # until resolution ~65.5 h later. Degradation weight 0.15 is an assumption.
    "harvard-may2026": Scenario(
        name="harvard-may2026",
        description="sacct -> DB OOM -> scheduler crash: 52 min hard outage plus "
        "~65.5 h degraded operation (weighted 15%).",
        gpus=1000,
        window_hours=720.0,
        hard_outage_hours=52.0 / 60.0,
        degraded_hours=65.5,
    ),
    # [34] Meta RSC-1-shaped fleet: ETTR ~0.9 on large runs. Here productivity
    # is the only modeled loss: what does the last 10% cost at 16k GPUs?
    "meta-ettr": Scenario(
        name="meta-ettr",
        description="16k-GPU fleet at ETTR ~0.90 (Meta, arXiv:2410.21680): the "
        "productivity layer alone, per 30 days.",
        gpus=16000,
        window_hours=720.0,
        productive_ratio=0.90,
    ),
    # [37] Alibaba ASI: allocation ratio 68% before optimization. What the
    # allocation layer strands on a 155,410-GPU fleet in 30 days.
    "alibaba-allocation-before": Scenario(
        name="alibaba-allocation-before",
        description="155,410 GPUs at 68% allocation ratio (Alibaba OSDI'26, "
        "pre-optimization): the allocation layer alone, per 30 days.",
        gpus=155410,
        window_hours=720.0,
        allocation_efficiency=0.68,
    ),
    # [37] Same fleet after scheduler-side optimization raised allocation to 93%.
    "alibaba-allocation-after": Scenario(
        name="alibaba-allocation-after",
        description="Same fleet at 93% allocation ratio (post-optimization). "
        "Compare with alibaba-allocation-before: the delta is what better "
        "scheduling recovered without buying a single GPU.",
        gpus=155410,
        window_hours=720.0,
        allocation_efficiency=0.93,
    ),
    # Composite: a realistic mid-size AI cluster carrying typical values of all
    # three layers at once. A/E/P chosen from the cited range midpoints:
    # one Aug-2026-style maintenance event, E=0.80 (between Alibaba's 68% and
    # 93%), P=0.90 (Meta ETTR).
    "typical-composite": Scenario(
        name="typical-composite",
        description="Composite 4,096-GPU cluster, 30 days: one 4 h control-plane "
        "event, allocation 80%, productive ratio 90%.",
        gpus=4096,
        window_hours=720.0,
        hard_outage_hours=4.0,
        allocation_efficiency=0.80,
        productive_ratio=0.90,
    ),
}


def format_result(s: Scenario, r: Result) -> str:
    lines = [
        f"scenario: {s.name}",
        f"  {s.description}",
        f"  fleet: {s.gpus:,} GPUs x {s.window_hours:,.0f} h = "
        f"{r.nominal_gpu_hours:,.0f} nominal GPU-hours",
        f"  A (scheduler availability) = {r.availability:.4f}",
        f"  E (allocation efficiency)  = {s.allocation_efficiency:.4f}",
        f"  P (productive ratio)       = {s.productive_ratio:.4f}",
        f"  usable GPU-hours           = {r.usable_gpu_hours:,.0f}",
        f"  stranded, scheduler layer  = {r.loss_scheduler:,.0f} GPU-h "
        f"(${r.loss_scheduler * r.usd_per_gpu_hour:,.0f})",
        f"  stranded, allocation layer = {r.loss_allocation:,.0f} GPU-h "
        f"(${r.loss_allocation * r.usd_per_gpu_hour:,.0f})",
        f"  stranded, productivity     = {r.loss_productivity:,.0f} GPU-h "
        f"(${r.loss_productivity * r.usd_per_gpu_hour:,.0f})",
        f"  stranded total             = {r.stranded_gpu_hours:,.0f} GPU-h "
        f"(${r.stranded_usd:,.0f} at ${r.usd_per_gpu_hour:.2f}/GPU-h)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preset", choices=sorted(PRESETS), help="run a worked example")
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--gpus", type=int)
    ap.add_argument("--window-hours", type=float, default=720.0)
    ap.add_argument("--hard-outage-hours", type=float, default=0.0)
    ap.add_argument("--degraded-hours", type=float, default=0.0)
    ap.add_argument("--degradation-weight", type=float, default=0.15)
    ap.add_argument("--allocation-efficiency", type=float, default=1.0)
    ap.add_argument("--productive-ratio", type=float, default=1.0)
    ap.add_argument("--usd-per-gpu-hour", type=float, default=2.00)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args(argv)

    if args.list_presets:
        for name, sc in sorted(PRESETS.items()):
            print(f"{name}: {sc.description}")
        return 0

    if args.preset:
        s = PRESETS[args.preset]
        if args.usd_per_gpu_hour != 2.00:
            s = dataclasses.replace(s, usd_per_gpu_hour=args.usd_per_gpu_hour)
    elif args.gpus:
        s = Scenario(
            name="custom",
            description="custom scenario from CLI flags",
            gpus=args.gpus,
            window_hours=args.window_hours,
            hard_outage_hours=args.hard_outage_hours,
            degraded_hours=args.degraded_hours,
            degradation_weight=args.degradation_weight,
            allocation_efficiency=args.allocation_efficiency,
            productive_ratio=args.productive_ratio,
            usd_per_gpu_hour=args.usd_per_gpu_hour,
        )
    else:
        ap.error("provide --preset or --gpus (or --list-presets)")

    r = compute(s)
    if args.json:
        print(json.dumps({"scenario": dataclasses.asdict(s), "result": r.as_dict()}, indent=2))
    else:
        print(format_result(s, r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
