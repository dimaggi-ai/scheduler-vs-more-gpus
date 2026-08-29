# Allocation-Plane Patterns for AI Clusters

*Reference numbers point to [REFERENCES.md](../REFERENCES.md).*

An AI cluster runs three planes that fail differently and must be engineered separately:

- **Allocation plane** — the real-time scheduling loop: admission, placement, preemption, accounting writes. Latency-sensitive, state-critical.
- **Observation plane** — telemetry, historical accounting, dashboards, reports, and (increasingly) AI agents querying job state. Bursty, unbounded, user-driven.
- **Execution plane** — the workers: GPUs/TPUs, node agents, fabrics.

The industry buys the execution plane by the megawatt and audits it constantly. The two planes that decide whether that capital produces *usable* capacity get neither the architecture nor the governance attention. The patterns below are ordered from "stop the bleeding" to "the end state."

---

## Pattern 1 — Separate the observation plane from the allocation plane

**Problem.** Standard Slurm deployments route user analytics (`sacct`, `sreport`, dashboards) into the same database engine that the scheduler's control loop depends on for admission and accounting. An unbounded analytical query then competes for memory with the operational path.

**The failure class.** Documented in the vendor's own tracker since 2016: "badly envisioned queries run by users can DoS the box" (SchedMD bugs 2346, 2845 [8, 9]). It recurs across sites in two load shapes. The single oversized scan: most publicly at Harvard FASRC in May 2026, where one `sacct` query exhausted the Slurm database host's memory and crashed the scheduler [1]. And the polling storm: a workflow manager launching ~1,000 concurrent `sacct` processes "crashed our SLURM db" at another site entirely (Cactus/Toil, 2019 [11]).

**Pattern.** The primary database serves exactly one client: the scheduler's write path. Every read-for-analysis — CLI tools, dashboards, portals, agents — goes to an asynchronous read replica. A replica OOM is then an analytics outage, not a cluster outage. This is the OLTP/OLAP separation every mature database practice already mandates; HPC control planes simply never adopted it because accounting *feels* operational.

![Separating the observation plane from the allocation plane](../figures/plane_separation.svg)

---

## Pattern 2 — Govern the observation plane

**Problem.** Even a separated observation plane can be starved by unbounded queries — and the defaults are unbounded: Slurm never purges job or step records unless configured (`PurgeJobAfter`/`PurgeStepAfter` unset by default [6]); MariaDB's `max_statement_time` defaults to 0 (no limit) and its in-memory temp-table thresholds to 16 MB before silent spill to disk [12, 13]. Response caps exist (≈3 GiB, `ESLURM_RESULT_TOO_LARGE` since Slurm 17.11 [6, 7]) but bound the *reply*, not the memory burned computing it.

**Pattern.** Defense in depth on every query path: statement execution timeouts; bounded query time-ranges; retention and purge schedules so tables stay operational-sized; admission limits on query concurrency. And a new clause: **agent governance**. Harvard's postmortem closes by asking users to "ensure any AI agents you have running limit their queries appropriately" [1] — a mainstream cluster postmortem naming autonomous agents as a load class on the control plane. Agents combine both dangerous load shapes (large scans *and* high-frequency polling), and "please be judicious" does not scale to non-human requesters; the bound must be enforced at the interface, by policy, not requested in a postmortem.

This is exactly the enforcement class a runtime policy firewall exists for. [Tool Guard](https://dimaggi.ai) — DIMAGGI's policy firewall for AI agents — sits between an agent and its tools, intercepting each tool call *before execution* and applying allow / deny / redact / escalate decisions against declared policy, with a hash-chained audit trail. Applied here: an agent's `sacct` invocation is checked against query-range ceilings, field scoping, and rate/concurrency budgets before it ever reaches the accounting daemon — and an out-of-policy sweep is bounded, escalated to a human, or rejected, rather than discovered in a postmortem. Postmortems ask humans to be judicious; a policy firewall makes judiciousness mechanical for the requesters that never read postmortems.

**Limit of this pattern.** Governance was Harvard's actual remedy — a 7-day query cap [1]. That contains the failure but taxes every legitimate user forever. Rate-limiting is what you do when you haven't separated the planes; it is a compensating control, not an architecture.

---

## Pattern 3 — Run the scheduler control plane as cattle

**Problem.** Bare-metal control planes recover at human speed, and their failures are opaque at human timescales. The two most fully documented public examples happen to come from one site: a 2023 scheduler degradation that ran ~6.5 days with the root cause never publicly identified [2, 3], and a 2026 crash resolved to "cluster back up" in ~52 minutes only because staff were available to act immediately on a Friday evening [1]. The condition is general — any site whose recovery path is "a human SSHes into the controller host" carries the same exposure.

**Pattern.** Run `slurmctld`, `slurmdbd`, and the database as supervised, declaratively-managed services on a Kubernetes substrate: liveness-probe restarts, persistent-volume reattachment, stable service endpoints so the scheduler never needs reconfiguration when a database pod moves or is resized, and cgroup limits that confine a memory blowup to the offending pod. This is now a supported first-class deployment mode, not an exotic hack: SchedMD's Slinky operator (v1.2.x, 2026) runs the Slurm control plane and workers on Kubernetes [14], with a bridge scheduler that lets Slurm keep making placement decisions [15]; CoreWeave's SUNK productized the same shape commercially [17]; AWS publishes a supported blueprint [18].

**Honest caveat.** Kubernetes does not prevent the OOM — it shrinks the blast radius and the MTTR. Pattern 1 prevents; Pattern 3 recovers.

---

## Pattern 4 — Schedule with topology and gang awareness

**Problem.** AI jobs are gangs: a 512-GPU training job needs all 512 GPUs, placed on the right fabric topology, or it needs none of them. Schedulers that admit partial gangs or ignore topology strand capacity through fragmentation — Alibaba's 155k-GPU study attributes idle allocated capacity to exactly this: fragmentation, CPU/GPU ratio mismatch, and network-locality constraints [37].

**Pattern.** All-or-nothing admission plus fabric-topology awareness in placement. The Kubernetes-native stack now ships both: Kueue's all-or-nothing admission with beta topology-aware scheduling [19], Volcano's gang-aware preemption and network-topology-aware placement down to InfiniBand fabric discovery [20], NVIDIA's KAI with gang scheduling and fractional-GPU consolidation [21].

**The hardware-level version is the TPU lesson.** Google attacked the same constraint below the scheduler: TPU v4's optical circuit switches let the scheduler compose a slice from *any* free 4³ blocks instead of finding contiguous chips — "The OCS also simplifies scheduling, which increases utilization. For TPU v3, a 256 chip slice meant the scheduler had to find 256 contiguous chips that were idle. For TPU v4, it can pick 4³ blocks from anywhere in the supercomputer" [28]. Reconfigurability turns fragmentation from a scheduling failure into a non-event.

---

## Pattern 5 — Allocate by intent, not by quota

**Problem.** Fair-share quotas answer "who deserves capacity," not "what does the business need this hour." They are static in a system whose demand (training vs inference mix), supply (failures, maintenance), and constraints (power price and availability) all move by the hour. The result is the well-documented gap between allocated and productive capacity [34–39] — and the policy machinery itself can strand capacity: Meta documents a single 1024-GPU job requeueing 35 times and inflicting 548 preemptions on other jobs, a cascade generated entirely by scheduling policy with no component failure [34].

**Pattern.** Carrier networks crossed this bridge a generation ago, and the mechanism is documented in the patent record: identify *heavy users* and *suffering users* and iteratively shape the heavy until the suffering recover (US 2020/0112876 [40]); let the operator declare *outcomes*, assign per-class floors and targets, measure quality continuously, and re-allocate in a closed loop with a strict degradation hierarchy under scarcity (US 11,128,536 [41]). Mapped to AI compute: training jobs are the heavy users — elastic, throughput-hungry, checkpointable, preemptible; inference is the suffering user — latency-bound and SLO-visible; the declared intent is training-throughput targets, inference SLOs, and cost/power envelopes; the feedback signal is goodput and SLO attainment rather than link QoE.

**Convergence evidence.** The scheduler ecosystem is already drifting this way: Google's Dynamic Workload Scheduler — "built on Google Borg technology," covering TPUs and GPUs — schedules against declared duration and start-flexibility rather than raw quota [32]; queued resources and Spot tiers express priority-for-price intent [31]; Borg itself has run priority bands with cascade-suppressed preemption since before 2015 [25]. What is still missing in the open stack is the closed loop: measured workload QoE driving continuous re-allocation. That is the gap this repository's simulator quantifies.

---

## Pattern 6 — Treat power as a schedulable resource

**Problem.** Power is now the binding constraint on AI capacity — and it is time-varying (grid peaks, curtailment, price) while schedulers treat it as a constant background fact. A cluster that cannot modulate its draw cannot be built where power is scarce, and wastes optionality where power is flexible.

**Pattern.** Make the power envelope an input to admission and placement: capacity that expands and contracts by hour, with workload classes mapped to it by intent (Pattern 5's degradation hierarchy decides *what* slows down when the envelope contracts — elastic training first, SLO-bound inference last). This is operational today, not speculative: Google's carbon-intelligent platform caps hourly cluster capacity with "Virtual Capacity Curves" and shifts flexible workloads accordingly [42]; NVIDIA and Emerald AI demonstrated a 256-GPU cluster cutting power 25% during a grid peak via workload orchestration alone, and announced a 96-MW power-flexible AI facility on the same model [43]. A growing research line formalizes the co-scheduling problem [44].

**Why it belongs in this list.** Power-aware allocation is the same closed-loop, intent-based machinery as Pattern 5 with one more constraint class. A scheduler that can degrade by declared intent can sell that capability upward as grid flexibility — which converts scheduling maturity directly into siting and capital advantages.

---

## The through-line

Patterns 1–3 make the allocation plane *survivable*. Pattern 4 makes it *efficient*. Patterns 5–6 make it *economic* — the layer where infrastructure strategy, workload demand, and power availability are planned as one system. Clusters that stop at survivability leave the difference on the table; the measurement of exactly how much is what the rest of this repository is for.
