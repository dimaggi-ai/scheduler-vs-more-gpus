# Scheduled Capacity: The Allocation Layer Decides How Much of a GPU Fleet Is Real

**Margaret Nanyonga**, DIMAGGI AI

> Research whitepaper. Bracketed citations resolve to [REFERENCES.md](../REFERENCES.md). The prose is hand-maintained; marked numerical blocks are generated from the committed [36-run CSV](../results/results.csv). Run `python3 sim/run.py`, then `python3 tools/sync_research.py --write` and review the surrounding interpretation. `python3 tools/sync_research.py --check --verify-run` checks publication consistency and regenerates CSV/summary in temporary storage. PNG rendering can differ across Matplotlib/font versions.

## Abstract

Accelerators, power and interconnect bound a fleet's potential capacity; allocation policy influences how much becomes useful work. This study separates scheduler availability *A*, allocation efficiency *E*, and productive ratio *P*, then compares three modeled policies on the same synthetic workload and event stream. External studies provide context and selected assumptions, not direct validation of the simulated performance gains.

<!-- research:headline:begin -->
**Corrected experiment (offered-load correction: 2026-09-10):** on a simulated 1,024-GPU cluster over 30 days, with a public-research-informed synthetic workload, power constraints, failures and demand surges (S4), the intent policy realizes **83.7%** of the available envelope versus **74.6%** for rigid FIFO. The difference is **~64,267 modeled productive GPU-hours (~89.3 continuously productive GPU equivalents)**. These are modeled output differences, not GPUs purchased or production savings. The comparison bundles reservation tracking and elasticity; it does not isolate their causal contributions.
<!-- research:headline:end -->

Inference SLO attainment improves in this scenario, while training incurs additional resizing and graceful preemption. These service outcomes and costs are reported together. The results support testing allocation policy before expanding capacity; they do not establish a universal return on investment or justify substituting interruptible work for guaranteed service.

## 1. Introduction

A fleet's nominal accelerator-hours are an upper bound. A consistent accounting window can distinguish whether the allocation plane can admit and place work (*A*), what share of schedulable accelerator-hours is assigned (*E*), and what share of assigned hours produces forward progress (*P*). `nominal × A × E × P` is an accounting decomposition when these denominators nest. It does not require statistically independent factors, and it must not multiply unrelated metrics from different fleets or populations.

Harvard FASRC's August 2026 emergency scheduler patch paused a roughly 1,000-GPU cluster for about 3.7 hours [4a, 4b]. By contrast, Alibaba's ASI reports allocation of about 68% for high-priority (HP) jobs and about 93% when lower-priority (LP) jobs are included [37, §3.3/Fig. 9]. LP work is interruptible and can be preempted when HP work reclaims resources [37, §4.2]. The two percentages describe different priority-class coverage, not a like-for-like before/after increase in guaranteed capacity. Nor is allocation a measurement of productive GPU-hours or revenue.

The metrics must remain distinct:

- **Allocation ratio:** share of the defined fleet's accelerator-hours assigned to the included job classes. The Alibaba HP-only and HP+LP values have different class coverage.
- **Hardware utilization:** device activity while allocated; this depends on the measurement method. Microsoft's Philly trace reports a mean near 52% [35]. Such a device-level measure does not alone establish useful model progress.
- **Productive/allocated ratio P:** useful progress divided by allocated accelerator-hours in this framework. The simulator exposes training's version under the historical CSV/API name `train_ettr`; its denominator excludes time waiting unallocated.
- **Meta ETTR:** productive training time divided by scheduled time plus eligible queue waiting time [34, §II-D]. It is not P. MFU, goodput and ETTR also have distinct definitions; they cannot be grouped into a universal multiplicative factor.

## 2. The allocation plane is where clusters can break

Published incident records show control-plane failures as well as hardware-triggered amplification. SchedMD's tracker warned in 2016 that user queries could overload the controller [8, 9]; a workflow manager issuing roughly 1,000 concurrent accounting polls disrupted a site's Slurm database [11]; Harvard FASRC recorded scheduler degradation in June 2023 with no publicly identified root cause [2, 3], an oversized accounting query exhausting database-host memory in May 2026 [1], and the August 2026 emergency patch above [4a]. At Meta, one node failure caused a 1,024-GPU job to be requeued 35 times, causing 548 preemptions of other jobs [34].

The allocation plane can originate losses or amplify an underlying failure. Harvard's May 2026 postmortem also asks users to limit AI-agent queries [1]. Agent-generated scans and polling motivate enforced query bounds, rate budgets, scoped access and separation of observation from allocation. These are general design requirements; this experiment does not evaluate a particular enforcement product.

## 3. Model and correction provenance

A discrete-event simulator steps a 1,024-GPU cluster in 5-minute increments for 30 days. The workload is synthetic and informed by Meta's reported job-size shape — many small jobs and a large-job share of GPU-time [34] — rather than a replay of Meta's production trace. Four scenarios are defined independently: **S1** steady state; **S2** daily 4-hour power contraction to 75%; **S3** node failures using Meta's published RSC-1 input rate; **S4** power contraction, failures and inference surges together. Three policies face the same seeded jobs and events:

- **rigid-fifo:** FIFO plus backfill, rigid sizes, no preemption, an inference reservation sized to the diurnal peak plus 5%; emergency-kills the newest jobs when necessary to meet the power envelope. This models a conservative configuration, not a benchmark of a Slurm binary.
- **tiered-preemption:** adds priority tiers and graceful checkpoint-preemption. Sizes and inference reservations remain fixed.
- **intent-closed-loop:** a 15-minute controller tracks inference demand with 10% headroom, shrinks elastic training jobs before escalating to graceful preemption, and uses a declared class hierarchy under scarcity.

The 10 September 2026 correction (`2d5f364`) fixed the arrival-rate calculation: the duration parameters are lognormal medians, not means. The expected GPU-hours per capped-lognormal job rose from 199.648 to approximately 268.317 for rate-setting purposes, removing about 34.4% unintended overload. That commit regenerated CSV, summary and figures and updated the README, but did not update this hand-maintained paper. No prior generator or CI check compared the paper with those artifacts. The corrected results below now use generated numerical blocks and a consistency check. Comparisons subtract means before rounding; subtracting separately rounded display totals can differ by one GPU-hour.

Conservation, deterministic seeds and policy contracts are tested in `sim/test_sim.py`. The three-seed mean is descriptive of these runs; it is not a production confidence interval.

## 4. Results

Means over seeds 42–44; the complete grid is in [results/summary.md](../results/summary.md). Capacity realization means productive GPU-hours divided by the power/failure-constrained available envelope, not nominal fleet capacity.

<!-- research:s4-table:begin -->
| Scenario S4 (power + failures + surges) | rigid-fifo | tiered-preemption | intent-closed-loop |
|---|---|---|---|
| Capacity realization | 0.746 | 0.747 | 0.837 |
| Inference SLO attainment | 0.968 | 0.968 | 0.998 |
| Training productive / allocated GPU-h (legacy `train_ettr` field) | 0.906 | 0.915 | 0.895 |
| Stranded GPU-h / month | 179,424 | 178,375 | 115,156 |
| — of which reservation waste | 67,416 | 67,416 | 21,154 |
| Kills / preemptions / resizes | 289 / 0 / 0 | 28 / 203 / 0 | 28 / 219 / 1083 |
| Mean started-job wait (h) | 1.3 | 1.2 | 1.5 |
<!-- research:s4-table:end -->

<!-- research:scenario-gains:begin -->
**(1) Scenario means.** Intent exceeds rigid FIFO by 7.8 percentage points in steady state, 9.2 under power contraction, 8.8 under failures, and 9.1 in S4 (differences of the three-seed means before display rounding). The ordering holds across these four scenario means, including S1 without failures, contraction or surges. This is a result for the stated synthetic workload, not a universal policy ranking.
<!-- research:scenario-gains:end -->

<!-- research:reservation:begin -->
**(2) Reservation accounting.** S4 reservation waste falls from 67,416 to 21,154 GPU-hours; the difference before display rounding is 46,262.3 GPU-hours. This component of the ledger does not by itself identify a causal contribution: the policies also differ in elasticity and admission. The separate `sim/sensitivity.py` factorial experiment varies demand tracking and elasticity within the intent mechanism; those outputs remain conditional simulations.
<!-- research:reservation:end -->

**(3) Inference behavior.** The static policies reserve the diurnal peak plus 5%, which the modeled surges exceed by construction. Covering all those surges statically would increase standing reservations. The demand-tracking policy follows the surge. This is an aggregate-demand experiment; it does not measure request-level latency or prove a production inference SLO.

<!-- research:tradeoffs:begin -->
**(4) Costs and service outcomes.** In S4 the intent policy performs 1,083 resizes and 219 graceful preemptions, versus 203 preemptions for tiered. Its training productive/allocated ratio is 0.895 versus 0.906/0.915; mean started-job wait is 1.5 h versus 1.3/1.2 h. The wait metric excludes jobs that never started. These tradeoffs require workload-specific judgment; the experiment does not establish that additional churn is always worth its cost.
<!-- research:tradeoffs:end -->

<!-- research:tiers:begin -->
**(5) Priority tiers in this workload.** Graceful preemption reduces S4 emergency kills from 289 to 28, while capacity realization changes from 0.746 to 0.747. Fixed inference reservations remain unchanged. The modeled failures affect all policies; this comparison does not establish that production failure losses are negligible.
<!-- research:tiers:end -->

## 5. Architectural context

Carrier-network work describes a related control pattern: identify resource-heavy and service-impaired users, shape the heavy users, measure service outcomes and repeat [40, 41]. Training and inference suggest an analogous scheduling problem, with different latency requirements, checkpoint behavior and resource demand. That analogy motivates the modeled controller; it does not establish novelty or show that network policies transfer without adaptation.

Borg documents priority bands, admission and preemption [25]. TPU v4's reconfigurable optical fabric changes placement constraints [28], while queued resources, Spot and Dynamic Workload Scheduler expose scheduling choices as cloud services [31–33]. These examples motivate joint consideration of hardware, fabric, workload and allocation. They do not make this simulation a comparison of vendors or accelerator generations.

## 6. Validation and its boundaries

The nine-point registry (`sim/validation.py`) distinguishes pinned assumptions, internally emergent behavior and arithmetic sanity checks. It pins the synthetic job-count shape and the RSC-1 failure-rate input; the large-job GPU-time share is an internal calculation of the capped-lognormal generator, not an external calibration score. A broad training-productivity smoke band catches changes to checkpoint arithmetic, but it is not calibration against Meta ETTR: the denominators differ. Meta's reported ETTR near 0.9 for high-priority, multi-day 2,048–4,096-GPU runs uses Daly–Young optimal checkpoint intervals and assumed restart/write overhead [34, Fig. 9/Observation 10], whereas this simulator fixes a one-hour checkpoint interval. Similar numbers do not establish equivalent metrics or shared checkpoint assumptions.

The emergent checks cover the direction of large-job queueing delays and the intent-versus-rigid ordering across the validation seeds. Philly supplies contextual evidence for queueing/fragmentation [35]; its observed magnitudes are not calibration targets here. Alibaba's HP/LP allocation accounting [37] is context for filling available resources with interruptible work, not causal validation of this simulator's policy difference. Sanity checks cover graceful versus emergency preemption, increasing queueing with offered load, and reservation arithmetic under equal modeled SLOs.

The registry prints a **DECLINED** list: it does not constrain the failure model's predictive accuracy, establish the production magnitude of a policy gain, validate real scheduler software, or establish request latency, topology-aware placement or multi-tenant fairness. Eight negative controls deliberately break selected assumptions or comparisons and require the corresponding checks to fail. Passing proves those checks are sensitive to those faults, not that the full model is valid. The separate factorial sensitivity experiment makes tracking/elasticity interactions inspectable; its magnitudes remain synthetic scenario outcomes.

## 7. What a skeptic should attack

The simulator measures conditional policy behavior. Time advances in 5-minute steps. Elastic scaling is linear, though resizing incurs an overhead step. Graceful preemption checkpoints at zero additional cost at the instant of preemption; emergency kills lose uncheckpointed work. These are optimistic abstractions. The static reservation intentionally covers diurnal peaks rather than rare surges. Inference is aggregate demand rather than per-request latency, node placement is abstracted, and the cluster is single-tenant. Mean waits omit never-started jobs. Cross-site rankings, production savings, guaranteed capacity and the economics of actual deployment remain unproven.

## 8. Conclusion

The corrected experiment shows a modeled capacity advantage from the combined intent policy under the stated workload and assumptions, alongside improved aggregate inference attainment and additional training churn. It supports measuring allocation losses and evaluating scheduling alternatives before purchasing more hardware. A deployment decision still needs representative traces, placement and network constraints, service-class guarantees, implementation cost and failure/recovery evidence. Interruptible allocation, productive progress and guaranteed customer capacity must remain separate in that decision.
