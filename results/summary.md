# Simulation results summary

1,024-GPU cluster, 30 days, seeds [42, 43, 44] (values are means across seeds).
Full per-run data in results.csv. Reproduce: `python3 sim/run.py`.

| Scenario | Policy | Capacity realization | Inference SLO | Train ETTR | Stranded GPU-h | ...idle | ...reservation | ...overhead+lost | Preempts | Kills | Resizes | Mean wait h |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-steady | rigid-fifo | 0.749 | 1.000 | 0.921 | 185,006 | 84,527 | 70,560 | 29,920 | 0 | 0 | 0 | 2.1 |
| S1-steady | tiered-preemption | 0.749 | 1.000 | 0.921 | 185,006 | 84,527 | 70,560 | 29,920 | 0 | 0 | 0 | 2.1 |
| S1-steady | intent-closed-loop | 0.827 | 1.000 | 0.908 | 127,286 | 65,228 | 20,505 | 41,553 | 15 | 0 | 810 | 0.9 |
| S2-power | rigid-fifo | 0.742 | 1.000 | 0.911 | 182,508 | 80,393 | 70,560 | 31,554 | 0 | 249 | 0 | 1.4 |
| S2-power | tiered-preemption | 0.745 | 1.000 | 0.920 | 180,042 | 81,417 | 70,560 | 28,065 | 198 | 0 | 0 | 1.3 |
| S2-power | intent-closed-loop | 0.834 | 1.000 | 0.896 | 117,258 | 51,439 | 20,505 | 45,314 | 182 | 0 | 1031 | 1.4 |
| S3-failures | rigid-fifo | 0.735 | 1.000 | 0.914 | 194,839 | 92,462 | 70,560 | 31,817 | 0 | 26 | 0 | 1.0 |
| S3-failures | tiered-preemption | 0.735 | 1.000 | 0.914 | 194,839 | 92,462 | 70,560 | 31,817 | 0 | 26 | 0 | 1.0 |
| S3-failures | intent-closed-loop | 0.824 | 1.000 | 0.902 | 129,897 | 65,452 | 20,505 | 43,940 | 33 | 26 | 794 | 0.8 |
| S4-full | rigid-fifo | 0.746 | 0.968 | 0.906 | 179,424 | 78,521 | 67,416 | 33,487 | 0 | 289 | 0 | 1.3 |
| S4-full | tiered-preemption | 0.747 | 0.968 | 0.915 | 178,375 | 81,130 | 67,416 | 29,829 | 203 | 28 | 0 | 1.2 |
| S4-full | intent-closed-loop | 0.837 | 0.998 | 0.895 | 115,156 | 48,723 | 21,154 | 45,280 | 219 | 28 | 1083 | 1.5 |
