# Control-plane incident case studies

Reference numbers point to [REFERENCES.md](../REFERENCES.md). These incidents are a plural evidence set for one claim: **the allocation plane, not the hardware, is where AI clusters lose capacity.** No single incident is the story; the recurrence is.

| # | Incident | Site | Year | Class | Refs |
|---|---|---|---|---|---|
| 1 | `sacct` query → database OOM → scheduler crash | Harvard FASRC | 2026 | Observation-plane load on the allocation path | [1] |
| 2 | Scheduler oscillation, ~6.5 days degraded, cause never public | Harvard FASRC | 2023 | Control-plane opacity, human-speed recovery | [2, 3] |
| 3 | ~1,000 concurrent `sacct` polls "crashed our SLURM db" | unnamed Slurm site (Cactus/Toil) | 2019 | Concurrency swamping by workflow automation | [11] |
| 4 | "agent queue is full (20140), discarding DBD_STEP_COMPLETE" | unnamed site (slurm-users list) | 2019 | Accounting-queue saturation during database loss | [10] |
| 5 | 1024-GPU job requeued 35× after a node failure, causing 548 preemptions of other jobs | Meta RSC | 2024 | Allocation-policy cascade (one fault, amplified by policy) | [34] |
| 6 | "badly envisioned queries run by users can DoS the box" | SchedMD tracker (bugs 2346, 2845) | 2016 | Vendor-known failure class, a decade early | [8, 9] |
| 7 | Emergency cluster-wide pause to patch scheduler memory leak (~3.7 h); upgrade terminated jobs | Harvard FASRC | 2026 | Scheduler defect + control-plane maintenance cost | [4a, 4b] |

Cases 1, 2, and 7 are expanded below; cases 3–6 are single-source incidents documented by their references in the table.

## Case 1 — the query that crashed a scheduler (Harvard, May 29 – June 1, 2026)

From the site's own status page [1], quoted directly:

- *Investigating (May 29, 8:21 PM UTC):* "The Slurm scheduler is experiencing an error which is impacting jobs. The Cannon cluster will be inaccessible while we troubleshoot."
- *Identified (9:13 PM UTC):* "we have reduced the maximum query time for sacct and other Slurm commands to be 1 day... The cluster is back up and the scheduler is accepting new jobs."
- *Resolved (June 1, 2:45 PM UTC):* "Slurm crashed on 4:30p on Friday due to a user running a large sacct query against the Slurm database. This caused the database host to run out of memory and crash the scheduler. To prevent this from reoccurring we are reducing the time range that users are permitted to query at one time to 7 days... Please also ensure any AI agents you have running limit their queries appropriately."

Three precise readings, because secondhand accounts of this incident vary:

1. **The hard outage was ~52 minutes; the degradation lasted days and the query caps are permanent.** (The 52 minutes is the status page's own span from "Investigating" at 8:21 PM UTC to "cluster is back up" at 9:13 PM UTC; Harvard's resolution note places the underlying crash at 4:30 PM local time, so the user-visible impact may have begun earlier than the page's first update.) "Multi-day downtime" overstates the crash; "under an hour, no big deal" understates the aftermath. The honest accounting: a sub-hour outage bought with immediate staff response on a Friday evening, plus a lasting tax on every user's observability.
2. **The remedy was governance, not architecture.** Query-range caps contain the failure but tax legitimate use forever — the compensating control you deploy when the observation plane and the allocation plane share a database (pattern 1).
3. **The postmortem names AI agents as a load class.** "Please ensure any AI agents you have running limit their queries appropriately" is a request; for non-human requesters the bound must be *enforced* at the interface (pattern 2).

The mechanism was vendor-documented ten years earlier: Slurm's accounting responses are capped at ~3 GiB (`ESLURM_RESULT_TOO_LARGE`, since 17.11 [6, 7]) — but that caps the *reply*, not the memory burned computing it, which is what OOM'd (SchedMD bugs 2346, 2845 [8, 9]). Defaults still ship unbounded: records never purged, `max_statement_time` unlimited, 16 MB temp-table thresholds before silent disk spill [6, 12, 13].

## Case 2 — six days of unexplained degradation (Harvard, June 13–20, 2023)

Scheduler slowness, failed submissions, and timeouts for ~6.5 days [2]; the companion emergency-maintenance page describes the scheduler "oscillating between two states every hour" and states "the root cause is still not known" while working with the vendor [3]. A separate lesson from Case 1: control planes can degrade for a *week* without a public root cause. Note this is a **different incident** from Case 1 — some circulated accounts have conflated the two (the 2023 pages never mention `sacct`, the database, or OOM).

## Case 7 — the maintenance tax (Harvard, August 18, 2026)

"We have been manually dealing with a Slurm memory leak bug behind the scenes and now have an official fix in the form of a Slurm upgrade (26.05.3)" [4a; the bug is SchedMD 25685, 4b]. The patch required pausing the entire cluster — ~3.7 hours of major outage across all compute (8:15–11:57 AM) — and afterward: "A number of jobs appear to have terminated during the upgrade for some reason." Even *fixing* the control plane costs fleet-wide capacity, and on bare metal it costs it all at once.

## What the set adds up to

- Three disruptions at one well-run academic site in 38 months — none involving compute-hardware failure.
- The same failure class at unrelated sites (cases 3, 4) and inside a hyperscaler's allocation policy itself (case 5).
- A vendor tracker that called it in 2016 (case 6).

The allocation plane is a system in production serving adversarially-shaped load (including, now, autonomous agents) with database defaults from a gentler era, recovering at human speed. Treating it with the engineering seriousness reserved for the data plane is the cheapest capacity you will ever buy — the quantitative version of that claim is the [simulator](../sim/) and [calculator](../calculator/).
