# References

All claims in this repository trace to the sources below. Items were verified against primary sources in August 2026; where a figure could only be confirmed via a secondary source, that is noted.

## Primary incident sources (Harvard FASRC)

- **[1]** Harvard FASRC status page, **"Cannon cluster down"** (May 29 – June 1, 2026). Root-cause statement: "Slurm crashed on 4:30p on Friday due to a user running a large sacct query against the Slurm database. This caused the database host to run out of memory and crash the scheduler. ... Please also ensure any AI agents you have running limit their queries appropriately." https://status.rc.fas.harvard.edu/default/cmprdafwo01e3qcjd4vhq0so9
- **[2]** Harvard FASRC status page, **"Slurm scheduler slowness/delays"** (June 13–20, 2023): ~6.5 days of scheduler slowness, failed submissions, and timeouts. https://status.rc.fas.harvard.edu/cliudds2w6101942tng0n8sn82v
- **[3]** Harvard FASRC, **"Emergency maintenance 6/20/23 – Cannon Slurm Scheduler"**: scheduler "oscillating between two states every hour"; "the root cause is still not known." https://status.rc.fas.harvard.edu/cliz0a0ed62418xfn0bx7sz38i
- **[4]** Harvard FASRC, Cluster Computing service page (Cannon/FASSE/Kempner aggregate figures; Cannon-proper: 99,900+ CPU cores, 1,000+ GPUs). https://www.rc.fas.harvard.edu/services/cluster-computing/
- **[4a]** Harvard FASRC status page, **"Emergency Slurm (scheduler) patch"** (August 18, 2026): cluster-wide pause to patch a Slurm memory-leak bug; ~3.7 h major outage (8:15–11:57 AM); "A number of jobs appear to have terminated during the upgrade." https://status.rc.fas.harvard.edu/cmsyt151c00bo0lmzmqhy77c4
- **[4b]** SchedMD bug **25685** (Slurm memory leak; fixed in 26.05.3). https://support.schedmd.com/show_bug.cgi?id=25685

## Slurm / SchedMD primary documentation and tickets

5. slurm.conf man page — `MaxDBDMsgs`: "The default value is 10000, or MaxJobCount * 2 + Node Count * 4, whichever is greater." https://slurm.schedmd.com/slurm.conf.html
6. slurmdbd.conf man page — `MaxQueryTimeRange` (3 GiB / ESLURM_RESULT_TOO_LARGE note), `PurgeJobAfter` / `PurgeStepAfter` ("If not set (default), then job [step] records are never purged."), `CommitDelay`. https://slurm.schedmd.com/slurmdbd.conf.html
7. Slurm source — `src/common/pack.h` (`REASONABLE_BUF_SIZE`, ≈3 GiB) and `src/plugins/accounting_storage/slurmdbd/slurmdbd_agent.c` ("agent queue is full (%u), discarding"). https://github.com/SchedMD/slurm
8. SchedMD bug **2346** (2016): "slurmdbd may exceed MAX_BUF_SIZE on responses... badly envisioned queries run by users can DoS the box" — fixed in 17.11.0-pre3. https://support.schedmd.com/show_bug.cgi?id=2346
9. SchedMD bug **2845** (2016): "slurmdbd and mysqd crash with large sreports / sacct." https://support.schedmd.com/show_bug.cgi?id=2845
10. slurm-users thread (2019): "agent queue is full (20140), discarding DBD_STEP_COMPLETE" — example of a site-computed MaxDBDMsgs value. https://groups.google.com/g/slurm-users/c/rbq82H_HaLc
11. ComparativeGenomicsToolkit/cactus issue #67 (2019): ~1,000 concurrent `sacct` processes "crashed our SLURM db" — concurrency-swamping load shape. https://github.com/ComparativeGenomicsToolkit/cactus/issues/67

## MariaDB documentation

12. MariaDB — Aborting statements that exceed a certain time to execute (`max_statement_time`, default 0 = unlimited). https://mariadb.com/docs/server/ha-and-performance/optimization-and-tuning/query-optimizations/aborting-statements
13. MariaDB — Server system variables (`tmp_table_size`, `max_heap_table_size`, both default 16 MB; overflow to on-disk temporary tables). https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables

## Slurm-on-Kubernetes and Kubernetes-native batch

14. SchedMD Slinky — slurm-operator (v1.2.1, July 2026; CRDs: accountings, loginsets, nodesets, restapis, tokens). https://github.com/SlinkyProject/slurm-operator · https://slinky.schedmd.com/docs/
15. SchedMD Slinky — slurm-bridge (Kubernetes scheduler delegating placement decisions to Slurm). https://github.com/SlinkyProject/slurm-bridge
16. NVIDIA acquisition of SchedMD (announced December 15, 2025). https://blogs.nvidia.com/blog/nvidia-acquires-schedmd · analysis: https://www.hpcwire.com/2026/01/06/what-does-nvidias-acquisition-of-schedmd-mean-for-slurm/
17. CoreWeave SUNK (Slurm on Kubernetes) and SUNK Anywhere (April 30, 2026; vendor claims: up to 96% goodput, 97–98% ETTR). https://www.coreweave.com/products/sunk · https://www.coreweave.com/news/coreweave-sunk-expands-capabilities-to-bring-ai-workloads-online-faster-anywhere
18. AWS Containers blog, "Running Slurm on Amazon EKS with Slinky" (October 14, 2025). https://aws.amazon.com/blogs/containers/running-slurm-on-amazon-eks-with-slinky/
19. Kueue (v0.19.2, Aug 2026; all-or-nothing admission; Topology-Aware Scheduling beta). https://github.com/kubernetes-sigs/kueue · https://kueue.sigs.k8s.io/docs/concepts/topology_aware_scheduling/
20. Volcano (v1.15.1, Jul 2026; gang-aware preemption, network-topology-aware scheduling). https://github.com/volcano-sh/volcano/releases · https://volcano.sh/docs/userguide/user_guide_how_to_use_network_topology_aware_scheduling/
21. NVIDIA KAI Scheduler (ex-Run:ai engine, open-sourced April 2025, CNCF Sandbox; v0.17.0 Aug 2026). https://github.com/NVIDIA/KAI-Scheduler · https://developer.nvidia.com/blog/nvidia-open-sources-runai-scheduler-to-foster-community-collaboration/
22. Nebius Soperator (open-source Slurm-in-K8s operator, Sept 2024). https://github.com/nebius/soperator

## Multi-cloud federation

23. SkyPilot (v0.13.0, July 2026; K8s, Slurm, hyperscalers, ~20 neoclouds; company + platform launch July 2026). https://pypi.org/project/skypilot/ · https://skypilot.ai/blog/skypilot-the-company · production case: https://shopify.engineering/skypilot
24. dstack (0.21.0, Aug 2026; NVIDIA/AMD/TPU/Tenstorrent across clouds, K8s, SSH fleets). https://github.com/dstackai/dstack

## Google TPU / Borg stack

25. Verma et al., "Large-scale cluster management at Google with Borg," EuroSys 2015. Priority bands, quota admission, cascade-suppressed preemption. https://research.google/pubs/large-scale-cluster-management-at-google-with-borg/
26. Tirmazi et al., "Borg: the Next Generation," EuroSys 2020. https://dl.acm.org/doi/10.1145/3342195.3387517
27. Barham et al., "Pathways: Asynchronous Distributed Dataflow for ML," MLSys 2022. arXiv:2203.12533.
28. Jouppi et al., "TPU v4: An Optically Reconfigurable Supercomputer for Machine Learning with Hardware Support for Embeddings," ISCA 2023. arXiv:2304.01433. (Scheduling-contiguity and goodput-vs-availability results.)
29. Poutievski et al., "Jupiter Evolving: Transforming Google's Datacenter Network via Optical Circuit Switches and Software-Defined Networking," SIGCOMM 2022. (Refereed OCS deployment; the "Mission Apollo" arXiv:2208.10041 preprint is unrefereed.)
30. Jouppi et al., "Google's Training Supercomputers from TPU v2 to Ironwood," IEEE Micro, Jul/Aug 2026. arXiv:2606.15870.
31. Google Cloud docs: TPU Multislice (https://docs.cloud.google.com/tpu/docs/multislice-introduction) · Queued resources (…/queued-resources) · Spot TPUs (…/spot) · TPU system architecture / ICI resiliency (…/system-architecture-tpu-vm) · ML Goodput (…/goodput).
32. Google Cloud blog, "Introducing Dynamic Workload Scheduler" (Dec 2023): "built on Google Borg technology"; supports TPUs and NVIDIA GPUs. https://cloud.google.com/blog/products/compute/introducing-dynamic-workload-scheduler
33. Google Cloud blog, "Cluster reliability for trillion parameter models on TPUs" (May 11, 2026). https://cloud.google.com/blog/products/compute/cluster-reliability-for-trillion-parameter-models-on-tpus

## Empirical cluster studies (utilization & reliability)

34. Kokolis et al. (Meta), "Revisiting Reliability in Large-Scale Machine Learning Research Clusters," arXiv:2410.21680 (v2 Feb 2025). RSC-1 16k / RSC-2 8k A100s; 11 months; 4M jobs; 150M+ GPU-hours; ETTR ~0.9 on multi-day 2–4k-GPU runs; failure rates 6.50 / 2.34 per 1,000 node-days; MTTF projections. Also cited from this paper: a 1,024-GPU job requeued 35 times after a node failure, causing 548 preemptions of other jobs; health checks every 5 minutes; lemon-node detection cutting large-job failure rates from 14% to 4%; job-size distribution (most jobs small, most GPU-time in large jobs) used to calibrate this repo's simulator.
35. Jeon et al. (Microsoft), "Analysis of Large-Scale Multi-Tenant GPU Clusters for DNN Training Workloads," USENIX ATC 2019 / MSR-TR-2018-13 (Philly trace; ~52% average hardware utilization of in-use GPUs). https://www.usenix.org/conference/atc19/presentation/jeon
36. Weng et al. (Alibaba), "MLaaS in the Wild," NSDI 2022 (PAI trace; median GPU utilization 4.2% — figure re-verification against primary PDF pending). https://www.usenix.org/conference/nsdi22/presentation/weng
37. Li et al. (Alibaba), "Heterogeneity at Hyperscale," OSDI 2026 (ASI; 155,410 GPUs; allocation ratio raised 68%→93% by scheduler-side work; attributes idle-while-allocated capacity to fragmentation, CPU/GPU-ratio mismatch, and network-locality constraints; cluster-trace-gpu-v2026). https://www.usenix.org/conference/osdi26/presentation/li-suyi · https://github.com/alibaba/clusterdata
38. Biewald (Weights & Biases), GPU-usage telemetry article (≈⅓ of users under 15% utilization), 2019. https://wandb.ai/wandb_fc/articles/reports/Monitor-Improve-GPU-Usage-for-Model-Training--Vmlldzo1NDQzNjM3
39. ClearML / FuriosaAI / AI Infrastructure Alliance, "The State of AI Infrastructure at Scale 2024." https://clear.ml/blog/the-state-of-ai-infrastructure-at-scale-2024

## Telecom prior art (patents)

40. US 2020/0112876 A1, "Method and System for Application Aware Congestion Management" (Sandvine; granted as US 11,297,527 B2). Heavy-user/suffering-user closed-loop shaping.
41. US 11,128,536 B2, "System and Method for Intent Based Traffic Management" (Sandvine). Intent → per-class min/target allocation → QoE feedback loop → hierarchical priority under scarcity.

## Power- and carbon-aware scheduling

42. Radovanović et al., "Carbon-Aware Computing for Datacenters," arXiv:2106.11750; and Google blog, "Our data centers now work harder when the sun shines and wind blows" (Apr 2020). https://blog.google/inside-google/infrastructure/data-centers-work-harder-sun-shines-wind-blows/
43. NVIDIA newsroom, "NVIDIA and Emerald AI Join Leading Energy Companies to Pioneer Flexible AI Factories as Grid Assets" (Oct 29, 2025; 96-MW Aurora AI Factory; Phoenix demo: 256 GPUs, −25% power at grid peak). https://nvidianews.nvidia.com/news/nvidia-and-emerald-ai-join-leading-energy-companies-to-pioneer-flexible-ai-factories-as-grid-assets
44. "A Survey on Task Scheduling in Carbon-Aware Container Orchestration," arXiv:2508.05949 (2025). Related: arXiv:2605.03751 (compute–power co-scheduling, 2026); arXiv:2412.17484 (power- and fragmentation-aware GPU scheduling); arXiv:2605.24569 ("Energy-Aware Computing in the Year 2026").
