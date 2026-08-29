# The TPU Parallel Hypothesis

Reference numbers point to [REFERENCES.md](../REFERENCES.md).

**Hypothesis.** Vertically integrated accelerator platforms win on *allocation efficiency*, not only on chip performance. Google's TPU stack is the existence proof: by co-designing the scheduler and the fabric, "scattered accelerators become a working cluster" is a native property of the platform. The merchant-GPU world is reassembling the same properties from parts — Slurm semantics, Kubernetes substrates, topology-aware batch schedulers, multi-cloud queues — and the pace and shape of that reassembly is the most important open variable in AI-infrastructure economics.

## The evidence chain

**1. The scheduler came first.** Borg has run the allocation end state's core mechanics since before 2015: non-overlapping priority bands ("monitoring, production, batch, and best effort"), quota-priced admission control, preemption with cascade suppression ("we disallow tasks in the production priority band to preempt one another"), and graceful eviction via SIGTERM-before-SIGKILL [25]. The 2020 follow-up shows the workload becoming radically heavier-tailed — the shape AI clusters now live with [26].

**2. Then the fabric was redesigned around allocation.** TPU v4 (ISCA 2023) introduced optical circuit switches that *dynamically reconfigure the interconnect topology* — and the paper's own framing is a scheduling argument [28]:

> "The OCS also simplifies scheduling, which increases utilization. For TPU v3, a 256 chip slice meant the scheduler had to find 256 contiguous chips that were idle. For TPU v4, it can pick 4³ blocks from anywhere in the supercomputer."

Fragmentation — the constraint every GPU-cluster scheduler fights in software (gang admission, binpacking, topology awareness) — was removed in hardware. The same mechanism carries availability: a 4,096-chip machine tolerates "1K CPU hosts that are unavailable 0.1%–1.0% of the time," and slice goodput survives at 99.0–99.5% host availability where a static fabric needs 99.9% [28]. OCS hardware costs under 5% of the system [28]. (For a refereed treatment of the underlying datacenter OCS deployment, see Jupiter Evolving, SIGCOMM 2022 [29].)

**3. The orchestration layer spans the fabric.** Pathways gang-schedules "heterogeneous parallel computations on thousands of accelerators," including computations sharded across accelerator islands connected over the datacenter network [27] — the software analogue of the OCS move: placement freedom without topology penalty. (Pathways works *with* the cluster scheduler; it does not replace it.)

**4. And it shipped as product.** Cloud TPU today exposes the allocation end state commercially: Multislice jobs spanning slices and pods; queued resources (declared, asynchronous capacity intent); Spot tiers; default-on ICI resiliency that routes around optical faults at the cost of temporary degradation; goodput measurement as a first-class library [31, 33]. The Dynamic Workload Scheduler generalizes it to *both* TPUs and GPUs and states its lineage outright: "built on Google Borg technology" [32].

## What the hypothesis predicts

Falsifiable expectations, stated in 2026:

1. **Scheduling consolidates under accelerator vendors.** Already observable: NVIDIA acquired Run:ai (engine open-sourced as KAI, CNCF Sandbox, 2025) and then SchedMD — Slurm itself — in December 2025 [16, 21]. If allocation were a commodity sideshow, the chip vendor would not be buying the schedulers.
2. **"GPUs-as-cattle" fabrics emerge.** Reconfigurable or rail-flexible fabrics (optical switching, disaggregated NVLink domains) will migrate into merchant GPU systems specifically to relax scheduler contiguity constraints, replicating the TPU v4 move.
3. **Allocation efficiency becomes a quoted metric.** Vendors already inch there — CoreWeave quotes goodput and ETTR figures for SUNK [17]; expect capacity-realization-style numbers to appear in cloud SLAs and financings, because the difference between 78% and 86% realization (this repo's simulated dividend) is worth more than a hardware-generation refresh cycle at fleet scale.
4. **Power-flexibility becomes an allocation feature.** A scheduler that degrades by declared intent can sell that capability upward as grid flexibility (demonstrated at 256-GPU scale by NVIDIA/Emerald: −25% power during grid peak via orchestration alone [43]; formalized for clusters by Google's carbon-intelligent capacity curves [42]). Siting advantages then accrue to operators whose *allocation layer* can promise curtailment.

## What the hypothesis does not claim

- **Not** that the GPU world is failing. Meta reaches ETTR ~0.9 on multi-day 2–4k-GPU runs with layered mitigations — health checks every five minutes, lemon-node detection that cut large-job failures from 14% to 4%, requeue policies, tuned checkpointing [34]. The contrast is *co-designed versus reassembled*, and reassembly demonstrably works; it is simply bought with integration effort that the co-designed stack amortized once.
- **Not** that TPUs win markets. Chips compete on many axes; this hypothesis prices exactly one — the allocation layer — and observes that the vertically integrated stack got it structurally, while everyone else buys it piecewise.
- **Not** a single-number availability claim for OCS. The TPU v4 paper gives goodput-versus-availability curves and tolerance ranges, quoted above, not one headline percentage [28].

## Why it matters for anyone building an AI-compute venture

For an operator bringing hundreds of megawatts online, the hypothesis converts into a design rule: **treat the scheduler, the fabric, and the power envelope as one co-designed system, planned together with customer workload demand — not as layers procured separately.** The capacity dividend measured in this repository is the floor of what that integration is worth; the TPU stack is the demonstration of its ceiling.
