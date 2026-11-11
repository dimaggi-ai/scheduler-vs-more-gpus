# Prediction and observation comparison reference

Maggie's offline product-domain reference, 19 September 2026. No calibration fit,
collector, scheduler, authorization or new physical model is implemented.

`capacity.calibration_evidence.compare_pair` consumes exactly one model prediction,
one observation, an explicit same-unit absolute tolerance and `as_of_utc`. The
template in `calibration_input_template.json` is deliberately incomplete. It is
an intake proposal, not a production wire schema. Do not fill it with demo values.

Each record has exactly `context`, `value`, `unit`, `state`, `source_id`,
`evidence_class`, `measurement_start_utc`, `observed_at_utc`, `valid_until_utc`.
Context contains workload, config, hardware, topology, scope and protocol IDs,
metric and statistic. These must all be bound and identical. `config_id` must
identify the full recipe/runtime comparison key defined by Maggie; a friendly
name alone is insufficient. The caller must verify the referenced manifests and
coverage. Unknown bindings are null and block evaluation, even on both sides.
Metric IDs are caller-defined: Maggie must approve their dimensional meaning and
the caller must enforce that mapping. Matching arbitrary labels alone is not proof
that the metric, unit or sampling coverage is appropriate.

Units are integer `byte`, or finite nonnegative `s` / `cpu_core`; bool and numeric
strings are invalid. Convert upstream with original units and conversion recorded.
States are `known/missing/stale/not_run/invalid`. Model predictions use immutable
source identity with null observation dates. Observations require UTC `Z` times
with at most six fractional-second digits; finer precision is rejected, never truncated.
Ordering is `start <= observed <= as_of < valid_until`. Explicit stale state also blocks
comparison before nominal expiry when drift is known. The validity window and
tolerance have no defaults; Maggie and the operator must justify them. Synthetic
fixtures use an arbitrary 60-second window solely to test expiration boundaries.

Output comparison is `not_evaluated/comparable/incomparable`. Assessment is
`incomplete/invalid/incomparable/within_supplied_tolerance/outside_supplied_tolerance`.
An error is observation minus prediction; positive means underprediction.
Absolute relative error divides by observation and is null at zero, including
zero versus zero. Tolerance equality passes this arithmetic assessment. None of
these outcomes proves capacity, safe headroom, truth, useful model improvement,
statistical confidence, scope completeness or permission. `execution_authorized`
is always false and `mutation_request` always null.

Error and tolerance comparisons use the exact values of supplied integers and
binary floats, without an acceptance epsilon. JSON uses integers for integral
derived results and rounded finite floats otherwise; a displayed error can round
to the tolerance while the exact comparison is outside it. Derived overflow, or
any nonzero error or relative ratio that would round to zero, makes assessment
invalid with null error outputs. A representable subnormal ratio remains nonzero.
Decimal precision and unit quantization must be made explicit upstream.

Examples: rough netcap even-shard state/activation estimate versus whole-device
worst-rank peak is incomparable. A matching host-peak prediction and observation
can quantify error, but a sample maximum is still not a future safety bound.
Use netcap's existing `observability.compare_collectives` for collective bandwidth
observations; do not normalize them through this memory/time reference.

`python -m capacity.calibration_examples` emits 15 deterministic synthetic cases.
Development and exposed acceptance are separate; tuning and protected heldout
sets are empty. `python -m pytest capacity/tests/test_calibration_evidence.py -q`
checks known answers, every context binding, malformed values, expiration and
arithmetic. No new random generator or invented operator resource demand is needed.
