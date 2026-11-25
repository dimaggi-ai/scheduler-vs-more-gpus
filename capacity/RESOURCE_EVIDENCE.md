# Batch resource evidence reference

Maggie domain reference v0.1, 19 September 2026. This adds finite resource
inequalities to the existing capacity package. It does not alter scheduling,
placement, inference, recovery or report accounting. There is no live adapter.

`capacity.resource_evidence.capacity_check` evaluates one resource at one supplied
node/device/storage scope. `checkpoint_bound_check` can refuse an impossible
deadline from a justified time lower bound, but never treats that bound as proof
of a completed save or restore. The caller must cover every required scope.

Each quantity has exactly these fields:

```json
{
  "value": null,
  "unit": "byte",
  "state": "missing",
  "source_id": null,
  "evidence_class": "operator_observed"
}
```

`evidence_class` identifies the intended evidence class; `missing` with null does
not claim that an observation exists. Supported classes are `synthetic_model`,
`synthetic_contract_fixture`, `lab_observed`, `operator_observed`. States are
`known`, `missing`, `stale`, `not_run`, `invalid`. A known value requires a source
ID. The reference checks supplied state and shape; it cannot establish the
truth, freshness, compatibility or authenticity of that source.

Memory/storage units are integer bytes. CPU uses finite nonnegative `cpu_core`
values under a declared scheduler CPU-unit mapping, including fractional amounts.
Time uses finite nonnegative seconds. Convert GB/GiB explicitly before calling;
no numeric strings or booleans. Unknown margin stays unknown. Zero is meaningful
only when explicitly evidenced; it is not the default for omitted input.

Capacity input:

- `scope_id`: bound node, device or shared-storage-domain ID.
- `resource`: `cpu`, `host_memory`, `pinned_host_memory`, `gpu_memory`, `storage`.
- `demand_components`: nonempty map of uniquely named **disjoint incremental peak**
  requirements. Use a total peak OR disjoint components, never both.
- `available`: residual usable capacity after existing commitments/reservations.
- `margin`: explicitly supplied additional workload uncertainty allowance.

The predicate is `sum(demand_components) + margin <= available`. Equality passes
this arithmetic screen only. A failed inequality is refused. Malformed quantities
are invalid/refused; missing/stale/not-run quantities produce incomplete. All
individual evidence states and source IDs remain visible. Invalid input is not
emitted as NaN JSON. Unsupported resource/empty scope/components raise `ValueError`.

Arithmetic compares the exact values of supplied integers and binary floats,
without an acceptance epsilon. Integer byte quantities stay exact. Derived CPU
quantities use exact internal sums and differences; JSON emits integers for
integral results and rounded finite floats otherwise. The displayed required
quantity can therefore round to the available quantity while exact negative
headroom still refuses the check. Derived overflow, or a nonzero result that
would round to zero, is invalid/refused. Supply explicit upstream conversions
when decimal precision or scheduler CPU-unit quantization is intended.

Do not sum a pinned subset into host total a second time. If a pinned limit applies,
evaluate that subset independently. Do not sum node/device capacity to hide one
overloaded rank. A shared storage budget appears once per shared scope; source
data must distinguish residual/free capacity from total capacity. Existing files
already deducted from free space must not be counted again as new demand. The
reference cannot discover overlaps, missing nodes or incorrect accounting bases.
Those mappings require the versioned workload/resource profile and adapter tests.

Output `feasible_within_supplied_capacity` means only this scalar capacity
predicate passed. It establishes no allocation, complete placement, performance,
isolation or execution permission. Every result sets `execution_authorized=false`
and `mutation_request=null`. Whole-job readiness must preserve all other gates.

Run from this repository root using the existing audit Python environment:

```sh
../../_Audits/2026-09-17-repo-aware-strategy/.venv/bin/python -m pytest capacity/tests -q
../../_Audits/2026-09-17-repo-aware-strategy/.venv/bin/python -m capacity.resource_evidence_examples \
  --netcap-root ../network-vs-more-gpus \
  --out /tmp/dimaggi-resource-evidence.json
```

The deterministic example builder retains IDs, units, split labels and expected
answers. No stochastic generator or parameter tuning is added. The small subset
and imbalance acceptance families are exposed regressions after this run; they
are not a protected improvement-evaluation holdout or measured fleet evidence.

Model probes call the existing pinned netcap `memory_per_accelerator_gb` and
`checkpoint_state_bytes`, then perform explicitly labeled conditional arithmetic.
The circuit lower bound already exists in netcap and is not copied or invoked
as a local storage model. The operator host capacity, storage bandwidth and
checkpoint implementation remain unknown.
