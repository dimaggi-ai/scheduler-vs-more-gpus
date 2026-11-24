# Declared KV allocation and inference scenarios

This additive Capacity bridge connects the public KV envelope evaluator to the existing single-device inference simulator. It models explicit hypothetical workloads, not observed traces. It does not create a planner, serving runtime, actuator or new product.

```sh
python3 -m capacity.kv_inference_bridge examples/kv-inference-bridge.json
python3 -m unittest capacity.tests.test_kv_inference_bridge
```

The CLI reads one bounded local regular file and prints one JSON result. It has no network access, output-file option, subprocess execution or source fetch. Source URIs remain declarations. The object API is `evaluate(scenario)`; `evaluate_bytes(raw)` additionally retains the identity of the exact supplied bytes.

## Explicit input contract

Schema: `capacity-kv-inference-bridge/v1`. Every field in the example is required, including zero cached-prefix counts, model and tokenizer revisions, model parameters and bytes per parameter, hardware name, service rates, efficiency, both SLO thresholds, batch bound, policy, source indices and assumptions. There are no implicit workload or service defaults. Extra fields, duplicate JSON keys and nonfinite numbers refuse.

The embedded parent uses the existing `capacity-kv-envelope/v1` schema and its existing bounds. Its requested concurrency must equal the number of requests; its context bound must equal the largest request context bound. Model and tokenizer revisions must match the parent. Parameters × bytes per parameter must equal resident weight bytes exactly. Zero resident weights cannot map to this engine and refuse as `unsupported_weight_mapping`.

Requests have unique slug IDs and explicitly declare arrival, input, output, cached-prefix and maximum resident context tokens. The resident bound must cover input plus output; cached prefixes save modeled prefill work but never reduce KV allocation. The bridge derives children by changing only the parent's demand to each distinct context bound and concurrency one. It calls the public envelope API for each child rather than reproducing the allocation formula.

Service source indices must be a nonempty unique list of valid indices into the parent's sources. These declarations attribute assumptions; they do not verify hardware rates or source truth.

Bounds: 262,144 input bytes, nesting depth 8, 8,192 structural nodes, strings up to 512 characters without control/format/surrogate characters, 1–128 requests, batch size 1–128 and at most 100,000 aggregate output tokens. Integer memory, model and token values and checked byte sums are bounded by 2^53 − 1; booleans and floating-point byte counts are refused. Output is fully serialized before printing and limited to 2 MiB. Parent validation retains its own stricter 65,536-byte and structural limits.

## Four outcomes

| Status | Meaning | CLI exit |
| --- | --- | --- |
| `refused` | Malformed, unsupported, contradictory or out-of-bound declaration; unsafe file; engine or consistency failure | 2 |
| `insufficient_evidence` | Required declarations are missing or null, listed as sorted paths | 2 |
| `infeasible` | Complete declarations reserve more fixed memory than available; engine not called | 0 |
| `simulated` | Valid nonnegative memory budget; engine ran, including scenarios where all requests are rejected | 0 |

Exit zero means a valid scenario conclusion, not readiness or fit. Syntactic corruption takes precedence over missingness. An engine exception after preflight is `engine_contract_violation`, not a fixed-memory infeasibility conclusion. Child/engine budget or feasibility disagreement is `bridge_consistency_violation`; no partial successful simulation is returned. Bounded refusals retain raw and canonical input digests when those validated identity fields fit within the output cap. Structural string refusals identify the offending field or list index. Paths use dotted diagnostic notation, so unsupported keys containing literal dots can be ambiguous; this is not a general JSON-path grammar. Bounded output refusals preserve the result schema and retain validated identities when they fit.

The report preserves distinct questions:

- `parent_uniform_reference`: unchanged uniform worst-case envelope, including its declarations, formula version, digest, metrics and limitations.
- `cohort_simultaneous_fit`: whether the actual heterogeneous reservations fit all at once, independent of arrivals.
- `individually_infeasible_ids`: requests whose declared reservation exceeds the entire available budget.
- `simulated_admission`: observed FCFS queue completions/rejections and peak/final memory accounting. Its peak is not an optimal packing bound.

`fixed_memory_deficit_bytes` is separate from parent and child envelope deficits. With weight 10, workspace 30, headroom 20 and HBM 59, fixed deficit is 1, parent deficit is 157 and child deficit is 79. With HBM 60, budget is zero: simulation rejects every positive reservation without service work.

## Reproducible synthetic arithmetic

The example has raw KV 2 bytes/token, blocks of 16 tokens, metadata 2 bytes/block and allocator overhead 10 bytes/request. Weight is 10 bytes, workspace 30 and headroom 20. These tiny fictional quantities make the arithmetic inspectable; they are not representative hardware measurements.

| Scenario | Budget | Reservations | Concurrent fit | Queue outcome |
| --- | ---: | --- | --- | --- |
| HBM 216, two contexts of 17 | 156 | 78, 78 | Yes | Peak 156; both TTFT 0.394 s |
| HBM 215, same requests | 155 | 78, 78 | No, deficit 1 | Both complete sequentially; TTFT 0.202 and 0.404 s |
| HBM 182, contexts 16 and 17 | 122 | 44, 78 | Yes | Peak 122; both TTFT 0.382 s |

In the heterogeneous case the unchanged parent uniform reference is infeasible by 34 bytes while the actual cohort fits. Full cached prefixes leave reservations unchanged and reduce modeled TTFT in the first case to 0.074 s. Timing assertions use absolute tolerance 1e-12; integer and serialized-identity checks remain exact.

## Conservative timing precision policy

The bridge leaves the engine and declared arrivals unchanged. Before precision evaluation, the bridge requires finite non-negative numeric makespan, served TTFT and served maximum ITL values, excluding booleans. Missing or malformed timing fields are `bridge_consistency_violation` with no partial report; interrupts still propagate. After these consistency checks, it applies a conservative first-order precision diagnostic. This is not a mathematical proof, a formal error bound, an event-order guarantee or guaranteed relative accuracy.

For the declared request count N and aggregate output tokens O, the addition-count bound is A = N + O. From returned makespan and declared arrivals it computes:

```text
T = max(max(arrival), min(arrival) + makespan) × (1 + 2^-40)
delta = (A + 8) × ulp(T)
```

A served result refuses as `timing_precision_indeterminate` at `$.service_simulation` if derived T/delta is nonfinite, or if makespan, any served TTFT or any served multi-token maximum ITL is at most 1000 × delta. It also refuses if any served TTFT or multi-token maximum ITL is within delta of its declared SLO threshold (including exact ties). Single-token ITL is an exact default zero, so that comparison is skipped. All-rejected scenarios skip precision evaluation and report `timing_precision.status=not_evaluated`, with reason `no_served_requests`; no potentially overflowing clock estimate is needed.

On accepted simulations, `timing_precision` exposes `estimate_s`, `clock_scale_s`, `event_addition_bound`, the resolution multiplier and method `conservative_first_order_estimate_not_proof`. These are diagnostic estimates, not measured error or verified guarantees. A long request cannot mask an absorbed short request: resolution checks apply to each served duration, not only makespan.

This policy has no fixed arrival cap. Ordinary scenarios shifted to 1e9 seconds can remain resolvable; extreme offsets and fine service durations may refuse. Tiny service at zero arrival can remain usable. Near-threshold passes and misses can both refuse, as can some otherwise valid large-duration scenarios. A precision refusal retains input digests without returning partial simulated results. Corrected declarations must state the intended scenario; the bridge never silently shifts, rounds or normalizes arrivals to obtain a pass.

## Identity and source attribution

Raw bridge input SHA-256 binds exact supplied JSON bytes. Canonical SHA-256 uses sorted keys, compact separators, `ensure_ascii=True`, `allow_nan=False`, encoded UTF-8. Whitespace changes raw identity only. For the object API, input bytes are this canonical serialization; an original upstream file identity is never inferred. Declared numeric representations are not silently normalized: for example, `-0.0` arrival is retained in the declaration and has a different canonical identity from `0`, despite the same timing semantics.

The embedded parent's digest identifies its canonical object, not an upstream raw file. Each derived child retains its parent canonical digest, minimal demand patch, canonical child digest, formula version, metrics and original request indices. Request mappings retain IDs, original indices, declared request fields, context bounds and reservations after arrival sorting.

Expected engine commit `2b013ff94699f549300d8c9c6ae34d7447c63982` and envelope commit `37080402c0df716dd9a379f3858eeaa6c73197c5`, plus source SHA-256 values, are build attribution only. The bridge does not read installed source files or verify these pins at runtime: `runtime_source_verified=false`. Independent source review does not constitute designated technical qualification or product acceptance.

## File lifecycle and limits

The CLI uses `O_NOFOLLOW | O_NONBLOCK`, verifies regular-file type and reads at most the input bound plus one byte. Symlinks, FIFOs, devices, directories, missing/unreadable paths and embedded NUL paths refuse. Platforms without the required safe-open flags refuse.

Raw descriptor ownership stays with the caller: `fdopen(..., closefd=False)`, stream cleanup first, exactly one raw close in `finally`. Raw-close `OSError` takes precedence over a pending stream/read failure or interrupt and returns a structured refusal. Otherwise interrupts propagate after cleanup. Tests use bounded finite inputs and subprocess timeouts, including negative controls.

## Limits and required humans

Admission is allocation-aware, but service timing remains the existing raw-KV compute/bandwidth approximation. Padding, metadata, allocator, workspace and headroom traffic/compute costs are not modeled. There is no calibrated hardware/kernel, accuracy, prefix sharing, offload, network, energy or operational qualification evidence.

Health-service IT continuity, defence logistics IT and finance reporting tests use fictional labels and the same arithmetic. They exercise success/refusal/recovery, not clinical decisions, weapons, financial transactions, domain certification or consequential operations. No real sensitive records are included.

Agents may evaluate these bounded offline declarations within existing authority. Claude exact-source review, Dmitry's technical qualification and Ronnie's independent verification remain separate gates. This bridge grants no merge, release, deployment, policy or expanded execution authority.

## Dependency failures and returned-result invariants

Input parsing errors remain input errors. Exceptions from the parent or derived envelope evaluator are reported as `bridge_consistency_violation` at that phase's path; returned envelope refusals retain their original codes. Exceptions from the engine call are `engine_contract_violation`. Unexpected type/value/key/overflow/recursion failures during post-engine checks are `bridge_consistency_violation`. Precise bridge refusals are preserved before these handlers. `MemoryError`, `KeyboardInterrupt` and `SystemExit` propagate; they are never relabelled as input or dependency failures. The public CLI returns exit 2 JSON for handled dependency failures, without exception details or partial successful results. Non-Refusal faults in the bridge’s own validate/compose code outside these dependency and post-engine wrappers propagate instead of being mislabeled as input errors; the CLI can then terminate with a traceback. This distinction does not add a broad internal-error handler.

Before the unchanged precision diagnostic, served rows must report an actual integer output-token count equal to the declaration and an actual boolean SLO verdict equal to the comparison of their returned TTFT/ITL against the declared thresholds. The clock also requires, for minimum declared arrival m:

```text
(arrival_i - m) + TTFT_i <= makespan + tau
(arrival_i - m) + TTFT_i + max_ITL_i <= makespan + tau
S = max(max(arrival), m + makespan, max_i(arrival_i + TTFT_i + max_ITL_i)) × (1 + 2^-40)
tau = (N + sum(output_tokens) + 8) × ulp(S)
```

Equality at the tolerance boundary is permitted. If derived S/tau is nonfinite, these two clock inequalities are skipped and the precision diagnostic handles the case. Actual contradictions are consistency refusals before precision checks. This separately computed tolerance does not change the reported precision estimate. No service formulas, throughput or attainment aggregates are recomputed.

Timing fields require built-in `int` or `float`; subclasses are refused. One `RESULT_SCHEMA` constant supplies the existing result schema. Pre-parse refusal shapes remain unchanged. In tests that override the fixed output cap to an impossibly small value, the minimal schema/code refusal is still returned even if it exceeds that artificial cap; there is no public cap configuration, and the fixed 2 MiB production cap accommodates this bounded diagnostic.
