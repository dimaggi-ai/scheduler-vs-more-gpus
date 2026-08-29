# Simulation results summary

1,024-GPU cluster, 30 days, seeds [42, 43, 44] (values are means across seeds).
Full per-run data in results.csv. Reproduce: `python3 sim/run.py`.

| Scenario | Policy | Capacity realization | Inference SLO | Train ETTR | Stranded GPU-h | ...idle | ...reservation | ...overhead+lost | Preempts | Kills | Resizes | Mean wait h |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-steady | rigid-fifo | 0.776 | 1.000 | 0.921 | 165,405 | 63,119 | 70,560 | 31,726 | 0 | 0 | 0 | 1.9 |
| S1-steady | tiered-preemption | 0.776 | 1.000 | 0.921 | 165,405 | 63,119 | 70,560 | 31,726 | 0 | 0 | 0 | 1.9 |
| S1-steady | intent-closed-loop | 0.861 | 1.000 | 0.910 | 102,215 | 39,118 | 20,505 | 42,593 | 173 | 0 | 1006 | 1.7 |
| S2-power | rigid-fifo | 0.781 | 1.000 | 0.911 | 154,934 | 50,224 | 70,560 | 34,150 | 0 | 347 | 0 | 2.5 |
| S2-power | tiered-preemption | 0.789 | 1.000 | 0.920 | 149,304 | 47,938 | 70,560 | 30,806 | 278 | 0 | 0 | 2.8 |
| S2-power | intent-closed-loop | 0.856 | 1.000 | 0.898 | 101,480 | 34,927 | 20,505 | 46,048 | 393 | 0 | 1241 | 4.5 |
| S3-failures | rigid-fifo | 0.766 | 1.000 | 0.917 | 172,053 | 68,531 | 70,560 | 32,962 | 0 | 26 | 0 | 1.2 |
| S3-failures | tiered-preemption | 0.766 | 1.000 | 0.917 | 172,053 | 68,531 | 70,560 | 32,962 | 0 | 26 | 0 | 1.2 |
| S3-failures | intent-closed-loop | 0.857 | 1.000 | 0.907 | 105,142 | 40,415 | 20,505 | 44,222 | 71 | 26 | 1048 | 1.1 |
| S4-full | rigid-fifo | 0.778 | 0.968 | 0.908 | 156,452 | 54,000 | 67,416 | 35,036 | 0 | 359 | 0 | 2.0 |
| S4-full | tiered-preemption | 0.779 | 0.968 | 0.916 | 155,892 | 56,960 | 67,416 | 31,516 | 263 | 28 | 0 | 1.8 |
| S4-full | intent-closed-loop | 0.858 | 0.998 | 0.898 | 100,354 | 33,834 | 21,154 | 45,366 | 438 | 28 | 1232 | 3.8 |
