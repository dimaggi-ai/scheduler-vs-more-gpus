# Declared KV scenario comparison

This offline AI/SI capacity planning component compares three **synthetic, declared**
single-device memory scenarios: `baseline`, `active`, and `candidate`. Those names
are scenario labels, not observations of a running system or permission to change it.
It calls the existing `capacity.kv_envelope.evaluate` for every scenario. It has no
independent memory formula, network access, connector, serving benchmark, ranking,
auto-promotion, control action, financial advice, or clinical/defence qualification.

Run from the repository root:

```sh
python3 -m capacity.kv_compare examples/kv-compare.json
python3 -m unittest discover -s capacity/tests -p 'test_kv*.py' -v
```

The module uses the standard library. Verified locally with Python 3.12.6 and
3.11.10; CI uses Python 3.12.

## Input contract

The only top-level fields are `schema: "capacity-kv-comparison/v1"`, `baseline`,
`active`, and `candidate`. Each scenario is a raw `capacity-kv-envelope/v1`
declaration, documented in [KV_ENVELOPE.md](KV_ENVELOPE.md). Reports are not inputs.
All existing envelope field, evidence kind, numerical, provenance-shape, and
unsupported-model refusals apply independently. Hash/revision declarations remain
assertions, not authenticated sources or checked measurements.

Every architecture field (including model/tokenizer revision and precision), every
demand field, and `evidence_kind` must match **exactly** across all three scenarios.
Active and candidate are both compared against baseline; strings are not trimmed
or normalized. A valid mismatch produces `not_comparable` with differing paths and
no deltas. The only supported evidence kind currently is `declared_scenario`, so
other kinds fail the underlying envelope contract before comparability is assessed.

Allocation/device/source/assumption/scenario-label differences are allowed and
explicitly disclosed against baseline. Sources and assumptions retain list order.
Complete original declarations and recomputed envelope reports are included for a
successful comparison. Missing or null required values produce
`insufficient_evidence`, not a fabricated zero. Malformed fields in another
scenario take precedence over missing declarations. Nonfinite object floats and parsed overflowing JSON numbers such as `1e400`
are refused as `nonfinite_number` with the field/list-index path before scenario
evaluation. Literal JSON NaN/Infinity tokens are refused during parsing, where
only the root path is available. Other object serialization errors report
`invalid_json_object`, not `expected_bytes` (reserved for non-byte bytes-API input).
Unknown fields, duplicate keys
(including nested scenario objects), unsupported schema, nonfinite values and
oversized/deep inputs are refused. No semantic equivalence is inferred from hashes.

Bundle limit: 197632 UTF-8 bytes; at most 3080 visited JSON values and depth 9.
Each envelope independently retains its 65536-byte, 1024-value, depth-8 bounds.
The scenario byte bound is measured by the unchanged envelope **object API** after
sorted compact JSON serialization with `ensure_ascii=True`, including Unicode
escape expansion. This applies to both comparator entry points: bundle bytes are
parsed, then each raw scenario is passed to `kv_envelope.evaluate`. A scenario
smaller than 65536 bytes in literal UTF-8 may therefore be refused as
`input_size_limit` at `$.candidate` (or the other scenario) when its escaped form
exceeds that bound, even though `kv_envelope.evaluate_bytes` accepts the literal
UTF-8 scenario directly. This conservative difference is retained intentionally;
no alternate serialization route bypasses the accepted envelope object contract.
Object callers are bounded and serialized to a snapshot before evaluations; callers
must not mutate objects concurrently during serialization. Byte callers preserve
exact input bytes in `input_sha256`; object callers hash sorted compact JSON.

## Results and arithmetic

Comparator version is `kv-scenario-comparator/v1`. `scenario_sha256` identifies each
canonical scenario evaluated by the envelope. `result_sha256` hashes sorted compact
UTF-8 JSON of the result **excluding `result_sha256` itself**. These digests establish
byte identity only. Every result says `authenticity: not_established` and
`qualification: not_established`.

`compared` means declarations satisfy the comparison contract. It does not mean
feasible, better, verified, accepted or deployable. Valid infeasible scenarios are
compared normally, with their feasibility/deficit/reason preserved in reports.

Deltas are signed **candidate minus baseline** and **candidate minus active** for
`kv_bytes_per_token` (bytes/token), `kv_bytes_per_request` (bytes/request),
`non_kv_reserved_bytes`, `kv_budget_bytes`, `requested_kv_bytes`, `remaining_bytes`,
and `deficit_bytes` (bytes). Counts, booleans and reasons are not subtracted.
No direction is universally preferred. All arithmetic is exact integer arithmetic;
if any signed delta exceeds ±(2^53−1), the whole comparison is refused with
`delta_integer_limit`, even when the individual scenarios are valid. The refusal path
`$.deltas.candidate_minus_baseline` (or `candidate_minus_active`) names the intended
output delta group; no partial `deltas` object is emitted on refusal.

The example baseline fits exactly; active reserves one additional workspace byte
and is one byte short. Candidate changes block allocation from 16 tokens to 1.
Its requested KV bytes decrease by 3932160 against baseline; remaining bytes
increase by 3932160 against baseline and 3932161 against active. These are synthetic
memory arithmetic outcomes, not measured speed, accuracy, reliability or savings.

## CLI and file boundary

Output is JSON on stdout only. Exit 0 means `compared`; exit 2 means any other
result (`refused`, `insufficient_evidence`, or `not_comparable`). Argparse usage
errors also exit 2 and help exits 0; callers must parse JSON status for evaluation
outcomes. The Python object and bytes APIs do not write files.

The CLI requires an OS with `O_NOFOLLOW`. It opens one bounded regular file,
refuses a final-component symlink, directories/FIFOs/devices, absent or malformed
paths, and detects changed descriptor identity/size/mtime/ctime during reading.
This is not a filesystem sandbox or a snapshot guarantee: ancestor symlinks are
not rejected, no root-containment policy is imposed, and hostile concurrent writes
that evade metadata detection are not ruled out. No output directory is created.

The tests include exact hand oracles, active and candidate context mutations,
infeasible cases, signed overflow, nested duplicate fields, source differences,
object snapshot behavior, and real CLI success/refusal/corrected-retry journeys.
Sensitive-domain scenario names confer no operational qualification. Independent
review and designated acceptance remain separate gates.
