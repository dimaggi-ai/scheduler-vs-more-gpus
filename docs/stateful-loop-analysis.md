# Synthetic stateful AI/SI loop analysis

`capacity.stateful_loop` calculates an **ideal dependency-only latency lower bound with unlimited stage resources**. It exposes a simple co-design issue: reducing compute duration cannot shorten a loop when a parallel fabric path remains longer. It is not a scheduler, hardware simulator, measured throughput result, production guarantee, or complete systems co-design model.

Each immutable `Stage` declares seconds and dependencies in a bounded acyclic graph. Host, compute, memory, fabric and state categories must all appear explicitly. Every stage must be an ancestor of the named final `state` stage. Exactly one sink is required. “Persisted” names that declared sink only; the calculation assumes that this stage's declared duration represents persistence completion; it neither persists data nor verifies durable storage. Each iteration starts after the previous iteration's final state completes. There is no interiteration overlap, retry, stochastic arrival, queueing, contention, crash recovery, metering, energy or price calculation.

The earliest stage finish is its duration plus the maximum dependency finish. Independent branches overlap perfectly. Stage kinds are descriptive labels, not resource pools: two compute stages can overlap without limit in this abstraction. Results also include `serial_sum_s`, the ideal no-overlap sum, and its sequential total. This is a comparison scenario, **not an upper bound on actual runtime**: contention, queueing and failures can exceed it. Per-stage slack uses an exact reverse latest-start pass. The reported critical path breaks exact ties by the lexically smallest full path. Deterministic sorted traversal uses exact rational arithmetic from the supplied binary floating-point values for sums, path comparisons and slack. Comparison ratios and saved seconds also use exact internal total fractions before converting to finite output floats. Results convert to finite floats only at the boundary. This avoids incremental summation drift without pretending decimal input values or final output rounding are exact measurements. Integer-valued synthetic seconds make the examples exact. Total loop latency multiplies the per-iteration makespan by the sequential iteration count. A reciprocal of this value must not be presented as measured throughput.

## Reproduce an entirely synthetic example

From the repository root, with Python 3.10 or newer and no additional dependencies:

```python
from dataclasses import replace
from capacity.stateful_loop import Stage, Loop, SyntheticProvenance, analyze, compare

base = Loop(
    stages=(
        Stage("host", "host", 8, source_id="host-fixture"),
        Stage("compute", "compute", 4, ("host",), source_id="stage-fixture"),
        Stage("memory", "memory", 2, ("host",), source_id="stage-fixture"),
        Stage("fabric", "fabric", 6, ("host",), source_id="stage-fixture"),
        Stage("persist", "state", 2, ("compute", "memory", "fabric"), source_id="state-fixture"),
    ),
    persisted_completion_id="persist", iterations=3,
    workload="synthetic-loop", quality="fixed-quality", protocol="v1",
    provenance=SyntheticProvenance(
        "hand-authored-v1", "inline synthetic example", "MIT",
        "2026-11-03", "declared-fixture-revision-v1",
    ),
)
def change(**durations):
    return replace(base, stages=tuple(
        replace(s, duration_seconds=durations.get(s.id, s.duration_seconds))
        for s in base.stages
    ))

assert analyze(base).total_lower_bound_s == 48
assert compare(base, change(compute=1)).lower_bound_speedup == 1
assert compare(base, change(host=4, fabric=3)).candidate.total_lower_bound_s == 30
assert compare(base, change(host=4, fabric=3, compute=2)).candidate.total_lower_bound_s == 27
assert analyze(base).critical_path == ("host", "fabric", "persist")
try:
    analyze(change(host=None))
except ValueError:
    pass  # Unknown refuses; corrected declaration below computes again.
else:
    raise AssertionError("unknown duration accepted")
assert analyze(change(host=8)).total_lower_bound_s == 48
```

These invented durations are not TPU, GPU or vendor estimates. The three-iteration baseline is 48 seconds; compute-only acceleration leaves it unchanged; the host/fabric intervention reduces it to 30; joint intervention reduces it to 27. These statements describe only the supplied synthetic graph under ideal overlap. They demonstrate methodology, not observed hardware advantages.

## Refusal, provenance and comparison boundaries

`analyze` and `compare` raise `ValueError` on invalid or unknown inputs and return no partial result. Durations must be strictly positive. Missing and explicit zero durations both refuse; unknown or omitted layers cannot be disguised as zero-length category placeholders. Boolean, negative or nonfinite durations, unknown/duplicate dependencies, cycles, dangling work, missing categories, non-state completion, and arithmetic overflow are rejected. Limits are 256 stages, 4096 dependency edges and 1,000,000 sequential iterations; these are defensive computational limits, not physical operating ranges. Text metadata is limited to 512 characters per field, without leading/trailing whitespace, ASCII control characters or DEL; input is refused rather than silently trimmed. Only the typed immutable records and tuples are accepted, not arbitrary JSON or executable inputs. Positive finite subnormal durations remain synthetic declarations; they do not establish physically plausible timing.

Comparison permits duration changes only. Stage IDs, kinds, dependency edges, completion, iteration count, workload, quality, protocol and global/per-stage synthetic provenance must match; a canonical graph/context SHA-256 excluding duration values checks this contract; stage and dependency ordering are immaterial. A change to precision, quality, graph or workload is a different experiment and cannot pass this comparison. `lower_bound_speedup` is baseline lower-bound total divided by candidate lower-bound total; it is not a measured speedup. Slower candidates legitimately produce a ratio below one and negative saved seconds. Nonfinite or underflow-to-zero speedup is rejected.

Each stage additionally requires a nonempty `source_id` and the class `synthetic`; measured and model-derived classes refuse rather than silently composing uncalibrated models. `SyntheticProvenance` fields identify the caller's declared fixture/source/licence/date/revision. The `sha256` string is retained as supplied and is neither calculated nor verified; the synthetic example deliberately uses a visible revision label, not a fabricated digest. The shared fixture/revision identifies an experiment family for matched interventions, not a digest of each actual duration record. `input_sha256` separately identifies all supplied record fields, including durations, with stage/dependency ordering canonicalized. It retains numeric representation (for example, `8` and `8.0` differ), so it is not a normalized semantic identity. `graph_context_sha256` excludes durations and remains the comparison gate. Neither output hash nor matching provenance establishes authenticity, calibration, freshness, quality equivalence or execution permission. No external source is read, no clock queried and no network or device called. Hardware-derived timings, finite shared resources and their calibration require separate reviewed work. This API does not compose the evidence gate, report APIs, or pending model changes.

## Qualification

```sh
python3 -m unittest capacity.tests.test_stateful_loop -v
```

Tests cover success, no-benefit controls, joint improvements, delay, permutations and ties, unknown/refusal/corrected input, omitted state, substitutions, invalid graph structure and bounded arithmetic. Corrected-input recovery means a later valid *calculation* succeeds; it is not actual crash recovery. The designated independent reviewer should challenge delay/substitution/omitted-state/cycle/overflow cases in an isolated offline environment with bounded time/memory and synthetic inputs. Abort on unexpected execution or unbounded resource use. No production chaos is authorized or necessary for this pure calculation. Technical acceptance and cross-tool review remain separate from passing source tests.
