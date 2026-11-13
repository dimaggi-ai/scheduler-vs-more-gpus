# Single-device KV memory envelope

This Capacity utility calculates a declared memory scenario with no network access,
cluster commands, model lookup or hardware defaults. It supplements the existing
`inference.py` service simulator; it neither replaces nor calls that engine. Memory
fit alone establishes no serving rate, latency, SLA, model accuracy or domain
qualification. Nothing is automatically promoted or deployed.

## Run and recover

From the repository root, with Python 3.11+ and no added dependencies:

```sh
python3 -m capacity.kv_envelope examples/kv-envelope.json
python3 -m unittest capacity.tests.test_kv_envelope -v
```

The synthetic example computes 131,072 KV bytes/token, two 16-token blocks for a
17-token context, 4,194,304 bytes/request and memory-feasible concurrency 2. Two
requests exactly consume 8,388,608 available KV bytes. All quantities are integer
bytes, not decimal GB or binary GiB. The fixture source digest binds the literal
`dimaggi-synthetic-kv-envelope-v1`, not a hardware measurement.

A complete valid scenario returns `status: simulated`, exit 0, even when its memory
demand is infeasible. Inspect `metrics.feasible` and `reason`; exit 0 does not mean
admission approval. Omitted or null required declarations return
`insufficient_evidence`, explicit missing paths and exit 2. Malformed or unsupported
supplied values return `refused`, a code/path and exit 2, taking precedence over
missing values. Correct the declarations and rerun: the input is never changed.
Callers must inspect the JSON `status` to distinguish missing declarations from
malformed input; exit 2 alone cannot distinguish them. Argument syntax/help uses normal argparse text; structured JSON applies after a
single scenario path is supplied. File failures return structured refusal.

Library: `evaluate_bytes(raw_bytes)` hashes exact supplied UTF-8JSON bytes;
`evaluate(scenario_dict)` hashes canonical JSON serialization. Both return an
outcome rather than approving an operation. Semantically equal documents with
different whitespace can have different byte digests. These hashes identify
inputs; they do not authenticate a publisher or the truth of declarations.

## Strict input contract

`capacity-kv-envelope/v1` permits exactly the following root fields; all required:

- `schema`, `scenario_label`, `evidence_kind` (only `declared_scenario`). Labels
  such as synthetic defence/logistics, health IT or finance reporting confer no
  sensitive-domain assurance or authority. No real sensitive data is required.
- `sources`: 1–16 source declarations, each exactly `uri`, `revision`, `sha256`,
  `license`, `retrieved_at` (ISO calendar date). URI must be HTTP(S) with a host and
  no userinfo, or a URN. URIs are never fetched; no credentials belong in them.
  Digest is 64 lowercase hexadecimal. This module cannot verify upstream bytes,
  license ownership or provenance accuracy. Link architecture/device assumptions
  to separately retained authorized evidence when leaving synthetic examples.
- `assumptions`: 1–32 nonempty statements. All scenario values remain declarations,
  even if a caller supplies a measured source. The result remains simulated.
- `architecture`: `kind` exactly `uniform_standard_attention`, explicit
  `model_revision`, `tokenizer_revision`, positive integers `layers`, `kv_heads`,
  `head_dimension`, and `k_bits`, `v_bits` each 8, 16 or 32. KV heads, not query heads,
  determine storage. No MLA, mixed/sliding layers, recurrent architecture,
  subbyte packing, tensor/pipeline sharding or multiple-device pooling. Architecture
labels are declarations: this utility cannot detect a hybrid or sliding-window
model mislabeled as uniform standard attention; verify that mapping independently.
- `allocation`: `prefix_sharing` exactly `none`, positive `block_tokens`,
  nonnegative `metadata_bytes_per_block`, `overhead_bytes_per_request`. Explicit
  zero overhead is permitted; omitted overhead is unknown, not zero. Per-block
  metadata is the total across the modeled layer/KV allocation, not per-head.
- `device`: positive `usable_hbm_bytes`, nonnegative `resident_weights_bytes`,
  `workspace_bytes`, `headroom_bytes`. These are disjoint reservations subtracted
  from the declared usable capacity; do not double-count an already excluded
  reserve. No architecture-to-weight-size or provider-to-GPU inference occurs.
- `demand`: positive `max_resident_context_tokens`, `requested_concurrency`.
  Context is explicitly declared maximum simultaneous resident tokens, not an
  inferred sum of provider counters. Trace mapping and tokenizer calibration
  are deliberately outside this first increment.

All unknown fields and duplicate JSON keys are rejected. Duplicate-key refusal
reports the document root `$`, not the nested object location. Integer fields refuse
booleans, floats, negatives and values above 2^53−1. Derived integer quantities are
also bounded to this range for interoperable exact JSON arithmetic. If only the
negative remaining bytes or positive deficit exceed this range, the result still
refuses with `derived_integer_limit`, rather than returning an infeasibility
report. No value is silently capped, omitted or converted to floating point. Text refuses Unicode control (`Cc`), format (`Cf`) and surrogate (`Cs`) code points, including
DEL, C1 controls and bidi overrides/isolates; ordinary multilingual text is
permitted, including valid non-BMP scalar characters. Escaped lone high/low
surrogates are refused by both APIs and the CLI. ZWJ/ZWNJ remain intentionally
refused as format characters; no Unicode normalization is performed. This display hygiene is not identity authentication or complete
confusable-character detection. Text is at
most 512 characters; bytes at most 64 KiB; nesting at most 8; traversed values at most
1,024. The object API rejects unsupported objects and bounds traversal before
serialization. The CLI reads only a regular nonsymlink file through POSIX
no-follow/nonblocking flags; Windows is not qualified. No recorded tools execute.

## Formula and meaning

Formula version: `uniform-standard-attention-no-sharing/v1`.

```text
kv_bytes_per_token = layers * kv_heads * head_dimension * (k_bits + v_bits) / 8
blocks = ceil(max_resident_context_tokens / block_tokens)
kv_bytes_per_request = blocks * (block_tokens * kv_bytes_per_token
                                + metadata_bytes_per_block)
                       + overhead_bytes_per_request
non_kv_reserved = resident_weights + workspace + headroom
kv_budget = usable_hbm - non_kv_reserved
requested_kv = requested_concurrency * kv_bytes_per_request
remaining = kv_budget - requested_kv
max_memory_feasible_concurrency = floor(max(0, kv_budget) / kv_bytes_per_request)
deficit = max(0, -remaining)
```

A negative KV budget is a complete but infeasible scenario with
`infeasible_non_kv_budget`. Zero budget permits zero requests. A one-byte deficit
is infeasible. The concurrency result is a memory-only upper bound; no serving
batch maximum or bandwidth limitation has been evaluated. Cached prefixes still
occupy memory: no cache-hit subtraction or deduplication is supported. Changing
precision changes this storage scenario, not proof of equal model accuracy.

Outputs retain the complete validated declarations, input digest, formula,
integer units and explicit `not_evaluated` entries for bandwidth, latency,
throughput, offload, network, energy, accuracy and operational qualification.
Do not substitute this envelope into the existing simulator without separately
validating allocator/headroom compatibility; its scalar KV parameter cannot
express all these reservations.

## Agentic use and review gates

Observe declared inputs → validate → calculate offline → inspect feasibility,
missingness and nonclaims → propose corrected declarations → rerun. Fixed-baseline
comparisons must keep demand, architecture, provenance and criteria explicit;
this utility does not compare or choose a winner. Agents cannot rewrite criteria,
self-promote, authorize consequential action or transform simulated results into
production evidence. Existing Tool Guard/harness controls still apply when an
agent invokes the command. Independent exact-source review and designated
Dmitry/Ronnie acceptance remain required for product qualification and release.

Tests include a hand-computed oracle, exact-fit/one-byte deficit/negative budget,
GQA/MHA head changes, precision/metadata accounting, refusal, missing evidence,
bounded malformed inputs, provenance, synthetic-domain nonclaims and real CLI
corrected recovery/file guards. Existing CI discovers the new test file under
`capacity/tests`; no workflow or dependency changes are needed.
