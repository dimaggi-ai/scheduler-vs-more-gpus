# Offline synthetic stateful-loop study

Generate a standalone visual study with the existing `stateful_loop` API:

```sh
python3 -m capacity.loop_study --output /private/tmp/my-new-loop-study
```

Open the emitted `index.html` locally using your ordinary browser/file workflow.
The command needs Python 3.10+ and POSIX directory/no-follow support (macOS or
Linux). It uses the standard library only: no JavaScript, server, subprocess,
network request or external font/image dependency. Use a real existing parent
and a fresh directory name. On macOS `/tmp` is a symlink; use `/private/tmp`.
The tool refuses symlinks anywhere in the requested path, existing targets,
parent traversal and missing parents. It creates exactly four files:

- `index.html`: inline HTML/CSS/SVG with comparison bars, a baseline graph and
  a bounded compute/fabric sensitivity table;
- `inputs.json`: every exact supplied fixture and the experiment-family record;
- `results.json`: unrounded API results, hashes, comparisons and visible limits;
- `manifest.json`: file byte lengths/digests, actual Python version and source
  digests. It does not include its own recursive hash.

No timestamp or absolute local source path enters these outputs. Identical source
and runtime produce identical bytes. Git SHA is explicitly unknown because this
command does not invoke Git; a delivery receipt must separately record the
observed checkout commit. A source/input digest is not an authenticity proof.

## What the page shows

The fixed synthetic loop has host 8 s, then compute 4 s / memory 2 s / fabric
6 s in parallel, then a 2 s declared state-completion stage. Three iterations run
sequentially, with each waiting for the previous state barrier. All five stages
remain explicit and positive. No actual state is persisted by the calculation.

| Intervention (all other durations unchanged) | Lower bound, 3 iterations | Serial no-overlap scenario |
|---|---:|---:|
| Baseline | 48 s | 66 s |
| Compute 4 → 1 s | 48 s | 57 s |
| Memory 2 → 1 s | 48 s | 63 s |
| Host 8 → 4 s | 36 s | 54 s |
| Fabric 6 → 3 s | 42 s | 57 s |
| Host 8 → 4 s, fabric 6 → 3 s | 30 s | 45 s |
| Host 8 → 4 s, fabric 6 → 3 s, compute 4 → 2 s | 27 s | 39 s |
| State 2 → 6 s (delay control) | 60 s | 78 s |

The 4×4 sensitivity grid varies compute and fabric duration multipliers over
0.25, 0.5, 1 and 2. It shows critical-path switches and no-benefit regions. A cell
names one critical branch using the API's lexical tie rule; another zero-slack
branch may be equally critical. These are declared scenarios, not statistical
uncertainty or confidence intervals. The study imports `analyze` and `compare`;
it does not duplicate their longest-path or accounting calculations.

All latency results are ideal dependency-only lower bounds with unlimited stage
resources and perfect parallel overlap. The serial sum is an ideal no-overlap
scenario, not an upper bound on actual runtime. There is no contention, queueing,
measured hardware ranking, reciprocal-as-throughput claim, energy or ROI model.
“Persisted” names declared completion, not verified durability or crash recovery.

## Provenance and identities

Fixtures are hand-authored synthetic data under MIT. `inputs.json` contains the
`family_definition`: the baseline stages, context, iteration count and family ID.
Its digest is SHA-256 of JSON encoded with sorted keys, indent 2, ASCII escaping,
no nonfinite values, and one trailing newline. This is the actual value in the
shared provenance `sha256` field. It identifies the baseline experiment family,
not each changed intervention. Every intervention retains that same family
identity so the existing duration-only comparison gate applies.

The API's `input_sha256` separately identifies each full supplied record, and
`graph_context_sha256` identifies the matched structure/context. The manifest
hashes the actual emitted `inputs.json`, `results.json` and HTML bytes. These
identities serve different purposes; none establishes truthful calibration,
execution permission, accepted composition or production safety.

## Refusal and corrected recovery

An existing output path refuses without modification. If a write fails after
creation, the command returns exit 2, prints an actionable error and retains the
bounded partial directory; it never recursively deletes anything or claims
success. Inspect that directory and rerun with a fresh output name. A successful
retry demonstrates export recovery only, not durable-state crash recovery.
Do not edit a partial directory into something claimed as a complete study;
only a successful export with matching manifest hashes establishes completeness.
Concurrent adversarial filesystem manipulation is not an isolation guarantee.

```sh
python3 -m unittest capacity.tests.test_loop_study -v
```

Tests cover independent numeric controls, API/output equality, critical-path
switches, real family/file hashes, deterministic bytes, escaping, local links,
existing-file/directory and symlink refusal, failed writes and corrected recovery.
An isolated synthetic delay/cycle/omitted-state and filesystem-failure challenge
belongs to designated technical qualification; no production chaos is implied.
Desktop/narrow browser visual review, exact-source Claude review and designated
technical acceptance are separate gates before a public study release. Source
checks alone do not establish visual usability or released-product readiness.
