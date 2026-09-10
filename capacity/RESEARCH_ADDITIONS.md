# Evidence and workload additions — 2026-09-10

## Corrected scheduling experiment

The generator samples capped lognormal durations. Its medians are not its
means. Expected work is now 268.317 GPU-hours/job rather than 199.648, so
the arrival rate realizes the declared offered load in expectation. The
previous rate offered about 34.4% more work than intended.

Reproduce the corrected headline with `python sim/run.py`; run the factorial
ablation with `python sim/sensitivity.py`. The latter holds the intent
admission/preemption mechanism fixed and toggles tracking and elasticity
independently: 12 seeds, three offered loads, three power fractions, four
policy cells. These are scenario sensitivity ranges, not empirical confidence
intervals. Results include interactions, not an assumption of additive gains.

## External workload evidence

`philly.py` reads the original Microsoft Research Philly archive, verifies its
published Git LFS SHA-256, and compares attempt-size distributions before and
after 2017-11-20. Calibration also excludes attempts completing after the
cutoff, preventing future-completion leakage. It reports missing/censored attempts rather than silently
imputing them. Allocated hours are never relabeled as productive hours.

Source: [Microsoft Research Project Fiddle, Philly traces](https://github.com/msr-fiddle/philly-traces),
revision `29a1b87fa2d9ed80b83c9e3a37f3a88d382b031d`, accompanying *Analysis of
Large-Scale Multi-Tenant GPU Clusters for DNN Training Workloads*, ATC 2019.
The source trace is [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
`results/philly-validation.json` is a DIMAGGI-derived aggregate: timestamps
were partitioned, incomplete attempts excluded, and counts/durations summarized.
It is not an unchanged source dataset. No raw trace or user/job identifiers
are included in this repository.

Download the pinned archive from the `source` URL in the result, then run:

```
python -m capacity.philly /path/to/trace-data.tar.gz --out results/philly-validation.json
```

This trace does not validate the Meta-shaped workload or modern accelerator
goodput. In particular, Philly's size distribution and hardware population
differ; the comparison is evidence against a universal fixed workload mix.

## Inference service scenarios

`python -m capacity.inference_experiment` compares input/output lengths,
concurrency, assumed prefix reuse and two hypothetical hardware classes.
The single-device model serializes compute-bound prefill with batched decode,
reserves KV capacity, and measures TTFT and every inter-token gap in its
simulated event sequence. Only requests satisfying both SLOs contribute to
reported token goodput. Queueing and memory rejection are explicit.

The model is not externally calibrated. It omits quadratic prefill attention,
kernel overhead, tensor-parallel communication and cache-eviction dynamics.
Its outputs establish conditional service-model behavior, not achievable
production throughput or a vendor ranking. Cache reuse is an input; no running
prefix-aware router has been built.

## Reproduction environment

The engineering pass used Python 3.12, NumPy 2.2.6 for final integration tests,
pytest 8.3.4 and jsonschema 4.23.0. The earlier headline regeneration used the
audit environment's NumPy 2.5.3; source and environment receipts must be kept
with comparisons. `evidence.json` identifies the corrected headline scope.
