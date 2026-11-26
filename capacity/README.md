# Offline capacity interfaces

This module extends the existing allocation-policy simulator without copying
its policies. Optional previews call the existing torus packing and span
admission packages. No commands access a cluster, inject faults, allocate real
hardware or act on infrastructure.

## Replay and compare

From the repository root:

```bash
python -m pip install -r capacity/requirements.txt
python -m capacity replay examples/capacity-replay.json
```

Output is JSON on stdout. Compare two saved reports made with different policies
on the same scenario:

```bash
python -m capacity compare baseline.json candidate.json
```

Reports include the complete configuration, policy, Python/NumPy versions,
model/interface source hashes, time window, schema, assumptions and an input/projection
identity. Hashes identify code and inputs; they do not authenticate the sender
or prove execution. Keep Python/NumPy versions fixed for study reproduction.

Five GPU-hour buckets conserve **nominal** capacity:

- Productive: training progress plus inference allocation up to aggregate demand.
- Unavailable: nominal minus the power/failure envelope.
- Idle: envelope not allocated to either workload class.
- Inference reservation: inference allocation beyond productive demand.
- Training overhead and discarded: allocated training time not retained as progress.

Productive/nominal and productive/envelope are separate ratios. Neither is
netcap's communication-exclusive productive fraction. Do not multiply this
ledger by network UCF or reliability goodput: the losses overlap.

Optional calibration converts each workload class separately from
scheduler-productive GPU-hours to its own work unit. The example token rate is
synthetic. Real calibration needs model, hardware, workload shape, software,
measurement protocol and service constraints that justify a constant rate.
It is not raw GPU busy time, a FLOPS conversion or guaranteed token goodput.
A measured calibration does not make a simulated projection a production result.
Different workload units are never added.

Comparisons reject different configurations (including seed/window), model and
interface hashes, workload sets, calibrations or accounting schemas. Schema and
conservation checks run before comparison. Invalid input exits 2. This is policy
comparison, not an architecture-mix optimizer.

## Placement and admission

```bash
python -m pip install -r capacity/integration-requirements.txt
```

```python
from slicepacker import Fabric, Topology, Request
from capacity.placement import placement_preview

fabric = Fabric(Topology((4, 4), (True, True)))
report = placement_preview(fabric, [Request("first", 12), Request("second", 12)])
# First is placeable; second is not. The original fabric is unchanged.
```

Requests are packed sequentially on a copy using `Fabric.place`, rather than
summing independently feasible placements. Tenant labels are refused: geometry
alone cannot enforce isolation; use `slicepacker.tenant` for that policy.
Failures/existing allocations constrain the preview. It is not integrated into
the simulator's time-step loop.

`admission_preview(envelope, plant=..., policy=...)` calls `spancontract.validate`
and preserves decisions, reasons and `not_checked` gaps. Missing checks do not
become a clean pass. It does not bind an envelope to a new rectangle, replace
cooling admission or authorize execution. These remain separate previews until
such binding is implemented and tested.

## Tests and boundaries

```bash
python -m pip install pytest
python -m pytest capacity/tests -q
```

Integration dependencies are pinned to inspected public revisions. Tests cover
conservation, reproducibility, incomparable baselines, malformed reports,
sequential placement, failed geometry, unchanged state and missing admission
checks. The original simulator/calculator tests are unchanged.

Not implemented: live fleet synchronization, Kubernetes/Slurm bindings,
prefix-cache routing, topology inside the simulation loop, cross-repository
failure replay, multi-tenant scheduling or automatic actions. This is an offline
foundation for a capacity twin, not a live digital twin.

## Declared inference memory reservations

`capacity.inference.simulate` can use explicit peak memory reservations while
retaining its existing FCFS scheduler and prefill/decode service model:

```python
from capacity.inference import Hardware, Request, simulate

hardware = Hardware('synthetic', 1000, 216, 1000, efficiency=1)
report = simulate(
    [Request(0, 16, 1), Request(0, 16, 1)], hardware,
    parameters=5, bytes_per_parameter=2, kv_bytes_per_token=2,
    request_reservations_bytes=[78, 78], workspace_headroom_bytes=50,
)
assert report['memory_accounting']['kv_budget_bytes'] == 156
assert report['memory_accounting']['peak_reserved_bytes'] == 156
assert report['memory_accounting']['final_remaining_bytes'] == 156
```

These tiny numbers are synthetic arithmetic, not a hardware configuration.
Both new keyword arguments default to `None`, preserving the legacy behavior,
validation and output shape when neither is supplied. Supplying either selects
explicit mode, which requires a finite `list` or `tuple` reservation vector in
**original request order**, before arrival sorting. An omitted global reservation
means declared zero. A global reservation without a vector is refused.

Each vector entry is the full positive peak request reservation, including any
caller-declared block rounding, metadata or allocation overhead. It must be at
least `(input_tokens + output_tokens) * kv_bytes_per_token`; cached prefix tokens
never reduce this storage floor. The vector is snapshotted before execution.
Resident weights are `parameters * bytes_per_parameter`; global workspace and
headroom are reserved once, separately from weights and per-request memory.
Hardware memory remains the original usable HBM declaration. The request budget
is `HBM - weights - workspace/headroom`. A negative budget raises `ValueError`;
a zero budget is valid and rejects every positive reservation. Legacy mode
continues to refuse weights greater than or equal to HBM.

Explicit mode requires actual integer memory values and parameters, excluding
booleans; it does not round the legacy `parameters=7e9` float default. Callers
must declare an integer parameter count. Requests must be `Request` values.
The mode consumes at most 129 requests before refusing more than 128; it accepts
at most 100,000 aggregate output tokens and a `max_batch` of at most 128. Every
reservation, fixed-memory sum, raw maximum-context KV footprint and aggregate
reservation sum is bounded by `2**53 - 1`. Empty requests with an empty vector
are valid. With a valid `Hardware` and an iterable of requests, malformed
reservation values, request elements and numeric parameters raise `ValueError`
without a partial report, but an exception raised by the iterable while it is
consumed propagates unchanged. Service-rate and conservative elapsed-time bounds are checked before the loop,
and nonfinite result metrics are refused.

Admission acquires the exact declared request reservation; completion releases
that same value once. Requests are rejected exactly when their reservation
exceeds the total request budget, using the existing rejection reason strings.
Otherwise they may wait. FCFS head-of-line blocking is preserved: a pending
request can block smaller requests behind it. Successful sequential completion
therefore does not establish simultaneous cohort fit, and observed peak
concurrency is not a packing limit. For a separately declared simultaneous
cohort, its total reservation must be compared with the budget independently.

Only explicit-mode output adds `memory_accounting`, recording original HBM,
weights, global reservation, request budget, original-order reservation vector,
observed peak reserved bytes and final remaining bytes. These are declarations
and simulated accounting, not authenticated allocator evidence.

**Timing boundary:** reservations affect admission and queueing only. The
existing prefill compute and decode weight/raw-KV bandwidth formulas are
unchanged. Real allocator metadata, padding, workspace and headroom may also
change timing; those costs are **not modeled**. This interface is not yet bound
to the KV envelope or a trace adapter, and establishes no measured hardware
performance, latency guarantee or production qualification.
