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
