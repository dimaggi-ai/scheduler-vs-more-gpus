# Capacity Orbital checkpoint replay

A bounded offline calculator for the useful work lost when synthetic payload processing is interrupted. It models one job on one processor, constant checkpoint/restart durations, durable completed checkpoints, and caller-declared interruptions. It does not infer radiation rates, control hardware, execute jobs or manage a settlement ledger.

```sh
python3 -m capacity.orbital.reliability --request capacity/orbital/examples/checkpoint-evaluate.json
python3 -m capacity.orbital.reliability --request capacity/orbital/examples/checkpoint-compare.json --output /tmp/new-checkpoint-comparison.json
python3 -m unittest capacity.orbital.test_reliability -v
```

Python 3.12 is the tested environment. No external dependencies or network access are needed. Output files must be fresh; inherited publication preserves existing files and rolls back ordinary publication failures, but is not crash-atomic. CLI exits 0 for a valid diagnostic, including a missed deadline, and 2 for malformed input, budget or IO refusal. Inspect `result.status`; envelope `status: ok` means processing succeeded, not that the job completed. Parse/IO failures print refusal to stdout; a structured tool refusal is written to the requested output file.

## Agent interfaces and numeric contract

`reliability.api.dispatch(request)` accepts exactly schema, id, tool, input. Schema is `capacity-orbital/checkpoint-tool-v1`; tools are `evaluate` and `compare`. Low-level pure functions `evaluate_checkpoint_policy(scenario)` and `compare_checkpoint_policies(baseline,candidate,expected_baseline_sha256)` raise validation exceptions. Dispatch returns structured refusals; programmer exceptions are not converted into successful diagnostics. IDs are stateless labels, not idempotent execution keys. No action or promotion is performed.

The scenario schema is `capacity-orbital/checkpoint-v1`; complete fields and explicit synthetic provenance appear in the examples. Times and useful work use seconds; productive speed is one work-second per elapsed second. Power fields are total declared kW for productive, checkpoint, restart and down states. Energy is exact kWh, including down power after release and before terminal time. No initial/final idle energy is counted. Down does not imply zero electrical draw.

JSON numeric lexemes are retained before conversion to exact `Fraction`. Direct Python calls accept bounded int, Decimal, or finite float via repr; numeric strings and booleans refuse. Use Decimal for exact decimal declarations. Limits: 48 token characters, 24 coefficient digits after removing leading zeros (trailing zeros count), at most two explicit exponent digits and magnitude 12, and at most 12 lexical fractional places after exponent adjustment. Thus `1.0000000000000`, `1e+012`, `5e-324` and float repr `0.30000000000000004` refuse. No silent rounding to an intended value. Duplicate keys, NaN/Infinity, malformed Unicode/surrogate strings and overlapping or unsorted outages refuse. Adjacent outages merge.

Every numeric result value is a reduced rational object with decimal-string `numerator` and positive `denominator`; zero is 0/1. No floating display values enter receipts. Event logic and energy remain exact. Replay uses the original request plus the pinned source, not rational result objects as input. Store the original request separately.

Scenario pins normalize numeric spellings, signed zero and adjacent outages but retain scenario ID/schema/provenance/policy version. They use existing sorted compact JSON canonicalization with ASCII escaping. `evaluate.result.input_sha256` is the baseline pin; the envelope input hash also includes request ID and must not be substituted for it. The non-ASCII hand-case fixture has scenario pin `4573714e8a4c374d5e96134129ebc8c49a935ec56069e96e37fb67fd0b618824`. Source hashes include this module and imported parent helpers. Output receipt and trace hashes establish consistency, not authenticity or approval.

## Event semantics

Durable work D plus uncheckpointed volatile V is current progress. A checkpoint starts when V reaches the declared interval; it pauses productive work. A completed checkpoint commits D+V and clears V. A fault loses V; interrupted checkpoint writes are entirely discarded. Restart produces no work and restarts in full if interrupted. Starting inside an outage deliberately requires full restart after recovery. Durations do not vary with state size.

At each boundary: advance/account the preceding half-open interval; finalize job completion first; commit a checkpoint or finish restart; apply outage boundaries; apply deadline; begin the next state. Completion exactly at fault/deadline succeeds. Checkpoint ending exactly at a fault/deadline commits. A checkpoint still in flight at deadline retains V without committing or losing it. Outage starting exactly at deadline loses V before stop. Release equal to deadline returns a valid zero-duration missed deadline. An interval at least as large as total work causes no final checkpoint.

Trace intervals are positive, contiguous and conserve productive work = lost + D + V. Per-state durations sum to stop−release; energy equals the power-weighted duration sum/3600. Valid missed-deadline reports retain partial work and consumed energy. Numerical model choices are not physical durability guarantees.

## Comparison and improvement-loop boundary

Only checkpoint interval and descriptive scenario ID/provenance/policy version may vary. Checkpoint and restart durations, work, power and interruption timeline remain fixed—even when a duration is unused. A required non-null lowercase baseline digest must match the normalized scenario. The label `baseline matched supplied digest` proves no independent approval: the caller must compare it with its own approved record.

Outcomes: both_completed, regression, candidate_completed_baseline_missed, both_missed. Completion-time delta is null unless both complete. Stop, energy, lost-work and durable-progress deltas are descriptive candidate-minus-baseline values; unfinished work consuming less energy is not an improvement. Comparisons contain summaries and trace hashes, not two full traces; obtain traces separately through evaluate. Summary receipt IDs link to full evaluation receipts and cannot be recomputed by hashing summaries alone.

Every comparison has `evidence_scope: one declared timeline` and a non-promoting recommendation. Choosing an interval against known faults can overfit. A later runner must use independently held baselines and separate fixed train/held-out timelines before any promotion. Tool Guard belongs at that runner's action boundary; this calculator does not change or enforce authority.

## Bounds and evidence

Input: 1,000,000 bytes, depth32, 50,000 nodes, 1,000 interruption intervals; horizon/work at most31,557,600 seconds and power at most1e9 kW. Trace cap10,000 intervals per evaluation; comparison runs two evaluations but emits summaries. Output cap8,000,000 bytes; rational size defence256 digits. Tiny intervals and year-long hourly checkpoints can exceed trace budget and refuse, never approximate or silently truncate. Output size may independently bind before the event limit. Direct Decimal requests are bounded structurally before canonical encoding.

Refusal codes: INVALID_ARGUMENT, UNSUPPORTED_SCHEMA, UNKNOWN_TOOL, BUDGET_EXCEEDED, BASELINE_BINDING, BASELINE_MISMATCH, SOURCE_UNAVAILABLE, OUTPUT_ERROR (CLI IO). Early invalid inputs may have no digest; a valid top-level request ID is retained where parsing permits. Fixed arithmetic/hardware assumptions, all ten hand timelines, decimal ties, malformed input, genuine CLI retry and independent conservation tests are documented in `../evidence/checkpoint/VALIDATION.md`. Source review, designated acceptance and product release remain separate gates. No radiation calibration, flight/financial/clinical safety, live isolation or physical qualification claim follows from these tests.

Trace row fields are exactly `state`, `start_s`, `end_s`, `duration_s`, `energy_kwh`, `progress_before`, `progress_after`, and `reasons`. Each progress object contains `durable_work_s`, `volatile_work_s`, and `lost_work_s`; these and all times/energy use the rational representation above. `reasons` is the ordered list of boundary events after the interval. The committed `checkpoint-evaluate.json` example produces a three-row trace with digest `ffab3991857f8007188464947085e2ac786bcec4e37a8a76ee8952f789379714`, computed as `digest(result["trace"])` using the shared canonical serializer. Trace digests bind these rows, not the envelope or source hash.

Reports expose `scenario_id` and the complete declared synthetic `provenance`, including when comparison permits descriptive differences. Hashes bind these values; they do not authenticate them. Comparison deliberately constructs each bounded full evaluation before producing summaries, preserving the full receipt links. Therefore a baseline or candidate full trace may hit the 8,000,000-byte limit even when the eventual comparison summary would fit; the BUDGET_EXCEEDED reason names the affected side and full evaluation/trace budget. This conservative intermediate-memory limit remains intentional.

When valid JSON has a known request ID but exceeds structural budgets, the CLI retains that ID. Output publication failure also retains the validated ID; malformed/unparseable input may not have one. Unexpected programmer ValueError exceptions from dispatch propagate rather than being mislabeled as IO failures. Only actual read/publication errors use OUTPUT_ERROR.
