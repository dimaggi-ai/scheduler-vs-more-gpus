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
explicitly disclosed against baseline in `changed_declarations_vs_baseline`.
There is no separate candidate-versus-active declaration-difference summary, even
though metric deltas are reported against both references. Callers needing that
summary must compare the retained declarations; the full inputs are included.
Sources and assumptions retain list order.
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
Conversely, whitespace in a supplied scenario is removed during compact canonical
serialization: a scenario with more than 65536 supplied bytes of whitespace may
compare if its canonical form fits. The complete raw bundle still must fit the
197632-byte bound.

Some oversized scenarios are refused with less specific diagnostics by the unchanged
envelope object API. For example, a 65537-character scenario-label string that fits
the bundle bound yields `invalid_json_object` at `$.candidate`; direct envelope
bytes input yields `input_size_limit`. This is a current diagnostic limitation,
not a relaxation of either bound. Similarly, an object bundle containing a lone
Unicode surrogate is refused as root `invalid_json_object` during UTF-8 encoding.
The same surrogate represented as a JSON escape in bytes input can instead reach
field validation and report `invalid_text` at `$.candidate.scenario_label`. Both
routes refuse it; their reason codes and paths are not interchangeable.

Object callers are bounded and serialized to a snapshot before evaluations; callers
must not mutate objects concurrently during serialization. Pre-serialization
validation visits siblings lazily with a depth-bounded stack and constructs the
escaped diagnostic path only on error; it does not queue a full ancestor string
per sibling. Shared object references count on every visit, and cycles fail the
depth bound. The limits bound this traversal, not the caller's pre-existing object
allocation or total process RSS. Object input is then canonically encoded
incrementally: accumulation stops at the bundle byte cap before joining an
oversized document. Valid canonical bytes/digests are unchanged. Each transient
encoder chunk is bounded by the already-checked scalar/key lengths (a maximum
input string can require Unicode/escape expansion); the implementation does not
claim the byte cap is a hard peak-memory limit. A synthetic 30,741-byte wide/deep regression checks
that traced incremental allocations stay below 8 MiB on the tested Pythons; it is
not a general process-memory or production-isolation guarantee. Byte callers preserve
exact input bytes in `input_sha256`; object callers hash sorted compact JSON.

## Results and arithmetic

Comparator version is `kv-scenario-comparator/v1`. The digest encodings differ:

- `scenario_sha256` hashes each scenario's sorted, compact, **ASCII-escaped JSON**
  encoded as UTF-8 (`ensure_ascii=True`), exactly as evaluated by the envelope object
  API. It is not the scenario's raw-file digest. For non-ASCII text it also differs
  from a digest of sorted compact JSON containing literal UTF-8 characters.
- `input_sha256` hashes the exact supplied bundle bytes for the bytes API. For the
  object API it hashes sorted compact JSON encoded as UTF-8 with
  `ensure_ascii=False`, after the bounded snapshot encoding succeeds.
- `result_sha256` hashes sorted compact JSON encoded as UTF-8 with
  `ensure_ascii=False`, **excluding `result_sha256` itself**.

These digests establish byte identity only. Every result says `authenticity: not_established` and
`qualification: not_established`.

`compared` means declarations satisfy the comparison contract. It does not mean
feasible, better, verified, accepted or deployable. Valid infeasible scenarios are
compared normally, with their feasibility/deficit/reason preserved in reports.

Deltas are signed **candidate minus baseline** and **candidate minus active** for
`kv_bytes_per_token` (bytes/token), `kv_bytes_per_request` (bytes/request),
`non_kv_reserved_bytes`, `kv_budget_bytes`, `requested_kv_bytes`, `remaining_bytes`,
and `deficit_bytes` (bytes). Counts, booleans and reasons are not subtracted. Under the required identical
architecture, `kv_bytes_per_token` deltas are necessarily zero; they are retained
as a consistency indicator, not an independently variable improvement metric.
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

### CLI descriptor ownership

The reader keeps ownership of its raw file descriptor throughout the read. Its
stream wrapper uses `closefd=False`; the raw descriptor is closed once in
`finally`, including construction and read failures. This avoids closing an
unrelated file that reuses the descriptor number after a failed owning wrapper.
A close `OSError` produces the reader's existing structured file-refusal JSON and
exit 2. For the envelope, this specifically replaces an exceptional raw-close
traceback; normal output and exit behavior are unchanged. Synthetic
`KeyboardInterrupt` and `MemoryError` propagate after descriptor cleanup unless
the final raw close itself raises `OSError`. That close error replaces the
in-flight exception and produces the existing file-refusal JSON with exit 2. The
tests inject exceptions rather than exhausting resources. No retry of a failed
raw close is attempted, since its descriptor number may already have been reused.
