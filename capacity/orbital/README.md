# Capacity Orbital

An offline planning tool for synthetic Earth-observation workloads. Compare
**ground**, **onboard** and **hybrid** processing under the same job deadlines,
quality requirements and declared resource envelopes. This is the first modular
space configuration of Capacity, not a new scheduler service or flight system.

## Run it

Python 3.10+; standard library only, no installation, network calls or credentials.
Run from the repository root:

```sh
python3 -m capacity.orbital --demo intermittent
python3 -m capacity.orbital --scenario capacity/orbital/examples/intermittent.json \
  --output /tmp/my-orbital-report.json --html /tmp/my-orbital-report.html
python3 -m unittest capacity.orbital.test_orbital -v
python3 -m capacity.orbital.benchmark
```

Open the HTML locally. It contains no scripts, fonts or external assets. Output
paths must not exist and must be distinct from each other and the input. Use
fresh paths for reruns; this preserves evidence rather than silently overwriting
it. `--jobs` is valid only with `--demo`. Invalid input exits 2 with `REFUSE:`.
All output parents and destinations are checked before any write. Output files
are staged in temporary siblings, then published without overwrite. On ordinary
write/publish errors, only files created by this run are removed. Rollback
moves each of its paths into a private `.rollback` directory before it checks
the file identity, so a foreign file that replaced a destination is not
deleted. It is linked back without overwrite; if that fails, it stays in the
`.rollback` directory and the error names it. A foreign file can be absent from
its path for a moment during this step, so use an output directory that no
other writer shares. Publication needs a filesystem that supports hard links,
because a hard link is how a file is published without overwrite. Where hard
links are not supported, the run exits 2 with `REFUSE:` and the operating
system error, and leaves no output or staged file. No successful report is printed to stdout until
file publication succeeds. This is **not** a multi-file atomic transaction under
process death, power loss or cleanup failure; inspect exit status and the complete
expected artifact set. Cleanup failures surface as errors rather than a success.

The JSON contains each job's completion time or refusal, deadline, assumed
quality, downlinked GB, compute kWh, partial cost, deterministic planning receipt
and reservation events. The HTML shows the same outcomes and source/input hashes.
A deterministic receipt is **not** a signature, actual executed result, a bill
or production metering integration. Receipt-v2 hashes bind the input, source
fingerprint, version, outcome fields and committed events. The CLI obtains the
source fingerprint before computing. Pure API callers may pass `source_sha256`;
if omitted, reports explicitly mark receipts **unbound to code**, not verified.
Caller-provided fingerprints are not authenticated. Identical input, source and
outcome replay to the same ID; changes to any binding change it. A planning
receipt is not an execution-idempotency key or authorization to charge a bill.

Saved exports are labelled. `--save-scenario` writes a
`capacity-orbital/scenario-export-v1` file: the scenario plus its classification,
the assumption list, the model version, `input_sha256` and `source_sha256`.
`--scenario` accepts this export or a bare v1 scenario. An export whose
`input_sha256` does not match its embedded scenario is refused. Benchmark JSON
(`capacity-orbital/benchmark-v1`) carries the same assumption list, the source
fingerprint and one `input_sha256` per measurement. Saved exports require a
source fingerprint, and the CLI and the benchmark always supply it. Only a
direct API call may omit it, and its report is then marked unbound. Do not use
an unbound report as qualification evidence.

## A concrete hand calculation

The continuous demo's first job starts in space with 10 decimal GB. At 1 Gbps,
raw downlink takes 80 seconds. Ground processing takes 20 seconds, finishing at
100 seconds. Onboard processing takes 30 seconds and emits 0.1 GB, finishing at
30.8 seconds. Hybrid preprocessing takes 10 seconds, transfers 1 GB in 8 seconds,
then uses 10 seconds on the ground: 28 seconds. These are **synthetic assumptions**,
not measured hardware results or claimed speedups on an actual AI workload.

Each job has the same required quality in all three counterfactuals. Ground
quality 1.0 is an assumed reference, **not measured perfect accuracy**. Onboard
and hybrid quality are user-supplied synthetic retained-quality scores. Work
below the requirement is refused even if it saves bytes. Lower cost with fewer
completed jobs is not an economic advantage; inspect counts before costs.

## Modular contracts

| Module | Responsibility |
|---|---|
| `contracts.py` | Strict `capacity-orbital/scenario-v1`, explicit units, finite domains, provenance and canonical input digest |
| `adapters.py` | Two replaceable synthetic contact adapters; neither changes planner code |
| `contacts.py` | Shared downlink reservation, decimal GB/Gbps, transfers split across windows |
| `resources.py` | Serial compute, memory/power/heat envelopes and cumulative compute-energy budget |
| `planner.py` | Pure route composition and transactional admission; no filesystem/network IO |
| `economics.py` | Partial cost formulas (compute time, compute electricity, transfer GB) and route summaries |
| `evidence_record.py` | Classification and assumption labels, source-digest check and receipt-v2 IDs |
| `report.py` | Escaped self-contained responsive HTML |
| `__main__.py`, `output.py` | CLI IO, source binding, staged no-overwrite artifact publication and ordinary-error rollback |
| `benchmark.py` | Reproducible scaling measurement, separate from planning results |

Inputs must have exactly the fields shown in the example. Unknown fields and
versions refuse; there are no implicit unit conversions or migrations. A new
schema needs an explicit adapter and compatibility tests. `horizon_s` is seconds
from scenario start, at most one year; job and contact lists are bounded at
10,000 each. This is a validation cap, not a guaranteed latency bound; review-fix
benchmarks include the cap for two declared fixture shapes only. IDs are unique.
`result_gb` and `compressed_gb` must be greater than zero. A zero-size output
is refused at validation, so no route is planned without a contact check.
Contact windows are ordered and nonoverlapping for
**one shared terminal**. Both nodes have **one serial compute lane**. Jobs are
scheduled by `(release_s, id)`, deterministically and greedily. There is no
optimality claim, backfill optimization, multiple satellite routing or DAG
execution in this version. Adding distributed fleet capacity is a later contract.

Each route uses an independent reservation ledger; comparisons do not compete
with each other. Within one route, all jobs share the same terminal and node
resources. Refused plans commit no reservations. This is admission planning,
not a claim that execution failures consume no energy or money. Power is assumed
to become heat; max_heat_kw is a declared steady envelope, not a radiator model.
One job power figure is used for both ground and orbital hardware; real payload
power differences require a future contract. Energy accounts for compute only,
with no replenishment. Costs include declared
compute time, compute electricity and transfer GB; no lifecycle, NRE, insurance,
launch, transfer energy, idle energy, radiation or orbit propagation is modeled.

## Evidence and qualification boundary

- [`examples/intermittent.json`](examples/intermittent.json): authored synthetic,
  MIT-licensed assumptions, not vendor/observational data.
- [`evidence/demo-report.json`](evidence/demo-report.json) and
  [`evidence/demo-report.html`](evidence/demo-report.html): reproducible CLI output.
- [`evidence/scaling.json`](evidence/scaling.json): retained initial run measurements.
- [`evidence/scaling-review-fixes.json`](evidence/scaling-review-fixes.json): observed
  run time and traced Python peak memory through 10,000 jobs with one and many
  contacts after review fixes. This is not total RSS or a production benchmark.
- `evidence/history/`: retained original reports before receipt-v2 corrections.
- [`evidence/VALIDATION.md`](evidence/VALIDATION.md): commands and remaining gates.

Validation now checks the slowest contact once rather than every job/contact
pair; each comparison validates once. Transfers bisect past expired contacts,
and transactions track only changed cursors. Contact scans can still approach
jobs × contacts for adversarial workloads; these optimizations do not establish
a universal complexity or horizontal-scaling guarantee. The post-review
10,000-job / 10,000-contact fixture completed in about 5.0 seconds with 43.4 MB
traced Python peak memory on the recorded host. One kernel owns accounting;
conservation tests are required before partitioning it.

This tool cannot contact hardware or execute tenant/flight actions. It does not
implement Tool Guard authorization or claim sandbox/network isolation of the
calling agent. Future executable integrations must use the existing authorized
Tool Guard boundary, with independent security review. No spacecraft control,
procurement, clinical, defense or financial safety qualification is implied.

Next increments: time-coupled battery/thermal physics and explicit contact
providers, fleet cohorts and uncertainty, stronger lifecycle economics, signed
external evidence and guarded runtime integration. Dmitry owns physical and
technical acceptance; Ronnie independently reproduces qualification; the other
AI harness reviews the pinned source. Release and website integration remain
gated on that evidence.
