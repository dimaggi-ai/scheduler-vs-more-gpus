# Capacity Orbital agent tools

A real, stdlib-only tool boundary for an AI/SI agent to **observe a scenario →
propose a registered route → validate → request a planning result → measure
synthetic replay → evaluate a candidate against a fixed baseline**. No model
service, credentials, network fetch, arbitrary callback or shell execution is
used. This module does not execute workloads or operate spacecraft.

The existing static `capacity.orbital.planner` performs all planning. Task106
battery/thermal composition is a future, separately reviewed evaluator adapter;
this version does not claim it. No existing planner file was changed.

## Agent-callable Python and JSON tools

```python
from capacity.orbital.agentic.dispatcher import Dispatcher, manifest
from capacity.orbital.adapters import synthetic

session = Dispatcher()
request = {
    'schema': 'capacity-orbital/agent-request-v1',
    'id': 'plan-1',
    'tool': 'plan',
    'arguments': {'scenario': synthetic('continuous', 1), 'route': 'onboard'},
}
proposal = session.dispatch(request)
assert proposal['status'] == 'proposed'
assert proposal['execution_performed'] is False
```

The fixed registry exposes `plan`, `compare` and `evaluate`. The manifest lists
arguments and bounds; [`request.schema.json`](request.schema.json) defines wire
shape. Runtime validation additionally enforces finite derived arithmetic,
resource domains, ordering, unique IDs and split leakage. Unknown fields refuse.
No JSON field can grant authority or supply executable code. Output
`authority_disposition: planning_only` is a disposition, not authentication or a
Tool Guard permit. A future executable boundary must use the existing authorized
Tool Guard integration; this planning API neither replaces nor configures it.

```sh
python3 -m capacity.orbital.agentic --manifest
python3 -m capacity.orbital.agentic --request capacity/orbital/examples/agentic-evaluate.json
python3 -m capacity.orbital.agentic --request capacity/orbital/examples/agentic-regression.json
python3 -m capacity.orbital.agentic --jsonl < requests.jsonl
python3 -m unittest capacity.orbital.test_orbital capacity.orbital.test_agentic -v
python3 -m capacity.orbital.agentic.benchmark
```

Single-request CLI prints JSON or writes `--output` through the existing safe
output publisher. Destination must be new and cannot be the input. A structured
refusal is still useful JSON evidence, exits 2 and never contains a proposed
plan. IO failures print `REFUSE:` to stderr. JSON-lines mode emits one response
per input line, stops on an overlong line, and ends after at most 32 lines with
an explicit budget message and exit 2; remaining input is not consumed. Empty
stdin ends normally. It is a bounded session, not a persistent daemon.

## Bounded idempotency and provenance

Within one `Dispatcher` object/process, the same request ID and identical
canonical payload returns the same response. Reusing the ID with different
content returns `REQUEST_ID_CONFLICT`. Cached results are copied so callers
cannot mutate the session record. A validated-ID refused request also consumes
its ID: corrected retries use a new ID. Idempotency does not persist across
process restarts, and the module claims neither durable settlement nor billing.

Limits are 1 MB/request, 32 unique session records, 20 total evaluation scenarios,
200 jobs and 200 contacts/scenario, three registered candidate routes, 4 MB per
response and 16 MB of canonical cached-response bytes. Limits apply together;
list caps do not guarantee that a large combination fits the byte cap. Cache
exhaustion closes admission of new work; existing matching retries remain
available. Memory includes Python object overhead beyond the byte counter.

Request, suite, scenario and outcome hashes are canonical SHA-256 bindings.
The source fingerprint includes the imported v1 orbital source files **and** the
agentic module source/schema. A changed or unreadable source tree refuses new
work. These bindings are not signatures, supply-chain attestation or evidence
that a caller is authorized. The report retains original scenario provenance.

## Fixed training and held-out evaluation

Candidates can only choose one whole-scenario registered `ground`, `onboard` or
`hybrid` route. They cannot edit jobs, thresholds, constraints, prices, evaluator,
objective or tolerances. The suite specification declares the fixed objective
`failures_then_cost` and absolute cost tolerance before any route is evaluated.
The baseline route is always included and is never changed by evaluation.

Training selects the candidate:

1. Exclude candidates losing any baseline successful job on training inputs.
2. Minimize failed jobs (refused, late or below required quality).
3. At equal useful output, minimize partial cost within the fixed tolerance.
4. Prefer the baseline on ties, otherwise use lexical route order.

Only after selection is fixed are the baseline and winner evaluated on held-out
inputs. Losing a baseline successful job is a regression, even if aggregate cost
falls or another job succeeds. Fewer failures with preserved baseline outcomes
is an improvement. At equal useful output, cost differences beyond tolerance
determine improvement/regression. Zero completed jobs cannot be a free win.

An improvement emits **`independent_review`**, never promotion. A regression or
no improvement emits **`retain_baseline`**. `active_policy` stays the baseline and
`promoted` is always false. Source review, Dmitry's technical acceptance and
Ronnie's independent reproduction remain open. Stop reasons are all candidates
evaluated, invalid data or a budget refusal; this is a finite evaluation loop.

Both partitions must be nonempty. IDs must be unique across the whole suite.
Canonical-content comparison also rejects copies disguised by different names,
scenario provenance labels, contact IDs, job IDs or job-list order. It retains
all numeric physics, times, resource values, costs, quality and schema fields.
This intentionally over-approximates duplicate content (job IDs can affect
planner tie order); relabelling alone never creates held-out evidence.

The caller supplies the full suite and therefore can see its held-out data.
This module enforces selection order and immutability **within a request**; it
cannot prevent a caller from repeatedly tuning candidates or tolerances across
sessions. Independently controlled, sealed holdouts remain a review/deployment
requirement. No statistical generalization or production improvement is claimed.

## What is measured

Every route retains per-scenario plans and outcome hashes plus totals: planned,
refused, late, quality-failing and failed jobs; latency p50/p95; downlink GB;
compute energy; partial cost; and minimum assumed and required quality. Latency
quantiles use nearest rank over successful plans. The ground quality of 1.0 is a
synthetic reference, not perfect measured AI accuracy. Equal quality requirements
do not mean identical actual route quality. All metrics are planning replay,
not hardware execution, lifecycle TCO, accepted outcomes or revenue.

The examples are authored synthetic scenarios under this repository's MIT
licence. `agentic-evaluate.json` has a cheaper successful training/held-out route;
`agentic-regression.json` deliberately makes that training winner fail held-out
quality. Both preserve the same baseline.

## Evidence and integration

`../evidence/agentic/` retains source-bound example responses, test output,
validation notes and a bounded-suite scaling run. Scaling measures one local
observation with tracemalloc, not total process memory or a production SLO.
The dedicated workflow runs both existing planner and agentic tests. No installs,
secrets, deployment or publish actions were added.

The adapter seam is `evaluation.assess(entries, route, source_sha256)` plus its
explicit evaluator identity and output contract. Adding a dynamic evaluator is
a code-reviewed composition change with new fixed-suite oracles, not a runtime
plugin name supplied by an agent. Reuse existing planner and receipt contracts;
do not introduce a competing scheduler, Tool Guard classifier or metering store.
